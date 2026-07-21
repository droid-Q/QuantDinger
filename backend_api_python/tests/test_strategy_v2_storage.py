import copy
import unittest

from app.services.strategy_v2.storage import _normalize_backtest_result


class StrategyV2StorageCompatibilityTests(unittest.TestCase):
    def test_legacy_backtest_result_restores_overview_fields_from_executions(self):
        legacy = {
            "equityCurve": [
                {"time": "2025-01-01 00:00:00", "value": 9995.0},
                {"time": "2025-01-02 00:00:00", "value": 10089.9},
            ],
            "rawTrades": [
                {
                    "time": "2025-01-01 00:00:00",
                    "side": "buy",
                    "symbol": "Crypto:BTC/USDT@spot",
                    "quantity": 50,
                    "price": 100,
                    "commission": 5,
                },
                {
                    "time": "2025-01-02 00:00:00",
                    "side": "sell",
                    "symbol": "Crypto:BTC/USDT@spot",
                    "quantity": 50,
                    "price": 102,
                    "commission": 5.1,
                },
            ],
        }

        restored = _normalize_backtest_result(legacy, {"initial_capital": 10000})

        first, last = restored["equityCurve"]
        self.assertAlmostEqual(first["cash"], 4995)
        self.assertAlmostEqual(first["netExposure"], 5000 / 9995)
        self.assertAlmostEqual(first["grossExposure"], 5000 / 9995)
        self.assertAlmostEqual(last["cash"], 10089.9)
        self.assertAlmostEqual(last["netExposure"], 0)
        self.assertAlmostEqual(restored["attribution"]["feeDrag"], 10.1 / 10000)
        self.assertEqual(restored["attribution"]["orderStatus"], {
            "filled": 2,
            "partial": 0,
            "deferred": 0,
            "rejected": 0,
        })
        self.assertEqual(len(restored["orderLedger"]), 2)
        self.assertTrue(restored["compatibility"]["legacyBackfill"])

    def test_current_backtest_result_keeps_saved_detail_values(self):
        current = {
            "initialCapital": 10000,
            "equityCurve": [{
                "time": "2025-01-01T00:00:00Z",
                "value": 10100,
                "cash": 2200,
                "grossExposure": 0.8,
                "netExposure": 0.6,
            }],
            "orderLedger": [{"orderId": "order-1", "status": "partial"}],
            "attribution": {
                "feeDrag": 0.0123,
                "orderStatus": {"filled": 0, "partial": 1, "deferred": 0, "rejected": 0},
            },
        }
        expected = copy.deepcopy(current)

        restored = _normalize_backtest_result(current, {"initial_capital": 5000})

        self.assertEqual(restored, expected)
        self.assertNotIn("compatibility", restored)


if __name__ == "__main__":
    unittest.main()
