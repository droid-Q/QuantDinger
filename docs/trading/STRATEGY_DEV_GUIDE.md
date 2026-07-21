# Strategy API V2 Development Guide

> Applies to: the current executable QuantDinger strategy contract
> Audience: first-time strategy authors, indicator-conversion users, and developers targeting both backtest and live execution

QuantDinger has one current executable Python strategy contract: **Strategy API V2**. The same source compiles into a strategy manifest used by backtest and live runtimes for instruments, subscriptions, events, order intents, portfolio accounting, and protection rules.

The source owns its market, instruments, frequency, schedules, and trading logic. Run forms provide dates, initial capital, costs, source-permitted leverage, and user parameters; they do not override source-controlled markets, symbols, or timeframes.

Chart indicators are separate artifacts. Their plots, signals, and layers cannot place orders. Convert an indicator into Strategy API V2 before backtesting or deploying it.

---

## 1. Quick start: a minimal executable strategy

~~~python
"""SPY 20-Day Moving Average
Trades a long-only SPY regime from completed daily bars.
"""

# @param period int 20 Moving-average period range=5:100:5
# @param target_pct float 0.95 Target portfolio weight range=0.1:1.0:0.05


def initialize(context):
    g.symbol = "USStock:SPY"
    context.set_universe([g.symbol])
    context.subscribe(
        frequency="1d",
        fields=["open", "high", "low", "close", "volume"],
    )
    context.set_warmup(120)
    context.set_benchmark("USStock:SPY")


def handle_data(context, data):
    period = int(context.params.get("period", 20))
    target_pct = float(context.params.get("target_pct", 0.95))

    bars = get_history(
        period + 1,
        "1d",
        "close",
        g.symbol,
    )
    if len(bars) < period:
        return

    price = float(bars["close"].iloc[-1])
    average = float(bars["close"].tail(period).mean())
    position = get_position(g.symbol)
    desired = target_pct if price > average else 0.0

    if desired > 0 and position.amount <= 0:
        order_target_percent(
            g.symbol,
            desired,
            reason="ma_long_entry",
            stop_loss_pct=0.05,
        )
    elif desired == 0 and position.amount > 0:
        order_target_percent(
            g.symbol,
            0.0,
            reason="ma_long_exit",
        )
~~~

Workflow:

1. Create a script in the Strategy IDE and paste the source.
2. Save the source.
3. Verify it and inspect the compiled manifest.
4. Choose dates, capital, commission, slippage, and parameters.
5. Inspect executions, closed trades, the order ledger, equity, and holdings.
6. Create a deployment only after the backtest behaves as intended. New deployments start stopped.

---

## 2. Compiler requirements and authoring standard

Hard compiler requirements:

- Source is non-empty and executes in the safe sandbox.
- <code>initialize(context)</code> exists.
- <code>initialize</code> declares a static universe, index, or named pool through <code>context.set_universe(...)</code>.
- If no subscription is declared, the compiler adds a default daily subscription; this guide still recommends an explicit <code>context.subscribe</code>.
- The source exposes <code>handle_data</code>, <code>on_rebalance</code>, or at least one registered schedule callback.
- Leveraged strategies satisfy the Crypto-swap-only policy.

The project authoring standard additionally requires:

- Start with a triple-quoted docstring. Its first line is the strategy name; following lines describe universe, signals, schedule, and risk.
- Use English identifiers and source comments.
- Use stable, auditable parameter and reason names.
- Avoid look-ahead, implicit reversals, unbounded scaling, and uncapped exposure.

<code>initialize</code> runs during compilation/manifest discovery. Use it for declarations and initial <code>g</code> state. Do not request market data, inspect real positions, or place orders there.

---

## 3. The source-owned manifest

Compilation discovers:

- API version and source hash;
- CTA or portfolio classification;
- static or dynamic universe;
- subscribed instruments, frequency, and fields;
- schedules;
- benchmark;
- lifecycle handlers;
- factor and fundamental dependencies;
- warm-up bars;
- leverage permission and maximum;
- custom metadata.

Verification endpoint:

~~~http
POST /api/strategies/verify
Content-Type: application/json

{"code": "...complete Strategy API V2 source..."}
~~~

A valid response contains <code>valid: true</code> and the manifest. Verify the final saved source before deployment, not only an earlier draft.

---

## 4. Canonical instruments

| Market | Example |
| --- | --- |
| China A-share | <code>CNStock:600519.SH</code> |
| US equity | <code>USStock:MSFT</code> |
| Hong Kong equity | <code>HKStock:00700.HK</code> |
| Crypto spot | <code>Crypto:BTC/USDT@spot</code> |
| Venue-specific Crypto spot | <code>Crypto:BTC/USDT@okx:spot</code> |
| Crypto perpetual | <code>Crypto:BTC/USDT@swap</code> |
| Venue-specific perpetual | <code>Crypto:BTC/USDT@okx:swap</code> |

The parser also normalizes selected aliases, such as <code>600519.XSHG</code> to <code>CNStock:600519.SH</code> and <code>BTCUSDT</code> to <code>BTC/USDT</code>.

Production strategies should use the full market prefix. Crypto defaults to spot when no market type is present. Only swap instruments can permit contract leverage.

---

## 5. Static and dynamic universes

Static single instrument:

~~~python
context.set_universe(["USStock:SPY"])
~~~

Static basket:

~~~python
context.set_universe([
    "USStock:AAPL",
    "USStock:MSFT",
    "USStock:NVDA",
])
~~~

Index universe:

~~~python
context.set_universe(index="INDEX:SP500")
members = get_index_stocks("INDEX:SP500")
~~~

Named platform pool:

~~~python
context.set_universe(pool="sp500")
members = get_universe_stocks()
~~~

Dynamic universes resolve point-in-time constituents. Do not copy today's pool members into source and then use them for a historical backtest.

A dynamic universe, more than one static instrument, or <code>on_rebalance</code> normally classifies the manifest as portfolio. One static instrument normally classifies it as CTA.

---

## 6. Subscriptions, warm-up, and benchmark

~~~python
context.subscribe(
    frequency="1d",
    fields=["open", "high", "low", "close", "volume"],
)
context.set_warmup(260)
context.set_benchmark("USStock:SPY")
~~~

Rules:

- Frequency belongs in source, for example <code>1m</code>, <code>5m</code>, <code>1h</code>, <code>4h</code>, <code>1d</code>, or <code>1w</code>.
- Aliases such as <code>daily</code>, <code>day</code>, and <code>d</code> normalize to <code>1d</code>.
- Omitting symbols subscribes the current universe.
- <code>set_warmup</code> asks the data service for history before the requested backtest start. It does not remove the need for <code>len(bars)</code> guards.
- A benchmark is for comparison; it is not traded automatically.
- The <code>get_history</code> frequency argument is API-compatible metadata. The current runtime reads subscribed frames, so request the same frequency the source subscribes.

---

## 7. Lifecycle and schedules

Supported handlers:

~~~python
def initialize(context):
    pass

def before_trading_start(context, data):
    pass

def handle_data(context, data):
    pass

def on_rebalance(context, panel):
    pass

def after_trading_end(context, data):
    pass
~~~

Schedule registration:

~~~python
def initialize(context):
    context.set_universe(["USStock:SPY"])
    context.subscribe(frequency="5m")
    run_daily(rebalance, time="09:35")
    run_weekly(weekly_review, weekday=1, time="09:40")
    run_monthly(monthly_rebalance, monthday=1, time="09:45")
~~~

Rules:

- <code>weekday</code> is 1–7, with Monday as 1.
- A monthday past the end of a month resolves to that month's last day.
- On daily or lower-frequency bars, a specific intraday time does not create a nonexistent bar.
- Prefer <code>callback(context, data)</code>; the runtime also adapts callbacks that accept only context.
- A portfolio strategy with no registered schedules invokes <code>on_rebalance</code>.
- The current engine invokes <code>before_trading_start</code> and <code>after_trading_end</code> for every event timestamp. Do not assume they run only once per calendar day in an intraday strategy.

---

## 8. The critical timing model

Backtests expose only point-in-time-visible data:

1. At a new bar, orders queued after the previous close execute first, using the current open.
2. <code>before_trading_start</code> and due schedule callbacks see data only through the previous bar; their orders can be processed at the current open.
3. The current completed bar becomes visible and <code>handle_data</code> runs.
4. Orders emitted by <code>handle_data</code> wait for the next bar open.
5. <code>after_trading_end</code> also sees the current bar; its new orders wait for the next bar.

This implements “confirm on close, fill at next open” without future leakage. Never use negative shifts or future rows to move execution earlier.

Live sessions process each closed bar once and preserve <code>g</code> state. Receiving the same bar twice should not duplicate strategy work.

---

## 9. context, data, and g

Common context fields:

| Field | Meaning |
| --- | --- |
| <code>context.params</code> | run parameters |
| <code>context.current_dt</code> | current event timestamp |
| <code>context.previous_trading_date</code> | previous event timestamp |
| <code>context.portfolio.starting_cash</code> | initial capital |
| <code>context.portfolio.available_cash</code> | available cash |
| <code>context.portfolio.total_value</code> | current equity |
| <code>context.portfolio.positions</code> | current position map |
| <code>context.data</code> | data view |

Use <code>data.current(symbol, field)</code> for a current visible value, <code>data.history(symbols, count, fields)</code> for history, and <code>data[symbol]</code> for its current visible DataFrame.

Persist state across callbacks on <code>g</code>:

~~~python
def initialize(context):
    g.last_signal = ""
    g.rebalance_count = 0
~~~

Do not store strategy state in files, databases, or external module services. <code>g</code> is the per-run user state namespace.

---

## 10. Parameters

~~~python
# @param fast_period int 20 Fast moving-average period range=2:100:1
# @param slow_period int 50 Slow moving-average period range=3:250:1
# @param target_pct float 0.95 Target weight values=0.5,0.75,0.95
# @param enabled bool true Enable entries
~~~

Read values through context:

~~~python
fast_period = int(context.params.get("fast_period", 20))
slow_period = int(context.params.get("slow_period", 50))
target_pct = float(context.params.get("target_pct", 0.95))
enabled = bool(context.params.get("enabled", True))
~~~

Declared defaults and code fallbacks must agree. The parameter panel supplies <code>context.params</code>; the fallback remains the final default when a value is absent.

Symbols, market, timeframe, and leverage permission are source contract fields. Do not disguise them as ordinary run-form overrides.

---

## 11. History, factors, and fundamentals

Single-instrument history:

~~~python
bars = get_history(
    60,
    "1d",
    ["open", "high", "low", "close", "volume"],
    "USStock:SPY",
)
~~~

One instrument returns a DataFrame. Multiple instruments return a dict of canonical instrument keys to DataFrames:

~~~python
frames = data.history(
    ["USStock:AAPL", "USStock:MSFT"],
    count=30,
    fields=["close", "volume"],
)
~~~

Technical indicators and factors:

~~~python
rsi_value = factor("rsi", g.symbol, period=14)
macd = indicator("MACD", g.symbol, fastperiod=12, slowperiod=26, signalperiod=9)
scores = get_factors(symbols, ["momentum_20", "volatility_20"])
~~~

Fundamentals:

~~~python
fundamentals = get_fundamentals(
    ["PE", "PB", "ROE", "MARKET_CAP"],
    symbols,
)
~~~

Other public aliases include <code>REVENUE_GROWTH</code>, <code>DEBT_TO_EQUITY</code>, and <code>FREE_CASH_FLOW</code>. Use only real point-in-time fields supported by the platform; do not invent fields or read future reports.

Pass a symbol to <code>factor</code>/<code>indicator</code> in a multi-asset strategy. The symbol may be omitted only when the data portal has exactly one instrument.

---

## 12. Positions and order APIs

Read positions:

~~~python
position = get_position(g.symbol)
all_positions = get_positions()
~~~

Common Position fields:

- <code>symbol</code>
- <code>amount</code>
- <code>avg_cost</code>
- <code>last_price</code>
- <code>market_value</code>

Order functions:

| Function | Meaning |
| --- | --- |
| <code>order(symbol, amount)</code> | add/subtract a quantity |
| <code>order_value(symbol, value)</code> | add/subtract quote-currency value |
| <code>order_target(symbol, amount)</code> | set a target quantity |
| <code>order_target_value(symbol, value)</code> | set a target quote value |
| <code>order_target_percent(symbol, percent)</code> | set a target share of portfolio equity |

Target APIs are usually best for repeatable rebalancing. Give every order a stable reason:

~~~python
order_target_percent(
    g.symbol,
    0.5,
    reason="breakout_long_entry",
)
~~~

Write spot and all non-Crypto markets as long-only under the current product policy. A long exit and a short entry are independent; do not turn a zero target into a negative position automatically.

The engine accounts for commission, slippage, lot size, liquidity caps, price limits, and suspensions. Deferred and rejected requests appear in the order audit ledger. “No fill” does not necessarily mean “no signal.”

---

## 13. Stop, take-profit, trailing, and time protection

Attach protection to an entry:

~~~python
order_target_percent(
    g.symbol,
    0.8,
    reason="breakout_long_entry",
    stop_loss_pct=0.03,
    take_profit_pct=0.08,
    trailing_stop_pct=0.025,
    trailing_activation_pct=0.02,
    time_limit_seconds=86400 * 10,
)
~~~

Or set defaults for later entries:

~~~python
set_default_protection(
    stop_loss_pct=0.03,
    take_profit_pct=0.08,
)
~~~

Percentage fields are ratios: <code>0.03</code> means 3%. Values are clamped to safe ranges, and negatives become zero.

Backtest behavior:

- A gap through a protection threshold fills at the available bar open.
- An intrabar touch fills at the trigger price.
- If several protections trigger in one bar, conservative mode prioritizes stop-loss, trailing stop, time limit, then take-profit.

Live execution checks the same protection semantics on an independent price clock instead of waiting for the next strategy bar. Protection state can be persisted and restored after a session restart.

---

## 14. Leverage and shorting

Only a static universe consisting entirely of Crypto swap instruments may declare:

~~~python
def initialize(context):
    g.symbol = "Crypto:BTC/USDT@okx:swap"
    context.set_universe([g.symbol])
    context.subscribe(frequency="1h")
    context.allow_leverage(max_leverage=5)
~~~

Rules:

- Do not call <code>allow_leverage</code> for Crypto spot, equities, index/pool universes, or non-Crypto markets.
- Dynamic universes cannot enable contract leverage.
- Backtest/deployment leverage cannot exceed the source maximum.
- A run form cannot force leverage on when the source has not permitted it.
- The runtime applies the selected leverage; do not multiply order sizing by leverage again.
- Shorting belongs only in swap strategies and requires independent short-entry, short-exit, and risk rules.

### Trading-direction capability

New Crypto swap strategies should declare their capability in `initialize`:

~~~python
context.set_metadata(direction_mode="both")
~~~

Supported values are `long_only`, `short_only`, `both`, and `neutral`. This declaration does not place orders or override strategy signals. It lets deployment validation reserve the correct hedge-mode leg or legs and reject new entry signals that exceed the declared capability. `both` and `neutral` require hedge mode for live execution.

The compiler still recognizes legacy top-level `DIRECTION = 1/-1` constants and literal `position_side="long"/"short"` order arguments. If a legacy swap strategy cannot be inferred safely, the deployment form asks for a compatibility mode. Spot strategies are treated as `long_only` automatically.

---

## 15. Complete CTA tutorial: dual EMA trend

~~~python
"""Dual EMA Long Trend
Trades a long-only daily SPY trend with a protected entry and next-open fills.
"""

# @param fast_period int 20 Fast EMA period range=5:80:5
# @param slow_period int 50 Slow EMA period range=20:250:10
# @param target_pct float 0.95 Target portfolio weight range=0.1:1.0:0.05
# @param stop_loss_pct float 0.05 Entry stop-loss ratio range=0.01:0.15:0.01


def initialize(context):
    g.symbol = "USStock:SPY"
    context.set_universe([g.symbol])
    context.subscribe(frequency="1d")
    context.set_warmup(300)
    context.set_benchmark("USStock:SPY")


def handle_data(context, data):
    fast_period = int(context.params.get("fast_period", 20))
    slow_period = int(context.params.get("slow_period", 50))
    target_pct = float(context.params.get("target_pct", 0.95))
    stop_loss_pct = float(context.params.get("stop_loss_pct", 0.05))

    if fast_period >= slow_period:
        log.warning("fast_period must be smaller than slow_period")
        return

    bars = get_history(
        slow_period + 2,
        "1d",
        "close",
        g.symbol,
    )
    if len(bars) < slow_period + 1:
        return

    close = bars["close"]
    fast_now = float(close.ewm(span=fast_period, adjust=False).mean().iloc[-1])
    slow_now = float(close.ewm(span=slow_period, adjust=False).mean().iloc[-1])
    position = get_position(g.symbol)

    if fast_now > slow_now and position.amount <= 0:
        order_target_percent(
            g.symbol,
            target_pct,
            reason="dual_ema_long_entry",
            stop_loss_pct=stop_loss_pct,
        )
    elif fast_now < slow_now and position.amount > 0:
        order_target_percent(
            g.symbol,
            0.0,
            reason="dual_ema_long_exit",
        )
~~~

Why it is structured this way:

- Universe, frequency, and benchmark live in source.
- Warm-up covers the slow EMA, while runtime length is still checked.
- Invalid fast/slow combinations stop the current event.
- Entry and exit are exclusive; the bearish condition exits a long but does not short.
- A completed daily bar emits an order for the next open.
- Protection is attached to the entry; the exit targets zero.

---

## 16. Portfolio tutorial: weekly factor rebalance

~~~python
"""S&P 500 Momentum Basket
Selects the strongest five point-in-time pool members and rebalances weekly.
"""

# @param holdings int 5 Number of holdings range=3:20:1
# @param max_weight float 0.18 Maximum weight per holding range=0.05:0.3:0.01


def initialize(context):
    context.set_universe(pool="sp500")
    context.subscribe(frequency="1d")
    context.set_warmup(80)
    context.set_benchmark("USStock:SPY")
    run_weekly(rebalance, weekday=1, time="09:35")


def rebalance(context, data):
    holdings = int(context.params.get("holdings", 5))
    max_weight = float(context.params.get("max_weight", 0.18))
    symbols = get_universe_stocks()
    if len(symbols) < holdings:
        return

    scores = get_factors(symbols, "momentum_20")
    if scores.empty or "momentum_20" not in scores.columns:
        return

    ranked = scores["momentum_20"].dropna().sort_values(ascending=False)
    selected = list(ranked.head(holdings).index)
    if not selected:
        return

    target_weight = min(max_weight, 0.95 / len(selected))
    current = get_positions()

    for symbol in current:
        if symbol not in selected:
            order_target_percent(symbol, 0.0, reason="weekly_remove")

    for symbol in selected:
        order_target_percent(symbol, target_weight, reason="weekly_select")
~~~

This strategy class must use point-in-time universe and factor data. Evaluate coverage, survivorship bias, turnover, trading costs, lot sizes, and unfilled orders in addition to headline return.

---

## 17. Backtests, results, and diagnosis

Core backtest request:

~~~json
{
  "code": "...",
  "startDate": "2024-01-01",
  "endDate": "2025-12-31",
  "initialCapital": 100000,
  "commission": 0.0005,
  "slippage": 0.0005,
  "leverageEnabled": false,
  "leverage": 1,
  "params": {},
  "persist": true
}
~~~

You may supply <code>sourceId</code> or <code>strategyId</code> to load saved source. The request cannot override source markets, instruments, or frequency.

Inspect:

- <code>resultStatus</code>: <code>no_signals</code>, <code>open_position_only</code>, or <code>completed_trades</code>.
- <code>totalExecutions</code>: fill count.
- <code>totalTrades</code>: closed round-trip count, not fill count.
- <code>rawTrades</code>/<code>executions</code>: opens, adds, reductions, and closes.
- <code>closedTrades</code>: completed round trips.
- <code>orderLedger</code>: fills, deferrals, rejections, and reasons.
- <code>holdingSnapshots</code>/<code>rebalanceRecords</code>: portfolio evolution.
- <code>equityCurve</code>, drawdown, win rate, Profit Factor, benchmark, and excess return.
- <code>dataProvenance</code>/<code>executionAssumptions</code>: data origin and fill model.

Zero executions can be valid: insufficient history, conditions never met, poor parameters, missing data, or rejected orders. Read logs and the order ledger before treating it as an engine failure.

---

## 18. Deployment and live boundaries

Core deployment fields include:

- <code>sourceId</code>
- <code>name</code>
- <code>initialCapital</code>
- <code>executionMode</code>: <code>signal</code> or <code>live</code>
- optional <code>credentialId</code>, <code>params</code>, leverage, position side, and notifications

A new deployment is stopped and must be started explicitly. Stop it before deletion.

Current live-account boundaries:

- Crypto live execution requires a supported exchange credential.
- USStock live execution requires Alpaca or IBKR.
- Mixed-market live deployment is unsupported.
- Other markets cannot be forced through a mismatched credential.

Use signal mode first to validate notifications, signal frequency, and state restoration. A successful backtest does not prove that credentials, balances, venue rules, minimum order sizes, and network health are ready for live trading.

---

## 19. Sandbox and common failures

Strategy source runs in a safe execution environment. File, network, database, process, dynamic execution, reflection, and unsafe imports are prohibited. Do not use <code>eval</code>, <code>exec</code>, <code>compile</code>, <code>open</code>, dunder bypasses, or external state.

| Error | Meaning | Fix |
| --- | --- | --- |
| <code>strategyV2.codeRequired</code> | empty source | submit complete source |
| <code>strategyV2.initializeRequired</code> | initialize missing | add it |
| <code>strategyV2.initializeFailed:...</code> | initialization failed | keep initialize declarative |
| <code>strategyV2.universeRequired</code> | universe missing | call <code>set_universe</code> |
| <code>strategyV2.handlerRequired</code> | no handler/schedule | add a handler or schedule |
| <code>strategyV2.leverageCryptoSwapOnly</code> | invalid leverage market | use static Crypto swaps only |
| <code>strategyV2.leverageNotAllowed</code> | run requests unpermitted leverage | permit it legally or disable it |
| <code>strategyV2.leverageExceedsStrategyLimit</code> | requested leverage too high | lower the request |
| <code>strategyV2.dataUnavailable:...</code> | instrument data unavailable | check canonical symbol and range |
| <code>strategyV2.runtimeFailed:...</code> | handler raised | inspect the named handler and cause |

---

## 20. Pre-publication checklist

- [ ] The file has an English docstring covering name, universe, signals, schedule, and risk.
- [ ] <code>initialize</code> only declares universe, subscription, warm-up, benchmark, schedules, leverage permission, and initial <code>g</code>.
- [ ] Instruments are canonical and Crypto explicitly distinguishes spot/swap.
- [ ] The source owns instruments and frequency; no run-form override is assumed.
- [ ] Parameter defaults and code fallbacks agree.
- [ ] Every history window checks actual length.
- [ ] No future rows, negative shifts, or centered rolling.
- [ ] Long exits and short entries are independent.
- [ ] Exposure is capped; grid, DCA, martingale, and scaling layers have hard limits.
- [ ] Every order has an auditable reason.
- [ ] Risk percentages use decimal ratios.
- [ ] Leverage is declared only for Crypto swaps and is not multiplied twice.
- [ ] The manifest verifies successfully.
- [ ] The order ledger is reviewed, not only the equity curve.
- [ ] Robustness is tested across periods and cost assumptions.
- [ ] At least one successful backtest exists before publication.
- [ ] Credentials, market, balance, lot size, and notifications are checked before live use.
