# QuantDinger MCP Server

The MCP server is a thin, tenant-scoped wrapper over `/api/agent/v1`. It exposes market data, chart-indicator authoring, Strategy API V2 deployment and backtesting, bounded job polling, runtime controls, and explicitly confirmed quick orders.

## Install and run

```bash
pip install "quantdinger-mcp==0.4.0"
export QUANTDINGER_BASE_URL=http://localhost:8888
export QUANTDINGER_AGENT_TOKEN=qd_agent_xxx
quantdinger-mcp
```

`pipx install quantdinger-mcp` and `uvx quantdinger-mcp` are also supported. Use `pip install -e ./mcp_server` only when developing from a repository checkout.

The default transport is `stdio`. Set `QUANTDINGER_MCP_TRANSPORT` to `sse` or `streamable-http` for a network transport. Optional limits include `QUANTDINGER_TIMEOUT_S`, `QUANTDINGER_MCP_JOB_STREAM_MAX_EVENTS`, `QUANTDINGER_MCP_JOB_STREAM_MAX_SECONDS`, and `QUANTDINGER_MCP_JOB_POLL_MAX_SECONDS`.

Network transports bound to a non-loopback host require a separate inbound bearer token. This token authenticates MCP clients and must not be the Agent Gateway token:

```bash
export QUANTDINGER_MCP_TRANSPORT=streamable-http
export QUANTDINGER_MCP_HOST=0.0.0.0
export QUANTDINGER_MCP_PORT=7800
export QUANTDINGER_MCP_PUBLIC_URL=https://mcp.example.com
export QUANTDINGER_MCP_AUTH_TOKEN=replace-with-a-random-32-plus-character-secret
quantdinger-mcp
```

Clients must send `Authorization: Bearer <QUANTDINGER_MCP_AUTH_TOKEN>` to `/mcp` or `/sse`. For a private ingress that already authenticates every request, `QUANTDINGER_MCP_ALLOW_INSECURE_HTTP=true` is an explicit escape hatch; never use it on a directly reachable public listener.

Docker builds use the official PyPI index by default. In regions where it is slow, override it without editing the image definition: `docker build --build-arg PIP_INDEX_URL=https://your-mirror.example/simple .`.

Never place an agent token in prompts, logs, screenshots, source control, or MCP configuration that will be shared. Responses redact credential fields, and clients must not attempt to recover them.

## Tool surface

| Tool group | Scope | Purpose |
|---|---:|---|
| `whoami`, `check_health` | R/public | Identity, allowlists, and liveness |
| `list_markets`, `search_symbols`, `get_klines`, `get_price` | R | Market discovery and data |
| `get_indicator_authoring_contract`, `validate_indicator_code`, `save_indicator`, `list_indicators`, `get_indicator` | R/W | Chart-only indicators |
| `list_strategy_templates`, `compile_strategy_code` | R | Strategy API V2 templates and manifest compilation |
| `list_strategy_sources`, `get_strategy_source`, `save_strategy_source` | R/W | Private Strategy API V2 source library |
| `list_strategy_source_versions`, `restore_strategy_source_version` | R/W | Source history and explicitly confirmed restore |
| `create_strategy`, `update_strategy`, `list_strategies`, `get_strategy` | R/W | Strategy API V2 deployments |
| `submit_backtest` | B | Strategy API V2 backtest job |
| `list_jobs`, `get_job`, `wait_for_job`, `stream_job_until_done` | R | Bounded async-job access |
| `runtime_overview`, `stop_strategy` | R/T | Runtime inspection and confirmed stop |
| `place_quick_order` | T | Explicitly confirmed quick order |
| `list_portfolio_positions`, `list_paper_orders` | R | Portfolio and paper-order reads |
| `cancel_open_paper_orders` | T | Explicitly confirmed paper-order kill switch |

`stop_strategy` requires `confirm_stop=true`. `place_quick_order` requires `confirm_order=true`; a live-capable token also requires `confirm_live_trading=true`. Optional `tp_price` and `sl_price` protection are forwarded to the shared Quick Trade execution path. Server-side trading flags and token allowlists still apply; a live-capable token receives an error instead of silently falling back to paper when live trading is disabled.

## Strategy API V2 workflow

Executable strategy code must define `initialize(context)` and declare its universe and subscriptions. It must provide `handle_data`, `on_rebalance`, or a scheduled callback. The manifest owns instruments, markets, frequencies, factor dependencies, warmup, and leverage policy.

Compile and save a source before creating a stopped deployment:

```text
compile_strategy_code(code="...Strategy API V2 Python...")
save_strategy_source(name="btc-momentum", code="...Strategy API V2 Python...")
```

Use the returned source id:

```text
create_strategy(
  name="btc-momentum",
  source_id=12,
  initial_capital=10000,
  execution_mode="signal",
  params={"lookback": 40}
)
```

Run a backtest directly from V2 code:

```text
submit_backtest(
  code="...Strategy API V2 Python...",
  start_date="2025-01-01",
  end_date="2025-12-31",
  initial_capital=10000,
  params={"lookback": 40},
  idempotency_key="btc-momentum-2025"
)
```

Market, symbol, and timeframe are not backtest parameters. They come from the compiled strategy manifest. Use `wait_for_job` or `stream_job_until_done` to obtain the result.

Indicators are chart-only. Validate and save them through the indicator tools, then convert the idea into Strategy API V2 code before using `submit_backtest` or `create_strategy`.

Restoring an older source snapshot requires `confirm_restore=true`. Cancelling open paper orders requires `confirm_cancel=true`. Neither action starts a strategy or places a live order.

## Development

```bash
pip install -e './mcp_server[dev]'
pytest mcp_server/tests
```
