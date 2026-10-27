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
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, render_template, request, Response, session
from flask_socketio import SocketIO

from bot.engine import BotEngine

# ---------- Setup ----------

BASE_DIR = Path(__file__).resolve().parent
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
    "exchange": "binance",
    "testnet": True,
    "symbol": "BTCUSDT",
    "symbols_list": ["BTCUSDT"],
    "timeframe": "5m",
    "leverage": 125,
    "amount_mode": "fixed",
    "amount": 100,
    "amount_pct": 10,
    "stop_loss_pct": 2,
    "take_profit_pct": 2,
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
}


def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            merged = {**DEFAULT_CONFIG, **cfg}
            # Enforce strict 1:1 TP & SL with auto-reversal
            merged["tp_mode"] = "fixed"
            merged["take_profit_pct"] = merged.get("stop_loss_pct", 2)
            merged["trailing_roe_pct"] = 100.0
            return merged
        except (json.JSONDecodeError, OSError) as e:
            logger.error("Failed to load config: %s", e)
    return DEFAULT_CONFIG.copy()


def save_config(cfg: dict):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


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
    safe = {**CONFIG}
    if safe.get("api_key"):
        safe["api_key_masked"] = safe["api_key"][:4] + "***" + safe["api_key"][-4:]
    if safe.get("api_secret"):
        safe["api_secret_masked"] = "***"
    safe["api_key"] = safe.get("api_key", "")
    safe["api_secret"] = safe.get("api_secret", "")
    return jsonify(safe)


@app.route("/api/config", methods=["POST"])
def update_config():
    global CONFIG
    data = request.get_json(force=True)

    for k in ["exchange", "api_passphrase", "symbol", "symbols_list", "timeframe",
              "leverage", "amount", "amount_mode", "amount_pct",
              "stop_loss_pct", "take_profit_pct", "trailing_roe_pct", "tp_mode", "mode", "testnet", "auto_start",
              "telegram_enabled", "telegram_bot_token", "telegram_chat_id",
              "email_enabled", "email_smtp_server", "email_smtp_port",
              "email_sender", "email_password", "email_receiver",
              "whatsapp_enabled", "whatsapp_phone", "whatsapp_apikey", "max_concurrent_trades"]:
        if k in data:
            CONFIG[k] = data[k]

    if data.get("api_key"):
        CONFIG["api_key"] = data["api_key"]
    if data.get("api_secret"):
        CONFIG["api_secret"] = data["api_secret"]

    CONFIG["exchange"] = (CONFIG.get("exchange") or "binance").lower()
    if CONFIG["exchange"] not in ("binance", "weex", "primexbt"):
        CONFIG["exchange"] = "binance"
    max_lev = 1000 if CONFIG["exchange"] == "primexbt" else (500 if CONFIG["exchange"] == "weex" else 125)
    CONFIG["leverage"] = max(1, min(max_lev, int(CONFIG["leverage"])))
    CONFIG["amount"] = max(1, float(CONFIG["amount"]))
    CONFIG["amount_pct"] = max(1, min(100, float(CONFIG["amount_pct"])))
    CONFIG["stop_loss_pct"] = max(0.5, min(50, float(CONFIG.get("stop_loss_pct", 2))))
    CONFIG["trailing_roe_pct"] = max(20.0, min(500.0, float(CONFIG.get("trailing_roe_pct", 100.0))))
    tp_m = (CONFIG.get("tp_mode") or "fixed").lower()
    if tp_m in ("both", "fixed"):
        CONFIG["tp_mode"] = "fixed"
    elif tp_m in ("trailing", "ema_reversal"):
        CONFIG["tp_mode"] = tp_m
    else:
        CONFIG["tp_mode"] = "fixed"

    if CONFIG["tp_mode"] == "fixed":
        CONFIG["take_profit_pct"] = CONFIG["stop_loss_pct"]
    else:
        CONFIG["take_profit_pct"] = CONFIG["stop_loss_pct"] * 3
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
    if 'ENGINE' in globals() and hasattr(ENGINE, 'config'):
        ENGINE.config["max_concurrent_trades"] = CONFIG["max_concurrent_trades"]

    save_config(CONFIG)

    # Immediately apply leverage on exchange if credentials are present
    if CONFIG.get("api_key") and CONFIG.get("api_secret"):
        try:
            ENGINE.apply_leverage(CONFIG["leverage"])
        except Exception as _e:
            logger.warning("Could not auto-apply leverage on config save: %s", _e)
        try:
            if not ENGINE.is_running:
                ENGINE.start_monitor(CONFIG)
            else:
                ENGINE.sync_config(CONFIG)
        except Exception as _e:
            logger.warning("Could not sync engine config on save: %s", _e)

    safe_keys = ("api_secret", "email_password", "telegram_bot_token", "whatsapp_apikey")
    return jsonify({"success": True, "config": {k: v for k, v in CONFIG.items() if k not in safe_keys}})


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
        # FIX: idempotent start — if the bot is genuinely running (alive workers),
        # return SUCCESS instead of an error. This kills the confusing
        # "already running" dead-end the UI showed after page refreshes.
        if ENGINE.is_running:
            alive = [w for w in ENGINE.workers.values() if w.is_alive()]
            if alive or not ENGINE.workers:
                _persist_runtime_state(trading=True)
                return jsonify({"success": True, "message": "Bot already running",
                                "status": ENGINE.status(), "already_running": True})
        try:
            ENGINE.start_monitor(CONFIG)
        except Exception as e:
            logger.warning("Monitor start failed (non-critical): %s", e)
        result = ENGINE.start(CONFIG)
        if result.get("success"):
            _persist_runtime_state(trading=True)
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
    _persist_runtime_state(trading=False)
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
    _persist_runtime_state(trading=False)
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


# ---------- Runtime state persistence (auto-resume after restart) ----------

RUNTIME_STATE_FILE = BASE_DIR / "runtime_state.json"


def _persist_runtime_state(trading: bool):
    """Persist whether the trading loop should be running, so a restarted
    engine process can RESUME automatically instead of silently dying."""
    try:
        RUNTIME_STATE_FILE.write_text(json.dumps({
            "trading": bool(trading),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }), encoding="utf-8")
    except Exception as e:
        logger.warning("Could not persist runtime state: %s", e)


def _read_runtime_state() -> dict:
    try:
        if RUNTIME_STATE_FILE.exists():
            return json.loads(RUNTIME_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


@app.route("/api/snapshot", methods=["GET"])
def snapshot():
    """One-shot full UI state: status + positions + cached chart + indicators.
    The frontend calls this ONCE on page load so a REFRESH instantly restores
    everything instead of waiting for the next worker tick (or showing an
    empty screen when socket events are delayed)."""
    data = {
        "status": ENGINE.status(),
        "positions": [],
        "chart": {},
        "indicators": {},
        "active_symbol": ENGINE.active_symbol,
    }
    # Positions (from engine trader or monitor trader)
    trader = ENGINE.trader or getattr(ENGINE, "monitor_trader", None)
    if trader:
        symbols = list(ENGINE.workers.keys()) or CONFIG.get("symbols_list") or []
        for sym in symbols:
            try:
                pos = trader.get_position(sym)
                worker = ENGINE.workers.get(sym)
                data["positions"].append({
                    "symbol": sym,
                    "side": pos.side,
                    "size": pos.size,
                    "entry_price": pos.entry_price,
                    "mark_price": pos.mark_price,
                    "unrealized_pnl": pos.unrealized_pnl,
                    "leverage": pos.leverage,
                    "tp_stage": worker.tp_stage if (worker and pos.side != "NONE") else 0,
                    "tp_price": worker.tp_price if (worker and pos.side != "NONE" and worker.tp_price) else 0.0,
                    "sl_price": worker.sl_price if (worker and pos.side != "NONE" and worker.sl_price) else 0.0,
                    "tp_mode": worker.tp_mode if worker else (CONFIG.get("tp_mode") or "fixed"),
                    "target_roe": getattr(worker, "target_roe_pct", 80.0) if worker else 80.0,
                })
            except Exception:
                pass
    # Cached chart + indicators per symbol (instant restore after refresh)
    for sym, w in ENGINE.workers.items():
        try:
            df = getattr(w, "_last_df", None)
            if df is not None and len(df):
                data["chart"][sym] = {
                    "candles": w._candles_to_list(df),
                    "emas": w._emas_to_list(df),
                }
            ind = w.strategy.latest_indicators(df) if df is not None and len(df) else None
            if ind:
                ind["mark_price"] = getattr(w, "_last_mark_price", 0) or (float(df.iloc[-1]["close"]) if len(df) else 0)
                data["indicators"][sym] = ind
        except Exception:
            pass
    return jsonify(data)


@app.route("/api/positions", methods=["GET"])
@app.route("/api/position", methods=["GET"])
def get_positions():
    trader = ENGINE.trader or getattr(ENGINE, "monitor_trader", None)
    if not trader:
        return jsonify({"success": False, "error": "Bot trader not connected", "positions": []})
    req_sym = request.args.get("symbol", "").strip().upper()
    # FIX: ENGINE.symbols never exists as an attribute -> AttributeError 500.
    # Use the live worker registry, then fall back to config.
    symbols = [req_sym] if req_sym else (list(ENGINE.workers.keys()) or CONFIG.get("symbols_list") or [CONFIG.get("symbol", "BTCUSDT")])
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
    limit = int(request.args.get("limit", 100))
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
    if not ENGINE.trader:
        return jsonify({"success": False, "error": "Bot not running"})
    try:
        df = ENGINE.trader.get_klines(symbol, interval=CONFIG.get("timeframe", "5m"), limit=5)
        if df is None or len(df) == 0:
            return jsonify({"success": False, "error": "No klines data", "rows": 0})
        candles = []
        for ts, row in df.iterrows():
            candles.append({"time": int(ts.timestamp()), "open": float(row["open"]),
                "high": float(row["high"]), "low": float(row["low"]), "close": float(row["close"])})
        return jsonify({"success": True, "symbol": symbol, "rows": len(df), "candles": candles})
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
    try:
        from bot.engine import get_trader
        trader = get_trader(CONFIG)
        result = trader.test_connection()
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/balance", methods=["GET"])
def get_balance():
    trader = ENGINE.trader or ENGINE.monitor_trader
    if not trader:
        if CONFIG.get("api_key") and CONFIG.get("api_secret"):
            try:
                from bot.engine import get_trader
                trader = get_trader(CONFIG)
                ENGINE.monitor_trader = trader
            except Exception as e:
                return jsonify({"success": False, "error": f"Connection error: {e}"})
        else:
            return jsonify({"success": False, "error": "Bot not connected"})
    try:
        bal = trader.get_balance()
        return jsonify({"success": True, "balance": bal,
                        "exchange": CONFIG.get("exchange", "binance"),
                        "testnet": CONFIG.get("testnet", True)})
    except Exception as e:
        logger.error("get_balance error: %s", e)
        # Try one fresh reconnection attempt
        if CONFIG.get("api_key") and CONFIG.get("api_secret"):
            try:
                from bot.engine import get_trader
                trader = get_trader(CONFIG)
                ENGINE.monitor_trader = trader
                bal = trader.get_balance()
                return jsonify({"success": True, "balance": bal,
                                "exchange": CONFIG.get("exchange", "binance"),
                                "testnet": CONFIG.get("testnet", True)})
            except Exception as e2:
                return jsonify({"success": False, "error": str(e2)})
        return jsonify({"success": False, "error": str(e)})


# ---------- SocketIO ----------

@socketio.on("connect")
def on_connect():
    socketio.emit("log", {"level": "info", "msg": "UI connected to bot"})
    socketio.emit("status", ENGINE.status())
    # FIX: push a FULL snapshot on every (re)connect so a refreshed page
    # immediately gets chart + indicators + positions without waiting for
    # the next worker tick (or when socket events race the page load).
    try:
        socketio.emit("snapshot", build_snapshot_payload())
    except Exception as e:
        logger.warning("Snapshot emit failed: %s", e)


def build_snapshot_payload():
    """Same payload as /api/snapshot but for socket emission."""
    with app.test_request_context("/api/snapshot"):
        return snapshot().get_json()

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

    # ============================================================
    # AUTO-RESUME: if the bot was trading before this process died
    # (VPS reboot / engine crash / SaaS respawn), restart the trading
    # loop automatically. Without this, every restart silently KILLED
    # trading and left open positions unmanaged (user sees STOPPED +
    # START button + 'already running' confusion afterwards).
    # ============================================================
    _state = _read_runtime_state()
    _should_resume = (
        CONFIG.get("api_key") and CONFIG.get("api_secret")
        and (
            _state.get("trading") is True
            or CONFIG.get("auto_start") is True
        )
    )
    if _should_resume:
        def _auto_resume():
            try:
                logger.info("AUTO-RESUME: trading was ON before restart - restarting trading loop")
                result = ENGINE.start(CONFIG)
                if result.get("success"):
                    _persist_runtime_state(trading=True)
                    socketio.emit("status", ENGINE.status())
                    socketio.emit("log", {"level": "success",
                                          "msg": "♻️ Bot auto-resumed after engine restart (positions continue to be managed)"})
                else:
                    logger.warning("AUTO-RESUME failed: %s", result.get("error"))
            except Exception as e:
                logger.exception("AUTO-RESUME crashed: %s", e)
        threading.Thread(target=_auto_resume, daemon=True).start()

    # NOTE: For production, use gunicorn with eventlet worker instead of this dev server
    socketio.run(app, host=host, port=port, debug=False, use_reloader=False, allow_unsafe_werkzeug=True)
