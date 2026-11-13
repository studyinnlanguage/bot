"""
Flask Web Application - Trading Bot UI
BOT ENGINE - Requests must come from the SaaS proxy (verified via X-Bot-Token header)

This bot engine is spawned by the SaaS app. Login/license is handled
by the parent SaaS app. This is only the trading bot.
All API access is protected by a shared secret token injected by the SaaS proxy.
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from flask import Flask, jsonify, render_template, request, Response, session
from flask_socketio import SocketIO

from bot.engine import BotEngine, get_trader
from bot.cred_slots import (
    EXCHANGES, clean_cred, normalize_cred_slots, slot_has_creds,
    store_creds_in_slot, archive_flat_into_slot, hydrate_flat_from_slot,
    merge_external_slots, saved_exchanges_summary, resolve_exchange,
)

# ---------- Setup ----------
try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")
    load_dotenv(BASE_DIR.parent / ".env")
except Exception:
    pass

CONFIG_FILE = BASE_DIR / "config.json"
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_DIR / "bot.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("app")

app = Flask(__name__, template_folder=str(BASE_DIR / "templates"),
            static_folder=str(BASE_DIR / "static"))
app.config["SECRET_KEY"] = os.environ.get("BOT_ENGINE_SECRET", secrets.token_hex(32))
# Theme iterations move fast: never let the browser cache stale CSS/JS across redeploys.
# (0 = always revalidate; changed files are picked up immediately after a redeploy.)
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

# Security: Suppress Werkzeug server banner disclosure in development / fallback modes
try:
    from werkzeug.serving import WSGIRequestHandler
    WSGIRequestHandler.server_version = "Web-Server"
    WSGIRequestHandler.sys_version = ""
except Exception:
    pass

@app.after_request
def apply_security_headers(response):
    response.headers["Server"] = "Web-Server"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    return response

# Fix 12: Shared secret token — set by parent SaaS when spawning this process.
# Requests without the correct X-Bot-Token header are rejected.
_BOT_ENGINE_TOKEN = os.environ.get("BOT_ENGINE_TOKEN", "")
if not _BOT_ENGINE_TOKEN:
    logger.warning("[SECURITY] BOT_ENGINE_TOKEN not set — API endpoints are unprotected!")

socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode="threading",
    ping_timeout=60,
    ping_interval=25,
    logger=False,
    engineio_logger=False,
)

# Fix 12: Static files, socket.io polling packets, and root page do not require manual token
# (Socket.IO manages its own connection sessions; browser loads static/HTML via SaaS proxy).
# API endpoints (/api/...) must have the valid X-Bot-Token.
_UNPROTECTED_PATHS = ("/", "/favicon.ico")

@app.before_request
def _verify_bot_token():
    """Reject API requests not bearing the correct X-Bot-Token header."""
    if not _BOT_ENGINE_TOKEN:
        return  # token not configured — skip check (warn logged at startup)
    # Allow static files, socket.io transport packets, and the root page without a token
    if request.path.startswith("/static/") or request.path.startswith("/socket.io") or request.path in _UNPROTECTED_PATHS:
        return
    incoming = request.headers.get("X-Bot-Token", "")
    if not incoming or not secrets.compare_digest(incoming, _BOT_ENGINE_TOKEN):
        logger.warning("[SECURITY] Blocked request without valid X-Bot-Token: %s %s",
                       request.method, request.path)
        return Response("Unauthorized", status=403)

# ---------- Default config ----------

DEFAULT_CONFIG = {
    "api_key": "",
    "api_secret": "",
    "api_passphrase": "",
    # PER-EXCHANGE CREDENTIAL MEMORY: credentials are remembered per exchange
    # so switching Binance <-> WEEX <-> PrimeXBT auto-loads the right set
    # instead of reusing/overwriting one shared set (root cause of the
    # "switch exchange -> API error / key length mismatch" reports).
    "api_keys": {},
    "exchange": "binance",
    "testnet": True,
    "symbol": "BTCUSDT",
    "symbols_list": ["BTCUSDT"],
    "timeframe": "5m",
    "leverage": 125,
    "amount_mode": "fixed",
    "amount": 100,
    "amount_pct": 10,
    "stop_loss_pct": 0.2,
    "take_profit_pct": 1.0,
    "trailing_roe_pct": 100.0,
    "tp_mode": "fixed",
    "mode": "both",
    "auto_start": False,
    "telegram_enabled": False,
    "telegram_bot_token": "",
    "telegram_chat_id": "",
    "email_enabled": False,
    "email_smtp_server": "smtp.gmail.com",
    "email_smtp_port": 587,
    "email_sender": "",
    "email_password": "",
    "email_receiver": "",
    "whatsapp_enabled": False,
    "whatsapp_phone": "",
    "whatsapp_apikey": "",
    "max_concurrent_trades": 3,
    "reentry_cooldown_sec": 180,
    "min_ema_spread": 0,
    "fresh_window": 2,
}


def load_config() -> dict:
    # Try the live config first, then the last-good backup. A crash or power
    # cut mid-write used to leave a truncated config.json behind, which made
    # the bot silently reset ALL dashboard settings (coins, leverage, SL,
    # exchange...) to defaults on the next start — the backup fixes that.
    for path in (CONFIG_FILE, CONFIG_FILE.with_suffix(".json.bak")):
        if not path.exists():
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            merged = {**DEFAULT_CONFIG, **cfg}
            # Fixed TP 1.0% & user-adjustable SL (default 0.2%) with auto-reversal
            merged["tp_mode"] = "fixed"
            if cfg.get("tp_mode") == "both" and cfg.get("take_profit_pct") == 6 and cfg.get("stop_loss_pct") == 2:
                merged["stop_loss_pct"] = 0.2
            else:
                try:
                    merged["stop_loss_pct"] = max(0.05, min(50.0, float(merged.get("stop_loss_pct", 0.2) or 0.2)))
                except (ValueError, TypeError):
                    merged["stop_loss_pct"] = 0.2
            merged["take_profit_pct"] = 1.0
            merged["trailing_roe_pct"] = 100.0
            try:
                merged["min_ema_spread"] = max(0.0, min(5.0, float(merged.get("min_ema_spread", 0) or 0)))
            except (ValueError, TypeError):
                merged["min_ema_spread"] = 0.0
            try:
                merged["fresh_window"] = max(2, min(8, int(merged.get("fresh_window", 2) or 2)))
            except (ValueError, TypeError):
                merged["fresh_window"] = 2
            # Per-exchange credential memory: if a slot map exists, the flat
            # fields MUST mirror the ACTIVE exchange's own saved credentials.
            # (A legacy file without slots keeps its flat credentials as-is;
            # they are archived into the right slot at the first live switch —
            # see update_config.)
            if isinstance(merged.get("api_keys"), dict) and any(
                    slot_has_creds(s) for s in normalize_cred_slots(merged["api_keys"]).values()):
                hydrate_flat_from_slot(merged, merged.get("exchange"))
            if path != CONFIG_FILE:
                logger.warning("config.json was unreadable — settings recovered from %s", path.name)
            return merged
        except (json.JSONDecodeError, OSError) as e:
            logger.error("Failed to load config from %s: %s", path.name, e)
    return DEFAULT_CONFIG.copy()


def save_config(cfg: dict):
    """Persist settings WITHOUT ever leaving a half-written config.json.

    The previous direct open(...,"w") write truncated the file first; any
    crash/kill/power-cut in that window corrupted config.json and the next
    start silently reset all settings to defaults. Now: backup the old file,
    write to a temp file, fsync, then atomically os.replace() it into place.
    """
    try:
        if CONFIG_FILE.exists():
            shutil.copyfile(CONFIG_FILE, CONFIG_FILE.with_suffix(".json.bak"))
        tmp = CONFIG_FILE.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, CONFIG_FILE)
    except OSError as e:
        logger.error("Failed to save config: %s", e)


CONFIG = load_config()
ENGINE = BotEngine(socketio, CONFIG)

# Auto-start monitor on startup if API credentials are already saved
if CONFIG.get("api_key") and CONFIG.get("api_secret"):
    try:
        ENGINE.start_monitor(CONFIG)
    except Exception as _e:
        logger.warning("Could not auto-start monitor on startup: %s", _e)


# ---------- Routes ----------

@app.route("/")
def index():
    return render_template("dashboard.html", config=CONFIG)


@app.route("/legal")
@app.route("/privacy")
@app.route("/terms")
@app.route("/security")
@app.route("/disclaimer")
@app.route("/risk-disclaimer")
def legal_hub():
    path = request.path.strip("/").lower()
    default_tab = "disclaimer"
    if "privacy" in path:
        default_tab = "privacy"
    elif "term" in path:
        default_tab = "terms"
    elif "sec" in path:
        default_tab = "security"
    elif "disclaimer" in path or "risk" in path:
        default_tab = "disclaimer"
    return render_template("legal.html", active_tab=default_tab)


@app.route("/favicon.ico")
def favicon():
    png_bytes = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000d49444154789c63000100000005000100"
        "0d0a2db40000000049454e44ae426082"
    )
    return Response(png_bytes, mimetype="image/png")


@app.route("/api/config", methods=["GET"])
def get_config():
    # SECURITY: never return raw secrets to any client (web or mobile).
    # Presence flags + masked previews only.
    _SECRET_FIELDS = (
        "api_key", "api_secret", "api_passphrase", "email_password",
        "telegram_bot_token", "whatsapp_apikey", "api_keys",
    )
    safe = {k: v for k, v in CONFIG.items() if k not in _SECRET_FIELDS}
    safe["has_api_key"] = bool(CONFIG.get("api_key"))
    safe["has_api_secret"] = bool(CONFIG.get("api_secret"))
    safe["has_api_passphrase"] = bool(CONFIG.get("api_passphrase"))
    safe["saved_exchanges"] = saved_exchanges_summary(CONFIG)
    safe["has_telegram_token"] = bool(CONFIG.get("telegram_bot_token"))
    safe["has_email_password"] = bool(CONFIG.get("email_password"))
    safe["has_whatsapp_apikey"] = bool(CONFIG.get("whatsapp_apikey"))
    if safe.get("has_api_key"):
        safe["api_key_masked"] = CONFIG["api_key"][:4] + "***" + CONFIG["api_key"][-4:]
    if safe.get("has_api_secret"):
        safe["api_secret_masked"] = "***"
    return jsonify(safe)


def _handle_exchange_switch(old_exchange: str, new_exchange: str) -> None:
    """Rebuild exchange adapters when the user switches exchange.

    Stops trading workers (exchange positions themselves are NOT touched),
    drops the stale trader object so the next START builds one for the NEW
    exchange, and reconnects the monitor with the new exchange config.
    """
    if 'ENGINE' not in globals() or ENGINE is None:
        return
    try:
        # 1) Safety check: open positions on the OLD exchange lose their
        #    software SL/TP watchdog once the workers stop. Warn loudly.
        open_syms = []
        old_trader = getattr(ENGINE, "trader", None)
        if old_trader is not None:
            for sym in (CONFIG.get("symbols_list") or []):
                try:
                    p = old_trader.get_position(sym)
                    if getattr(p, "side", "NONE") not in (None, "NONE") and getattr(p, "size", 0) > 0:
                        open_syms.append(sym)
                except Exception:
                    continue

        # 2) Stop trading workers (positions on the exchange stay as they are)
        was_running = bool(getattr(ENGINE, "is_running", False))
        if was_running:
            try:
                ENGINE.stop()
            except Exception as e:
                logger.warning("Engine stop during exchange switch failed: %s", e)

        # 3) Drop the stale trader + rebuild the monitor on the NEW exchange
        ENGINE.trader = None
        try:
            ENGINE.stop_monitor()
            ENGINE.start_monitor(CONFIG)
        except Exception as e:
            logger.warning("Monitor rebuild during exchange switch failed: %s", e)

        try:
            ENGINE._emit("log", {
                "level": "warn",
                "msg": (f"\U0001f504 Exchange changed: {old_exchange.upper()} -> {new_exchange.upper()}. "
                        + ("Bot stop kiya gaya aur adapters rebuild ho gaye — START dabayein." if was_running
                           else "Adapters rebuild ho gaye."))
            })
            if open_syms:
                ENGINE._emit("log", {
                    "level": "error",
                    "msg": (f"\u26a0\ufe0f OPEN POSITION(S) purane exchange ({old_exchange.upper()}) par: "
                            f"{', '.join(open_syms)}. Un ka software SL/TP watchdog ab band hai "
                            f"— unhay khud manage/close karein!")
                })
        except Exception:
            pass
        logger.warning("Exchange switch handled: %s -> %s (open on old exchange: %s)",
                       old_exchange, new_exchange, open_syms)
    except Exception as e:
        logger.error("Exchange switch handling failed: %s", e)


@app.route("/api/config", methods=["POST"])
def update_config():
    global CONFIG
    data = request.get_json(force=True)
    # Remember the exchange BEFORE merging the new settings so a live
    # exchange switch can be detected and handled safely.
    prev_exchange = (CONFIG.get("exchange") or "binance").lower()

    for k in ["exchange", "symbol", "symbols_list", "timeframe",
              "leverage", "amount", "amount_mode", "amount_pct",
              "stop_loss_pct", "take_profit_pct", "trailing_roe_pct", "tp_mode", "mode", "testnet", "auto_start",
              "telegram_enabled", "telegram_bot_token", "telegram_chat_id",
              "email_enabled", "email_smtp_server", "email_smtp_port",
              "email_sender", "email_password", "email_receiver",
              "whatsapp_enabled", "whatsapp_phone", "whatsapp_apikey", "max_concurrent_trades",
              "reentry_cooldown_sec",
              "min_ema_spread", "fresh_window", "live_confirmed"]:
        if k in data:
            CONFIG[k] = data[k]
    if data.get("testnet") is False and "live_confirmed" not in data:
        CONFIG["live_confirmed"] = True

    # ---- PER-EXCHANGE CREDENTIAL MEMORY -------------------------------------
    # Credentials are remembered PER EXCHANGE (api_keys slots). The flat
    # api_key/api_secret/api_passphrase stay the LIVE credentials of the
    # ACTIVE exchange for every existing consumer (engine, traders, gates).
    # This replaces the old behaviour of one shared credential set that was
    # silently reused on the new exchange (Binance 64-char key on PrimeXBT
    # -> "API-key format invalid" / length mismatch) and overwritten on save
    # (switch back -> keys gone).
    incoming_exchange = resolve_exchange(data.get("exchange") or CONFIG.get("exchange"))
    # Preserve any legacy flat credentials into prev_exchange's slot before
    # merging external slots or switching exchanges (never overwrites an existing slot).
    if incoming_exchange != prev_exchange or isinstance(data.get("api_keys"), dict):
        archive_flat_into_slot(CONFIG, prev_exchange)
    # 1) Merge a payload-supplied slot map first (mobile API sync sends
    #    api_keys so the engine learns every exchange's credentials).
    if isinstance(data.get("api_keys"), dict):
        merge_external_slots(CONFIG, data["api_keys"])
    # 2) Hydrate flat fields on exchange switch OR external slot sync.
    if incoming_exchange != prev_exchange or isinstance(data.get("api_keys"), dict):
        hydrate_flat_from_slot(CONFIG, incoming_exchange)
    # 3) Newly typed credentials go into the ACTIVE exchange's slot and are
    #    mirrored to the flat fields (a switch + new keys in one save both work).
    if (clean_cred(data.get("api_key")) or clean_cred(data.get("api_secret"))
            or clean_cred(data.get("api_passphrase"))):
        store_creds_in_slot(CONFIG, incoming_exchange,
                            data.get("api_key"), data.get("api_secret"), data.get("api_passphrase"))
        hydrate_flat_from_slot(CONFIG, incoming_exchange)

    CONFIG["exchange"] = incoming_exchange

    # ---- Exchange switch safety ------------------------------------------
    # Detect a live exchange change and rebuild the engine adapters, so the
    # old exchange's trader never receives the new exchange's symbols.
    if CONFIG["exchange"] != prev_exchange:
        _handle_exchange_switch(prev_exchange, CONFIG["exchange"])
        # Tell the user which credentials are now live for the new exchange.
        try:
            _slot_now = normalize_cred_slots(CONFIG.get("api_keys")).get(CONFIG["exchange"]) or {}
            if slot_has_creds(_slot_now):
                socketio.emit("log", {"level": "success",
                                      "msg": (f"\U0001f511 {CONFIG['exchange'].upper()} ki saved credentials "
                                              "auto-load ho gayin — dobara enter karne ki zaroorat nahi.")})
            else:
                socketio.emit("log", {"level": "warn",
                                      "msg": (f"\U0001f511 {CONFIG['exchange'].upper()} ke liye koi API saved nahi "
                                              "— is exchange ki API Key/Secret enter karke SAVE karein.")})
        except Exception:
            pass

    max_lev = 1000 if CONFIG["exchange"] == "primexbt" else (500 if CONFIG["exchange"] == "weex" else 125)
    CONFIG["leverage"] = max(1, min(max_lev, int(CONFIG["leverage"])))
    CONFIG["amount"] = max(1, float(CONFIG["amount"]))
    CONFIG["amount_pct"] = max(1, min(100, float(CONFIG["amount_pct"])))
    CONFIG["stop_loss_pct"] = max(0.05, min(50, float(CONFIG.get("stop_loss_pct", 0.2))))
    # Take Profit is strictly fixed at 1.0% (never let stale cached JS or old DB overwrite to 0.2% 1:1)
    CONFIG["take_profit_pct"] = 1.0
    CONFIG["trailing_roe_pct"] = 100.0
    CONFIG["tp_mode"] = "fixed"
    CONFIG["testnet"] = bool(CONFIG["testnet"])
    CONFIG["telegram_enabled"] = bool(CONFIG.get("telegram_enabled"))
    CONFIG["email_enabled"] = bool(CONFIG.get("email_enabled"))
    CONFIG["whatsapp_enabled"] = bool(CONFIG.get("whatsapp_enabled"))
    CONFIG["email_smtp_port"] = int(CONFIG.get("email_smtp_port", 587))

    if isinstance(CONFIG.get("symbols_list"), str):
        CONFIG["symbols_list"] = [s.strip().upper() for s in CONFIG["symbols_list"].split(",") if s.strip()]
    elif isinstance(CONFIG.get("symbols_list"), list):
        CONFIG["symbols_list"] = [str(s).strip().upper() for s in CONFIG["symbols_list"] if str(s).strip()]
    if CONFIG["symbols_list"]:
        CONFIG["symbol"] = CONFIG["symbols_list"][0]

    try:
        CONFIG["max_concurrent_trades"] = max(1, min(3, int(CONFIG.get("max_concurrent_trades", 3))))
    except (ValueError, TypeError):
        CONFIG["max_concurrent_trades"] = 3
    # Same-coin re-entry cooldown (seconds) — blocks instant re-open after a close
    try:
        CONFIG["reentry_cooldown_sec"] = max(0, min(7200, int(float(CONFIG.get("reentry_cooldown_sec", 180)))))
    except (ValueError, TypeError):
        CONFIG["reentry_cooldown_sec"] = 180
    if 'ENGINE' in globals() and hasattr(ENGINE, 'config'):
        ENGINE.config["max_concurrent_trades"] = CONFIG["max_concurrent_trades"]
        ENGINE.config["reentry_cooldown_sec"] = CONFIG["reentry_cooldown_sec"]

    # Strategy tuning keys: 0 = auto per-symbol default (majors 0.15%, memes 0.20%)
    try:
        CONFIG["min_ema_spread"] = max(0.0, min(5.0, float(CONFIG.get("min_ema_spread", 0) or 0)))
    except (ValueError, TypeError):
        CONFIG["min_ema_spread"] = 0
    try:
        CONFIG["fresh_window"] = max(2, min(8, int(CONFIG.get("fresh_window", 2) or 2)))
    except (ValueError, TypeError):
        CONFIG["fresh_window"] = 2
    if 'ENGINE' in globals() and hasattr(ENGINE, 'config'):
        ENGINE.config["min_ema_spread"] = CONFIG["min_ema_spread"]
        ENGINE.config["fresh_window"] = CONFIG["fresh_window"]
        ENGINE.config["stop_loss_pct"] = CONFIG["stop_loss_pct"]
        ENGINE.config["take_profit_pct"] = 1.0
        ENGINE.config["tp_mode"] = "fixed"

    save_config(CONFIG)

    # ---- SAVE-TIME CREDENTIAL VALIDATION -------------------------------------
    # One READ-ONLY signed call right after Save. -2014/-2015-style problems
    # now surface HERE with an exact message instead of after the bot starts
    # (this is the fix for "workers start and immediately terminate": they
    # never spawn for bad credentials anymore).
    auth_check = None
    if CONFIG.get("api_key") and CONFIG.get("api_secret"):
        try:
            probe = get_trader(CONFIG)
            auth_check = probe.validate_credentials(timeout=10)
            ENGINE.auth_check = auth_check
            ENGINE.connection["auth_check"] = auth_check
            ENGINE.connection["env"] = getattr(probe, "env_label", lambda: "UNKNOWN")()
            if hasattr(ENGINE, "validate_credentials"):
                # Record states without a second network call
                ENGINE.connection["api_auth"] = "ok" if auth_check.get("ok") else "failed"
                ENGINE.connection["balance_access"] = "ok" if auth_check.get("ok") else "unknown"
                if auth_check.get("ok") and auth_check.get("balance") is not None:
                    ENGINE.connection["balance_access"] = "ok"
                if auth_check.get("can_trade") is True:
                    ENGINE.connection["trading_permission"] = "ok"
                elif auth_check.get("can_trade") is False:
                    ENGINE.connection["trading_permission"] = "failed"
            socketio.emit("connection", dict(ENGINE.connection))
            if auth_check.get("ok"):
                socketio.emit("log", {"level": "success", "msg": f"✅ Credentials verified: {auth_check.get('message', '')}"})
            else:
                socketio.emit("log", {"level": "error", "msg": f"❌ Credential check FAILED: {auth_check.get('message', '')}"})
        except Exception as _ve:
            logger.warning("Save-time credential validation failed: %s", _ve)

    # Immediately apply leverage & live-sync settings to running workers
    if CONFIG.get("api_key") and CONFIG.get("api_secret"):
        try:
            ENGINE.apply_leverage(CONFIG["leverage"])
        except Exception as _e:
            logger.warning("Could not auto-apply leverage on config save: %s", _e)
    try:
        if ENGINE.is_running:
            ENGINE.sync_config(CONFIG)
        elif CONFIG.get("api_key") and CONFIG.get("api_secret"):
            ENGINE.start_monitor(CONFIG)
    except Exception as _e:
        logger.warning("Could not sync engine config on save: %s", _e)

    _SECRET_FIELDS = ("api_secret", "email_password", "telegram_bot_token", "whatsapp_apikey",
                      "api_key", "api_passphrase", "api_keys")
    safe_cfg = {k: v for k, v in CONFIG.items() if k not in _SECRET_FIELDS}
    safe_cfg["has_api_key"] = bool(CONFIG.get("api_key"))
    safe_cfg["has_api_secret"] = bool(CONFIG.get("api_secret"))
    safe_cfg["has_api_passphrase"] = bool(CONFIG.get("api_passphrase"))
    safe_cfg["saved_exchanges"] = saved_exchanges_summary(CONFIG)
    resp = {"success": True, "config": safe_cfg}
    if auth_check is not None:
        resp["auth_check"] = auth_check
    return jsonify(resp)


@app.route("/api/leverage", methods=["POST"])
def set_leverage():
    data = request.get_json(silent=True) or {}
    lev = data.get("leverage")
    symbol = data.get("symbol")
    if not lev:
        return jsonify({"success": False, "error": "Leverage is required"}), 400
    try:
        lev = int(lev)
    except (ValueError, TypeError):
        return jsonify({"success": False, "error": "Invalid leverage"}), 400

    ex = (CONFIG.get("exchange") or "binance").lower()
    max_lev = 1000 if ex == "primexbt" else (500 if ex == "weex" else 125)
    lev = max(1, min(max_lev, lev))
    CONFIG["leverage"] = lev
    save_config(CONFIG)

    res = ENGINE.apply_leverage(lev, symbol=symbol)
    return jsonify(res)


@app.route("/api/test_notification", methods=["POST"])
def test_notification():
    try:
        ENGINE.notifier.update_config(CONFIG)
        results = ENGINE.notifier.send("Test Notification",
            "This is a test notification from your trading bot. If you received this, your notification settings are correct!")
        summary_parts = []
        any_enabled = False
        any_success = False
        for channel in ("telegram", "email", "whatsapp"):
            if CONFIG.get(f"{channel}_enabled"):
                any_enabled = True
                r = results.get(channel)
                if r is None:
                    summary_parts.append(f"{channel}: still sending...")
                elif r.get("success"):
                    summary_parts.append(f"{channel}: OK sent")
                    any_success = True
                else:
                    summary_parts.append(f"{channel}: FAILED {r.get('error', 'unknown')}")
        if not any_enabled:
            return jsonify({"success": False, "error": "No notification channel is enabled."})
        return jsonify({"success": any_success, "message": " | ".join(summary_parts), "results": results})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/start", methods=["POST"])
def start_bot():
    try:
        if not CONFIG.get("api_key") or not CONFIG.get("api_secret"):
            return jsonify({"success": False, "error": "Please set your API key and secret first"})
        if CONFIG.get("exchange") == "weex" and not CONFIG.get("api_passphrase"):
            return jsonify({"success": False, "error": "WEEX requires a passphrase"})
        if not CONFIG.get("symbols_list"):
            return jsonify({"success": False, "error": "Please add at least one coin"})
        try:
            ENGINE.start_monitor(CONFIG)
        except Exception as e:
            logger.warning("Monitor start failed (non-critical): %s", e)
        result = ENGINE.start(CONFIG)
        return jsonify(result)
    except Exception as e:
        logger.exception("START BOT CRASHED:")
        return jsonify({"success": False, "error": f"Bot start error: {str(e)}"})


@app.route("/api/stop", methods=["POST"])
def stop_bot():
    result = ENGINE.stop()
    try:
        ENGINE.stop_monitor()
    except Exception as e:
        logger.warning("Monitor stop failed: %s", e)
    ENGINE.is_running = False
    socketio.emit("status", ENGINE.status())
    socketio.emit("log", {"level": "info", "msg": "Bot STOPPED completely (trading + monitor)"})
    return jsonify({"success": True, "message": "Bot stopped"})


@app.route("/api/force_stop", methods=["POST"])
def force_stop_bot():
    result = ENGINE.force_stop()
    try:
        ENGINE.stop_monitor()
    except Exception as e:
        logger.warning("Monitor stop failed: %s", e)
    ENGINE.is_running = False
    socketio.emit("status", ENGINE.status())
    return jsonify(result)


@app.route("/api/active_symbol", methods=["POST"])
def set_active_symbol():
    data = request.get_json(silent=True) or {}
    symbol = data.get("symbol", "").strip().upper()
    if not symbol:
        return jsonify({"success": False, "error": "Symbol required"})
    ENGINE.set_active_symbol(symbol)
    return jsonify({"success": True, "active_symbol": symbol})


@app.route("/api/status", methods=["GET"])
def status():
    return jsonify(ENGINE.status())


@app.route("/api/positions", methods=["GET"])
@app.route("/api/position", methods=["GET"])
def get_positions():
    trader = ENGINE.trader or getattr(ENGINE, "monitor_trader", None)
    if not trader:
        return jsonify({"success": False, "error": "Bot trader not connected", "positions": []})
    req_sym = request.args.get("symbol", "").strip().upper()
    symbols = [req_sym] if req_sym else (ENGINE._symbols_list() or [CONFIG.get("symbol", "BTCUSDT")])
    if not symbols:
        symbols = ["BTCUSDT"]

    positions = []
    for sym in symbols:
        try:
            pos = trader.get_position(sym)
            worker = ENGINE.workers.get(sym)
            tp_stage = worker.tp_stage if (worker and pos.side != "NONE") else 0
            tp_price = worker.tp_price if (worker and pos.side != "NONE" and worker.tp_price) else 0.0
            sl_price = worker.sl_price if (worker and pos.side != "NONE" and worker.sl_price) else 0.0
            # Fallback calculation if position is open but software TP/SL was not yet cached
            if pos.side != "NONE" and pos.entry_price and float(pos.entry_price) > 0:
                ep = float(pos.entry_price)
                if not tp_price:
                    tp_pct = float(CONFIG.get("take_profit_pct", 1.0) or 1.0)
                    tp_price = round(ep * (1.0 + tp_pct / 100.0) if pos.side == "LONG" else ep * (1.0 - tp_pct / 100.0), 6)
                if not sl_price:
                    sl_pct = float(CONFIG.get("stop_loss_pct", 0.2) or 0.2)
                    sl_price = round(ep * (1.0 - sl_pct / 100.0) if pos.side == "LONG" else ep * (1.0 + sl_pct / 100.0), 6)
            tp_mode = worker.tp_mode if worker else (CONFIG.get("tp_mode") or "trailing")
            target_roe = getattr(worker, "target_roe_pct", 80.0) if worker else float(CONFIG.get("trailing_roe_pct", 80.0))
            positions.append({
                "symbol": sym,
                "side": pos.side,
                "size": pos.size,
                "entry_price": pos.entry_price,
                "mark_price": pos.mark_price,
                "unrealized_pnl": pos.unrealized_pnl,
                "leverage": pos.leverage,
                "tp_stage": tp_stage,
                "tp_price": tp_price,
                "sl_price": sl_price,
                "target_roe": target_roe,
                "tp_mode": tp_mode,
            })
        except Exception as e:
            logger.warning("Failed to fetch position for %s: %s", sym, e)

    return jsonify({
        "success": True,
        "positions": positions,
        "position": positions[0] if positions else None
    })


@app.route("/api/close", methods=["POST"])
def close_position():
    data = request.get_json(silent=True) or {}
    symbol = data.get("symbol") or CONFIG.get("symbol", "BTCUSDT")

    # Fallback to monitor_trader or instantiate trader from CONFIG so manual close works even if bot is STOPPED
    trader = ENGINE.trader or getattr(ENGINE, "monitor_trader", None)
    if not trader:
        try:
            from bot.engine import get_trader
            trader = get_trader(CONFIG)
            ENGINE.monitor_trader = trader
        except Exception as te:
            logger.error("Could not instantiate trader for close: %s", te)

    if not trader:
        return jsonify({"success": False, "error": "Bot not connected to exchange. Please check API keys."})

    # 1. Fetch current open position before closing to get accurate entry, size & mark price
    pos = None
    try:
        pos = trader.get_position(symbol)
    except Exception as pe:
        logger.warning("Could not fetch position before close: %s", pe)

    # 2. Close position via trader
    result = trader.close_position(symbol)

    # 3. If closed successfully, record in Trade History & reset worker state
    if result.get("success"):
        if pos and pos.side != "NONE" and pos.size != 0:
            try:
                entry = pos.entry_price or 0.0
                mark = pos.mark_price or entry
                size = abs(pos.size)
                pos_side = pos.side
                worker = ENGINE.workers.get(symbol)
                cfg_lev = int(CONFIG.get("leverage", 50))
                lev = pos.leverage if (pos.leverage and int(pos.leverage) > 1) else (worker._get_effective_leverage(symbol) if worker else cfg_lev)
                margin = (entry * size) / lev if (lev > 0 and entry > 0 and size > 0) else 0.0
                pnl = (mark - entry) * size if pos_side == "LONG" else (entry - mark) * size
                roe_pct = (pnl / margin * 100.0) if margin > 0 else 0.0
                fees = (entry + mark) * size * 0.0006

                if hasattr(ENGINE, "history"):
                    ENGINE.history.record_close(
                        symbol=symbol,
                        exit_price=mark,
                        reason="👤 Manual Close (Bot Dashboard)",
                        pnl=pnl,
                        roe_pct=roe_pct,
                        fee_est=fees,
                        leverage=lev,
                        qty=size,
                    )
                    socketio.emit("trades_updated", {
                        "trades": ENGINE.history.get_trades(limit=50),
                        "stats": ENGINE.history.get_stats(),
                    })
            except Exception as he:
                logger.error("Failed to record manual close in history: %s", he)

        # Sync worker state completely so worker slot is immediately freed
        worker = ENGINE.workers.get(symbol)
        if worker:
            worker._last_close_timestamp = time.time()
            worker.expected_pos_side = None
            worker.position_side = None
            worker.entry_price = None
            worker.entry_signal = None
            worker.ema_reversal_tp_fired = False
            worker.reversal_pending_side = None
            worker.waiting_for_new_cross = True
            worker.strategy.reset_cross_state()
            worker.sl_price = None
            worker.tp_price = None
            worker.tp_stage = 0
            worker.be_sl_set = False
            worker.partial_tp_done = False

        # Same-coin re-entry cooldown: manual close ke foran baad bot is coin
        # pe dobara trade NAHI kholta (user complaint: "close karo to usi time
        # ne khol deta hai same coin pe").
        try:
            ENGINE.set_reentry_cooldown(symbol, reason="manual close")
        except Exception as ce:
            logger.warning("Manual close cooldown set failed: %s", ce)

        # Emit position cleared event immediately to update UI
        socketio.emit("position", {
            "symbol": symbol,
            "side": "NONE",
            "size": 0.0,
            "entry_price": 0.0,
            "mark_price": pos.mark_price if pos else 0.0,
            "unrealized_pnl": 0.0,
            "leverage": 1,
            "tp_stage": 0,
            "tp_price": 0.0,
            "sl_price": 0.0,
            "target_roe": 100.0,
            "tp_mode": "fixed",
        })

    socketio.emit("log", {"level": "info", "msg": f"Manual close requested for {symbol}: {result}"})
    return jsonify(result)


@app.route("/api/close_all", methods=["POST"])
def close_all_positions():
    """Emergency manual close for ALL active positions."""
    trader = ENGINE.trader or getattr(ENGINE, "monitor_trader", None)
    if not trader:
        try:
            from bot.engine import get_trader
            trader = get_trader(CONFIG)
            ENGINE.monitor_trader = trader
        except Exception as te:
            logger.error("Could not instantiate trader for close_all: %s", te)

    if not trader:
        return jsonify({"success": False, "error": "Bot not connected to exchange."})

    symbols_to_check = set()
    # 1. From engine workers
    for sym, w in getattr(ENGINE, "workers", {}).items():
        if getattr(w, "position_side", None) in ("LONG", "SHORT") or getattr(w, "expected_pos_side", None) in ("LONG", "SHORT") or getattr(w, "entry_price", 0) > 0:
            symbols_to_check.add(sym)
    # 2. From config coins
    for c in CONFIG.get("coins", []):
        symbols_to_check.add(c)
    # 3. From active / default symbol
    if CONFIG.get("symbol"):
        symbols_to_check.add(CONFIG.get("symbol"))

    results = {}
    for sym in symbols_to_check:
        try:
            pos = trader.get_position(sym)
            if pos.side != "NONE" and abs(pos.size) > 0:
                res = trader.close_position(sym)
                results[sym] = res
                if res.get("success"):
                    # Record history
                    try:
                        entry = pos.entry_price or 0.0
                        mark = pos.mark_price or entry
                        size = abs(pos.size)
                        worker = ENGINE.workers.get(sym)
                        cfg_lev = int(CONFIG.get("leverage", 50))
                        lev = pos.leverage if (pos.leverage and int(pos.leverage) > 1) else (worker._get_effective_leverage(sym) if worker else cfg_lev)
                        margin = (entry * size) / lev if (lev > 0 and entry > 0 and size > 0) else 0.0
                        pnl = (mark - entry) * size if pos.side == "LONG" else (entry - mark) * size
                        roe_pct = (pnl / margin * 100.0) if margin > 0 else 0.0
                        fees = (entry + mark) * size * 0.0006
                        if hasattr(ENGINE, "history"):
                            ENGINE.history.record_close(
                                symbol=sym,
                                exit_price=mark,
                                reason="⚡ Manual Close All Positions",
                                pnl=pnl,
                                roe_pct=roe_pct,
                                fee_est=fees,
                                leverage=lev,
                                qty=size,
                            )
                    except Exception as he:
                        logger.error("Failed to record close_all history for %s: %s", sym, he)

                    # Reset worker
                    worker = ENGINE.workers.get(sym)
                    if worker:
                        worker._last_close_timestamp = time.time()
                        worker.expected_pos_side = None
                        worker.position_side = None
                        worker.entry_price = None
                        worker.entry_signal = None
                        worker.ema_reversal_tp_fired = False
                        worker.reversal_pending_side = None
                        worker.waiting_for_new_cross = True
                        worker.strategy.reset_cross_state()
                        worker.sl_price = None
                        worker.tp_price = None
                        worker.tp_stage = 0
                        worker.be_sl_set = False
                        worker.partial_tp_done = False

                    # Same-coin re-entry cooldown after Close All too.
                    try:
                        ENGINE.set_reentry_cooldown(sym, reason="close all")
                    except Exception as ce:
                        logger.warning("Close-all cooldown set failed for %s: %s", sym, ce)

                    socketio.emit("position", {
                        "symbol": sym,
                        "side": "NONE",
                        "size": 0.0,
                        "entry_price": 0.0,
                        "mark_price": pos.mark_price if pos else 0.0,
                        "unrealized_pnl": 0.0,
                        "leverage": 1,
                        "tp_stage": 0,
                        "tp_price": 0.0,
                        "sl_price": 0.0,
                        "target_roe": 100.0,
                        "tp_mode": "fixed",
                    })
        except Exception as e:
            results[sym] = {"success": False, "error": str(e)}

    if hasattr(ENGINE, "history"):
        socketio.emit("trades_updated", {
            "trades": ENGINE.history.get_trades(limit=50),
            "stats": ENGINE.history.get_stats(),
        })

    socketio.emit("log", {"level": "warn", "msg": f"⚡ Emergency Close All results: {results}"})
    return jsonify({"success": True, "results": results})


@app.route("/api/trades", methods=["GET"])
def get_trades():
    if not hasattr(ENGINE, "history"):
        return jsonify({"success": True, "trades": [], "stats": {}})
    limit_raw = request.args.get("limit", "100")
    try:
        limit = max(1, min(500, int(limit_raw)))
    except (TypeError, ValueError):
        limit = 100
    symbol = request.args.get("symbol")
    trades = ENGINE.history.get_trades(limit=limit, symbol=symbol)
    stats = ENGINE.history.get_stats()
    return jsonify({"success": True, "trades": trades, "stats": stats})


@app.route("/api/trades/clear", methods=["POST"])
def clear_trades():
    if not hasattr(ENGINE, "history"):
        return jsonify({"success": True})
    ENGINE.history.clear_history()
    socketio.emit("trades_updated", {"trades": [], "stats": ENGINE.history.get_stats()})
    return jsonify({"success": True})


@app.route("/api/price", methods=["GET"])
def get_price():
    symbol = request.args.get("symbol", CONFIG.get("symbol", "BTCUSDT"))
    if not ENGINE.trader:
        return jsonify({"success": False, "error": "Bot not connected"})
    try:
        price = ENGINE.trader.get_mark_price(symbol)
        return jsonify({"success": True, "symbol": symbol, "price": price})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/symbols", methods=["GET"])
def get_all_symbols():
    exchange = (CONFIG.get("exchange") or "binance").lower()
    testnet = CONFIG.get("testnet", True)
    import requests as _req

    if exchange == "primexbt":
        try:
            from bot.primexbt_trader import PrimeXBTTrader
            pxbt = PrimeXBTTrader(CONFIG)
            symbols = pxbt.get_all_symbols()
            if symbols:
                return jsonify({"success": True, "symbols": symbols, "count": len(symbols),
                                "exchange": "primexbt", "mode": "cfd_futures"})
        except Exception as e:
            logger.error("Failed to fetch PrimeXBT symbols: %s", e)
        fallback = [
            "XAU/USD", "GOLD 24/7", "XAG/USD",
            "BTC/USD", "ETH/USD", "SOL/USD", "XRP/USD", "DOGE/USD", "ADA/USD",
            "EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD",
            "USTEC", "US30", "GER30", "SP500", "BRENT", "CRUDE"
        ]
        return jsonify({"success": True, "symbols": fallback, "count": len(fallback),
                        "exchange": "primexbt", "mode": "cfd_futures"})

    if exchange == "weex":
        try:
            resp = _req.get(
                "https://api-contract.weex.com/capi/v3/market/apiTradingSymbols",
                timeout=10,
            )
            data = resp.json()
            all_symbols = []
            if isinstance(data, list):
                for sym in data:
                    if isinstance(sym, str) and sym.upper().endswith("USDT"):
                        all_symbols.append(sym.upper())
            all_symbols = sorted(set(all_symbols))

            if testnet:
                symbols = [s for s in all_symbols if s.endswith("SUSDT")]
                mode_label = "demo"
            else:
                symbols = [s for s in all_symbols
                           if s.endswith("USDT") and not s.endswith("SUSDT")]
                mode_label = "live"

            if symbols:
                return jsonify({"success": True, "symbols": symbols, "count": len(symbols),
                                "exchange": "weex", "mode": mode_label})
        except Exception as e:
            logger.error("Failed to fetch WEEX symbols: %s", e)
        if testnet:
            fallback = ["BTCSUSDT", "ETHSUSDT", "BNBSUSDT", "SOLSUSDT", "XRPSUSDT"]
        else:
            fallback = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"]
        return jsonify({"success": True, "symbols": fallback, "count": len(fallback),
                        "exchange": "weex", "mode": "demo" if testnet else "live"})

    try:
        resp = _req.get("https://fapi.binance.com/fapi/v1/exchangeInfo", timeout=10)
        data = resp.json()
        symbols = []
        for s in data.get("symbols", []):
            if s.get("quoteAsset") == "USDT" and s.get("contractType") == "PERPETUAL":
                if s.get("status") == "TRADING":
                    symbols.append(s.get("symbol"))
        symbols.sort()
        if symbols:
            return jsonify({"success": True, "symbols": symbols, "count": len(symbols),
                            "exchange": "binance"})
    except Exception as e:
        logger.error("Failed to fetch Binance symbols: %s", e)
    return jsonify({"success": True, "symbols": [
        "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
        "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "MATICUSDT",
    ], "count": 10, "exchange": "binance"})


@app.route("/api/test_chart", methods=["GET"])
def test_chart():
    symbol = request.args.get("symbol", CONFIG.get("symbol", "BTCUSDT"))
    trader = ENGINE.trader or ENGINE.monitor_trader
    if not trader:
        try:
            from bot.engine import get_trader
            trader = get_trader(CONFIG)
            ENGINE.monitor_trader = trader
        except Exception as e:
            return jsonify({"success": False, "error": f"Trader unavailable: {e}"})
    try:
        df = trader.get_klines(symbol, interval=CONFIG.get("timeframe", "5m"), limit=200)
        if df is None or len(df) == 0:
            return jsonify({"success": False, "error": "No klines data", "rows": 0})
        candles = []
        for ts, row in df.iterrows():
            candles.append({"time": int(ts.timestamp()), "open": float(row["open"]),
                "high": float(row["high"]), "low": float(row["low"]), "close": float(row["close"])})

        emas = {}
        try:
            from bot.strategy import EMACrossoverStrategy
            strat = EMACrossoverStrategy(ema_fast=8, ema_mid1=13, ema_mid2=21, ema_long=55)
            enriched = strat.indicators.compute(df)
            tail = enriched.tail(200)
            for col, key in [("ema_8", "ema8"), ("ema_13", "ema13"),
                             ("ema_21", "ema21"), ("ema_55", "ema55")]:
                emas[key] = [
                    {"time": int(ts.timestamp()), "value": float(v)}
                    for ts, v in zip(tail.index, tail[col])
                    if not (v != v)
                ]
        except Exception as ema_err:
            logger.warning(f"Failed to compute EMAs for test_chart: {ema_err}")

        return jsonify({"success": True, "symbol": symbol, "rows": len(df), "candles": candles, "emas": emas})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/preview", methods=["POST"])
def start_preview():
    try:
        if not CONFIG.get("api_key") or not CONFIG.get("api_secret"):
            return jsonify({"success": False, "error": "API keys not set"})
        result = ENGINE.start_monitor(CONFIG)
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/test_connection", methods=["POST"])
def test_connection():
    """Uniform per-exchange credential check (read-only, no orders).

    Returns the adapter's validate_credentials() result with both `ok` and
    `success` booleans populated: {ok, success, error_code, error, message,
    balance, can_trade, env, exchange, demo}. Accepts optional override fields
    in POST JSON ({exchange, testnet, api_key, api_secret, api_passphrase}) so
    both Web and Mobile can test unsaved or newly-saved credentials directly.
    """
    try:
        override = request.get_json(silent=True) or {}
        probe_cfg = dict(CONFIG)
        if isinstance(override, dict):
            if override.get("exchange"):
                probe_cfg["exchange"] = resolve_exchange(override.get("exchange"))
            if "testnet" in override and override["testnet"] is not None:
                probe_cfg["testnet"] = bool(override["testnet"])
            for cred_k in ("api_key", "api_secret", "api_passphrase"):
                if cred_k in override and clean_cred(override.get(cred_k)):
                    probe_cfg[cred_k] = clean_cred(override.get(cred_k))

        ex = resolve_exchange(probe_cfg.get("exchange"))
        demo_flag = bool(probe_cfg.get("testnet", True))
        if not clean_cred(probe_cfg.get("api_key")) or not clean_cred(probe_cfg.get("api_secret")):
            msg = f"{ex.upper()} API Key aur Secret dono enter karke Save karein."
            return jsonify({
                "ok": False, "success": False, "error_code": 400,
                "error": msg, "message": msg, "balance": None,
                "exchange": ex, "demo": demo_flag,
            })
        if ex == "weex" and not clean_cred(probe_cfg.get("api_passphrase")):
            msg = ("WEEX credentials incomplete: API Key, Secret aur Passphrase teeno chahiye "
                   "(Passphrase wahi jo API key banate waqt set ki thi).")
            return jsonify({
                "ok": False, "success": False, "error_code": 400,
                "error": msg, "message": msg, "balance": None,
                "exchange": "weex", "demo": demo_flag,
            })

        trader = get_trader(probe_cfg)
        if hasattr(trader, "validate_credentials"):
            result = trader.validate_credentials()
            result["success"] = bool(result.get("ok"))
            if ex == resolve_exchange(CONFIG.get("exchange")):
                ENGINE.auth_check = result
                ENGINE.connection["auth_check"] = result
                ENGINE.connection["env"] = getattr(trader, "env_label", lambda: "UNKNOWN")()
                ENGINE.connection["api_auth"] = "ok" if result.get("ok") else "failed"
                socketio.emit("connection", dict(ENGINE.connection))
            return jsonify(result)
        result = trader.test_connection()
        result["ok"] = bool(result.get("success"))
        return jsonify(result)
    except Exception as e:
        err_str = str(e)
        return jsonify({"ok": False, "success": False, "error": err_str, "message": err_str})


def _honest_demo_flag(trader) -> bool:
    """Honest DEMO/LIVE flag for balance responses.

    Strictly reflects the configured environment (DEMO vs LIVE).
    Never label a live account as demo or a demo account as live.
    """
    if trader and hasattr(trader, "testnet"):
        return bool(trader.testnet)
    return bool(CONFIG.get("testnet", True))


@app.route("/api/balance", methods=["GET"])
def get_balance():
    trader = ENGINE.trader or ENGINE.monitor_trader
    if not trader:
        try:
            from bot.engine import get_trader
            trader = get_trader(CONFIG)
            ENGINE.monitor_trader = trader
        except Exception as e:
            return jsonify({"success": False, "error": f"Connection error: {e}"})
    try:
        bal = trader.get_balance()
        return jsonify({"success": True, "balance": bal,
                        "exchange": CONFIG.get("exchange", "binance"),
                        "demo": _honest_demo_flag(trader),
                        "testnet": CONFIG.get("testnet", True)})
    except Exception as e:
        logger.error("get_balance error: %s", e)
        return jsonify({"success": False, "error": str(e)})


# ---------- SocketIO ----------

@socketio.on("connect")
def on_connect():
    socketio.emit("log", {"level": "info", "msg": "UI connected to bot"})
    socketio.emit("status", ENGINE.status())

@socketio.on("disconnect")
def on_disconnect():
    logger.info("UI disconnected")


# ---------- Entry point ----------

def _crash_handler(exc_type, exc_value, exc_tb):
    import traceback
    error_msg = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    logger.error("FATAL ERROR:\n%s", error_msg)
    try:
        with open("crash.log", "w", encoding="utf-8") as f:
            f.write(f"Crash Report\nTime: {datetime.now(timezone.utc).isoformat()}\n\n{error_msg}")
    except OSError:
        pass
    sys.exit(1)


if __name__ == "__main__":
    sys.excepthook = _crash_handler
    port = int(os.environ.get("PORT", 5000))
    host = os.environ.get("HOST", "0.0.0.0")
    logger.info("="*60)
    logger.info(" Bot Engine - Starting (port %d)", port)
    logger.info("="*60)
    # NOTE: For production, use gunicorn with eventlet worker instead of this dev server
    socketio.run(app, host=host, port=port, debug=False, use_reloader=False, allow_unsafe_werkzeug=True)
