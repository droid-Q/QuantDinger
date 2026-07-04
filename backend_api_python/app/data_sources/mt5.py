"""MT5 / CPT Markets data source backed by the connected local terminal."""

from typing import Any, Dict, List, Optional

from app.data_sources.base import BaseDataSource
from app.utils.mt5_session import mt5_sessions


class MT5DataSource(BaseDataSource):
    """Read quotes and candles from the current user's connected MT5 client."""

    name = "mt5"

    def _client(self) -> Optional[Any]:
        client = mt5_sessions.get()
        if client is None or not getattr(client, "connected", False):
            return None
        return client

    def get_ticker(self, symbol: str) -> Dict[str, Any]:
        client = self._client()
        if client is None:
            return {"last": 0, "symbol": symbol}
        return client.get_ticker(symbol)

    def get_kline(
        self,
        symbol: str,
        timeframe: str,
        limit: int,
        before_time: Optional[int] = None,
        after_time: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        client = self._client()
        if client is None:
            return []
        return client.get_kline(symbol, timeframe, limit, before_time, after_time)
