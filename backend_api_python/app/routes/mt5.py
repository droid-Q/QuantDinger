"""MetaTrader 5 API routes."""

from flask import jsonify, request

from app.openapi.blueprint import HumanBlueprint as Blueprint
from app.services.mt5_trading import MT5Client, MT5Config
from app.utils.auth import login_required
from app.utils.local_brokers import desktop_broker_cloud_reject_message, local_desktop_brokers_allowed
from app.utils.logger import get_logger
from app.utils.mt5_session import mt5_sessions

logger = get_logger(__name__)

mt5_blp = Blueprint("mt5", __name__)
_sessions = mt5_sessions


def _placeholder_status():
    return {"connected": False, "broker": "CPT Markets", "server": "", "login": None}


def _require_connected_client():
    client = _sessions.get()
    if client is None or not client.connected:
        return None, (jsonify({"success": False, "error": "Not connected to MT5"}), 400)
    return client, None


def _int(value, default=0):
    try:
        return int(value)
    except Exception:
        return default


def _bool(value, default=False):
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


@mt5_blp.route("/status", methods=["GET"])
@login_required
def get_status():
    try:
        client = _sessions.get()
        if client is None:
            return jsonify({"success": True, "data": _placeholder_status()})
        return jsonify({"success": True, "data": client.get_connection_status()})
    except Exception as e:
        logger.error("MT5 status failed: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@mt5_blp.route("/connect", methods=["POST"])
@login_required
def connect():
    try:
        if not local_desktop_brokers_allowed():
            return jsonify({"success": False, "error": desktop_broker_cloud_reject_message()}), 400

        data = request.get_json() or {}
        config = MT5Config(
            login=_int(data.get("login") or data.get("mt5_login") or data.get("account")),
            password=str(data.get("password") or data.get("mt5_password") or ""),
            server=str(data.get("server") or data.get("mt5_server") or ""),
            path=str(data.get("path") or data.get("mt5_path") or ""),
            timeout=_int(data.get("timeout") or data.get("mt5_timeout"), 60000),
            portable=_bool(data.get("portable"), False),
            broker=str(data.get("broker") or "CPT Markets"),
            symbol_prefix=str(data.get("symbol_prefix") or data.get("mt5_symbol_prefix") or ""),
            symbol_suffix=str(data.get("symbol_suffix") or data.get("mt5_symbol_suffix") or ""),
        )
        if not config.login or not config.password or not config.server:
            return jsonify({"success": False, "error": "login, password and server are required"}), 400

        client = MT5Client(config)
        if not client.connect():
            return jsonify({"success": False, "error": "Connection failed. Please check MT5 Terminal and account settings."}), 400

        _sessions.set(client)
        return jsonify({"success": True, "message": "Connected successfully", "data": client.get_connection_status()})
    except ImportError as e:
        return jsonify({"success": False, "error": str(e)}), 500
    except Exception as e:
        logger.error("MT5 connect failed: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@mt5_blp.route("/disconnect", methods=["POST"])
@login_required
def disconnect():
    try:
        _sessions.disconnect_current()
        return jsonify({"success": True, "message": "Disconnected"})
    except Exception as e:
        logger.error("MT5 disconnect failed: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@mt5_blp.route("/account", methods=["GET"])
@login_required
def get_account():
    try:
        client, err = _require_connected_client()
        if err is not None:
            return err
        return jsonify({"success": True, "data": client.get_account_summary()})
    except Exception as e:
        logger.error("MT5 account failed: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@mt5_blp.route("/positions", methods=["GET"])
@login_required
def get_positions():
    try:
        client, err = _require_connected_client()
        if err is not None:
            return err
        return jsonify({"success": True, "data": client.get_positions(symbol=request.args.get("symbol", ""))})
    except Exception as e:
        logger.error("MT5 positions failed: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@mt5_blp.route("/orders", methods=["GET"])
@login_required
def get_orders():
    try:
        client, err = _require_connected_client()
        if err is not None:
            return err
        return jsonify({"success": True, "data": client.get_open_orders()})
    except Exception as e:
        logger.error("MT5 orders failed: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@mt5_blp.route("/order", methods=["POST"])
@login_required
def place_order():
    try:
        client, err = _require_connected_client()
        if err is not None:
            return err
        data = request.get_json() or {}
        symbol = str(data.get("symbol") or "").strip()
        side = str(data.get("side") or "").strip().lower()
        quantity = _float(data.get("quantity") or data.get("size") or 0)
        order_type = str(data.get("orderType") or data.get("order_type") or "market").strip().lower()
        if not symbol:
            return jsonify({"success": False, "error": "Missing symbol"}), 400
        if side not in ("buy", "sell"):
            return jsonify({"success": False, "error": "side must be buy or sell"}), 400
        if quantity <= 0:
            return jsonify({"success": False, "error": "quantity must be > 0"}), 400
        if order_type == "limit":
            price = _float(data.get("price") or 0)
            if price <= 0:
                return jsonify({"success": False, "error": "Limit order requires price"}), 400
            result = client.place_limit_order(symbol=symbol, side=side, size=quantity, price=price)
        else:
            result = client.place_market_order(
                symbol=symbol,
                side=side,
                quantity=quantity,
                reduce_only=_bool(data.get("reduce_only") or data.get("reduceOnly"), False),
            )
        if not result.success:
            return jsonify({"success": False, "error": result.message, "data": result.raw}), 400
        return jsonify({
            "success": True,
            "message": result.message,
            "data": {"orderId": result.order_id, "filled": result.filled, "avgPrice": result.avg_price, "status": result.status, "raw": result.raw},
        })
    except Exception as e:
        logger.error("MT5 place order failed: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@mt5_blp.route("/order/<int:order_id>", methods=["DELETE"])
@login_required
def cancel_order(order_id: int):
    try:
        client, err = _require_connected_client()
        if err is not None:
            return err
        if client.cancel_order(str(order_id)):
            return jsonify({"success": True, "message": f"Order {order_id} cancelled"})
        return jsonify({"success": False, "error": f"Order {order_id} not found"}), 404
    except Exception as e:
        logger.error("MT5 cancel order failed: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@mt5_blp.route("/quote", methods=["GET"])
@login_required
def get_quote():
    try:
        client, err = _require_connected_client()
        if err is not None:
            return err
        symbol = request.args.get("symbol")
        if not symbol:
            return jsonify({"success": False, "error": "Missing symbol"}), 400
        return jsonify(client.get_quote(symbol))
    except Exception as e:
        logger.error("MT5 quote failed: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


mt5_bp = mt5_blp
