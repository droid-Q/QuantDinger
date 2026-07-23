import pandas as pd

from app.services.strategy_v2 import OrderIntent
from app.services.strategy_v2.live_execution import LiveOrderRequest, StrategyV2OrderGateway
from app.services.trading_executor import TradingExecutor, live_history_days


def test_live_history_lookback_is_frequency_aware():
    assert live_history_days("1m", 2) == 1
    assert live_history_days("4h", 100) == 50
    assert live_history_days("1d", 50) == 150


def test_bar_evaluation_distinguishes_noop_from_executable_signal(monkeypatch):
    captured = []
    monkeypatch.setattr(
        "app.services.trading_executor.append_strategy_log",
        lambda strategy_id, level, message: captured.append((strategy_id, level, message)),
    )
    timestamp = pd.Timestamp("2026-07-23T06:35:00Z")

    TradingExecutor._record_bar_evaluation(
        345,
        timestamp,
        intent_count=1,
        submitted_count=0,
    )
    TradingExecutor._record_bar_evaluation(
        345,
        timestamp,
        intent_count=1,
        submitted_count=1,
    )

    assert captured == [
        (
            345,
            "info",
            "Closed bar 2026-07-23T06:35:00+00:00 evaluated: intents=1, executable_signals=0",
        ),
        (
            345,
            "signal",
            "Closed bar 2026-07-23T06:35:00+00:00 evaluated: intents=1, executable_signals=1",
        ),
    ]


def test_intent_signal_timestamp_prefers_scheduled_wall_clock():
    intent = OrderIntent(
        symbol="Crypto:BTC/USDT@okx:swap",
        kind="target_percent",
        value=0.5,
        signal_time=pd.Timestamp("2026-07-19 09:35:00+08:00"),
    )

    result = TradingExecutor._intent_signal_timestamp(
        intent,
        pd.Timestamp("2026-07-18 00:00:00Z"),
    )

    assert result == int(pd.Timestamp("2026-07-19 01:35:00Z").timestamp())


def _frame(price: float = 100.0) -> pd.DataFrame:
    index = pd.DatetimeIndex([pd.Timestamp("2026-07-13T00:00:00Z")])
    return pd.DataFrame(
        {"open": [price], "high": [price], "low": [price], "close": [price], "volume": [1.0]},
        index=index,
    )


def _member() -> dict:
    return {
        "key": "Crypto:BTC/USDT@okx:swap",
        "market": "Crypto",
        "symbol": "BTC/USDT",
        "exchange_id": "okx",
        "market_type": "swap",
    }


def _forex_member() -> dict:
    return {
        "key": "Forex:XAUUSD",
        "market": "Forex",
        "symbol": "XAUUSD",
        "exchange_id": "cptmarkets",
        "market_type": "spot",
    }


def test_target_percent_opens_position_with_explicit_quantity():
    executor = TradingExecutor.__new__(TradingExecutor)
    executor._get_current_positions = lambda *_args: []
    captured = {}

    def execute_signal(**kwargs):
        captured.update(kwargs)
        return True

    executor._execute_signal = execute_signal
    intent = OrderIntent(symbol=_member()["key"], kind="target_percent", value=0.25)

    result = executor._execute_strategy_v2_intent(
        strategy_id=7,
        strategy_name="V2 CTA",
        intent=intent,
        frames={_member()["key"]: _frame()},
        candidates=[_member()],
        initial_capital=10_000.0,
        leverage=2.0,
        execution_mode="signal",
        notification_config={},
        trading_config={},
        exchange_config={},
        signal_ts=1,
        strategy_run_id=42,
    )

    assert result is True
    assert captured["signal_type"] == "open_long"
    assert captured["script_base_qty"] == 50.0
    assert captured["market_type"] == "swap"
    assert captured["price_exchange_id"] == "okx"
    assert captured["strategy_run_id"] == 42


def test_mt5_forex_spot_can_open_short():
    executor = TradingExecutor.__new__(TradingExecutor)
    executor._get_current_positions = lambda *_args: []
    captured = {}
    executor._execute_signal = lambda **kwargs: captured.update(kwargs) or True
    member = _forex_member()

    result = executor._execute_strategy_v2_intent(
        strategy_id=10,
        strategy_name="MT5 short",
        intent=OrderIntent(
            symbol=member["key"],
            kind="target_quantity",
            value=-0.01,
            position_side="short",
        ),
        frames={member["key"]: _frame(price=4000.0)},
        candidates=[member],
        initial_capital=10_000.0,
        leverage=1.0,
        execution_mode="live",
        notification_config={},
        trading_config={},
        exchange_config={"exchange_id": "cptmarkets"},
        signal_ts=3,
        strategy_run_id=44,
    )

    assert result is True
    assert captured["signal_type"] == "open_short"
    assert captured["market_category"] == "Forex"


def test_order_gateway_allows_only_forex_spot_short():
    common = dict(
        strategy_id=10,
        strategy_run_id=44,
        user_id=1,
        symbol="XAUUSD",
        action="open_short",
        quantity=0.01,
        reference_price=4000.0,
        signal_timestamp=3,
        market_type="spot",
        execution_mode="live",
    )

    request = LiveOrderRequest(**common, market_category="Forex")
    assert StrategyV2OrderGateway._validate(request) is request
    try:
        StrategyV2OrderGateway._validate(LiveOrderRequest(**common, market_category="Crypto"))
    except ValueError as exc:
        assert str(exc) == "strategyV2.spotShortUnsupported"
    else:
        raise AssertionError("Crypto spot short must remain blocked")


def test_spot_target_percent_does_not_expand_with_leverage():
    intent = OrderIntent(symbol="USStock:AAPL", kind="target_percent", value=0.25)

    target = TradingExecutor._target_amount(
        intent,
        current=0.0,
        capital=10_000.0,
        price=100.0,
        leverage=5.0,
        market_type="spot",
    )

    assert target == 25.0


def test_explicit_quantity_is_not_scaled_by_leverage():
    intent = OrderIntent(symbol=_member()["key"], kind="target_quantity", value=2.5)

    target = TradingExecutor._target_amount(
        intent,
        current=0.0,
        capital=10_000.0,
        price=100.0,
        leverage=5.0,
        market_type="swap",
    )

    assert target == 2.5


def test_target_zero_closes_existing_long_position():
    executor = TradingExecutor.__new__(TradingExecutor)
    executor._get_current_positions = lambda *_args: [{"side": "long", "size": 3.0}]
    captured = {}

    def execute_signal(**kwargs):
        captured.update(kwargs)
        return True

    executor._execute_signal = execute_signal
    intent = OrderIntent(symbol=_member()["key"], kind="target_quantity", value=0.0)

    result = executor._execute_strategy_v2_intent(
        strategy_id=8,
        strategy_name="V2 CTA",
        intent=intent,
        frames={_member()["key"]: _frame()},
        candidates=[_member()],
        initial_capital=10_000.0,
        leverage=1.0,
        execution_mode="signal",
        notification_config={},
        trading_config={},
        exchange_config={},
        signal_ts=2,
    )

    assert result is True
    assert captured["signal_type"] == "close_long"
    assert captured["script_base_qty"] == 3.0


def test_hedged_target_updates_only_the_requested_leg():
    executor = TradingExecutor.__new__(TradingExecutor)
    executor._get_current_positions = lambda *_args: [
        {"side": "long", "size": 2.0},
        {"side": "short", "size": 5.0},
    ]
    calls = []
    executor._execute_signal = lambda **kwargs: calls.append(kwargs) or True
    intent = OrderIntent(
        symbol=_member()["key"],
        kind="target_quantity",
        value=-3.0,
        position_side="short",
    )

    result = executor._execute_strategy_v2_intent(
        strategy_id=8,
        strategy_name="V2 Neutral Grid",
        intent=intent,
        frames={_member()["key"]: _frame()},
        candidates=[_member()],
        initial_capital=10_000.0,
        leverage=1.0,
        execution_mode="signal",
        notification_config={},
        trading_config={},
        exchange_config={},
        signal_ts=2,
    )

    assert result is True
    assert len(calls) == 1
    assert calls[0]["signal_type"] == "reduce_short"
    assert calls[0]["script_base_qty"] == 2.0


def test_target_rebalance_skips_sub_dollar_dust_order():
    executor = TradingExecutor.__new__(TradingExecutor)
    executor._get_current_positions = lambda *_args: [{"side": "long", "size": 10.0}]
    calls = []
    executor._execute_signal = lambda **kwargs: calls.append(kwargs) or True
    intent = OrderIntent(symbol="USStock:AAPL", kind="target_quantity", value=10.004)
    member = {
        "key": "USStock:AAPL",
        "market": "USStock",
        "symbol": "AAPL",
        "exchange_id": "alpaca",
        "market_type": "spot",
    }

    result = executor._execute_strategy_v2_intent(
        strategy_id=9,
        strategy_name="Portfolio",
        intent=intent,
        frames={member["key"]: _frame(price=200.0)},
        candidates=[member],
        initial_capital=10_000.0,
        leverage=1.0,
        execution_mode="live",
        notification_config={},
        trading_config={},
        exchange_config={},
        signal_ts=3,
        strategy_run_id=43,
    )

    assert result is False
    assert calls == []


def test_live_order_carries_run_sizing_diagnostics():
    executor = TradingExecutor.__new__(TradingExecutor)
    executor._load_strategy = lambda _strategy_id: {"user_id": 12}
    captured = {}

    class Gateway:
        def submit(self, request):
            captured["request"] = request
            return None

    executor.order_gateway = Gateway()
    result = executor._execute_signal(
        strategy_id=7,
        strategy_run_id=42,
        symbol="BTC/USDT",
        signal_type="open_long",
        script_base_qty=0.006,
        current_price=10_000.0,
        market_type="swap",
        execution_mode="live",
        leverage=2.0,
        initial_capital=100.0,
        signal_ts=4,
    )

    assert result is False
    assert captured["request"].sizing == {
        "initial_capital": 100.0,
        "entry_pct": 30.0,
        "leverage": 2.0,
        "source": "strategy_v2",
    }


def test_demo_account_price_overrides_public_market_price(monkeypatch):
    from app.services.live_trading import factory

    class Client:
        def get_mark_price(self, *, symbol):
            assert symbol == "BTC/USDT"
            return 63_943.1

    monkeypatch.setattr(factory, "create_client", lambda *_args, **_kwargs: Client())
    monkeypatch.setattr(
        TradingExecutor,
        "_live_prices",
        staticmethod(lambda _candidates: {"Crypto:BTC/USDT@binance:swap": 64_294.6}),
    )
    candidates = [_member() | {"key": "Crypto:BTC/USDT@binance:swap", "exchange_id": "binance"}]

    prices = TradingExecutor._execution_account_prices(
        candidates,
        {"exchange_id": "binance", "environment": "demo"},
        {},
    )

    assert prices["Crypto:BTC/USDT@binance:swap"] == 63_943.1


def test_live_frame_latest_bar_is_aligned_to_execution_account_price():
    frame = _frame(price=64_294.6)
    key = "Crypto:BTC/USDT@binance:swap"

    aligned = TradingExecutor._align_latest_frame_prices({key: frame}, {key: 63_943.1})

    assert aligned[key].iloc[-1][["open", "high", "low", "close"]].tolist() == [
        63_943.1,
        63_943.1,
        63_943.1,
        63_943.1,
    ]
