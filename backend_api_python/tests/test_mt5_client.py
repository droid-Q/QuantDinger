import sys
import types
from collections import namedtuple

from flask import Flask, g

from app.routes import mt5 as mt5_routes
from app.services.mt5_trading import client as mt5_client_module
from app.services.mt5_trading.client import MT5Client, MT5Config


def _fake_mt5():
    SymbolInfo = namedtuple("SymbolInfo", "visible volume_min volume_max volume_step")
    Tick = namedtuple("Tick", "bid ask last time")
    Account = namedtuple("Account", "login server name company currency balance equity margin margin_free")
    Position = namedtuple("Position", "type volume price_open price_current profit ticket symbol")
    Result = namedtuple("Result", "retcode order deal volume price comment")
    Check = namedtuple("Check", "comment")

    mod = types.SimpleNamespace()
    mod.POSITION_TYPE_BUY = 0
    mod.POSITION_TYPE_SELL = 1
    mod.ORDER_TYPE_BUY = 0
    mod.ORDER_TYPE_SELL = 1
    mod.ORDER_TYPE_BUY_LIMIT = 2
    mod.ORDER_TYPE_SELL_LIMIT = 3
    mod.TRADE_ACTION_DEAL = 1
    mod.TRADE_ACTION_PENDING = 5
    mod.TRADE_ACTION_REMOVE = 8
    mod.ORDER_TIME_GTC = 0
    mod.ORDER_FILLING_IOC = 1
    mod.ORDER_FILLING_RETURN = 2
    mod.TRADE_RETCODE_DONE = 10009
    mod.TRADE_RETCODE_PLACED = 10008
    mod.TRADE_RETCODE_DONE_PARTIAL = 10010
    mod.TIMEFRAME_M1 = 1
    mod.TIMEFRAME_M3 = 3
    mod.TIMEFRAME_M5 = 5
    mod.TIMEFRAME_M15 = 15
    mod.TIMEFRAME_M30 = 30
    mod.TIMEFRAME_H1 = 60
    mod.TIMEFRAME_H4 = 240
    mod.TIMEFRAME_D1 = 1440
    mod.TIMEFRAME_W1 = 10080
    mod.sent = []
    mod.initialize = lambda **kwargs: True
    mod.shutdown = lambda: None
    mod.last_error = lambda: (0, "")
    mod.account_info = lambda: Account(1, "CPT-Demo", "Demo", "CPT Markets", "USD", 1000, 1005, 10, 995)
    mod.symbol_info = lambda symbol: SymbolInfo(True, 0.01, 100.0, 0.01) if symbol == "XAUUSD" else None
    mod.symbol_select = lambda symbol, visible: True
    mod.symbol_info_tick = lambda symbol: Tick(2300.0, 2300.5, 2300.25, 1710000000)
    mod.positions_get = lambda symbol=None: [Position(mod.POSITION_TYPE_BUY, 0.03, 2290.0, 2300.0, 30.0, 12345, "XAUUSD")]
    mod.orders_get = lambda: []
    mod.copy_rates_from_pos = lambda symbol, timeframe, start, count: [
        {"time": 1, "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "tick_volume": 10},
        {"time": 2, "open": 1.5, "high": 2.5, "low": 1.0, "close": 2.0, "tick_volume": 11},
    ]
    mod.order_check = lambda request: Check("checked")

    def order_send(request):
        mod.sent.append(dict(request))
        return Result(mod.TRADE_RETCODE_DONE, 777, 888, request.get("volume"), request.get("price"), "done")

    mod.order_send = order_send
    return mod


class AmbiguousRows(list):
    def __bool__(self):
        raise ValueError("truth value is ambiguous")


def test_mt5_client_market_and_reduce_only_orders(monkeypatch):
    fake = _fake_mt5()
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake)
    monkeypatch.setattr(mt5_client_module, "_mt5", None)

    client = MT5Client(MT5Config(login=1, password="pw", server="CPT-Demo"))
    assert client.connect() is True
    assert client.get_account_summary()["freeMargin"] == 995
    assert client.get_ticker("XAU/USD")["last"] == 2300.25
    assert len(client.get_kline("XAUUSD", "1H", 2)) == 2

    open_result = client.place_market_order("XAUUSD", "buy", 0.02)
    close_result = client.place_market_order("XAUUSD", "sell", 0.02, reduce_only=True)

    assert open_result.success is True
    assert open_result.exchange_order_id == "777"
    assert close_result.success is True
    assert "position" not in fake.sent[-2]
    assert fake.sent[-1]["position"] == 12345


def test_mt5_client_kline_accepts_numpy_like_rows(monkeypatch):
    fake = _fake_mt5()
    fake.copy_rates_from_pos = lambda symbol, timeframe, start, count: AmbiguousRows([
        {"time": 1, "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "tick_volume": 10},
        {"time": 2, "open": 1.5, "high": 2.5, "low": 1.0, "close": 2.0, "tick_volume": 11},
    ])
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake)
    monkeypatch.setattr(mt5_client_module, "_mt5", None)

    client = MT5Client(MT5Config(login=1, password="pw", server="CPT-Demo"))
    assert client.connect() is True
    assert len(client.get_kline("XAUUSD", "1h", 2)) == 2


def test_mt5_connect_accepts_saved_credential_id(monkeypatch):
    app = Flask(__name__)
    captured = {}

    class DummyClient:
        connected = True

        def __init__(self, config):
            self.config = config
            captured["config"] = config

        def connect(self):
            return True

        def get_connection_status(self):
            return {
                "connected": True,
                "login": self.config.login,
                "server": self.config.server,
            }

    monkeypatch.setattr(mt5_routes, "local_desktop_brokers_allowed", lambda: True)
    monkeypatch.setattr(mt5_routes, "_load_saved_mt5_config", lambda user_id, credential_id=0: {
        "credential_id": credential_id,
        "exchange_id": "cptmarkets",
        "broker": "CPT Markets",
        "mt5_login": "89958589",
        "mt5_password": "secret",
        "mt5_server": "CPTMarkets-Live",
        "mt5_path": r"C:\Program Files\CPT Markets MT5 Terminal\terminal64.exe",
        "mt5_timeout": 60000,
    })
    monkeypatch.setattr(mt5_routes, "MT5Client", DummyClient)
    monkeypatch.setattr(mt5_routes, "_save_or_update_mt5_credential", lambda user_id, config: 7)
    monkeypatch.setattr(mt5_routes._sessions, "set", lambda client: captured.setdefault("session", client))

    with app.test_request_context(json={"credential_id": 7}):
        g.user_id = 1
        response = mt5_routes.connect.__wrapped__()

    body = response.get_json()
    assert body["success"] is True
    assert body["data"]["credential_id"] == 7
    assert captured["config"].login == 89958589
    assert captured["config"].password == "secret"
    assert captured["config"].server == "CPTMarkets-Live"
    assert captured["session"].connected is True
