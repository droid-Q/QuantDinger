from unittest.mock import MagicMock

from app.routes.script_source_routes import _attach_v2_manifest
from app.services import script_source


def test_script_source_service_upgrades_legacy_asset_type_column(monkeypatch):
    db = MagicMock()
    connection = db.__enter__.return_value
    connection.cursor.return_value.fetchone.return_value = {"present": False}
    monkeypatch.setattr(script_source, "get_db_connection", lambda: db)
    monkeypatch.setattr(script_source, "_service", None)

    script_source.get_script_source_service()

    sql = connection.cursor.return_value.execute.call_args_list[-1].args[0]
    assert "ADD COLUMN IF NOT EXISTS asset_type" in sql
    connection.commit.assert_called_once()
    monkeypatch.setattr(script_source, "_service", None)


def test_script_source_service_skips_ddl_when_asset_type_exists(monkeypatch):
    db = MagicMock()
    connection = db.__enter__.return_value
    connection.cursor.return_value.fetchone.return_value = {"present": True}
    monkeypatch.setattr(script_source, "get_db_connection", lambda: db)
    monkeypatch.setattr(script_source, "_service", None)

    script_source.get_script_source_service()

    assert connection.cursor.return_value.execute.call_count == 1
    connection.commit.assert_not_called()
    monkeypatch.setattr(script_source, "_service", None)


def test_v2_portfolio_source_is_classified_from_compiled_manifest():
    payload = _attach_v2_manifest({
        "asset_type": "script",
        "code": """
def initialize(context):
    context.set_universe(pool="sp500")
    context.subscribe(frequency="1d")

def handle_data(context, data):
    for symbol in get_universe_stocks():
        order_target_percent(symbol, 0.0)
""",
    })

    assert payload["asset_type"] == "portfolio_strategy"
    assert payload["metadata"]["strategy_manifest"]["strategyType"] == "portfolio"
    assert "apiVersion" not in payload["metadata"]
    assert "api_version" not in payload["metadata"]


def test_v2_cta_source_is_classified_from_compiled_manifest():
    payload = _attach_v2_manifest({
        "asset_type": "portfolio_strategy",
        "code": """
def initialize(context):
    context.set_universe(["USStock:SPY"])
    context.subscribe(frequency="1d")

def handle_data(context, data):
    order_target_percent("USStock:SPY", 1.0)
""",
    })

    assert payload["asset_type"] == "script"
    assert payload["metadata"]["strategy_manifest"]["strategyType"] == "cta"
