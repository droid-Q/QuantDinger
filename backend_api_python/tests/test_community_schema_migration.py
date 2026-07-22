from pathlib import Path

import pytest

from app.services import community_service
from app.services.community_service import CommunityService


MIGRATION = Path(__file__).resolve().parents[1] / "migrations" / "init.sql"


def test_existing_indicator_tables_receive_marketplace_columns_before_indexes():
    sql = MIGRATION.read_text(encoding="utf-8")
    asset_upgrade = "ALTER TABLE qd_indicator_codes ADD COLUMN IF NOT EXISTS asset_type"
    source_upgrade = "ALTER TABLE qd_indicator_codes ADD COLUMN IF NOT EXISTS source_script_source_id"
    source_index = "CREATE INDEX IF NOT EXISTS idx_indicator_codes_source_script"

    assert asset_upgrade in sql
    assert source_upgrade in sql
    assert sql.index(source_upgrade) < sql.index(source_index)


def test_existing_script_source_tables_receive_asset_type_before_index():
    sql = MIGRATION.read_text(encoding="utf-8")
    asset_upgrade = "ALTER TABLE qd_script_sources\nADD COLUMN IF NOT EXISTS asset_type"
    asset_index = "CREATE INDEX IF NOT EXISTS idx_script_sources_asset_type"

    assert asset_upgrade in sql
    assert sql.index(asset_upgrade) < sql.index(asset_index)


def test_existing_strategy_runtime_tables_receive_columns_before_indexes():
    sql = MIGRATION.read_text(encoding="utf-8")
    upgrades = (
        (
            "ALTER TABLE qd_backtest_runs ADD COLUMN IF NOT EXISTS source_id",
            "CREATE INDEX IF NOT EXISTS idx_backtest_runs_source_id",
        ),
        (
            "ALTER TABLE strategy_order_intents ADD COLUMN IF NOT EXISTS portfolio_id",
            "CREATE INDEX IF NOT EXISTS idx_strategy_order_intents_strategy",
        ),
    )

    for upgrade, index in upgrades:
        assert upgrade in sql
        assert sql.index(upgrade) < sql.index(index)


def test_author_published_surfaces_database_errors(monkeypatch):
    def fail_connection():
        raise RuntimeError("schema mismatch")

    monkeypatch.setattr(community_service, "get_db_connection", fail_connection)

    with pytest.raises(RuntimeError, match="schema mismatch"):
        CommunityService().get_author_published(user_id=7)
