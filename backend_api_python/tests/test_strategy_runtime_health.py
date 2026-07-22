from app.routes import strategy as strategy_routes
from app.services.strategy_runtime import health


def test_strategy_rows_include_runtime_health(monkeypatch):
    captured = {}

    def load(strategy_ids, *, strategy_statuses=None):
        captured["ids"] = list(strategy_ids)
        captured["statuses"] = dict(strategy_statuses or {})
        return {
            20: {
                "health": "healthy",
                "last_heartbeat_at": 1784434455,
                "loop_latency_ms": 37,
            }
        }

    monkeypatch.setattr(strategy_routes, "load_runtime_health", load)

    rows = strategy_routes._attach_runtime_health([
        {"id": 20, "status": "running", "strategy_name": "Momentum"}
    ])

    assert captured == {"ids": [20], "statuses": {20: "running"}}
    assert rows[0]["runtime_health"]["health"] == "healthy"
    assert rows[0]["runtime_health"]["loop_latency_ms"] == 37


def test_runtime_heartbeat_persists_loop_latency(monkeypatch):
    saved = {}

    class Store:
        def __init__(self, **kwargs):
            saved["identity"] = kwargs

        def save(self, values):
            saved["values"] = values

    from app.services.strategy_runtime import state

    monkeypatch.setattr(state, "RuntimeStateStore", Store)
    monkeypatch.setattr(health.time, "time", lambda: 1784434455)

    health.record_runtime_heartbeat(
        strategy_id=20,
        strategy_run_id=7,
        symbol="BTC/USDT",
        price=64655.9,
        pending_signal_count=2,
        loop_latency_ms=41,
    )

    assert saved["identity"] == {
        "strategy_id": 20,
        "strategy_run_id": 7,
        "state_key": "health",
    }
    assert saved["values"]["last_heartbeat_at"] == 1784434455
    assert saved["values"]["loop_latency_ms"] == 41
    assert saved["values"]["latency_ms"] == 41


def test_pending_order_health_only_counts_latest_runs(monkeypatch):
    captured = {}

    def query(sql, params):
        captured["sql"] = sql
        captured["params"] = params
        return []

    monkeypatch.setattr(health, "_query", query)

    health._load_pending_orders({20: {"run_id": 7}}, "%s", [20])

    assert "strategy_run_id IN (%s)" in captured["sql"]
    assert captured["params"] == (20, 7)
