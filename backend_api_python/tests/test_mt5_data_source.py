from app.data_sources.factory import DataSourceFactory
from app.data_sources.mt5 import MT5DataSource
from app.utils.mt5_session import mt5_sessions


class DummyMT5Client:
    connected = True

    def __init__(self):
        self.disconnected = False

    def disconnect(self):
        self.disconnected = True

    def get_ticker(self, symbol):
        return {"symbol": symbol, "last": 2300.25}

    def get_kline(self, symbol, timeframe, limit, before_time=None, after_time=None):
        return [
            {
                "time": 1,
                "open": 1,
                "high": 2,
                "low": 1,
                "close": 2,
                "volume": 10,
            }
        ][:limit]


def test_mt5_data_source_uses_shared_connected_session():
    mt5_sessions.clear()
    mt5_sessions.set(DummyMT5Client())
    try:
        source = MT5DataSource()

        assert source.get_ticker("XAUUSD") == {"symbol": "XAUUSD", "last": 2300.25}
        assert source.get_kline("XAUUSD", "1H", 1)[0]["close"] == 2
    finally:
        mt5_sessions.clear()


def test_mt5_data_source_returns_empty_when_not_connected():
    mt5_sessions.clear()
    source = MT5DataSource()

    assert source.get_ticker("XAUUSD") == {"last": 0, "symbol": "XAUUSD"}
    assert source.get_kline("XAUUSD", "1H", 10) == []


def test_mt5_exchange_id_routes_forex_market_to_mt5_source():
    source = DataSourceFactory._resolve_source("Forex", exchange_id="cptmarkets", market_type="spot")
    assert isinstance(source, MT5DataSource)
