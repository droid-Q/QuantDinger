"""MetaTrader 5 local terminal client.

The official ``MetaTrader5`` Python package talks to a Windows MT5 Terminal
installed on the same reachable machine. Keep imports lazy so Linux/macOS
deployments and tests can run without the optional Windows wheel.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)

_mt5 = None


def _ensure_mt5():
    global _mt5
    if _mt5 is None:
        try:
            import MetaTrader5 as mt5

            _mt5 = mt5
        except ImportError as exc:
            raise ImportError(
                "MetaTrader5 is not installed. On Windows run: pip install MetaTrader5. "
                "The official package is a Windows-only MT5 Terminal connector."
            ) from exc
    return _mt5


def _as_dict(value: Any) -> Dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "_asdict"):
        return dict(value._asdict())
    if hasattr(value, "dtype") and getattr(value.dtype, "names", None):
        return {name: value[name].item() if hasattr(value[name], "item") else value[name] for name in value.dtype.names}
    out: Dict[str, Any] = {}
    for key in dir(value):
        if key.startswith("_"):
            continue
        try:
            item = getattr(value, key)
        except Exception:
            continue
        if callable(item):
            continue
        out[key] = item
    return out


def _num(value: Any) -> float:
    try:
        return float(str(value).replace(",", "").strip())
    except Exception:
        return 0.0


@dataclass
class MT5Config:
    login: int = 0
    password: str = ""
    server: str = ""
    path: str = ""
    timeout: int = 60000
    portable: bool = False
    broker: str = "CPT Markets"
    symbol_prefix: str = ""
    symbol_suffix: str = ""


@dataclass
class OrderResult:
    success: bool
    order_id: str = ""
    filled: float = 0.0
    avg_price: float = 0.0
    status: str = ""
    message: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def exchange_order_id(self) -> str:
        return self.order_id


class MT5Client:
    """Small wrapper around the local MT5 Terminal Python API."""

    def __init__(self, config: Optional[MT5Config] = None):
        self.config = config or MT5Config()
        self._connected = False

    @property
    def connected(self) -> bool:
        if not self._connected:
            return False
        try:
            mt5 = _ensure_mt5()
            return mt5.account_info() is not None
        except Exception:
            return False

    def connect(self) -> bool:
        mt5 = _ensure_mt5()
        kwargs: Dict[str, Any] = {
            "timeout": int(self.config.timeout or 60000),
            "portable": bool(self.config.portable),
        }
        if self.config.path:
            kwargs["path"] = self.config.path
        if self.config.login:
            kwargs["login"] = int(self.config.login)
        if self.config.password:
            kwargs["password"] = self.config.password
        if self.config.server:
            kwargs["server"] = self.config.server

        ok = bool(mt5.initialize(**kwargs))
        if not ok:
            code, msg = self._last_error()
            logger.error("MT5 initialize failed: %s %s", code, msg)
            self._connected = False
            return False
        self._connected = True
        return True

    def disconnect(self) -> None:
        try:
            _ensure_mt5().shutdown()
        except Exception:
            pass
        self._connected = False

    def _ensure_connected(self) -> None:
        if not self.connected and not self.connect():
            code, msg = self._last_error()
            raise ConnectionError(f"Cannot connect to MT5 Terminal: {code} {msg}")

    def _last_error(self) -> tuple[int, str]:
        try:
            err = _ensure_mt5().last_error()
            if isinstance(err, tuple) and len(err) >= 2:
                return int(err[0] or 0), str(err[1] or "")
        except Exception:
            pass
        return 0, ""

    def _symbol_candidates(self, symbol: str) -> List[str]:
        raw = str(symbol or "").strip()
        compact = raw.replace("/", "").replace("-", "").replace("_", "")
        values = [
            raw,
            compact,
            compact.upper(),
            f"{self.config.symbol_prefix}{compact.upper()}{self.config.symbol_suffix}",
        ]
        out: List[str] = []
        for value in values:
            if value and value not in out:
                out.append(value)
        return out

    def resolve_symbol(self, symbol: str) -> str:
        self._ensure_connected()
        mt5 = _ensure_mt5()
        for candidate in self._symbol_candidates(symbol):
            info = mt5.symbol_info(candidate)
            if info is None:
                continue
            if not bool(getattr(info, "visible", True)):
                mt5.symbol_select(candidate, True)
            return candidate
        raise ValueError(f"MT5 symbol not found or not visible: {symbol}")

    def _symbol_info(self, symbol: str):
        mt5 = _ensure_mt5()
        sym = self.resolve_symbol(symbol)
        info = mt5.symbol_info(sym)
        if info is None:
            raise ValueError(f"MT5 symbol info unavailable: {symbol}")
        return sym, info

    def _normalize_volume(self, symbol: str, volume: float) -> float:
        sym, info = self._symbol_info(symbol)
        qty = _num(volume)
        min_v = _num(getattr(info, "volume_min", 0)) or 0.01
        max_v = _num(getattr(info, "volume_max", 0)) or qty
        step = _num(getattr(info, "volume_step", 0)) or min_v
        if qty < min_v:
            qty = min_v
        if max_v > 0:
            qty = min(qty, max_v)
        if step > 0:
            qty = int(qty / step) * step
        digits = max(0, len(str(step).split(".")[-1].rstrip("0"))) if "." in str(step) else 2
        qty = round(qty, digits)
        if qty <= 0:
            raise ValueError(f"Invalid MT5 volume for {sym}: {volume}")
        return qty

    def get_connection_status(self) -> Dict[str, Any]:
        account = self.get_account_summary() if self.connected else {}
        return {
            "connected": bool(self.connected),
            "broker": self.config.broker,
            "server": self.config.server,
            "login": self.config.login or None,
            "account": account,
        }

    def get_account_summary(self) -> Dict[str, Any]:
        self._ensure_connected()
        info = _as_dict(_ensure_mt5().account_info())
        return {
            "login": info.get("login"),
            "server": info.get("server") or self.config.server,
            "name": info.get("name"),
            "company": info.get("company"),
            "currency": info.get("currency"),
            "balance": _num(info.get("balance")),
            "equity": _num(info.get("equity")),
            "margin": _num(info.get("margin")),
            "freeMargin": _num(info.get("margin_free")),
            "marginFree": _num(info.get("margin_free")),
            "raw": info,
        }

    def get_balance(self) -> Dict[str, Any]:
        return self.get_account_summary()

    def get_positions(self, symbol: str = "") -> List[Dict[str, Any]]:
        self._ensure_connected()
        mt5 = _ensure_mt5()
        rows = mt5.positions_get(symbol=self.resolve_symbol(symbol)) if symbol else mt5.positions_get()
        items = rows or []
        out: List[Dict[str, Any]] = []
        for item in items:
            row = _as_dict(item)
            typ = int(row.get("type") or 0)
            side = "short" if typ == getattr(mt5, "POSITION_TYPE_SELL", 1) else "long"
            volume = abs(_num(row.get("volume")))
            out.append(
                {
                    "symbol": row.get("symbol") or symbol,
                    "side": side,
                    "position_side": side,
                    "volume": volume,
                    "size": volume,
                    "price": _num(row.get("price_open")),
                    "markPrice": _num(row.get("price_current")),
                    "profit": _num(row.get("profit")),
                    "ticket": row.get("ticket"),
                    "raw": row,
                }
            )
        return out

    def get_open_orders(self) -> List[Dict[str, Any]]:
        self._ensure_connected()
        rows = _ensure_mt5().orders_get() or []
        return [_as_dict(row) for row in rows]

    def get_ticker(self, symbol: str) -> Dict[str, Any]:
        self._ensure_connected()
        sym = self.resolve_symbol(symbol)
        tick = _as_dict(_ensure_mt5().symbol_info_tick(sym))
        bid = _num(tick.get("bid"))
        ask = _num(tick.get("ask"))
        last = _num(tick.get("last")) or ((bid + ask) / 2 if bid > 0 and ask > 0 else bid or ask)
        return {
            "symbol": sym,
            "last": last,
            "bid": bid,
            "ask": ask,
            "time": int(tick.get("time") or time.time()),
            "raw": tick,
        }

    def get_quote(self, symbol: str, market_type: str = "MT5") -> Dict[str, Any]:
        ticker = self.get_ticker(symbol)
        return {"success": True, "data": ticker, **ticker}

    def get_kline(self, symbol: str, timeframe: str, limit: int, before_time: Optional[int] = None, after_time: Optional[int] = None) -> List[Dict[str, Any]]:
        self._ensure_connected()
        mt5 = _ensure_mt5()
        tf_map = {
            "1m": mt5.TIMEFRAME_M1,
            "3m": getattr(mt5, "TIMEFRAME_M3", mt5.TIMEFRAME_M1),
            "5m": mt5.TIMEFRAME_M5,
            "15m": mt5.TIMEFRAME_M15,
            "30m": mt5.TIMEFRAME_M30,
            "1H": mt5.TIMEFRAME_H1,
            "1h": mt5.TIMEFRAME_H1,
            "4H": mt5.TIMEFRAME_H4,
            "4h": mt5.TIMEFRAME_H4,
            "1D": mt5.TIMEFRAME_D1,
            "1d": mt5.TIMEFRAME_D1,
            "1W": mt5.TIMEFRAME_W1,
            "1w": mt5.TIMEFRAME_W1,
        }
        mt5_tf = tf_map.get(str(timeframe), mt5.TIMEFRAME_H1)
        sym = self.resolve_symbol(symbol)
        rows = mt5.copy_rates_from_pos(sym, mt5_tf, 0, int(limit or 300))
        if rows is None:
            code, msg = self._last_error()
            logger.warning("MT5 copy_rates_from_pos returned None for %s %s: %s %s", sym, timeframe, code, msg)
            rows = []
        out: List[Dict[str, Any]] = []
        for row in rows:
            item = _as_dict(row)
            ts = int(item.get("time") or 0)
            if before_time and ts >= int(before_time):
                continue
            if after_time is not None and ts < int(after_time):
                continue
            out.append(
                {
                    "time": ts,
                    "open": _num(item.get("open")),
                    "high": _num(item.get("high")),
                    "low": _num(item.get("low")),
                    "close": _num(item.get("close")),
                    "volume": _num(item.get("tick_volume") or item.get("real_volume") or 0),
                }
            )
        out.sort(key=lambda x: x["time"])
        return out[-int(limit or 300):]

    def _close_position_ticket(self, symbol: str, action: str) -> int:
        mt5 = _ensure_mt5()
        want_type = mt5.POSITION_TYPE_BUY if action == "sell" else mt5.POSITION_TYPE_SELL
        for pos in self.get_positions(symbol=symbol):
            raw = pos.get("raw") or {}
            try:
                if int(raw.get("type") or 0) == int(want_type):
                    return int(raw.get("ticket") or 0)
            except Exception:
                continue
        return 0

    def _send_order(self, request: Dict[str, Any]) -> OrderResult:
        mt5 = _ensure_mt5()
        check = mt5.order_check(request)
        check_raw = _as_dict(check)
        result = mt5.order_send(request)
        raw = _as_dict(result)
        raw["order_check"] = check_raw
        retcode = int(raw.get("retcode") or 0)
        ok_codes = {
            getattr(mt5, "TRADE_RETCODE_DONE", 10009),
            getattr(mt5, "TRADE_RETCODE_PLACED", 10008),
            getattr(mt5, "TRADE_RETCODE_DONE_PARTIAL", 10010),
        }
        success = retcode in ok_codes
        order_id = str(raw.get("order") or raw.get("deal") or "")
        return OrderResult(
            success=success,
            order_id=order_id,
            filled=_num(raw.get("volume") or request.get("volume")),
            avg_price=_num(raw.get("price") or request.get("price")),
            status="filled" if success else "rejected",
            message=str(raw.get("comment") or check_raw.get("comment") or ("success" if success else f"MT5 retcode {retcode}")),
            raw=raw,
        )

    def place_market_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        market_type: str = "MT5",
        client_order_id: str = "",
        reduce_only: bool = False,
    ) -> OrderResult:
        self._ensure_connected()
        mt5 = _ensure_mt5()
        sym = self.resolve_symbol(symbol)
        action = str(side or "").strip().lower()
        if action not in ("buy", "sell"):
            raise ValueError("MT5 side must be buy or sell")
        volume = self._normalize_volume(sym, quantity)
        tick = self.get_ticker(sym)
        price = _num(tick.get("ask")) if action == "buy" else _num(tick.get("bid"))
        order_type = mt5.ORDER_TYPE_BUY if action == "buy" else mt5.ORDER_TYPE_SELL
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": sym,
            "volume": volume,
            "type": order_type,
            "price": price,
            "deviation": 20,
            "magic": 510810,
            "comment": client_order_id or "QuantDinger",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        ticket = self._close_position_ticket(sym, action) if reduce_only else 0
        if ticket:
            request["position"] = ticket
        return self._send_order(request)

    def place_limit_order(self, symbol: str, side: str, size: float = 0, quantity: float = 0, price: float = 0, client_order_id: str = "") -> OrderResult:
        self._ensure_connected()
        mt5 = _ensure_mt5()
        sym = self.resolve_symbol(symbol)
        action = str(side or "").strip().lower()
        if action not in ("buy", "sell"):
            raise ValueError("MT5 side must be buy or sell")
        volume = self._normalize_volume(sym, quantity or size)
        order_type = mt5.ORDER_TYPE_BUY_LIMIT if action == "buy" else mt5.ORDER_TYPE_SELL_LIMIT
        request = {
            "action": mt5.TRADE_ACTION_PENDING,
            "symbol": sym,
            "volume": volume,
            "type": order_type,
            "price": float(price or 0),
            "deviation": 20,
            "magic": 510810,
            "comment": client_order_id or "QuantDinger",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_RETURN,
        }
        return self._send_order(request)

    def cancel_order(self, order_id: str) -> bool:
        self._ensure_connected()
        mt5 = _ensure_mt5()
        request = {"action": mt5.TRADE_ACTION_REMOVE, "order": int(order_id)}
        result = _as_dict(mt5.order_send(request))
        return int(result.get("retcode") or 0) in {
            getattr(mt5, "TRADE_RETCODE_DONE", 10009),
            getattr(mt5, "TRADE_RETCODE_PLACED", 10008),
        }

    def wait_for_fill(self, order_id: str, max_wait_sec: float = 2.0, **_: Any) -> Dict[str, Any]:
        # MT5 market orders usually return the deal synchronously. Keep a tiny
        # compatible hook for Quick Trade enrichment without polling history.
        return {"filled": 0.0, "avg_price": 0.0, "fee": 0.0, "fee_ccy": ""}
