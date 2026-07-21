"""Trading (class T) — paper-only by default, hard-gated for live execution.

Live execution from agents requires *all* of the following:
  1. Token has scope `T`.
  2. Token has `paper_only=false` (operator must flip explicitly).
  3. Server-side env `AGENT_LIVE_TRADING_ENABLED=true` (deployment kill switch).

Until live is unlocked, this endpoint records orders to `qd_agent_paper_orders`
using the latest market price as the simulated fill — so AI workflows can
exercise the round trip without ever touching exchange credentials.
"""
from __future__ import annotations

import os
import time
import uuid
from typing import Any

from app.services.kline import KlineService
from app.utils.agent_auth import (
    SCOPE_T, agent_required, current_token, current_user_id,
    instrument_allowed, market_allowed, paper_only, with_idempotency,
)
from app.utils.agent_jobs import record_completed_job
from app.utils.db import get_db_connection
from app.utils.logger import get_logger
from flask import request

from . import agent_v1_bp
from ._helpers import envelope, error, get_json_or_400

logger = get_logger(__name__)
_kline = KlineService()
_ORDER_FIELDS = {
    "market", "symbol", "side", "qty", "order_type", "limit_price",
    "credential_id", "market_type", "leverage", "margin_mode", "tp_price", "sl_price",
}


def _live_trading_kill_switch() -> bool:
    return os.getenv("AGENT_LIVE_TRADING_ENABLED", "false").lower() in ("1", "true", "yes")


def _last_price(market: str, symbol: str) -> float | None:
    try:
        rows = _kline.get_kline(market=market, symbol=symbol, timeframe="1m", limit=1) or []
        if not rows:
            return None
        last = rows[-1]
        if isinstance(last, dict):
            for k in ("close", "c", "Close"):
                v = last.get(k)
                if v is not None:
                    return float(v)
        return None
    except Exception as exc:
        logger.warning(f"agent_v1 quick_trade last_price failed: {exc}")
        return None


def _paper_fill_outcome(body: dict, last_price: float | None) -> tuple[float | None, str, str]:
    if last_price is None:
        return None, "rejected", "no last price available; recorded without fill"
    order_type = str(body.get("order_type") or "market").strip().lower()
    if order_type == "market":
        return float(last_price), "filled", ""
    side = str(body.get("side") or "").strip().lower()
    limit_price = float(body.get("limit_price") or body.get("limitPrice") or 0)
    marketable = (
        side == "buy" and float(last_price) <= limit_price
    ) or (
        side == "sell" and float(last_price) >= limit_price
    )
    if marketable:
        return float(last_price), "filled", ""
    return None, "submitted", "paper limit order is waiting for its trigger price"


def _record_paper_order(*, body: dict, fill_price: float | None, status: str, note: str = "") -> dict:
    import uuid

    order_uid = uuid.uuid4().hex
    market = (body.get("market") or "").strip()
    symbol = (body.get("symbol") or "").strip()
    side = (body.get("side") or "").strip().lower()
    order_type = (body.get("order_type") or body.get("orderType") or "market").strip().lower()
    qty = float(body.get("qty") or body.get("quantity") or 0)
    limit_price = body.get("limit_price") or body.get("limitPrice")
    if limit_price is not None:
        limit_price = float(limit_price)

    fill_value = (fill_price * qty) if (fill_price is not None and qty) else None

    with get_db_connection() as db:
        cur = db.cursor()
        cur.execute(
            """
            INSERT INTO qd_agent_paper_orders
              (order_uid, user_id, agent_token_id, market, symbol, side, order_type,
               qty, limit_price, fill_price, fill_value, status, note)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                order_uid, current_user_id(), int(current_token().get("id") or 0),
                market, symbol, side, order_type,
                qty, limit_price, fill_price, fill_value, status, note,
            ),
        )
        db.commit()
        cur.close()

    return {
        "order_uid": order_uid,
        "market": market,
        "symbol": symbol,
        "side": side,
        "order_type": order_type,
        "qty": qty,
        "limit_price": limit_price,
        "fill_price": fill_price,
        "fill_value": fill_value,
        "status": status,
        "paper": True,
        "note": note,
    }


def _place_live_order(*, body: dict, user_id: int) -> dict:
    credential_id = int(body.get("credential_id") or body.get("credentialId") or 0)
    market = (body.get("market") or "").strip()
    symbol = (body.get("symbol") or "").strip()
    side = (body.get("side") or "").strip().lower()
    order_type = (body.get("order_type") or body.get("orderType") or "market").strip().lower()
    qty = float(body.get("qty") or body.get("quantity") or body.get("amount") or 0)
    limit_price = body.get("limit_price") or body.get("limitPrice") or body.get("price")
    limit_price_f = float(limit_price or 0)
    market_type = (body.get("market_type") or body.get("marketType") or "").strip().lower()
    leverage = int(body.get("leverage") or 1)
    margin_mode = (body.get("margin_mode") or body.get("marginMode") or "").strip().lower()
    if market_type in ("futures", "future", "perp", "perpetual"):
        market_type = "swap"
    if market_type not in ("spot", "swap"):
        market_type = "swap" if leverage > 1 else "spot"
    if market_type == "swap" and not margin_mode:
        margin_mode = "cross"
    if order_type == "limit" and limit_price_f <= 0:
        raise ValueError("limit_price is required for limit orders")
    if not credential_id:
        raise ValueError("credential_id is required for live agent trading")

    from app.routes.quick_trade import _record_quick_trade, _reject_quick_trade_if_desktop_broker
    from app.services.quick_trade.credentials import build_exchange_config, create_exchange_client
    from app.services.quick_trade.orders import (
        attach_quick_trade_protection,
        enrich_fill,
        limit_order_kwargs,
        quick_order_status,
    )

    cfg_overrides: dict[str, Any] = {"market_type": market_type}
    if margin_mode in ("cross", "crossed"):
        cfg_overrides["margin_mode"] = "cross"
        cfg_overrides["td_mode"] = "cross"
    elif margin_mode in ("iso", "isolated"):
        cfg_overrides["margin_mode"] = "isolated"
        cfg_overrides["td_mode"] = "isolated"

    exchange_config = build_exchange_config(credential_id, user_id, cfg_overrides)
    exchange_id = (exchange_config.get("exchange_id") or "").strip().lower()
    if not exchange_id:
        raise ValueError("Invalid credential: missing exchange_id")
    reject = _reject_quick_trade_if_desktop_broker(exchange_id)
    if reject is not None:
        raise ValueError("Quick Trade currently supports crypto exchange API keys only.")

    client = create_exchange_client(exchange_config, market_type=market_type)

    if market_type == "swap":
        from app.services.live_trading.account_configuration import configure_derivatives_account

        configure_derivatives_account(
            client,
            exchange_id=exchange_id,
            symbol=symbol,
            leverage=leverage,
            margin_mode=margin_mode,
        )

    client_order_id = f"qa{str(int(time.time()))[-6:]}{uuid.uuid4().hex[:8]}"
    if order_type == "market":
        from app.services.live_trading.execution import place_order_from_signal

        if market_type == "spot":
            signal_type = "open_long" if side == "buy" else "close_long"
        else:
            signal_type = "open_long" if side == "buy" else "open_short"
        result = place_order_from_signal(
            client=client,
            signal_type=signal_type,
            symbol=symbol,
            amount=qty,
            market_type=market_type,
            exchange_config=exchange_config,
            client_order_id=client_order_id,
        )
    else:
        result = client.place_limit_order(
            symbol=symbol,
            side=side.upper() if "binance" in exchange_id else side,
            **limit_order_kwargs(client, symbol, qty, limit_price_f, side, market_type, client_order_id),
        )

    exchange_order_id = str(getattr(result, "exchange_order_id", "") or "")
    filled = float(getattr(result, "filled", 0) or 0)
    avg_fill = float(getattr(result, "avg_price", 0) or 0)
    raw = getattr(result, "raw", {}) or {}
    commission = 0.0
    commission_ccy = ""
    commission_quote = None
    exchange_status = ""
    if exchange_order_id:
        enrich = enrich_fill(client, order_id=exchange_order_id, symbol=symbol, market_type=market_type)
        if enrich.get("filled", 0.0) > 0:
            filled = float(enrich["filled"])
        if enrich.get("avg_price", 0.0) > 0:
            avg_fill = float(enrich["avg_price"])
        commission = float(enrich.get("fee") or 0.0)
        commission_ccy = str(enrich.get("fee_ccy") or "")
        exchange_status = str(enrich.get("status") or "")
        from app.services.live_trading.fee_quote import fee_to_quote
        commission_quote = fee_to_quote(
            client,
            symbol=symbol,
            fee=commission,
            fee_ccy=commission_ccy,
            fill_price=avg_fill,
        )

    tp_price = float(body.get("tp_price") or body.get("tpPrice") or 0)
    sl_price = float(body.get("sl_price") or body.get("slPrice") or 0)
    protection_result = []
    protection_error = ""
    try:
        protection_result = attach_quick_trade_protection(
            client,
            symbol=symbol,
            side=side,
            filled_qty=filled,
            avg_price=avg_fill,
            tp_price=tp_price,
            sl_price=sl_price,
            market_type=market_type,
            exchange_config=exchange_config,
            leverage=leverage,
            margin_mode=margin_mode,
            client_order_id=f"{client_order_id}p",
        )
    except Exception as protection_exc:
        protection_error = str(protection_exc)

    status = quick_order_status(
        requested_qty=qty,
        filled_qty=filled,
        exchange_status=exchange_status,
    )
    raw_record = dict(raw) if isinstance(raw, dict) else {"raw": raw}
    raw_record["_quick_trade"] = {
        "requested_base_qty": qty,
        "exchange_status": exchange_status,
        "native_protection": protection_result,
        "native_protection_error": protection_error,
        "protected_filled_qty": filled if protection_result else 0.0,
        "margin_mode": margin_mode,
    }

    trade_id = _record_quick_trade(
        user_id=user_id,
        credential_id=credential_id,
        exchange_id=exchange_id,
        symbol=symbol,
        side=side,
        order_type=order_type,
        amount=qty,
        price=limit_price_f if order_type == "limit" else avg_fill,
        leverage=leverage,
        market_type=market_type,
        tp_price=tp_price,
        sl_price=sl_price,
        status=status,
        exchange_order_id=exchange_order_id,
        filled=filled,
        avg_price=avg_fill,
        error_msg="",
        source="agent_mcp",
        raw_result=raw_record,
        commission=commission,
        commission_ccy=commission_ccy,
        commission_quote=commission_quote,
    )

    return {
        "trade_id": trade_id,
        "exchange_order_id": exchange_order_id,
        "market": market,
        "symbol": symbol,
        "side": side,
        "order_type": order_type,
        "qty": qty,
        "limit_price": limit_price_f if order_type == "limit" else None,
        "filled": filled,
        "avg_price": avg_fill,
        "status": status,
        "protection_status": "failed" if protection_error else ("attached" if protection_result else "not_requested"),
        "protection_error": protection_error,
        "paper": False,
    }


@agent_v1_bp.route("/quick-trade/orders", methods=["POST"])
@agent_required(SCOPE_T)
def place_order():
    """Place an order. Paper-only unless explicitly unlocked (see module doc)."""
    body, err = get_json_or_400()
    if err:
        return err
    unsupported = sorted(set(body) - _ORDER_FIELDS)
    if unsupported:
        return error(400, f"Unsupported order fields: {', '.join(unsupported)}")

    market = (body.get("market") or "").strip()
    symbol = (body.get("symbol") or "").strip()
    side = (body.get("side") or "").strip().lower()
    qty = body.get("qty")
    order_type = str(body.get("order_type") or "market").strip().lower()

    if not market or not symbol:
        return error(400, "market and symbol are required")
    if side not in ("buy", "sell"):
        return error(400, "side must be 'buy' or 'sell'")
    try:
        qty_f = float(qty)
        if qty_f <= 0:
            raise ValueError
    except Exception:
        return error(400, "qty must be a positive number")
    if order_type not in {"market", "limit"}:
        return error(400, "order_type must be 'market' or 'limit'")
    if order_type == "limit":
        try:
            if float(body.get("limit_price") or 0) <= 0:
                raise ValueError
        except (TypeError, ValueError):
            return error(400, "limit_price is required for limit orders")

    body = dict(body)
    body["qty"] = qty_f
    body["order_type"] = order_type

    if not market_allowed(market):
        return error(403, f"Market not allowed: {market}", http=403)
    if not instrument_allowed(symbol):
        return error(403, f"Instrument not allowed: {symbol}", http=403)

    with with_idempotency("quick_trade_order") as existing:
        if existing:
            return envelope({
                "duplicate": True,
                "previous": existing.get("result"),
            }, message="idempotent replay")

    # Live trading is hard-gated. Even with paper_only=false on the token, the
    # operator must enable AGENT_LIVE_TRADING_ENABLED to actually route to
    # exchange clients — keeping a final environment-level kill switch.
    if not paper_only() and not _live_trading_kill_switch():
        return error(
            501,
            "Live agent trading is disabled by AGENT_LIVE_TRADING_ENABLED",
            http=501,
        )

    if not paper_only():
        try:
            result = _place_live_order(body=body, user_id=current_user_id())
        except ValueError as exc:
            return error(400, str(exc), http=400)
        except Exception as exc:
            logger.error(f"agent_v1 live quick_trade failed: {exc}", exc_info=True)
            return error(500, "live quick_trade failed", details=str(exc), http=500)
        record_completed_job(
            user_id=current_user_id(),
            agent_token_id=int(current_token().get("id") or 0),
            kind="quick_trade_order",
            request_payload=body,
            result=result,
            idempotency_key=request.headers.get("Idempotency-Key"),
        )
        return envelope(result, message="live-order")

    fill_price, status, note = _paper_fill_outcome(body, _last_price(market, symbol))
    result = _record_paper_order(body=body, fill_price=fill_price, status=status, note=note)
    record_completed_job(
        user_id=current_user_id(),
        agent_token_id=int(current_token().get("id") or 0),
        kind="quick_trade_order",
        request_payload=body,
        result=result,
        idempotency_key=request.headers.get("Idempotency-Key"),
    )
    return envelope(result, message="paper-fill")


@agent_v1_bp.route("/quick-trade/kill-switch", methods=["POST"])
@agent_required(SCOPE_T)
def kill_switch():
    """Cancel all of the calling tenant's open paper orders.

    This intentionally limits scope to the agent's own surface; revoking live
    exchange orders requires the human admin path (separate, audited).
    """
    with get_db_connection() as db:
        cur = db.cursor()
        cur.execute(
            """
            UPDATE qd_agent_paper_orders
            SET status = 'cancelled', note = COALESCE(note,'') || ' [kill_switch]'
            WHERE user_id = %s AND status NOT IN ('filled','cancelled','rejected')
            """,
            (current_user_id(),),
        )
        affected = cur.rowcount
        db.commit()
        cur.close()
    return envelope({"cancelled_open_paper_orders": int(affected or 0)})
