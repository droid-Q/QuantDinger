import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pandas as pd

from app.services.live_trading.account_snapshot import fetch_account_snapshot
from app.services.strategy_v2.data import MultiAssetDataPortal
from app.services.trading_executor import TradingExecutor, _frame_from_exchange_rows, _member_key


class MT5RuntimePositionTest(unittest.TestCase):
    def test_mt5_runtime_key_matches_strategy_portal_identity(self):
        member = {
            "market": "Forex",
            "symbol": "XAUUSD",
            "exchange_id": "cptmarkets",
            "market_type": "spot",
        }
        key = _member_key(member)
        frame = pd.DataFrame(
            {"open": [1], "high": [1], "low": [1], "close": [1]},
            index=[pd.Timestamp("2026-07-22T00:00:00Z")],
        )

        self.assertEqual(MultiAssetDataPortal({key: frame}).resolve_key("Forex:XAUUSD"), key)

    def test_explicit_position_ledger_overrides_legacy_dca_fallback(self):
        from app.services.live_trading.strategy_position_sync import strategy_uses_fill_ledger

        self.assertTrue(strategy_uses_fill_ledger({"trading_config": {"position_ledger": "fills"}}))
        self.assertFalse(
            strategy_uses_fill_ledger(
                {"trading_config": {"bot_type": "dca", "position_ledger": "exchange"}}
            )
        )
        self.assertTrue(strategy_uses_fill_ledger({"trading_config": {"bot_type": "dca"}}))

    def test_mt5_password_is_redacted_from_exchange_logs(self):
        from app.services.exchange_execution import (
            _infer_market_category_from_exchange,
            safe_exchange_config_for_log,
        )

        safe = safe_exchange_config_for_log(
            {"exchange_id": "cptmarkets", "mt5_password": "top-secret"}
        )

        self.assertNotEqual(safe["mt5_password"], "top-secret")
        self.assertEqual(_infer_market_category_from_exchange("cptmarkets"), "Forex")

    def test_mt5_rows_are_normalized_for_strategy_v2_runtime(self):
        frame = _frame_from_exchange_rows(
            [
                {"time": 1_700_000_000, "open": 2000, "high": 2002, "low": 1999, "close": 2001},
                {"time": 1_700_003_600, "open": 2001, "high": 2004, "low": 2000, "close": 2003},
            ],
            datetime.fromtimestamp(1_699_999_000, tz=timezone.utc),
            datetime.fromtimestamp(1_700_004_000, tz=timezone.utc),
        )

        self.assertEqual(len(frame), 2)
        self.assertEqual(float(frame.iloc[-1]["close"]), 2003.0)

    def test_runtime_prices_use_bound_cptmarkets_client_for_forex(self):
        client = MagicMock()
        client.get_ticker.return_value = {"last": 4078.5}
        candidates = [
            {
                "key": "Forex:XAUUSD@cptmarkets:spot",
                "market": "Forex",
                "symbol": "XAUUSD",
                "market_type": "spot",
            }
        ]

        with patch.object(TradingExecutor, "_live_prices", return_value={}):
            prices = TradingExecutor._execution_account_prices(
                candidates,
                {"exchange_id": "cptmarkets"},
                {"client": client},
            )

        self.assertEqual(prices[candidates[0]["key"]], 4078.5)
        client.get_ticker.assert_called_once_with(symbol="XAUUSD")

    def test_runtime_matches_compact_forex_symbol_to_ledger_symbol(self):
        db = MagicMock()
        db.__enter__.return_value = db
        db.cursor.return_value.fetchall.return_value = [
            {
                "id": 1,
                "symbol": "XAU/USD",
                "side": "long",
                "size": 0.03,
                "entry_price": 4049.0,
                "highest_price": 4061.0,
                "lowest_price": 4040.0,
            }
        ]
        executor = TradingExecutor.__new__(TradingExecutor)

        with patch("app.services.trading_executor.get_db_connection", return_value=db):
            positions = executor._get_current_positions(7, "XAUUSD")

        self.assertEqual(len(positions), 1)
        self.assertEqual(positions[0]["symbol"], "XAU/USD")

    def test_twenty_percent_take_profit_uses_underlying_price_move(self):
        executor = TradingExecutor.__new__(TradingExecutor)
        position = {
            "symbol": "XAU/USD",
            "side": "long",
            "size": 3.64,
            "entry_price": 4049.6534,
            "highest_price": 4061.5150,
            "lowest_price": 4049.6534,
        }
        config = {
            "take_profit_pct": 20,
            "enable_server_side_take_profit": True,
        }

        with (
            patch.object(executor, "_get_current_positions", return_value=[position]),
            patch.object(executor, "_update_position"),
        ):
            below_target = executor._server_side_take_profit_or_trailing_signal(
                strategy_id=7,
                symbol="XAUUSD",
                current_price=4061.5150,
                market_type="spot",
                leverage=1.0,
                trading_config=config,
                timeframe_seconds=60,
                execution_mode="live",
            )
            at_target = executor._server_side_take_profit_or_trailing_signal(
                strategy_id=7,
                symbol="XAUUSD",
                current_price=4859.5841,
                market_type="spot",
                leverage=1.0,
                trading_config=config,
                timeframe_seconds=60,
                execution_mode="live",
            )

        self.assertIsNone(below_target)
        self.assertEqual(at_target["reason"], "server_take_profit")
        self.assertAlmostEqual(at_target["matched_entry_price"], 4049.6534, places=5)
        self.assertAlmostEqual(at_target["trigger_price"], 4859.5841, places=5)

    @patch("app.services.live_trading.account_snapshot.create_client")
    @patch("app.services.live_trading.account_snapshot.resolve_exchange_config")
    def test_cptmarkets_positions_are_returned_as_spot(self, resolve_config, create_client):
        resolve_config.return_value = {"exchange_id": "cptmarkets"}
        create_client.return_value.get_positions.return_value = [
            {
                "symbol": "XAUUSD",
                "side": "long",
                "size": 0.03,
                "price": 4049.0,
            }
        ]

        snapshot = fetch_account_snapshot(user_id=1, credential_id=9)

        self.assertEqual(snapshot["swap_positions"], [])
        self.assertEqual(snapshot["spot_positions"][0]["symbol"], "XAU/USD")
        self.assertEqual(snapshot["spot_positions"][0]["entry_price"], 4049.0)


if __name__ == "__main__":
    unittest.main()
