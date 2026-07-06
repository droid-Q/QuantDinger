"""MetaTrader 5 API routes."""

import json

from flask import g, jsonify, request

from app.openapi.blueprint import HumanBlueprint as Blueprint
from app.services.mt5_trading import MT5Client, MT5Config
from app.utils.auth import login_required
from app.utils.credential_crypto import decrypt_credential_blob, encrypt_credential_blob
from app.utils.db import get_db_connection
from app.utils.local_brokers import desktop_broker_cloud_reject_message, local_desktop_brokers_allowed
from app.utils.logger import get_logger
from app.utils.mt5_session import mt5_sessions

logger = get_logger(__name__)

mt5_blp = Blueprint("mt5", __name__)
_sessions = mt5_sessions


def _placeholder_status():
    return {"connected": False, "broker": "CPT Markets", "server": "", "login": None}


def _mt5_exchange_id(config_or_dict) -> str:
    broker = ""
    if isinstance(config_or_dict, MT5Config):
        broker = config_or_dict.broker
    elif isinstance(config_or_dict, dict):
        broker = config_or_dict.get("broker") or config_or_dict.get("exchange_id") or ""
    return "cptmarkets" if "cpt" in str(broker or "").lower() else "mt5"


def _config_to_vault_dict(config: MT5Config) -> dict:
    exchange_id = _mt5_exchange_id(config)
    return {
        "exchange_id": exchange_id,
        "broker": "CPT Markets" if exchange_id == "cptmarkets" else (config.broker or "MetaTrader 5"),
        "mt5_login": str(config.login or "").strip(),
        "mt5_password": config.password or "",
        "mt5_server": config.server or "",
        "mt5_path": config.path or "",
        "mt5_timeout": int(config.timeout or 60000),
        "market_category": "Forex",
        "market_type": "spot",
        "symbol_prefix": config.symbol_prefix or "",
        "symbol_suffix": config.symbol_suffix or "",
    }


def _load_saved_mt5_config(user_id: int, credential_id: int = 0) -> dict:
    """Load a saved MT5/CPT credential for this user."""
    with get_db_connection() as db:
        cur = db.cursor()
        if int(credential_id or 0) > 0:
            cur.execute(
                """
                SELECT id, encrypted_config
                FROM qd_exchange_credentials
                WHERE user_id = %s
                  AND id = %s
                  AND exchange_id IN ('mt5', 'cptmarkets', 'cpt_markets')
                LIMIT 1
                """,
                (int(user_id), int(credential_id)),
            )
        else:
            cur.execute(
                """
                SELECT id, encrypted_config
                FROM qd_exchange_credentials
                WHERE user_id = %s AND exchange_id IN ('mt5', 'cptmarkets', 'cpt_markets')
                ORDER BY updated_at DESC NULLS LAST, id DESC
                LIMIT 1
                """,
                (int(user_id),),
            )
        row = cur.fetchone() or {}
        cur.close()
    if not row:
        return {}
    try:
        plain = decrypt_credential_blob(row.get("encrypted_config"))
        cfg = json.loads(plain) if plain else {}
        if not isinstance(cfg, dict):
            return {}
        cfg["credential_id"] = int(row.get("id") or 0)
        return cfg
    except Exception as e:
        logger.warning("Failed to load saved MT5 credential: %s", e)
        return {}


def _save_or_update_mt5_credential(user_id: int, config: MT5Config) -> int:
    """Persist the connected MT5/CPT account so strategy templates can reuse it."""
    vault_cfg = _config_to_vault_dict(config)
    login = vault_cfg["mt5_login"]
    server = vault_cfg["mt5_server"]
    hint = f"{login}@{server}"
    encrypted = encrypt_credential_blob(json.dumps(vault_cfg, ensure_ascii=False))

    with get_db_connection() as db:
        cur = db.cursor()
        cur.execute(
            """
            SELECT id, encrypted_config
            FROM qd_exchange_credentials
            WHERE user_id = %s AND exchange_id IN ('mt5', 'cptmarkets', 'cpt_markets')
            ORDER BY id DESC
            """,
            (int(user_id),),
        )
        rows = cur.fetchall() or []
        target_id = 0
        for row in rows:
            try:
                plain = decrypt_credential_blob(row.get("encrypted_config"))
                existing = json.loads(plain) if plain else {}
                if not isinstance(existing, dict):
                    continue
                same_login = str(existing.get("mt5_login") or existing.get("login") or "").strip() == login
                same_server = str(existing.get("mt5_server") or existing.get("server") or "").strip() == server
                if same_login and same_server:
                    target_id = int(row.get("id") or 0)
                    break
            except Exception:
                continue

        if target_id > 0:
            cur.execute(
                """
                UPDATE qd_exchange_credentials
                SET exchange_id = %s,
                    api_key_hint = %s,
                    encrypted_config = %s,
                    updated_at = NOW()
                WHERE id = %s AND user_id = %s
                """,
                (vault_cfg["exchange_id"], hint, encrypted, target_id, int(user_id)),
            )
            cred_id = target_id
        else:
            cur.execute(
                """
                INSERT INTO qd_exchange_credentials
                    (user_id, name, exchange_id, api_key_hint, encrypted_config, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, NOW(), NOW())
                RETURNING id
                """,
                (int(user_id), f"{vault_cfg['broker']} {login}", vault_cfg["exchange_id"], hint, encrypted),
            )
            cred_id = int((cur.fetchone() or {}).get("id") or 0)
        db.commit()
        cur.close()
    return cred_id


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
            saved = _load_saved_mt5_config(int(getattr(g, "user_id", 1) or 1))
            data = _placeholder_status()
            if saved:
                data.update({
                    "saved": True,
                    "credential_id": saved.get("credential_id") or 0,
                    "broker": saved.get("broker") or data["broker"],
                    "server": saved.get("mt5_server") or saved.get("server") or "",
                    "login": saved.get("mt5_login") or saved.get("login") or None,
                })
            return jsonify({"success": True, "data": data})
        data = client.get_connection_status()
        user_id = int(getattr(g, "user_id", 1) or 1)
        saved = _load_saved_mt5_config(user_id)
        cfg = getattr(client, "config", None)
        if not saved and cfg and cfg.login and cfg.password and cfg.server:
            saved = {"credential_id": _save_or_update_mt5_credential(user_id, cfg)}
        if saved:
            data["credential_id"] = saved.get("credential_id") or 0
            data["saved"] = True
        return jsonify({"success": True, "data": data})
    except Exception as e:
        logger.error("MT5 status failed: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@mt5_blp.route("/connect", methods=["POST"])
@login_required
def connect():
    try:
        if not local_desktop_brokers_allowed():
            return jsonify({"success": False, "error": desktop_broker_cloud_reject_message()}), 400

        user_id = int(getattr(g, "user_id", 1) or 1)
        data = request.get_json() or {}
        credential_id = _int(data.get("credential_id") or data.get("credentialId"), 0)
        if credential_id > 0:
            saved = _load_saved_mt5_config(user_id, credential_id)
            if not saved:
                return jsonify({"success": False, "error": "Saved MT5 credential not found"}), 404
            merged = dict(saved)
            for key, value in data.items():
                if key in ("credential_id", "credentialId") or value in (None, ""):
                    continue
                merged[key] = value
            data = merged
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

        cred_id = credential_id if credential_id > 0 else _save_or_update_mt5_credential(user_id, config)
        _sessions.set(client)
        status = client.get_connection_status()
        status["credential_id"] = cred_id
        status["saved"] = True
        return jsonify({"success": True, "message": "Connected successfully", "data": status})
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
