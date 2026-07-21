import unittest
from unittest.mock import MagicMock, patch

from app.services.live_trading.account_snapshot import fetch_account_snapshot
from app.services.trading_executor import TradingExecutor


class MT5RuntimePositionTest(unittest.TestCase):
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
            patch.object(executor, "_effective_taker_fee_rate", return_value=0.0),
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
        self.assertAlmostEqual(at_target["take_profit_price"], 4859.58408, places=5)

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
