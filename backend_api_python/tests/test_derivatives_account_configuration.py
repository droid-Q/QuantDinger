"""Derivative account configuration safety checks."""

import pytest

from app.services.live_trading.account_configuration import configure_derivatives_account
from app.services.live_trading.base import LiveTradingError
from app.services.live_trading.bybit import BybitClient
from app.services.live_trading.okx import OkxClient


def test_okx_spot_account_mode_is_rejected_before_leverage_change():
    client = OkxClient.__new__(OkxClient)
    leverage_calls = []
    client.get_account_config = lambda: {"acctLv": "1", "posMode": "net_mode"}
    client.set_leverage = lambda **kwargs: leverage_calls.append(kwargs) or True

    with pytest.raises(LiveTradingError, match="OKX_SWAP_ACCOUNT_MODE_REQUIRED"):
        configure_derivatives_account(
            client,
            exchange_id="okx",
            symbol="BTC/USDT",
            leverage=5,
            margin_mode="cross",
        )

    assert leverage_calls == []


def test_bybit_unchanged_leverage_is_success():
    client = BybitClient.__new__(BybitClient)
    client.category = "linear"

    def unchanged(*_args, **_kwargs):
        raise LiveTradingError("Bybit error: {'retCode': 110043, 'retMsg': 'leverage not modified'}")

    client._signed_request = unchanged

    assert client.set_leverage(symbol="BTC/USDT", leverage=1) is True


def test_bybit_unchanged_margin_mode_is_success():
    client = BybitClient.__new__(BybitClient)
    client.category = "linear"

    def unchanged(*_args, **_kwargs):
        raise LiveTradingError("Bybit error: {'retCode': 110026, 'retMsg': 'margin mode not modified'}")

    client._signed_request = unchanged

    assert client.set_margin_mode("cross") is True
