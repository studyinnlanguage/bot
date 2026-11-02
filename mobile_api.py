"""
WEEXIONIC Mobile API — JWT bearer layer for the native mobile clients.

Design rules (see docs/ARCHITECTURE.md):
- SAME user accounts as the web (users table). No duplicate identity, web and
  mobile share sessions/subscription state.
- Access token 12h / refresh token 30d, HS256, secrets live only on the server.
- ROLE SEPARATION: this layer exposes ZERO admin endpoints. Web admin keeps its
  own cookie + role check; a mobile JWT can never reach /api/admin/* because
  those routes authenticate via the Flask session cookie only.
- The bot plane proxies to the user's PRIVATE bot-engine through proxy_to_bot()
  with the X-Bot-Token injected server-side. Users never see hosts, ports or
  tokens. Exchange API secrets never leave the server (masked values only).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
import uuid
from datetime import datetime, timezone, timedelta

from flask import Blueprint, jsonify, request, current_app

logger = logging.getLogger("mobile_api")

mobile_bp = Blueprint("mobile_api", __name__, url_prefix="/api/mobile")

# ---------------------------------------------------------------------------
# Module registry (bound once from app.py to avoid circular imports)
# ---------------------------------------------------------------------------
_cfg = {
    "db": None,            # the live in-memory DB dict
    "save_db": None,       # persist function
    "rate_limit": None,    # _check_rate_limit(key, max_requests, window_seconds)
    "encrypt": None,       # Fernet encrypt()
    "decrypt": None,       # Fernet decrypt()
    "verify_password": None,
    "check_subscription": None,
    "proxy_to_bot": None,      # (user_id, method, path, body) -> dict
    "ensure_bot": None,        # (user_id) -> {"success", "port", ...}
    "start_bot": None,         # (user_id) -> dict
    "stop_bot": None,          # (user_id) -> dict
    "bot_processes": None,     # accessor for DB["bot_processes"]
    "flask_secret": None,      # to derive JWT secret
    "admin_secret_path": "/x7k2-admin",
    "packages": None,              # static PACKAGES dict
    "verify_tx": None,             # _verify_tx_blockchain(tx, amount)
    "activate_order": None,        # _activate_order_and_credit_referral(...)
    "payment_lock": None,          # shared payment serialization lock
    "payout_lock": None,           # shared payout serialization lock
}


def init_module(db, save_db, rate_limit, encrypt, decrypt, verify_password,
                check_subscription, proxy_to_bot, ensure_bot, start_bot,
                stop_bot, flask_secret, packages, verify_tx, activate_order,
                payment_lock, payout_lock):
    _cfg.update({
        "db": db, "save_db": save_db, "rate_limit": rate_limit,
        "encrypt": encrypt, "decrypt": decrypt, "verify_password": verify_password,
        "check_subscription": check_subscription, "proxy_to_bot": proxy_to_bot,
        "ensure_bot": ensure_bot, "start_bot": start_bot, "stop_bot": stop_bot,
        "flask_secret": flask_secret, "packages": packages,
        "verify_tx": verify_tx, "activate_order": activate_order,
        "payment_lock": payment_lock, "payout_lock": payout_lock,
    })


def _db():
    return _cfg["db"]


def _save():
    _cfg["save_db"](_db())


# ---------------------------------------------------------------------------
# JWT (HS256) — compact, dependency-free
# ---------------------------------------------------------------------------
_ACCESS_TTL = 12 * 3600
_REFRESH_TTL = 30 * 86400


def _jwt_secret() -> bytes:
    raw = os.environ.get("MOBILE_JWT_SECRET", "")
    if not raw:
        # Derived from the Flask secret so tokens die if the app secret rotates
        raw = "weexionic-mobile:" + (_cfg["flask_secret"] or "")
    return hashlib.sha256(raw.encode("utf-8")).digest()


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_dec(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def jwt_encode(payload: dict, ttl: int) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    body = {**payload, "iat": int(time.time()), "exp": int(time.time()) + ttl,
            "jti": secrets.token_hex(8)}
    h = _b64url(json.dumps(header, separators=(",", ":")).encode())
    p = _b64url(json.dumps(body, separators=(",", ":")).encode())
    sig = hmac.new(_jwt_secret(), f"{h}.{p}".encode(), hashlib.sha256).digest()
    return f"{h}.{p}.{_b64url(sig)}"


def jwt_decode(token: str) -> dict | None:
    try:
        h, p, s = token.split(".")
        expected = hmac.new(_jwt_secret(), f"{h}.{p}".encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _b64url_dec(s)):
            return None
        body = json.loads(_b64url_dec(p))
        if int(body.get("exp", 0)) < int(time.time()):
            return None
        # Refresh-token blocklist (logout) — checked for refresh tokens only
        if body.get("typ") == "refresh":
            revoked = (_db().get("revoked_tokens") or {}).get(body.get("jti", ""))
            if revoked is not None:
                return None
        return body
    except Exception:
        return None


def mobile_verify_token(token: str) -> dict | None:
    """Validate an ACCESS token; returns claims or None."""
    claims = jwt_decode(token)
    if claims and claims.get("typ") == "access":
        return claims
    return None


def _issue_tokens(user: dict) -> dict:
    return {
        "access_token": jwt_encode({"uid": user["id"], "role": user.get("role", "user"),
                                    "typ": "access"}, _ACCESS_TTL),
        "refresh_token": jwt_encode({"uid": user["id"], "typ": "refresh"}, _REFRESH_TTL),
        "token_type": "Bearer",
        "expires_in": _ACCESS_TTL,
    }


def _bearer_claims() -> dict | None:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    return mobile_verify_token(auth[7:].strip())


def _current_mobile_user() -> dict | None:
    claims = _bearer_claims()
    if not claims:
        return None
    user = (_db().get("users") or {}).get(claims.get("uid", ""))
    if not user or user.get("banned"):
        return None
    return user


def _unauthorized():
    return jsonify({"success": False, "error": "Authentication required"}), 401


def _subscription_snapshot(user: dict) -> dict:
    sub = _cfg["check_subscription"](user)
    return {
        "plan": sub.get("plan", "none"),
        "status": sub.get("status", "inactive"),
        "expires_at": (user.get("subscription") or {}).get("expires_at"),
        "days_left": sub.get("days_left"),
        "active": bool(sub.get("active")),
    }


def _user_snapshot(user: dict) -> dict:
    cfg = user.get("bot_config", {})
    return {
        "id": user["id"],
        "email": user.get("email"),
        "name": user.get("name") or (user.get("email") or "").split("@")[0],
        "role": user.get("role", "user"),
        "created_at": user.get("created_at"),
        "subscription": _subscription_snapshot(user),
        "license_key": user.get("license_key"),
        "bot_config": {
            "exchange": cfg.get("exchange", "binance"),
            "testnet": cfg.get("testnet", True),
            "has_api_key": bool(cfg.get("api_key_enc")),
            "has_api_secret": bool(cfg.get("api_secret_enc")),
            "has_passphrase": bool(cfg.get("api_passphrase_enc")),
        },
    }


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
@mobile_bp.post("/auth/register")
def m_register():
    db = _db()
    data = request.get_json(force=True, silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    name = (data.get("name") or "").strip()[:80]
    if not _cfg["rate_limit"](f"m_register:{request.remote_addr}", 3, 600):
        return jsonify({"success": False, "error": "Too many attempts. Try later."}), 429
    if not email or "@" not in email or "." not in email:
        return jsonify({"success": False, "error": "Please enter a valid email address"}), 400
    if len(password) < 8:
        return jsonify({"success": False, "error": "Password must be at least 8 characters"}), 400
    for u in db["users"].values():
        if (u.get("email") or "").lower() == email:
            return jsonify({"success": False, "error": "An account with this email already exists. Please log in."}), 409

    from werkzeug.security import generate_password_hash
    user_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    referral_code = user_id[:8].upper()
    referred_by = None
    ref_code = (data.get("referral_code") or "").strip().upper()
    if ref_code:
        for u in db["users"].values():
            if u.get("referral_code") == ref_code:
                referred_by = u["id"]
                break

    user = {
        "id": user_id, "email": email, "name": name or email.split("@")[0],
        "password_hash": generate_password_hash(password), "role": "user",
        "banned": False, "created_at": now,
        "subscription": {"plan": "none", "status": "inactive", "started_at": now,
                         "expires_at": None},
        "license_key": None, "referral_code": referral_code,
        "referred_by": referred_by, "referral_earnings": 0.0,
        "referral_history": [], "payout_wallet": "", "payout_requests": [],
        "google_id": None,
        "bot_config": {
            "exchange": "binance", "testnet": True, "symbols_list": [],
            "timeframe": "5m", "leverage": 10, "amount_mode": "fixed",
            "amount": 100, "amount_pct": 10, "stop_loss_pct": 2,
            "take_profit_pct": 6, "tp_mode": "fixed", "mode": "both",
            "max_concurrent_trades": 3,
            "api_key_enc": "", "api_secret_enc": "", "api_passphrase_enc": "",
        },
    }
    db["users"][user_id] = user
    _save()
    logger.info("Mobile signup: %s (ref=%s)", email, ref_code or "-")
    return jsonify({"success": True, "user": _user_snapshot(user), **_issue_tokens(user)}), 201


@mobile_bp.post("/auth/login")
def m_login():
    db = _db()
    data = request.get_json(force=True, silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    if not _cfg["rate_limit"](f"m_login:{request.remote_addr}", 5, 300):
        return jsonify({"success": False, "error": "Too many attempts. Please wait 5 minutes."}), 429
    user = None
    for u in db["users"].values():
        if (u.get("email") or "").lower() == email:
            user = u
            break
    if not user or not _cfg["verify_password"](password, user.get("password_hash", "")):
        return jsonify({"success": False, "error": "Invalid email or password"}), 401
    if user.get("banned"):
        return jsonify({"success": False, "error": "Account suspended. Please contact support."}), 403
    logger.info("Mobile login: %s", email)
    return jsonify({"success": True, "user": _user_snapshot(user), **_issue_tokens(user)})


@mobile_bp.post("/auth/refresh")
def m_refresh():
    data = request.get_json(force=True, silent=True) or {}
    claims = jwt_decode(data.get("refresh_token") or "")
    if not claims or claims.get("typ") != "refresh":
        return jsonify({"success": False, "error": "Session expired. Please log in again."}), 401
    user = (_db().get("users") or {}).get(claims.get("uid", ""))
    if not user or user.get("banned"):
        return jsonify({"success": False, "error": "Account unavailable"}), 401
    return jsonify({"success": True, "user": _user_snapshot(user), **_issue_tokens(user)})


@mobile_bp.post("/auth/google")
def m_google():
    """Exchange a Google ID token (from the native Google sign-in sheet) for
    WEEXIONIC tokens. Only verified emails of the configured client are trusted."""
    db = _db()
    data = request.get_json(force=True, silent=True) or {}
    id_token = (data.get("id_token") or "").strip()
    if not id_token:
        return jsonify({"success": False, "error": "id_token is required"}), 400

    client_id = os.environ.get("GOOGLE_CLIENT_ID", "")
    if not client_id:
        return jsonify({"success": False, "error": "Google sign-in is not configured on the server"}), 501

    import requests as req_lib
    try:
        resp = req_lib.get("https://oauth2.googleapis.com/tokeninfo",
                           params={"id_token": id_token}, timeout=10)
        info = resp.json()
    except Exception as e:
        logger.warning("Google tokeninfo failed: %s", e)
        return jsonify({"success": False, "error": "Google verification failed"}), 401

    if info.get("aud") != client_id:
        return jsonify({"success": False, "error": "Google token audience mismatch"}), 401
    email = (info.get("email") or "").lower().strip()
    if not email:
        return jsonify({"success": False, "error": "No email in Google token"}), 401
    if info.get("email_verified") not in (True, "true", "1"):
        return jsonify({"success": False, "error": "Google email is not verified"}), 401
    if int(info.get("exp", 0)) < int(time.time()):
        return jsonify({"success": False, "error": "Google token expired"}), 401

    # Find or create the account (same account as web)
    user = None
    for u in db["users"].values():
        if (u.get("email") or "").lower() == email:
            user = u
            break
    if not user:
        user_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        referred_by = None
        ref_code = (data.get("referral_code") or "").strip().upper()
        if ref_code:
            for u in db["users"].values():
                if u.get("referral_code") == ref_code:
                    referred_by = u["id"]
                    break
        user = {
            "id": user_id, "email": email,
            "name": info.get("name") or email.split("@")[0],
            "password_hash": "", "role": "user", "banned": False, "created_at": now,
            "subscription": {"plan": "none", "status": "inactive", "started_at": now,
                             "expires_at": None},
            "license_key": None, "referral_code": user_id[:8].upper(),
            "referred_by": referred_by, "referral_earnings": 0.0,
            "referral_history": [], "payout_wallet": "", "payout_requests": [],
            "google_id": info.get("sub", ""),
            "bot_config": {
                "exchange": "binance", "testnet": True, "symbols_list": [],
                "timeframe": "5m", "leverage": 10, "amount_mode": "fixed",
                "amount": 100, "amount_pct": 10, "stop_loss_pct": 2,
                "take_profit_pct": 6, "tp_mode": "fixed", "mode": "both",
                "max_concurrent_trades": 3,
                "api_key_enc": "", "api_secret_enc": "", "api_passphrase_enc": "",
            },
        }
        db["users"][user_id] = user
        _save()
        logger.info("Mobile Google signup: %s", email)

    if user.get("banned"):
        return jsonify({"success": False, "error": "Account suspended. Please contact support."}), 403
    if user.get("google_id") != info.get("sub", ""):
        user["google_id"] = info.get("sub", "")
        _save()
    return jsonify({"success": True, "user": _user_snapshot(user), **_issue_tokens(user)})


@mobile_bp.post("/auth/logout")
def m_logout():
    data = request.get_json(force=True, silent=True) or {}
    token = data.get("refresh_token") or ""
    claims = jwt_decode(token)
    if claims and claims.get("typ") == "refresh":
        db = _db()
        db.setdefault("revoked_tokens", {})[claims.get("jti", "")] = claims.get("exp", 0)
        _save()
    return jsonify({"success": True})


@mobile_bp.get("/auth/me")
def m_me():
    user = _current_mobile_user()
    if not user:
        return _unauthorized()
    snap = _user_snapshot(user)
    snap["bot_running"] = bool((_db().get("bot_processes") or {}).get(user["id"], {}).get("should_run"))
    return jsonify({"success": True, "user": snap})


# ---------------------------------------------------------------------------
# Bot plane — everything proxies to the user's private engine
# ---------------------------------------------------------------------------
def _require_sub(user):
    sub = _cfg["check_subscription"](user)
    if not sub.get("active"):
        return jsonify({"success": False, "error": "Subscription inactive. Please activate a package.",
                        "subscription": _subscription_snapshot(user)}), 403
    return None


@mobile_bp.get("/bot/status")
def m_bot_status():
    user = _current_mobile_user()
    if not user:
        return _unauthorized()
    gated = _require_sub(user)
    if gated:
        return gated
    status = _cfg["proxy_to_bot"](user["id"], "GET", "/api/status")
    balance = _cfg["proxy_to_bot"](user["id"], "GET", "/api/balance")
    return jsonify({
        "success": True,
        "engine_running": bool(status.get("running", False)),
        "engine": status if status.get("running") else None,
        "balance": balance if balance.get("success") else None,
        "subscription": _subscription_snapshot(user),
    })


def _proxy_passthrough(path: str):
    user = _current_mobile_user()
    if not user:
        return _unauthorized()
    gated = _require_sub(user)
    if gated:
        return gated
    method = "POST" if request.method == "POST" else "GET"
    body = request.get_json(force=True, silent=True) if method == "POST" else None
    result = _cfg["proxy_to_bot"](user["id"], method, path, body)
    code = 200 if result.get("success", True) else 502
    return jsonify(result), code


@mobile_bp.post("/bot/start")
def m_bot_start():
    user = _current_mobile_user()
    if not user:
        return _unauthorized()
    gated = _require_sub(user)
    if gated:
        return gated
    result = _cfg["start_bot"](user["id"])
    return jsonify(result), (200 if result.get("success") else 502)


@mobile_bp.post("/bot/stop")
def m_bot_stop():
    user = _current_mobile_user()
    if not user:
        return _unauthorized()
    return jsonify(_cfg["stop_bot"](user["id"]))


@mobile_bp.post("/bot/force_stop")
def m_bot_force_stop():
    return _proxy_passthrough("/api/force_stop")


@mobile_bp.route("/bot/config", methods=["GET", "POST"])
def m_bot_config():
    user = _current_mobile_user()
    if not user:
        return _unauthorized()

    if request.method == "GET":
        config = user.get("bot_config", {})
        return jsonify({
            "success": True,
            "config": {
                **config,
                "api_key_enc": None, "api_secret_enc": None, "api_passphrase_enc": None,
                "has_api_key": bool(config.get("api_key_enc")),
                "has_api_secret": bool(config.get("api_secret_enc")),
                "has_passphrase": bool(config.get("api_passphrase_enc")),
            },
        })

    data = request.get_json(force=True, silent=True) or {}
    config = user.setdefault("bot_config", {})

    # ---- validation mirroring the web config route ----
    if "exchange" in data:
        ex = str(data["exchange"]).lower().strip()
        if ex not in ("binance", "weex", "primexbt"):
            return jsonify({"success": False, "error": "Unsupported exchange"}), 400
        config["exchange"] = ex
    if "testnet" in data:
        config["testnet"] = bool(data["testnet"])
    if "api_key" in data and data["api_key"]:
        config["api_key_enc"] = _cfg["encrypt"](str(data["api_key"]).strip())
    if "api_secret" in data and data["api_secret"]:
        config["api_secret_enc"] = _cfg["encrypt"](str(data["api_secret"]).strip())
    if "api_passphrase" in data and data["api_passphrase"]:
        config["api_passphrase_enc"] = _cfg["encrypt"](str(data["api_passphrase"]).strip())
    if "symbols_list" in data:
        symbols = data["symbols_list"]
        if isinstance(symbols, str):
            symbols = [s for s in symbols.replace(",", " ").split() if s]
        if not isinstance(symbols, list):
            symbols = []
        config["symbols_list"] = [str(s).upper().strip() for s in symbols if str(s).strip()]
    if "timeframe" in data:
        config["timeframe"] = str(data["timeframe"])
    if "leverage" in data:
        try:
            lev = int(data["leverage"])
        except (TypeError, ValueError):
            return jsonify({"success": False, "error": "Invalid leverage"}), 400
        max_lev = 1000 if config.get("exchange") == "primexbt" else (500 if config.get("exchange") == "weex" else 125)
        config["leverage"] = max(1, min(max_lev, lev or 10))
    if "amount_mode" in data:
        config["amount_mode"] = "percent" if data["amount_mode"] == "percent" else "fixed"
    if "amount" in data:
        try:
            config["amount"] = max(1, float(data["amount"]) or 100)
        except (TypeError, ValueError):
            return jsonify({"success": False, "error": "Invalid amount"}), 400
    if "amount_pct" in data:
        try:
            config["amount_pct"] = max(1, min(100, float(data["amount_pct"]) or 10))
        except (TypeError, ValueError):
            return jsonify({"success": False, "error": "Invalid amount percent"}), 400
    if "stop_loss_pct" in data:
        try:
            sl = max(0.5, min(50, float(data["stop_loss_pct"]) or 2))
        except (TypeError, ValueError):
            return jsonify({"success": False, "error": "Invalid stop loss"}), 400
        config["stop_loss_pct"] = sl
        config["take_profit_pct"] = sl  # strict 1:1 TP/SL (engine enforces the same)
    if "mode" in data:
        config["mode"] = data["mode"] if data["mode"] in ("long", "short", "both") else "both"
    if "max_concurrent_trades" in data:
        try:
            config["max_concurrent_trades"] = max(1, min(3, int(data["max_concurrent_trades"])))
        except (TypeError, ValueError):
            config["max_concurrent_trades"] = 3
    if "min_ema_spread" in data:
        try:
            config["min_ema_spread"] = max(0, min(5, float(data["min_ema_spread"]) or 0))
        except (TypeError, ValueError):
            config["min_ema_spread"] = 0
    if "fresh_window" in data:
        try:
            config["fresh_window"] = max(2, min(50, int(data["fresh_window"]) or 8))
        except (TypeError, ValueError):
            config["fresh_window"] = 8
    # Notifications (Radar tab)
    for key in ("telegram_enabled", "email_enabled", "whatsapp_enabled"):
        if key in data:
            config[key] = bool(data[key])
    for key in ("telegram_bot_token", "telegram_chat_id", "email_smtp_server",
                "email_sender", "email_password", "email_receiver",
                "whatsapp_phone", "whatsapp_apikey"):
        if key in data and data[key] is not None:
            config[key] = str(data[key])
    if "email_smtp_port" in data:
        try:
            config["email_smtp_port"] = int(data["email_smtp_port"]) or 587
        except (TypeError, ValueError):
            config["email_smtp_port"] = 587

    _save()

    # Live-sync to the engine when it is running (same semantics as the web flow)
    engine_result = None
    status = _db().get("bot_processes", {}).get(user["id"])
    if status and status.get("running"):
        engine_payload = {k: v for k, v in config.items() if not k.endswith("_enc")}
        for src, dst in (("api_key_enc", "api_key"), ("api_secret_enc", "api_secret"),
                         ("api_passphrase_enc", "api_passphrase")):
            if config.get(src):
                try:
                    engine_payload[dst] = _cfg["decrypt"](config[src])
                except Exception:
                    pass
        engine_result = _cfg["proxy_to_bot"](user["id"], "POST", "/api/config", engine_payload)

    return jsonify({
        "success": True,
        "engine_sync": engine_result,
        "config": {
            **config,
            "api_key_enc": None, "api_secret_enc": None, "api_passphrase_enc": None,
            "has_api_key": bool(config.get("api_key_enc")),
            "has_api_secret": bool(config.get("api_secret_enc")),
            "has_passphrase": bool(config.get("api_passphrase_enc")),
        },
    })


@mobile_bp.route("/bot/positions", methods=["GET"])
def m_bot_positions():
    sym = (request.args.get("symbol") or "").strip()
    path = f"/api/positions?symbol={sym}" if sym else "/api/positions"
    return _proxy_passthrough(path)


@mobile_bp.route("/bot/trades", methods=["GET"])
def m_bot_trades():
    from urllib.parse import quote
    limit = (request.args.get("limit") or "100").strip()
    symbol = (request.args.get("symbol") or "").strip()
    path = f"/api/trades?limit={quote(limit)}"
    if symbol:
        path += f"&symbol={quote(symbol.upper())}"
    return _proxy_passthrough(path)


@mobile_bp.post("/bot/trades/clear")
def m_bot_trades_clear():
    return _proxy_passthrough("/api/trades/clear")


@mobile_bp.post("/bot/close")
def m_bot_close():
    return _proxy_passthrough("/api/close")


@mobile_bp.post("/bot/close_all")
def m_bot_close_all():
    return _proxy_passthrough("/api/close_all")


@mobile_bp.get("/bot/symbols")
def m_bot_symbols():
    return _proxy_passthrough("/api/symbols")


@mobile_bp.get("/bot/balance")
def m_bot_balance():
    return _proxy_passthrough("/api/balance")


@mobile_bp.get("/bot/price")
def m_bot_price():
    sym = (request.args.get("symbol") or "").strip()
    return _proxy_passthrough(f"/api/price?symbol={sym}")


@mobile_bp.get("/bot/test_chart")
def m_bot_test_chart():
    sym = (request.args.get("symbol") or "").strip()
    return _proxy_passthrough(f"/api/test_chart?symbol={sym}")


@mobile_bp.post("/bot/leverage")
def m_bot_leverage():
    return _proxy_passthrough("/api/leverage")


@mobile_bp.post("/bot/active_symbol")
def m_bot_active_symbol():
    return _proxy_passthrough("/api/active_symbol")


@mobile_bp.post("/bot/test_connection")
def m_bot_test_connection():
    return _proxy_passthrough("/api/test_connection")


@mobile_bp.post("/bot/test_notification")
def m_bot_test_notification():
    return _proxy_passthrough("/api/test_notification")


# ---------------------------------------------------------------------------
# Subscription / packages / orders
# ---------------------------------------------------------------------------
@mobile_bp.get("/packages")
def m_packages():
    # Wallets saved from the web Admin Panel live in DB settings (two shapes
    # used over time); ENV vars are only the fallback. Previously ENV-only,
    # so the app showed "Wallet address unavailable" even after saving.
    try:
        _db = _cfg.get("db") or {}
        _st = _db.get("settings") or {}
        _s = _st.get("payment_wallets") or {}
        _w = _st.get("wallets") or {}
    except Exception:
        _s, _w = {}, {}
    trc20 = _s.get("wallet_trc20") or _w.get("trc20") or os.environ.get("PAYMENT_WALLET_TRC20", "")
    bep20 = _s.get("wallet_bep20") or _w.get("bep20") or os.environ.get("PAYMENT_WALLET_BEP20", "")
    return jsonify({"success": True, "packages": _cfg["packages"],
                    "wallets": {"trc20": trc20, "bep20": bep20}})


@mobile_bp.post("/license/activate")
def m_license_activate():
    user = _current_mobile_user()
    if not user:
        return _unauthorized()
    db = _db()
    data = request.get_json(force=True, silent=True) or {}
    key = (data.get("key") or "").strip().upper()
    if not key:
        return jsonify({"success": False, "error": "License key is required"}), 400
    lic = db.get("licenses", {}).get(key)
    if not lic:
        return jsonify({"success": False, "error": "Invalid license key"}), 404
    if lic.get("revoked"):
        return jsonify({"success": False, "error": "This license key has been revoked"}), 403
    if lic.get("used_by") and lic["used_by"] != user["id"]:
        holder = db["users"].get(lic["used_by"], {})
        if (holder.get("email") or "").lower() != (user.get("email") or "").lower():
            return jsonify({"success": False, "error": "This license key is already used by another account"}), 403
    expires_at = lic.get("expires_at")
    if expires_at:
        try:
            if datetime.fromisoformat(expires_at.replace("Z", "+00:00")) < datetime.now(timezone.utc):
                return jsonify({"success": False, "error": "This license key has expired"}), 403
        except ValueError:
            pass
    lic["used_by"] = user["id"]
    lic["activated_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    lic["active"] = True
    # deactivate old license of this user
    for k, l in db.get("licenses", {}).items():
        if l.get("used_by") == user["id"] and k != key:
            l["active"] = False
    user["license_key"] = key
    user["subscription"] = {
        "plan": lic.get("plan", "basic"), "status": "active",
        "started_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "expires_at": expires_at,
    }
    _save()
    logger.info("Mobile license activation: %s -> %s", user.get("email"), key)
    return jsonify({"success": True, "subscription": _subscription_snapshot(user),
                    "message": "License activated successfully"})


@mobile_bp.post("/orders/create")
def m_order_create():
    user = _current_mobile_user()
    if not user:
        return _unauthorized()
    db = _db()
    data = request.get_json(force=True, silent=True) or {}
    package_id = data.get("package_id") or data.get("package")
    pkg = (_cfg["packages"] or {}).get(package_id)
    if not pkg:
        return jsonify({"success": False, "error": "Invalid package selected"}), 400
    sub = _cfg["check_subscription"](user)
    if sub.get("active"):
        return jsonify({"success": False, "error": "Your subscription is already active"}), 400
    # one open order at a time
    for o in db.get("orders", {}).values():
        if o["user_id"] == user["id"] and o.get("status") in ("pending", "submitted"):
            return jsonify({"success": False, "error": "You already have a pending payment order",
                            "order_id": o["id"]}), 409
    order_id = "ORD-" + secrets.token_hex(4).upper()
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    order = {
        "id": order_id, "user_id": user["id"], "user_email": user.get("email"),
        "user_name": user.get("name"), "package_id": package_id,
        "package_name": pkg.get("name", package_id), "amount": pkg.get("price", 0),
        "currency": "USDT", "days": pkg.get("days", 30), "status": "pending",
        "tx_hash": "", "screenshot": "", "created_at": now, "submitted_at": None,
        "verified_at": None, "license_key": None, "rejection_reason": None,
    }
    db.setdefault("orders", {})[order_id] = order
    _save()
    return jsonify({"success": True, "order": order}), 201


@mobile_bp.get("/orders/my")
def m_orders_my():
    user = _current_mobile_user()
    if not user:
        return _unauthorized()
    orders = [o for o in (_db().get("orders") or {}).values() if o["user_id"] == user["id"]]
    orders.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return jsonify({"success": True, "orders": orders})


@mobile_bp.post("/orders/submit")
def m_order_submit():
    """Submit tx hash + optional screenshot for blockchain verification."""
    user = _current_mobile_user()
    if not user:
        return _unauthorized()
    db = _db()
    order_id = (request.form.get("order_id") or "").strip()
    tx_hash = (request.form.get("tx_hash") or "").strip()
    order = db.get("orders", {}).get(order_id)
    if not order or order["user_id"] != user["id"]:
        return jsonify({"success": False, "error": "Order not found"}), 404
    if order.get("status") in ("verified", "rejected"):
        return jsonify({"success": False, "error": f"Order already {order['status']}"}), 400
    if not tx_hash:
        return jsonify({"success": False, "error": "Transaction hash is required"}), 400

    screenshot_path = ""
    file = request.files.get("screenshot")
    if file and file.filename:
        allowed = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
        ext = "." + file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
        if ext not in allowed:
            return jsonify({"success": False, "error": "Screenshot must be an image (jpg/png/webp/gif)"}), 400
        blob = file.read()
        if len(blob) > 5 * 1024 * 1024:
            return jsonify({"success": False, "error": "Screenshot must be under 5MB"}), 400
        head = blob[:12]
        ok_magic = head[:3] == b"\xff\xd8\xff" or head[:8] == b"\x89PNG\r\n\x1a\n" or \
            head[:4] in (b"GIF8",) or (head[:4] == b"RIFF" and head[8:12] == b"WEBP")
        if not ok_magic:
            return jsonify({"success": False, "error": "That file is not a valid image"}), 400
        from pathlib import Path
        upload_dir = Path(current_app.root_path) / "uploads"
        upload_dir.mkdir(exist_ok=True)
        safe_name = f"ORD-{secrets.token_hex(6)}{ext}"
        (upload_dir / safe_name).write_bytes(blob)
        screenshot_path = safe_name

    with _cfg["payment_lock"]:
        order["tx_hash"] = tx_hash
        if screenshot_path:
            order["screenshot"] = screenshot_path
        order["status"] = "submitted"
        order["submitted_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        _save()
        verified, note = _cfg["verify_tx"](tx_hash, float(order.get("amount", 79)))
        if verified:
            _, lic_key, _email_res = _cfg["activate_order"](order, verified_by="auto_blockchain")
            clean_tx = tx_hash.strip().lower()
            clean_tx_no_0x = clean_tx[2:] if clean_tx.startswith("0x") else clean_tx
            db.setdefault("used_txids", {})[clean_tx] = order_id
            db["used_txids"][clean_tx_no_0x] = order_id
            _save()
            logger.info("Mobile order %s AUTO-VERIFIED for %s: %s", order_id, user["email"], note)
            return jsonify({"success": True, "verified": True, "auto_verified": True,
                            "license_key": lic_key,
                            "message": "Payment verified on blockchain! Your Bot has been activated."})

    logger.info("Mobile order %s submitted by %s (tx=%s) status: %s", order_id, user["email"], tx_hash[:20], note)
    return jsonify({"success": True, "verified": False,
                    "message": "Payment proof submitted! Verification usually completes in 1-2 minutes."})


@mobile_bp.route("/orders/check-verification/<order_id>", methods=["POST"])
def m_order_check(order_id):
    user = _current_mobile_user()
    if not user:
        return _unauthorized()
    db = _db()
    order = db.get("orders", {}).get(order_id)
    if not order or order["user_id"] != user["id"]:
        return jsonify({"success": False, "error": "Order not found"}), 404
    if order.get("status") == "verified":
        return jsonify({"success": True, "verified": True,
                        "license_key": order.get("license_key")})
    if order.get("status") == "rejected":
        return jsonify({"success": True, "verified": False, "status": "rejected",
                        "reason": order.get("rejection_reason")})
    tx_hash = (order.get("tx_hash") or "").strip()
    if tx_hash and order.get("status") == "submitted":
        with _cfg["payment_lock"]:
            verified, note = _cfg["verify_tx"](tx_hash, float(order.get("amount", 79)))
            if verified:
                _, lic_key, _email_res = _cfg["activate_order"](order, verified_by="auto_blockchain")
                clean_tx = tx_hash.strip().lower()
                clean_tx_no_0x = clean_tx[2:] if clean_tx.startswith("0x") else clean_tx
                db.setdefault("used_txids", {})[clean_tx] = order_id
                db["used_txids"][clean_tx_no_0x] = order_id
                _save()
                return jsonify({"success": True, "verified": True, "license_key": lic_key})
    return jsonify({"success": True, "verified": False, "status": order.get("status", "pending")})


# ---------------------------------------------------------------------------
# Referral & payouts
# ---------------------------------------------------------------------------
@mobile_bp.get("/user/referral")
def m_referral():
    user = _current_mobile_user()
    if not user:
        return _unauthorized()
    db = _db()
    referred_users = []
    referral_history = user.get("referral_history", [])
    for u in db["users"].values():
        if u.get("referred_by") == user["id"]:
            raw = u.get("email", "")
            at = raw.find("@")
            masked = (raw[:2] + "***" + raw[at:]) if at > 2 else "***@***"
            sub = u.get("subscription", {})
            is_active = sub.get("status") == "active" or bool(u.get("license_key"))
            earned_from_user = sum(float(h.get("bonus_amount", 0.0)) for h in referral_history
                                   if h.get("buyer_id") == u["id"])
            referred_users.append({
                "id": u["id"][:8], "email": masked,
                "name": u.get("name") or masked.split("@")[0],
                "created_at": u.get("created_at"), "has_license": is_active,
                "plan": sub.get("plan") if is_active else "none",
                "bonus_earned": earned_from_user,
            })
    total_earnings = float(user.get("referral_earnings", 0.0) or 0.0)
    payouts = user.get("payout_requests", [])
    total_withdrawn = sum(float(p.get("amount", 0)) for p in payouts if p.get("status") == "paid")
    pending = sum(float(p.get("amount", 0)) for p in payouts if p.get("status") == "pending")
    return jsonify({
        "success": True,
        "referral_code": user.get("referral_code", ""),
        "referral_link": f"https://weexionic.duckdns.org/?ref={user.get('referral_code', '')}",
        "referred_users": referred_users,
        "referral_history": referral_history,
        "total_earnings": round(total_earnings, 2),
        "total_withdrawn": round(total_withdrawn, 2),
        "pending_payout": round(pending, 2),
        "available_balance": round(max(0.0, total_earnings - total_withdrawn - pending), 2),
        "payout_wallet": user.get("payout_wallet", ""),
        "payout_requests": payouts,
    })


@mobile_bp.post("/user/payout-wallet")
def m_payout_wallet():
    user = _current_mobile_user()
    if not user:
        return _unauthorized()
    data = request.get_json(force=True, silent=True) or {}
    wallet = (data.get("wallet_address") or "").strip()
    if len(wallet) < 10:
        return jsonify({"success": False, "error": "Please enter a valid USDT wallet address"}), 400
    user["payout_wallet"] = wallet
    _save()
    return jsonify({"success": True, "payout_wallet": wallet})


@mobile_bp.post("/user/request-payout")
def m_request_payout():
    user = _current_mobile_user()
    if not user:
        return _unauthorized()
    data = request.get_json(force=True, silent=True) or {}
    wallet = (data.get("wallet_address") or user.get("payout_wallet") or "").strip()
    if not wallet:
        return jsonify({"success": False, "error": "Please provide a USDT payout wallet address"}), 400
    with _cfg["payout_lock"]:
        payouts = user.setdefault("payout_requests", [])
        total_earnings = float(user.get("referral_earnings", 0.0) or 0.0)
        withdrawn = sum(float(p.get("amount", 0)) for p in payouts if p.get("status") == "paid")
        pending = sum(float(p.get("amount", 0)) for p in payouts if p.get("status") == "pending")
        available = max(0.0, round(total_earnings - withdrawn - pending, 2))
        if available <= 0:
            return jsonify({"success": False, "error": "No available referral commission to withdraw"}), 400
        entry = {
            "id": "PAY-" + secrets.token_hex(4).upper(), "amount": available,
            "currency": "USDT", "wallet_address": wallet, "status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "paid_at": None, "tx_hash": "",
        }
        user["payout_wallet"] = wallet
        payouts.append(entry)
        _save()
    logger.info("Mobile payout request %s: %s $%s", entry["id"], user.get("email"), available)
    return jsonify({"success": True, "payout": entry})
