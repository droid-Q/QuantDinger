import unittest

from app.services.strategy_v2.contract import StrategyV2ContractError
from app.services.strategy_v2.deployment import StrategyV2DeploymentService


class StrategyV2ForexAccountTest(unittest.TestCase):
    def test_live_forex_requires_mt5_credential(self):
        validate = StrategyV2DeploymentService._validate_execution_account

        validate(("Forex",), "cptmarkets", "live")

        with self.assertRaisesRegex(
            StrategyV2ContractError,
            "strategyV2.forexCredentialRequired",
        ):
            validate(("Forex",), "alpaca", "live")
