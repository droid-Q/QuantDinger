# Strategy API V2 策略开发指南

> 适用范围：当前 QuantDinger 可执行策略契约 Strategy API V2
> 面向读者：第一次编写策略的用户、指标转策略用户，以及需要同时覆盖回测与实盘的策略开发者

QuantDinger 只有一套当前可执行的 Python 策略契约：**Strategy API V2**。同一份源码会编译成策略清单，并由回测和实盘运行时共享标的、订阅、事件模型、订单意图、组合记账和保护规则。

策略源码拥有市场、标的、周期、调度和交易逻辑。运行面板只提供日期、初始资金、交易成本、源码允许范围内的杠杆，以及用户参数；它不能改写源码声明的市场、标的或周期。

图表指标是另一种产物。指标中的 plots、signals 和 layers 不能下单，必须先转换成 Strategy API V2。

---

## 1. 快速开始：最小可运行策略

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

运行步骤：

1. 在策略 IDE 新建脚本并粘贴源码。
2. 保存源码。
3. 调用验证或在界面点击验证，确认编译清单正确。
4. 选择回测日期、初始资金、手续费、滑点和参数。
5. 检查成交、已平仓交易、订单审计、权益曲线和持仓快照。
6. 只有回测符合预期后才创建部署；新部署默认为停止状态。

---

## 2. 编译器硬性要求与编写规范

编译器硬性要求：

- 源码非空且能在安全沙箱中执行。
- 必须定义 <code>initialize(context)</code>。
- <code>initialize</code> 必须通过 <code>context.set_universe(...)</code> 声明静态标的、指数或命名股票池。
- 如果未显式订阅，编译器会创建默认日线订阅；教程仍建议始终显式调用 <code>context.subscribe</code>。
- 必须存在 <code>handle_data</code>、<code>on_rebalance</code>，或至少注册一个定时回调。
- 杠杆策略必须满足 Crypto swap 专用规则。

项目编写规范还要求：

- 文件以三引号 docstring 开头；第一行是策略名称，后续说明标的、信号、调度和风控。
- 标识符和源码注释使用英文。
- 参数和交易原因使用稳定、可审计的名称。
- 禁止未来数据、隐式反手、无界加仓和不受控仓位。

<code>initialize</code> 在编译/清单发现阶段执行，用于声明配置和初始化 <code>g</code>。不要在这里请求行情、读取真实仓位或下单。

---

## 3. 源码拥有的策略清单

编译后清单包含：

- API 版本与源码哈希；
- CTA 或 portfolio 类型；
- 静态/动态 universe；
- 订阅标的、周期和字段；
- 定时任务；
- benchmark；
- 生命周期处理器；
- 因子和基本面依赖；
- warm-up 数量；
- 是否允许杠杆及最大杠杆；
- 自定义 metadata。

验证接口：

~~~http
POST /api/strategies/verify
Content-Type: application/json

{"code": "...complete Strategy API V2 source..."}
~~~

成功响应会返回 <code>valid: true</code> 和 manifest。部署前必须重新验证最终保存的源码，不要只验证早期草稿。

---

## 4. 标的规范

推荐使用规范标的：

| 市场 | 示例 |
| --- | --- |
| A 股 | <code>CNStock:600519.SH</code> |
| 美股 | <code>USStock:MSFT</code> |
| 港股 | <code>HKStock:00700.HK</code> |
| Crypto 现货 | <code>Crypto:BTC/USDT@spot</code> |
| 指定交易所 Crypto 现货 | <code>Crypto:BTC/USDT@okx:spot</code> |
| Crypto 永续 | <code>Crypto:BTC/USDT@swap</code> |
| 指定交易所 Crypto 永续 | <code>Crypto:BTC/USDT@okx:swap</code> |

系统也会规范化部分别名，例如 <code>600519.XSHG</code> → <code>CNStock:600519.SH</code>、<code>BTCUSDT</code> → <code>BTC/USDT</code>。

为避免歧义，生产策略应写完整市场前缀。Crypto 未写市场类型时默认为 spot。只有 swap 可以启用合约杠杆。

---

## 5. 静态和动态 universe

静态单标的：

~~~python
context.set_universe(["USStock:SPY"])
~~~

静态多标的：

~~~python
context.set_universe([
    "USStock:AAPL",
    "USStock:MSFT",
    "USStock:NVDA",
])
~~~

指数 universe：

~~~python
context.set_universe(index="INDEX:SP500")
members = get_index_stocks("INDEX:SP500")
~~~

平台命名股票池：

~~~python
context.set_universe(pool="sp500")
members = get_universe_stocks()
~~~

动态 universe 在每个历史时点解析当时成分，避免直接把今天的成分复制进历史回测。不要把 pool 成分硬编码进源码。

使用动态 universe、多个静态标的或 <code>on_rebalance</code> 时，清单通常分类为 portfolio；单一静态标的通常分类为 CTA。

---

## 6. 订阅、预热和 benchmark

~~~python
context.subscribe(
    frequency="1d",
    fields=["open", "high", "low", "close", "volume"],
)
context.set_warmup(260)
context.set_benchmark("USStock:SPY")
~~~

要点：

- 周期写在源码中，例如 <code>1m</code>、<code>5m</code>、<code>1h</code>、<code>4h</code>、<code>1d</code>、<code>1w</code>。
- <code>daily</code>、<code>day</code>、<code>d</code> 等别名会规范化为 <code>1d</code>。
- 未指定 symbols 时，订阅当前 universe。
- <code>set_warmup</code> 告诉数据服务在回测开始日前额外获取历史数据；它不代表策略可以跳过 <code>len(bars)</code> 检查。
- benchmark 只用于对比收益，不会自动交易。
- <code>get_history</code> 的 frequency 参数用于 API 兼容；当前运行时从已订阅数据取历史，因此调用周期应与订阅周期保持一致。

---

## 7. 生命周期与调度

支持的处理器：

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

定时任务：

~~~python
def initialize(context):
    context.set_universe(["USStock:SPY"])
    context.subscribe(frequency="5m")
    run_daily(rebalance, time="09:35")
    run_weekly(weekly_review, weekday=1, time="09:40")
    run_monthly(monthly_rebalance, monthday=1, time="09:45")
~~~

规则：

- <code>weekday</code> 使用 1–7，1 为星期一。
- 月度日期超出当月天数时会落在当月最后一天。
- 日线及更低频率下，具体 <code>time</code> 不用于制造不存在的盘中 bar。
- 回调推荐签名为 <code>callback(context, data)</code>；运行时也会适配只接收 context 的函数。
- portfolio 策略如果没有定时任务，会调用 <code>on_rebalance</code>。
- 当前引擎在每个事件时间戳调用 <code>before_trading_start</code> 和 <code>after_trading_end</code>；不要假设它们在分钟策略中每天只调用一次。

---

## 8. 最重要的时间语义

回测只向策略暴露当时可见的数据：

1. 进入新 bar 时，先执行上一 bar 收盘后排队的订单，成交参考当前 bar 开盘。
2. <code>before_trading_start</code> 和到期的定时回调只看到前一根及更早的数据；其订单可以在当前开盘处理。
3. 然后当前 bar 变为可见，调用 <code>handle_data</code>。
4. <code>handle_data</code> 根据当前已完成 bar 产生的订单排队到下一根 bar 开盘。
5. <code>after_trading_end</code> 同样能看到当前 bar；其新订单也等待下一根 bar。

因此，“收盘确认、下一开盘成交”是默认的无未来执行模型。不要用负 shift 或未来行把成交提前。

实盘会对每根已收盘 bar 只处理一次，并保留 <code>g</code> 状态。重复收到同一根 bar 不应重复触发策略。

---

## 9. context、data 和 g

常用 context 字段：

| 字段 | 含义 |
| --- | --- |
| <code>context.params</code> | 本次运行参数 |
| <code>context.current_dt</code> | 当前事件时间 |
| <code>context.previous_trading_date</code> | 上一个事件时间 |
| <code>context.portfolio.starting_cash</code> | 初始资金 |
| <code>context.portfolio.available_cash</code> | 可用现金 |
| <code>context.portfolio.total_value</code> | 当前总权益 |
| <code>context.portfolio.positions</code> | 当前持仓字典 |
| <code>context.data</code> | 数据视图 |

<code>data.current(symbol, field)</code> 读取当前可见值；<code>data.history(symbols, count, fields)</code> 读取历史；<code>data[symbol]</code> 返回当前可见 DataFrame。

跨回调状态放在 <code>g</code>：

~~~python
def initialize(context):
    g.last_signal = ""
    g.rebalance_count = 0
~~~

不要把用户状态放在文件、数据库或模块外部全局服务中。<code>g</code> 是单次运行的策略状态空间。

---

## 10. 参数

~~~python
# @param fast_period int 20 Fast moving-average period range=2:100:1
# @param slow_period int 50 Slow moving-average period range=3:250:1
# @param target_pct float 0.95 Target weight values=0.5,0.75,0.95
# @param enabled bool true Enable entries
~~~

读取：

~~~python
fast_period = int(context.params.get("fast_period", 20))
slow_period = int(context.params.get("slow_period", 50))
target_pct = float(context.params.get("target_pct", 0.95))
enabled = bool(context.params.get("enabled", True))
~~~

声明默认值和代码回退值必须一致。参数面板把用户值放入 <code>context.params</code>；若没有用户值，代码回退值是最后保障。

标的、市场、周期和杠杆许可属于源码契约，不要把它们伪装成可由运行面板任意覆盖的普通参数。

---

## 11. 历史数据、因子和基本面

单标的历史：

~~~python
bars = get_history(
    60,
    "1d",
    ["open", "high", "low", "close", "volume"],
    "USStock:SPY",
)
~~~

一个标的返回 DataFrame；多个标的返回以规范标的为键的 DataFrame 字典：

~~~python
frames = data.history(
    ["USStock:AAPL", "USStock:MSFT"],
    count=30,
    fields=["close", "volume"],
)
~~~

技术指标和因子：

~~~python
rsi_value = factor("rsi", g.symbol, period=14)
macd = indicator("MACD", g.symbol, fastperiod=12, slowperiod=26, signalperiod=9)
scores = get_factors(symbols, ["momentum_20", "volatility_20"])
~~~

基本面：

~~~python
fundamentals = get_fundamentals(
    ["PE", "PB", "ROE", "MARKET_CAP"],
    symbols,
)
~~~

常用公开别名还包括 <code>REVENUE_GROWTH</code>、<code>DEBT_TO_EQUITY</code> 和 <code>FREE_CASH_FLOW</code>。只使用平台真实支持、按时点可见的字段，不要发明字段或读取未来财报。

多标的 <code>factor</code>/<code>indicator</code> 调用必须传 symbol；只有单标的数据门户可以省略 symbol。

---

## 12. 仓位与订单 API

读取仓位：

~~~python
position = get_position(g.symbol)
all_positions = get_positions()
~~~

Position 常用字段：

- <code>symbol</code>
- <code>amount</code>
- <code>avg_cost</code>
- <code>last_price</code>
- <code>market_value</code>

订单函数：

| 函数 | 含义 |
| --- | --- |
| <code>order(symbol, amount)</code> | 增减指定数量 |
| <code>order_value(symbol, value)</code> | 增减指定报价币价值 |
| <code>order_target(symbol, amount)</code> | 把持仓调整到目标数量 |
| <code>order_target_value(symbol, value)</code> | 调整到目标价值 |
| <code>order_target_percent(symbol, percent)</code> | 调整到组合权益的目标比例 |

目标型 API 最适合可重复执行的再平衡逻辑。每个订单都应提供稳定的 <code>reason</code>：

~~~python
order_target_percent(
    g.symbol,
    0.5,
    reason="breakout_long_entry",
)
~~~

现货和所有非 Crypto 市场当前按 long-only 编写。多头离场条件与空头入场条件必须独立；不要把 <code>target=0</code> 的离场自动改成负仓位。

引擎会处理手续费、滑点、最小交易单位、成交量上限、涨跌停和停牌。被延迟或拒绝的订单会出现在订单审计账本中，不应从“没有成交”直接推断策略没有发单。

---

## 13. 止损、止盈、追踪和时间保护

随开仓声明：

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

或设置后续开仓的默认保护：

~~~python
set_default_protection(
    stop_loss_pct=0.03,
    take_profit_pct=0.08,
)
~~~

所有 pct 都使用小数比率，<code>0.03</code> 表示 3%。保护值会限制在安全范围内；负值按 0 处理。

回测规则：

- 跳空越过保护价时按可成交的 bar 开盘价处理。
- bar 内触发按触发价处理。
- 同一 bar 同时触发多个保护时，默认 conservative 模式优先止损，再追踪止损、时间限制、止盈。

实盘使用独立价格时钟检查同样的保护语义，不必等待下一根策略 bar。保护状态会保存并可在会话重启后恢复。

---

## 14. 杠杆和做空

只有 universe 中全部静态标的都是 Crypto swap 时，源码才能声明：

~~~python
def initialize(context):
    g.symbol = "Crypto:BTC/USDT@okx:swap"
    context.set_universe([g.symbol])
    context.subscribe(frequency="1h")
    context.allow_leverage(max_leverage=5)
~~~

规则：

- Crypto spot、股票、指数/股票池和其他非 Crypto 市场不能调用 <code>allow_leverage</code>。
- 动态 universe 不能启用合约杠杆。
- 回测或部署选择的杠杆不能超过源码声明的最大值。
- 源码没有许可时，运行面板不能强制开启杠杆。
- 用户选择的杠杆由运行时应用，不要再在订单金额中手工乘一次。
- 做空只应出现在 swap 策略中，并且必须有独立的空头入场、空头离场和风险规则。

### 交易方向能力

新的 Crypto swap 策略应在 `initialize` 中声明方向能力：

~~~python
context.set_metadata(direction_mode="both")
~~~

支持 `long_only`（仅做多）、`short_only`（仅做空）、`both`（多空双向）和 `neutral`（中性双腿）。这个声明不会下单，也不会覆盖策略信号；它用于在部署时分配正确的双向持仓腿，并拒绝超出声明能力的新开仓信号。`both` 和 `neutral` 在实盘中要求交易所账户开启双向持仓模式。

编译器仍会兼容识别旧策略顶层的 `DIRECTION = 1/-1` 常量，以及订单中的字面量 `position_side="long"/"short"`。如果无法安全推断旧版合约策略，部署页面才会要求选择兼容模式。现货策略会自动视为 `long_only`。

---

## 15. 完整 CTA 教程：双 EMA 趋势策略

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

为什么这样写：

- universe、周期和 benchmark 都在源码中。
- warm-up 覆盖慢 EMA，但仍检查实际数据长度。
- 快慢周期错误时直接停止本 bar。
- 入场与离场互斥，死叉只平多，不开空。
- 读取当前已完成日线后发单，下一根开盘成交。
- 只有入场附带保护，离场目标为 0。

---

## 16. Portfolio 教程：每周因子再平衡

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

此类策略必须使用按时点解析的 universe 和因子数据。回测还要关注覆盖率、幸存者偏差、换手、交易成本、最小交易单位和无法成交订单。

---

## 17. 回测、结果和诊断

回测请求的核心字段：

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

还可以传 <code>sourceId</code> 或 <code>strategyId</code> 读取已保存源码。市场、标的和周期不能从请求覆盖。

重点检查：

- <code>resultStatus</code>：<code>no_signals</code>、<code>open_position_only</code> 或 <code>completed_trades</code>。
- <code>totalExecutions</code>：实际成交次数。
- <code>totalTrades</code>：已平仓交易次数，不等于成交次数。
- <code>rawTrades</code>/<code>executions</code>：开仓、加仓、减仓、平仓成交。
- <code>closedTrades</code>：完整往返交易。
- <code>orderLedger</code>：成交、延迟、拒绝及原因。
- <code>holdingSnapshots</code>、<code>rebalanceRecords</code>：组合过程。
- <code>equityCurve</code>、回撤、胜率、Profit Factor 和 benchmark/excess return。
- <code>dataProvenance</code> 和 <code>executionAssumptions</code>：数据来源与执行假设。

零成交不一定是系统错误：可能是数据不足、条件从未触发、参数不合理、标的无数据或订单被拒绝。先看日志和 orderLedger。

---

## 18. 部署与实盘边界

部署核心字段包括：

- <code>sourceId</code>
- <code>name</code>
- <code>initialCapital</code>
- <code>executionMode</code>：<code>signal</code> 或 <code>live</code>
- 可选 <code>credentialId</code>、<code>params</code>、杠杆、仓位方向和通知配置

部署创建后状态为 stopped，必须显式 start。删除前必须先停止。

当前 live 账户边界：

- Crypto live 需要受支持交易所凭证。
- USStock live 需要 Alpaca 或 IBKR 凭证。
- 混合市场 live 不支持。
- 其他市场不能强行用不匹配的凭证部署。

先用 signal 模式验证通知、信号频率和状态恢复，再考虑 live。回测通过不代表连接、余额、最小下单量、交易所规则和网络状态一定满足实盘。

---

## 19. 安全限制和常见失败

策略运行在安全执行环境中。禁止文件、网络、数据库、进程、动态执行、反射和不安全导入。不要使用 <code>eval</code>、<code>exec</code>、<code>compile</code>、<code>open</code>、dunder 绕过或外部状态。

常见编译错误：

| 错误 | 含义 | 修复 |
| --- | --- | --- |
| <code>strategyV2.codeRequired</code> | 源码为空 | 提交完整源码 |
| <code>strategyV2.initializeRequired</code> | 缺少 initialize | 添加初始化函数 |
| <code>strategyV2.initializeFailed:...</code> | 初始化执行失败 | 只在 initialize 做声明和状态初始化 |
| <code>strategyV2.universeRequired</code> | 未声明 universe | 调用 <code>set_universe</code> |
| <code>strategyV2.handlerRequired</code> | 没有可执行处理器/定时任务 | 添加 handler 或 schedule |
| <code>strategyV2.leverageCryptoSwapOnly</code> | 杠杆市场不合法 | 仅用于静态 Crypto swap |
| <code>strategyV2.leverageNotAllowed</code> | 面板开了源码未许可的杠杆 | 源码合法许可或关闭杠杆 |
| <code>strategyV2.leverageExceedsStrategyLimit</code> | 请求杠杆超过上限 | 降低请求值 |
| <code>strategyV2.dataUnavailable:...</code> | 标的没有可用数据 | 检查规范标的和数据范围 |
| <code>strategyV2.runtimeFailed:...</code> | 回调运行异常 | 根据处理器名和原始异常修复 |

---

## 20. 发布前检查清单

- [ ] 文件有英文 docstring，说明名称、universe、信号、调度和风控。
- [ ] <code>initialize</code> 只声明 universe、订阅、预热、benchmark、调度、杠杆许可和初始 <code>g</code>。
- [ ] 标的使用规范格式，Crypto 明确 spot/swap。
- [ ] 源码拥有标的和周期，不依赖运行面板覆盖。
- [ ] 参数默认值与代码回退值一致。
- [ ] 所有历史窗口都检查长度。
- [ ] 不使用未来行、负 shift 或居中 rolling。
- [ ] 多头离场与空头入场独立。
- [ ] 仓位有明确上限；网格、DCA、马丁和加仓层数有硬限制。
- [ ] 订单都有可审计 reason。
- [ ] 风险百分比使用小数比率。
- [ ] 只对 Crypto swap 声明杠杆，且不重复乘杠杆。
- [ ] 已验证 manifest。
- [ ] 已检查 orderLedger，而不只看收益曲线。
- [ ] 已用不同时间区间和成本假设做稳健性测试。
- [ ] 已有至少一次成功回测后再发布。
- [ ] live 前先确认凭证、市场、余额、最小交易单位和通知。
