"""
TradeBot SaaS - Webapp (Wrapper around Bot-Engine)
====================================================

This webapp wraps around the bot-engine. The bot-engine itself
is the original trading bot - this SaaS layer handles:
  - User signup/login
  - License activation (admin-generated keys)
  - Admin panel (license management, user management)
  - Dashboard -> bot-engine proxied via iframe

Architecture:
  Webapp (port 5000)
    - Login page (email + password)
    - License activation (admin provides keys)
    - Admin panel (generate licenses, manage users)
    - Dashboard -> bot-engine proxied in iframe

  Bot-Engine (port 5001+ - one per user)
    - Trading dashboard (unchanged)
    - EMA 8,13,21,55 strategy
    - 1:3 RR hardcoded
    - All trading logic

Flow:
  1. User signup -> login
  2. User enters license key (obtained from admin)
  3. License valid - webapp spawns user's bot-engine (port 5001+)
  4. Dashboard shows bot-engine in iframe
  5. User enters API keys, adds coins, clicks START
  6. Bot runs 24/7 on the server
"""
from __future__ import annotations

import json
import logging
import os
import sys
import hashlib
import secrets
import subprocess
import time
import uuid
import shutil
import signal
import socket
import struct
import threading as _threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from flask import Flask, jsonify, render_template, render_template_string, request, Response, session, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash
import urllib.request
import urllib.error
import requests as req_lib

# ============================================================
# Setup
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")
    load_dotenv()
except Exception:
    pass
BOT_ENGINE_DIR = BASE_DIR / "bot-engine"
DB_FILE = BASE_DIR / "database.json"

# PostgreSQL is the PRIMARY database when DATABASE_URL is set
# (recommended on Railway / VPS). Without it, the app transparently
# falls back to the local database.json file so it still runs anywhere.
# 'bot_processes' pid/port state is ALSO mirrored to .bot_processes.json so a
# restarted SaaS worker re-adopts still-running bot-engine instances.
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
try:
    import psycopg2
    import psycopg2.extras
    _Json = psycopg2.extras.Json
except ImportError:
    psycopg2 = None
    _Json = None
PG_ENABLED = bool(DATABASE_URL) and psycopg2 is not None
LOG_DIR = BASE_DIR / "logs"
USER_CONFIGS_DIR = BASE_DIR / "user_configs"
USER_INSTANCES_DIR = BASE_DIR / "user_instances"
LOG_DIR.mkdir(exist_ok=True)
USER_CONFIGS_DIR.mkdir(exist_ok=True)
USER_INSTANCES_DIR.mkdir(exist_ok=True)
BOT_PROCESSES_FILE = BASE_DIR / ".bot_processes.json"

def _load_bot_processes() -> dict:
    try:
        if BOT_PROCESSES_FILE.exists():
            return json.loads(BOT_PROCESSES_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}

def _save_bot_processes(procs: dict):
    try:
        tmp = BOT_PROCESSES_FILE.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(procs, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, BOT_PROCESSES_FILE)
    except Exception:
        pass


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_DIR / "saas.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("saas")

app = Flask(__name__, template_folder=str(BASE_DIR / "templates"),
            static_folder=str(BASE_DIR / "static"))

# Fix 2: FLASK_SECRET must be set in production to preserve sessions across restarts
_flask_secret = os.environ.get("FLASK_SECRET", "").strip()
if not _flask_secret:
    _secret_file = BASE_DIR / ".flask_secret"
    if _secret_file.exists():
        try:
            _flask_secret = _secret_file.read_text(encoding="utf-8").strip()
        except Exception:
            _flask_secret = ""
    if not _flask_secret:
        _flask_secret = secrets.token_hex(32)
        try:
            _secret_file.write_text(_flask_secret, encoding="utf-8")
        except Exception:
            pass
app.config["SECRET_KEY"] = _flask_secret
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=7)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
# Set COOKIE_SECURE=1 in production (HTTPS) so session cookies never travel over plain HTTP
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("COOKIE_SECURE", "0") == "1"

# Bad numeric input ("abc" as leverage/amount/days) must return a clean 400,
# never an unhandled 500
@app.errorhandler(ValueError)
@app.errorhandler(TypeError)
def _bad_numeric_value(e):
    logger.warning("Rejected request with invalid value: %s", e)
    return jsonify({"success": False, "error": "Invalid value provided", "detail": str(e)}), 400

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


from werkzeug.exceptions import HTTPException as _HTTPException


def _is_json_api_path(path: str) -> bool:
    return path.startswith(("/api/", "/bot/api/", "/bot/socket.io"))


@app.errorhandler(_HTTPException)
def handle_http_exception(err):
    """Return JSON instead of Flask HTML error pages for /api/* and /bot/api/* routes."""
    if _is_json_api_path(request.path):
        return jsonify({"success": False, "error": f"HTTP {err.code}: {err.name}"}), (err.code or 500)
    return err


@app.errorhandler(500)
def handle_internal_server_error(err):
    """Return JSON on unhandled 500 errors for /api/* and /bot/api/* routes."""
    if _is_json_api_path(request.path):
        return jsonify({"success": False, "error": "Internal server error"}), 500
    return err

# ============================================================
# Configuration
# ============================================================

# Secret Admin URL path (e.g. /x7k2-admin) - hides admin endpoint from automated scanners
ADMIN_SECRET_PATH = (os.environ.get("ADMIN_SECRET_PATH") or "/x7k2-admin").strip()
if not ADMIN_SECRET_PATH.startswith("/"):
    ADMIN_SECRET_PATH = "/" + ADMIN_SECRET_PATH

# Admin password - supports ADMIN_SECRET, ADMIN_PASSWORD, ADMIN_PASS, etc.
# SECURITY: no default password. Admin panel stays DISABLED until ADMIN_SECRET
# is configured (fail-closed). Set it in .env on the server.
ADMIN_SECRET = (
    os.environ.get("ADMIN_SECRET")
    or os.environ.get("ADMIN_PASSWORD")
    or os.environ.get("ADMIN_PASS")
    or os.environ.get("SAAS_ADMIN_PASSWORD")
    or os.environ.get("SAAS_ADMIN_SECRET")
    or ""
).strip()
if ADMIN_SECRET:
    logger.info("Admin panel: ENABLED (secret path: %s)", ADMIN_SECRET_PATH)
else:
    logger.warning("Admin panel DISABLED — set ADMIN_SECRET in .env to enable it.")

# Fix 1: Encryption key for API keys — MUST be set via env var in production.
# If unset, a strong random key is generated and persisted to .encryption_key
# (next to .flask_secret). The old hardcoded default is retired: deployments
# that relied on it must re-save users' API keys once after setting the env.
_ENCRYPTION_RAW = os.environ.get("ENCRYPTION_KEY", "")
if not _ENCRYPTION_RAW:
    _enc_key_file = BASE_DIR / ".encryption_key"
    try:
        if _enc_key_file.exists():
            _ENCRYPTION_RAW = _enc_key_file.read_text().strip()
        if not _ENCRYPTION_RAW:
            _ENCRYPTION_RAW = secrets.token_hex(32)
            _enc_key_file.write_text(_ENCRYPTION_RAW)
            logger.warning("[SECURITY] ENCRYPTION_KEY not set — generated and persisted a new "
                           "random key at .encryption_key. Back it up with your secrets.")
            logger.warning("[SECURITY] EPHEMERAL-HOSTING WARNING: Railway/Coolify containers "
                           "are wiped on every redeploy. If this file is not on a persistent "
                           "volume a NEW key is generated each boot and every saved API key "
                           "becomes unreadable -> Binance 401/-2014 'API-key format invalid' "
                           "for all users. FIX: set ENCRYPTION_KEY as an environment variable "
                           "in your hosting dashboard, then re-save each user's API key once.")
    except Exception:
        logger.critical("[SECURITY] Could not persist encryption key — refusing to use an "
                        "insecure default. Set ENCRYPTION_KEY env var.")
        raise SystemExit(1)
# Derive a valid 32-byte key
_ENCRYPTION_KEY_BYTES = hashlib.sha256(_ENCRYPTION_RAW.encode("utf-8")).digest()

# Fix 12: Shared secret token for SaaS ↔ Bot-Engine communication
# Bot engine instances will only accept requests bearing this token.
# Persist to .bot_engine_token if unset so restarts / workers stay in sync.
BOT_ENGINE_TOKEN = os.environ.get("BOT_ENGINE_TOKEN", "").strip()
if not BOT_ENGINE_TOKEN:
    _bot_token_file = BASE_DIR / ".bot_engine_token"
    try:
        if _bot_token_file.exists():
            BOT_ENGINE_TOKEN = _bot_token_file.read_text(encoding="utf-8").strip()
        if not BOT_ENGINE_TOKEN:
            BOT_ENGINE_TOKEN = secrets.token_hex(32)
            _bot_token_file.write_text(BOT_ENGINE_TOKEN, encoding="utf-8")
    except Exception:
        BOT_ENGINE_TOKEN = secrets.token_hex(32)

# Serialization guards: payment activation + referral payouts must be atomic
# (prevents double licenses / double withdrawals under concurrent requests)
_payment_lock = _threading.RLock()
_payout_lock = _threading.RLock()

# Port range for per-user bot-engine instances
PORT_START = 5001
PORT_END = 5999

# Payment wallets (TRC-20 Tron & BEP-20 BSC BNB Smart Chain)
WALLET_TRC20 = os.environ.get("PAYMENT_WALLET_TRC20", "TLponfWCPEqdv8CqbvXAZESQYnoNiw5Bpp")
WALLET_BEP20 = os.environ.get("PAYMENT_WALLET_BEP20", "0xc53cd5f340bea5148ed657ca80ff51626901e609")
WALLET_ADDRESS = WALLET_TRC20
WALLET_NETWORK = os.environ.get("PAYMENT_NETWORK", "TRC20 (USDT)")

# Google OAuth (set via env vars)
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.environ.get("GOOGLE_REDIRECT_URI", "")

# SaaS email (for sending license keys to users after payment verification)
def _get_smtp_config():
    """Retrieve SaaS SMTP settings from DB or environment variables (supports multiple naming conventions)."""
    cfg = DB.get("settings", {}).get("smtp", {}) if isinstance(DB.get("settings"), dict) else {}

    # Priority: 1. ENV vars (.env from Coolify or OS), 2. DB settings saved in Admin UI
    env_user = (
        os.environ.get("SAAS_SMTP_USER")
        or os.environ.get("SMTP_USER")
        or os.environ.get("EMAIL_USER")
        or os.environ.get("MAIL_USERNAME")
        or os.environ.get("GMAIL_USER")
        or ""
    ).strip()

    env_pass = (
        os.environ.get("SAAS_SMTP_PASS")
        or os.environ.get("SMTP_PASS")
        or os.environ.get("SMTP_PASSWORD")
        or os.environ.get("EMAIL_PASSWORD")
        or os.environ.get("MAIL_PASSWORD")
        or os.environ.get("GMAIL_APP_PASS")
        or ""
    ).strip()

    db_user = str(cfg.get("user") or cfg.get("username") or "").strip()
    db_pass = str(cfg.get("pass") or cfg.get("password") or "").strip()

    if env_user and env_pass:
        source = "environment (.env)"
        user = env_user
        password = env_pass
        server = (
            os.environ.get("SAAS_SMTP_SERVER")
            or os.environ.get("SMTP_SERVER")
            or os.environ.get("MAIL_SERVER")
            or cfg.get("server")
            or cfg.get("host")
            or "smtp.gmail.com"
        ).strip()
        try:
            port = int(
                os.environ.get("SAAS_SMTP_PORT")
                or os.environ.get("SMTP_PORT")
                or os.environ.get("MAIL_PORT")
                or cfg.get("port")
                or 587
            )
        except (ValueError, TypeError):
            port = 587
    elif db_user and db_pass:
        source = "database (Admin Settings)"
        user = db_user
        password = db_pass
        server = str(cfg.get("server") or cfg.get("host") or "smtp.gmail.com").strip()
        try:
            port = int(cfg.get("port", 587))
        except (ValueError, TypeError):
            port = 587
    else:
        source = "not_configured"
        user = env_user or db_user
        password = env_pass or db_pass
        server = str(cfg.get("server") or cfg.get("host") or os.environ.get("SMTP_SERVER") or "smtp.gmail.com").strip()
        try:
            port = int(cfg.get("port") or os.environ.get("SMTP_PORT") or 587)
        except (ValueError, TypeError):
            port = 587

    sender_name = str(cfg.get("sender_name") or os.environ.get("SMTP_SENDER_NAME") or "Weexionic Trading Bot").strip()
    from_email = str(cfg.get("from_email") or os.environ.get("SMTP_FROM_EMAIL") or user).strip()

    return {
        "server": server,
        "host": server,
        "port": port,
        "user": user,
        "pass": password,
        "sender_name": sender_name,
        "from_email": from_email,
        "source": source,
    }

SAAS_SMTP_SERVER = os.environ.get("SAAS_SMTP_SERVER", "smtp.gmail.com")
SAAS_SMTP_PORT = int(os.environ.get("SAAS_SMTP_PORT", 587))
SAAS_SMTP_USER = os.environ.get("SAAS_SMTP_USER", "")
SAAS_SMTP_PASS = os.environ.get("SAAS_SMTP_PASS", "")

# Upload directory for payment screenshots
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

# Package definitions (Monthly = $19 [$2 ref bonus]; 1-Year = $79 [$10 ref bonus]; Lifetime = $500 [$50 ref bonus])
PACKAGES = {
    "monthly": {"name": "Monthly", "price": 19, "days": 30, "currency": "USDT", "popular": False, "referral_bonus": 2},
    "yearly": {"name": "1-Year", "price": 79, "days": 365, "currency": "USDT", "popular": True, "referral_bonus": 10},
    "lifetime": {"name": "Lifetime", "price": 500, "days": 9999, "currency": "USDT", "popular": False, "referral_bonus": 50},
}

logger.info("=" * 60)
logger.info(" TradeBot SaaS Webapp - Starting")
logger.info(" Bot engine dir: %s", BOT_ENGINE_DIR)
# Admin password is NEVER printed to logs (security)
if ADMIN_SECRET:
    logger.info(" Admin panel: ENABLED (password set via env)")
else:
    logger.info(" Admin panel: DISABLED (no ADMIN_SECRET env var)")
logger.info(" Payment wallet: %s...%s (%s)", WALLET_ADDRESS[:8] if len(WALLET_ADDRESS) > 8 else WALLET_ADDRESS, WALLET_ADDRESS[-4:] if len(WALLET_ADDRESS) > 4 else "", WALLET_NETWORK)
logger.info(" Google OAuth: %s", "configured" if GOOGLE_CLIENT_ID else "NOT configured")
logger.info("=" * 60)

# ============================================================
# Encryption (Fernet - real AES-128-CBC encryption)
# ============================================================

def _get_fernet():
    """Lazy-init Fernet cipher from derived key."""
    from cryptography.fernet import Fernet
    import base64
    key_b64 = base64.urlsafe_b64encode(_ENCRYPTION_KEY_BYTES)
    return Fernet(key_b64)

def encrypt(plain_text: str) -> str:
    if not plain_text:
        return ""
    try:
        f = _get_fernet()
        return f.encrypt(plain_text.encode("utf-8")).decode("utf-8")
    except Exception as e:
        logger.error("Encryption failed: %s", e)
        return ""

def decrypt_checked(cipher_text: str) -> tuple:
    """Decrypt with an explicit success flag — NEVER silently return "".

    Root cause of the -2014 outage: decrypt() returned "" on any failure
    (e.g. ENCRYPTION_KEY regenerated after a redeploy on an ephemeral
    filesystem), so an EMPTY key was pushed into the engine and Binance
    answered 401/-2014 'API-key format invalid' for every symbol.
    Returns (ok, value). ok=False means the ciphertext exists but cannot be
    read with the current key — the user MUST re-save the credential.
    """
    if not cipher_text:
        return True, ""  # nothing stored — not an error
    try:
        f = _get_fernet()
        return True, f.decrypt(cipher_text.encode("utf-8")).decode("utf-8")
    except Exception as e:
        logger.error("Decryption FAILED (key changed or ciphertext corrupt): %s", e)
        return False, ""

def decrypt(cipher_text: str) -> str:
    if not cipher_text:
        return ""
    ok, val = decrypt_checked(cipher_text)
    return val if ok else ""

# Fix 6: Upgrade password hashing to PBKDF2-SHA256 via Werkzeug
def hash_password(password: str) -> str:
    """Hash password using PBKDF2-SHA256 (industry standard, slow by design)."""
    return generate_password_hash(password, method="pbkdf2:sha256:260000")

def verify_password(password: str, stored: str) -> bool:
    """Verify password — supports new PBKDF2 and legacy SHA256 hashes (backward compat)."""
    if not stored:
        return False
    # New format: werkzeug PBKDF2 hash
    if stored.startswith("pbkdf2:") or stored.startswith("scrypt:"):
        return check_password_hash(stored, password)
    # Legacy format: "salt$sha256hash" — allows old accounts to still log in
    try:
        salt, hashed = stored.split("$", 1)
        return hashlib.sha256((salt + password).encode()).hexdigest() == hashed
    except (ValueError, AttributeError):
        return False

# ============================================================
# Database (JSON file with thread lock)
# ============================================================

def _pg_connect():
    return psycopg2.connect(DATABASE_URL)

def _sync_table_columns(cur, table_name, expected_columns):
    """Check if all expected columns exist in the table. If not, auto-add them."""
    cur.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
        (table_name,)
    )
    existing_cols = {row[0].lower() for row in cur.fetchall()}
    
    for col_name, col_def in expected_columns.items():
        if col_name.lower() not in existing_cols:
            logger.info("Auto-migration: Adding missing column '%s' to table '%s'", col_name, table_name)
            cur.execute(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_def}")

def _pg_init():
    try:
        conn = _pg_connect()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        id VARCHAR(36) PRIMARY KEY,
                        email VARCHAR(255) UNIQUE NOT NULL,
                        name VARCHAR(255),
                        password_hash VARCHAR(255),
                        role VARCHAR(50) DEFAULT 'user',
                        banned BOOLEAN DEFAULT FALSE,
                        created_at VARCHAR(50),
                        google_id VARCHAR(255) DEFAULT '',
                        google_picture TEXT DEFAULT '',
                        subscription JSONB DEFAULT '{}'::jsonb,
                        license_key VARCHAR(50),
                        referral_code VARCHAR(50),
                        referred_by VARCHAR(36),
                        referral_earnings NUMERIC DEFAULT 0,
                        referral_history JSONB DEFAULT '[]'::jsonb,
                        payout_wallet VARCHAR(255) DEFAULT '',
                        payout_requests JSONB DEFAULT '[]'::jsonb,
                        bot_config JSONB DEFAULT '{}'::jsonb
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS licenses (
                        key VARCHAR(50) PRIMARY KEY,
                        plan VARCHAR(50),
                        days INTEGER,
                        note TEXT,
                        created_at VARCHAR(50),
                        expires_at VARCHAR(50),
                        used_by VARCHAR(36),
                        activated_at VARCHAR(50),
                        active BOOLEAN DEFAULT FALSE,
                        revoked BOOLEAN DEFAULT FALSE
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS orders (
                        id VARCHAR(50) PRIMARY KEY,
                        user_id VARCHAR(36),
                        user_email VARCHAR(255),
                        user_name VARCHAR(255),
                        package_id VARCHAR(50),
                        package_name VARCHAR(50),
                        amount NUMERIC,
                        currency VARCHAR(20) DEFAULT 'USDT',
                        days INTEGER,
                        status VARCHAR(50) DEFAULT 'pending',
                        tx_hash VARCHAR(255),
                        screenshot VARCHAR(255),
                        created_at VARCHAR(50),
                        submitted_at VARCHAR(50),
                        verified_at VARCHAR(50),
                        license_key VARCHAR(50),
                        rejection_reason TEXT
                    )
                """)
                
                # Sync columns for schema updates
                users_cols = {
                    "id": "VARCHAR(36)",
                    "email": "VARCHAR(255)",
                    "name": "VARCHAR(255)",
                    "password_hash": "VARCHAR(255)",
                    "role": "VARCHAR(50) DEFAULT 'user'",
                    "banned": "BOOLEAN DEFAULT FALSE",
                    "created_at": "VARCHAR(50)",
                    "google_id": "VARCHAR(255) DEFAULT ''",
                    "google_picture": "TEXT DEFAULT ''",
                    "subscription": "JSONB DEFAULT '{}'::jsonb",
                    "license_key": "VARCHAR(50)",
                    "referral_code": "VARCHAR(50)",
                    "referred_by": "VARCHAR(36)",
                    "referral_earnings": "NUMERIC DEFAULT 0",
                    "referral_history": "JSONB DEFAULT '[]'::jsonb",
                    "payout_wallet": "VARCHAR(255) DEFAULT ''",
                    "payout_requests": "JSONB DEFAULT '[]'::jsonb",
                    "bot_config": "JSONB DEFAULT '{}'::jsonb"
                }
                licenses_cols = {
                    "key": "VARCHAR(50)",
                    "plan": "VARCHAR(50)",
                    "days": "INTEGER",
                    "note": "TEXT",
                    "created_at": "VARCHAR(50)",
                    "expires_at": "VARCHAR(50)",
                    "used_by": "VARCHAR(36)",
                    "activated_at": "VARCHAR(50)",
                    "active": "BOOLEAN DEFAULT FALSE",
                    "revoked": "BOOLEAN DEFAULT FALSE"
                }
                orders_cols = {
                    "id": "VARCHAR(50)",
                    "user_id": "VARCHAR(36)",
                    "user_email": "VARCHAR(255)",
                    "user_name": "VARCHAR(255)",
                    "package_id": "VARCHAR(50)",
                    "package_name": "VARCHAR(50)",
                    "amount": "NUMERIC",
                    "currency": "VARCHAR(20) DEFAULT 'USDT'",
                    "days": "INTEGER",
                    "status": "VARCHAR(50) DEFAULT 'pending'",
                    "tx_hash": "VARCHAR(255)",
                    "screenshot": "VARCHAR(255)",
                    "created_at": "VARCHAR(50)",
                    "submitted_at": "VARCHAR(50)",
                    "verified_at": "VARCHAR(50)",
                    "license_key": "VARCHAR(50)",
                    "rejection_reason": "TEXT"
                }
                
                _sync_table_columns(cur, "users", users_cols)
                _sync_table_columns(cur, "licenses", licenses_cols)
                _sync_table_columns(cur, "orders", orders_cols)
                
            conn.commit()
            logger.info("PostgreSQL database tables initialized and verified successfully")
        finally:
            conn.close()
    except Exception as e:
        logger.error("PostgreSQL init failed: %s", e)

def _load_json_db() -> dict:
    db = {"users": {}, "licenses": {}, "orders": {}, "bot_processes": {}, "settings": {}, "used_txids": {}}
    bak_file = DB_FILE.with_suffix(".json.bak")
    for candidate in (DB_FILE, bak_file):
        if not candidate.exists():
            continue
        try:
            with open(candidate, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                continue
            for section in ("users", "licenses", "orders", "settings", "used_txids"):
                val = data.get(section)
                if isinstance(val, dict):
                    db[section] = val
            logger.info("Loaded %s (%d users)", candidate.name, len(db["users"]))
            return db
        except (json.JSONDecodeError, OSError) as e:
            logger.error("DB load failed for %s: %s", candidate.name, e)
    return db

def _parse_json_column(val, default=dict):
    fallback = default() if callable(default) else {}
    if val is None:
        return fallback
    if isinstance(val, (dict, list)):
        if default is list and not isinstance(val, list):
            return fallback
        if default is dict and not isinstance(val, dict):
            return fallback
        return val
    if isinstance(val, str):
        try:
            parsed = json.loads(val)
            if default is list and not isinstance(parsed, list):
                return fallback
            if default is dict and not isinstance(parsed, dict):
                return fallback
            return parsed
        except json.JSONDecodeError:
            pass
    return fallback

def _load_pg_db() -> dict:
    db = {"users": {}, "licenses": {}, "orders": {}, "bot_processes": {}, "used_txids": {}}
    _pg_init()
    conn = _pg_connect()
    try:
        with conn.cursor() as cur:
            # Load users
            cur.execute("SELECT id, email, name, password_hash, role, banned, created_at, subscription, license_key, referral_code, referred_by, bot_config, referral_earnings, referral_history, payout_wallet, payout_requests, google_id, google_picture FROM users")
            user_rows = cur.fetchall()
            for r in user_rows:
                db["users"][r[0]] = {
                    "id": r[0],
                    "email": (r[1] or "").strip().lower(),
                    "name": r[2],
                    "password_hash": r[3] or "",
                    "role": r[4] or "user",
                    "banned": bool(r[5]),
                    "created_at": r[6],
                    "subscription": _parse_json_column(r[7], dict),
                    "license_key": r[8],
                    "referral_code": r[9],
                    "referred_by": r[10],
                    "bot_config": _parse_json_column(r[11], dict),
                    "referral_earnings": float(r[12] or 0),
                    "referral_history": _parse_json_column(r[13], list) if len(r) > 13 else [],
                    "payout_wallet": r[14] if len(r) > 14 and r[14] else "",
                    "payout_requests": _parse_json_column(r[15], list) if len(r) > 15 else [],
                    "google_id": r[16] if len(r) > 16 and r[16] else "",
                    "google_picture": r[17] if len(r) > 17 and r[17] else "",
                }

            # Load licenses
            cur.execute("SELECT key, plan, days, note, created_at, expires_at, used_by, activated_at, active, revoked FROM licenses")
            lic_rows = cur.fetchall()
            for r in lic_rows:
                db["licenses"][r[0]] = {
                    "key": r[0],
                    "plan": r[1],
                    "days": r[2],
                    "note": r[3],
                    "created_at": r[4],
                    "expires_at": r[5],
                    "used_by": r[6],
                    "activated_at": r[7],
                    "active": r[8],
                    "revoked": r[9]
                }

            # Load orders
            cur.execute("SELECT id, user_id, user_email, user_name, package_id, package_name, amount, currency, days, status, tx_hash, screenshot, created_at, submitted_at, verified_at, license_key, rejection_reason FROM orders")
            order_rows = cur.fetchall()
            for r in order_rows:
                db["orders"][r[0]] = {
                    "id": r[0],
                    "user_id": r[1],
                    "user_email": r[2],
                    "user_name": r[3],
                    "package_id": r[4],
                    "package_name": r[5],
                    "amount": float(r[6]) if r[6] is not None else 0.0,
                    "currency": r[7],
                    "days": r[8],
                    "status": r[9],
                    "tx_hash": r[10],
                    "screenshot": r[11],
                    "created_at": r[12],
                    "submitted_at": r[13],
                    "verified_at": r[14],
                    "license_key": r[15],
                    "rejection_reason": r[16]
                }
    finally:
        conn.close()
    logger.info("Loaded %d users, %d licenses, %d orders from PostgreSQL",
                len(db["users"]), len(db["licenses"]), len(db["orders"]))
    return db

def _attach_file_settings(db: dict):
    """settings{} lives in database.json even when PostgreSQL is primary."""
    try:
        s = {}
        if DB_FILE.exists():
            with open(DB_FILE, "r", encoding="utf-8") as f:
                s = (json.load(f) or {}).get("settings") or {}
        db["settings"] = s
    except Exception as e:
        logger.debug("settings sidecar load skipped: %s", e)
        db.setdefault("settings", {})


def _write_settings_sidecar(db: dict):
    """Persist settings{} to database.json even when PostgreSQL is primary."""
    try:
        data = {}
        if DB_FILE.exists():
            try:
                with open(DB_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f) or {}
            except Exception:
                data = {}
        data["settings"] = db.get("settings") or {}
        tmp = DB_FILE.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, DB_FILE)
    except OSError as e:
        logger.error("settings sidecar save failed: %s", e)


def load_db() -> dict:
    """Load the DB — PostgreSQL when available, else database.json."""
    if PG_ENABLED:
        try:
            db = _load_pg_db()
            _attach_file_settings(db)
            if db["users"] or db["licenses"] or db["orders"]:
                return db
            # Empty Postgres → one-time seed from the existing database.json.
            if DB_FILE.exists():
                seed = _load_json_db()
                for section in ("users", "licenses", "orders"):
                    db[section].update(seed[section])
                if db["users"] or db["licenses"] or db["orders"]:
                    save_db(db)
                    logger.info("Seeded PostgreSQL from database.json (%d users)", len(db["users"]))
            return db
        except Exception as e:
            logger.error("PostgreSQL load failed (%s) — falling back to database.json", e)
    return _load_json_db()

_db_lock = _threading.Lock()

# Serializes bot-engine process spawn/stop so two concurrent requests
# (e.g. rapid page loads after login) never start duplicate instances.
_spawn_lock = _threading.Lock()

def save_db(db: dict):
    """Persist the DB (PostgreSQL primary, database.json fallback)."""
    with _db_lock:
        if PG_ENABLED:
            try:
                conn = _pg_connect()
                try:
                    with conn.cursor() as cur:
                        # 1. Sync Users (delete removed/merged IDs first so UNIQUE(email) never collides)
                        user_ids = list((db.get("users") or {}).keys())
                        if user_ids:
                            cur.execute("DELETE FROM users WHERE id NOT IN %s", (tuple(user_ids),))
                        else:
                            cur.execute("DELETE FROM users")
                        for uid, u in (db.get("users") or {}).items():
                            cur.execute("""
                                INSERT INTO users (id, email, name, password_hash, role, banned, created_at, google_id, google_picture, subscription, license_key, referral_code, referred_by, bot_config, referral_earnings, referral_history, payout_wallet, payout_requests)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                                ON CONFLICT (id) DO UPDATE SET
                                    email = EXCLUDED.email,
                                    name = EXCLUDED.name,
                                    password_hash = EXCLUDED.password_hash,
                                    role = EXCLUDED.role,
                                    banned = EXCLUDED.banned,
                                    created_at = EXCLUDED.created_at,
                                    google_id = EXCLUDED.google_id,
                                    google_picture = EXCLUDED.google_picture,
                                    subscription = EXCLUDED.subscription,
                                    license_key = EXCLUDED.license_key,
                                    referral_code = EXCLUDED.referral_code,
                                    referred_by = EXCLUDED.referred_by,
                                    bot_config = EXCLUDED.bot_config,
                                    referral_earnings = EXCLUDED.referral_earnings,
                                    referral_history = EXCLUDED.referral_history,
                                    payout_wallet = EXCLUDED.payout_wallet,
                                    payout_requests = EXCLUDED.payout_requests
                            """, (
                                u.get("id"),
                                (u.get("email") or "").strip().lower(),
                                u.get("name"),
                                u.get("password_hash") or "",
                                u.get("role", "user"),
                                u.get("banned", False),
                                u.get("created_at"),
                                u.get("google_id") or "",
                                u.get("google_picture") or "",
                                _Json(u.get("subscription", {})),
                                u.get("license_key"),
                                u.get("referral_code"),
                                u.get("referred_by"),
                                _Json(u.get("bot_config", {})),
                                float(u.get("referral_earnings", 0.0) or 0.0),
                                _Json(u.get("referral_history", [])),
                                u.get("payout_wallet", "") or "",
                                _Json(u.get("payout_requests", []))
                            ))

                        # 2. Sync Licenses
                        lic_keys = []
                        for key, l in (db.get("licenses") or {}).items():
                            lic_keys.append(key)
                            cur.execute("""
                                INSERT INTO licenses (key, plan, days, note, created_at, expires_at, used_by, activated_at, active, revoked)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                                ON CONFLICT (key) DO UPDATE SET
                                    plan = EXCLUDED.plan,
                                    days = EXCLUDED.days,
                                    note = EXCLUDED.note,
                                    created_at = EXCLUDED.created_at,
                                    expires_at = EXCLUDED.expires_at,
                                    used_by = EXCLUDED.used_by,
                                    activated_at = EXCLUDED.activated_at,
                                    active = EXCLUDED.active,
                                    revoked = EXCLUDED.revoked
                            """, (
                                l.get("key"),
                                l.get("plan"),
                                l.get("days"),
                                l.get("note"),
                                l.get("created_at"),
                                l.get("expires_at"),
                                l.get("used_by"),
                                l.get("activated_at"),
                                l.get("active", False),
                                l.get("revoked", False)
                            ))
                        if lic_keys:
                            cur.execute("DELETE FROM licenses WHERE key NOT IN %s", (tuple(lic_keys),))
                        else:
                            cur.execute("DELETE FROM licenses")

                        # 3. Sync Orders
                        order_ids = []
                        for oid, o in (db.get("orders") or {}).items():
                            order_ids.append(oid)
                            cur.execute("""
                                INSERT INTO orders (id, user_id, user_email, user_name, package_id, package_name, amount, currency, days, status, tx_hash, screenshot, created_at, submitted_at, verified_at, license_key, rejection_reason)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                                ON CONFLICT (id) DO UPDATE SET
                                    user_id = EXCLUDED.user_id,
                                    user_email = EXCLUDED.user_email,
                                    user_name = EXCLUDED.user_name,
                                    package_id = EXCLUDED.package_id,
                                    package_name = EXCLUDED.package_name,
                                    amount = EXCLUDED.amount,
                                    currency = EXCLUDED.currency,
                                    days = EXCLUDED.days,
                                    status = EXCLUDED.status,
                                    tx_hash = EXCLUDED.tx_hash,
                                    screenshot = EXCLUDED.screenshot,
                                    created_at = EXCLUDED.created_at,
                                    submitted_at = EXCLUDED.submitted_at,
                                    verified_at = EXCLUDED.verified_at,
                                    license_key = EXCLUDED.license_key,
                                    rejection_reason = EXCLUDED.rejection_reason
                            """, (
                                o.get("id"),
                                o.get("user_id"),
                                o.get("user_email"),
                                o.get("user_name"),
                                o.get("package_id"),
                                o.get("package_name"),
                                o.get("amount"),
                                o.get("currency", "USDT"),
                                o.get("days"),
                                o.get("status", "pending"),
                                o.get("tx_hash"),
                                o.get("screenshot"),
                                o.get("created_at"),
                                o.get("submitted_at"),
                                o.get("verified_at"),
                                o.get("license_key"),
                                o.get("rejection_reason")
                            ))
                        if order_ids:
                            cur.execute("DELETE FROM orders WHERE id NOT IN %s", (tuple(order_ids),))
                        else:
                            cur.execute("DELETE FROM orders")

                    conn.commit()
                except Exception as e:
                    conn.rollback()
                    raise e
                finally:
                    conn.close()
                _write_settings_sidecar(db)
                return
            except Exception as e:
                logger.error("PostgreSQL save failed (%s) — writing database.json fallback", e)
        try:
            # Atomic write + rolling backup: never leave a truncated database.json behind
            tmp = DB_FILE.with_suffix(".json.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(db, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            if DB_FILE.exists():
                try:
                    shutil.copy2(DB_FILE, DB_FILE.with_suffix(".json.bak"))
                except OSError:
                    pass
            os.replace(tmp, DB_FILE)
        except OSError as e:
            logger.error("DB save failed: %s", e)


def _norm_email(email: Optional[str]) -> str:
    """Return canonical lowercase, trimmed email address."""
    return (email or "").strip().lower()


def _find_users_by_email(email: str, db: Optional[dict] = None) -> list:
    """Return all user dicts matching `email` case-insensitively."""
    norm = _norm_email(email)
    if not norm:
        return []
    store = db if db is not None else DB
    return [
        u for u in (store.get("users") or {}).values()
        if _norm_email(u.get("email")) == norm
    ]


def _gmail_canonical_email(email: str) -> str:
    """Return dot-insensitive canonical Gmail address, or normalized email otherwise."""
    norm = _norm_email(email)
    if "@" not in norm:
        return norm
    local, domain = norm.rsplit("@", 1)
    if domain in ("gmail.com", "googlemail.com"):
        return f"{local.replace('.', '')}@gmail.com"
    return norm


def _find_users_by_email_tolerant(email: str, db: Optional[dict] = None) -> list:
    """Match exact email first, falling back to dot-insensitive Gmail match."""
    exact = _find_users_by_email(email, db=db)
    if exact:
        return exact
    norm = _norm_email(email)
    if not norm or not norm.endswith(("@gmail.com", "@googlemail.com")):
        return []
    canon = _gmail_canonical_email(norm)
    store = db if db is not None else DB
    return [
        u for u in (store.get("users") or {}).values()
        if isinstance(u, dict) and _gmail_canonical_email(u.get("email") or "") == canon
    ]


def _default_bot_config(symbols_list: Optional[list] = None) -> dict:
    """Standard initial per-user bot configuration."""
    return {
        "exchange": "binance",
        "testnet": True,
        "symbols_list": list(symbols_list) if symbols_list is not None else [],
        "timeframe": "5m",
        "leverage": 10,
        "amount_mode": "fixed",
        "amount": 100,
        "amount_pct": 10,
        "stop_loss_pct": 0.2,
        "take_profit_pct": 1.0,
        "tp_mode": "fixed",
        "mode": "both",
        "max_concurrent_trades": 3,
        "api_key_enc": "",
        "api_secret_enc": "",
        "api_passphrase_enc": "",
    }


def _user_richness_score(u: dict, db: Optional[dict] = None) -> tuple:
    """Rank duplicate user records so the primary account survives merge."""
    store = db if db is not None else DB
    uid = u.get("id", "")
    sub_active = 1 if (u.get("subscription") or {}).get("status") == "active" else 0
    has_lic = 1 if u.get("license_key") else 0
    bc = u.get("bot_config") or {}
    has_keys = 1 if (bc.get("api_key_enc") or bc.get("api_keys_enc")) else 0
    has_inst = 1 if (uid and (USER_INSTANCES_DIR / uid).exists()) else 0
    order_cnt = sum(
        1 for o in (store.get("orders") or {}).values()
        if o.get("user_id") == uid
    )
    has_pw = 1 if u.get("password_hash") else 0
    is_admin_rec = 1 if (uid == "admin" or _norm_email(u.get("email")) == "admin@tradebot.com") else 0
    return (is_admin_rec, sub_active, has_lic, has_keys, has_inst, order_cnt, has_pw, uid)


def _migrate_user_files(src_uid: str, dst_uid: str) -> bool:
    """Copy missing instance and config files from `src_uid` to `dst_uid`."""
    if not src_uid or not dst_uid or src_uid == dst_uid:
        return False
    changed = False
    src_inst = USER_INSTANCES_DIR / src_uid
    dst_inst = USER_INSTANCES_DIR / dst_uid
    if src_inst.exists() and src_inst.is_dir():
        dst_inst.mkdir(parents=True, exist_ok=True)
        for root, _, files in os.walk(src_inst):
            rel = Path(root).relative_to(src_inst)
            (dst_inst / rel).mkdir(parents=True, exist_ok=True)
            for fn in files:
                src_f = Path(root) / fn
                dst_f = dst_inst / rel / fn
                try:
                    if not dst_f.exists() or (dst_f.stat().st_size == 0 and src_f.stat().st_size > 0):
                        shutil.copy2(src_f, dst_f)
                        changed = True
                except OSError:
                    pass
    src_cfg = USER_CONFIGS_DIR / f"{src_uid}.json"
    dst_cfg = USER_CONFIGS_DIR / f"{dst_uid}.json"
    if src_cfg.exists() and not dst_cfg.exists():
        try:
            shutil.copy2(src_cfg, dst_cfg)
            changed = True
        except OSError:
            pass
    return changed


def _merge_user_into(src_uid: str, src: dict, keep_id: str, keep: dict, db: dict) -> bool:
    """Non-destructively merge credentials, subscriptions, orders, referrals, and configs into `keep`."""
    changed = False
    keep_email = _norm_email(keep.get("email") or src.get("email"))
    if keep_email and keep.get("email") != keep_email:
        keep["email"] = keep_email
        changed = True

    if not keep.get("password_hash") and src.get("password_hash"):
        keep["password_hash"] = src["password_hash"]
        changed = True
    for fld in ("name", "google_id", "google_picture", "referred_by"):
        if src.get(fld) and not keep.get(fld):
            if fld == "referred_by" and src.get(fld) == keep_id:
                continue
            keep[fld] = src[fld]
            changed = True
    if src.get("banned") and not keep.get("banned"):
        keep["banned"] = True
        changed = True
    if src.get("role") == "admin" and keep.get("role") != "admin":
        keep["role"] = "admin"
        changed = True
    src_created = str(src.get("created_at") or "")
    keep_created = str(keep.get("created_at") or "")
    if src_created and (not keep_created or src_created < keep_created):
        keep["created_at"] = src_created
        changed = True

    src_sub = src.get("subscription") or {}
    keep_sub = keep.get("subscription") or {}
    src_active = src_sub.get("status") == "active"
    keep_active = keep_sub.get("status") == "active"
    src_exp = str(src_sub.get("expires_at") or "")
    keep_exp = str(keep_sub.get("expires_at") or "")
    if src_active and (not keep_active or src_exp > keep_exp):
        keep["subscription"] = json.loads(json.dumps(src_sub))
        if src.get("license_key"):
            keep["license_key"] = src["license_key"]
        changed = True
    elif src.get("license_key") and not keep.get("license_key"):
        keep["license_key"] = src["license_key"]
        changed = True

    for lic in (db.get("licenses") or {}).values():
        if lic.get("used_by") == src_uid:
            lic["used_by"] = keep_id
            changed = True

    for o in (db.get("orders") or {}).values():
        if o.get("user_id") == src_uid:
            o["user_id"] = keep_id
            if keep_email:
                o["user_email"] = keep_email
            changed = True

    for other in (db.get("users") or {}).values():
        if other.get("referred_by") == src_uid:
            other["referred_by"] = keep_id
            changed = True

    src_hist = src.get("referral_history") or []
    if src_hist:
        dst_hist = keep.setdefault("referral_history", [])
        seen = {json.dumps(item, sort_keys=True, default=str) for item in dst_hist}
        for item in src_hist:
            key = json.dumps(item, sort_keys=True, default=str)
            if key not in seen:
                dst_hist.append(item)
                seen.add(key)
                changed = True
    src_earn = float(src.get("referral_earnings") or 0.0)
    if src_earn > 0:
        keep["referral_earnings"] = float(keep.get("referral_earnings") or 0.0) + src_earn
        changed = True

    src_payouts = src.get("payout_requests") or []
    if src_payouts:
        dst_payouts = keep.setdefault("payout_requests", [])
        seen_ids = {p.get("id") for p in dst_payouts if isinstance(p, dict) and p.get("id")}
        for p in src_payouts:
            pid = p.get("id") if isinstance(p, dict) else None
            if pid and pid in seen_ids:
                continue
            dst_payouts.append(p)
            if pid:
                seen_ids.add(pid)
            changed = True

    keep_bc = keep.setdefault("bot_config", {})
    for k, v in (src.get("bot_config") or {}).items():
        if k == "api_keys_enc" and isinstance(v, dict):
            dst_keys = keep_bc.setdefault("api_keys_enc", {})
            if not isinstance(dst_keys, dict):
                dst_keys = {}
                keep_bc["api_keys_enc"] = dst_keys
            for ex_name, ex_blob in v.items():
                if ex_blob and not dst_keys.get(ex_name):
                    dst_keys[ex_name] = ex_blob
                    changed = True
        elif v and not keep_bc.get(k):
            keep_bc[k] = v
            changed = True

    procs = db.get("bot_processes") or {}
    if src_uid in procs:
        if keep_id not in procs:
            procs[keep_id] = procs.pop(src_uid)
        else:
            procs.pop(src_uid, None)
        changed = True

    if _migrate_user_files(src_uid, keep_id):
        changed = True
    return changed


def _dedupe_users_by_email(keep_id: str, db: Optional[dict] = None, save: bool = True) -> str:
    """Merge duplicate user records sharing the same email into `keep_id` cleanly.

    Preserves password_hash, google_id, role, active subscription, licenses, orders,
    referrals, payouts, bot_config (including per-exchange keys), and user_instances files.
    """
    store = db if db is not None else DB
    users = store.get("users") or {}
    keep = users.get(keep_id)
    if not keep:
        return keep_id
    keep_email = _norm_email(keep.get("email"))
    if not keep_email:
        return keep_id

    dirty = False
    if keep.get("email") != keep_email:
        keep["email"] = keep_email
        dirty = True

    for uid, u in list(users.items()):
        if uid == keep_id or _norm_email(u.get("email")) != keep_email:
            continue
        _merge_user_into(uid, u, keep_id, keep, store)
        logger.info("Merged duplicate account %s (id=%s) into %s (id=%s)",
                    u.get("email"), uid, keep.get("email"), keep_id)
        del users[uid]
        dirty = True

    if dirty and save:
        save_db(store)
    return keep_id


def _heal_users_integrity(db: dict) -> bool:
    """Normalize emails, merge duplicate-email accounts, and reattach orphaned orders on startup."""
    if not isinstance(db, dict):
        return False
    users = db.setdefault("users", {})
    healed = False

    by_email: dict = {}
    for uid, u in list(users.items()):
        if not isinstance(u, dict):
            continue
        norm = _norm_email(u.get("email"))
        if norm and u.get("email") != norm:
            u["email"] = norm
            healed = True
        if norm:
            by_email.setdefault(norm, []).append(u)

    for norm_email, group in by_email.items():
        if len(group) > 1:
            best = max(group, key=lambda item: _user_richness_score(item, db=db))
            _dedupe_users_by_email(best["id"], db=db, save=False)
            healed = True

    email_to_uid = {
        _norm_email(u.get("email")): uid
        for uid, u in users.items()
        if isinstance(u, dict) and _norm_email(u.get("email"))
    }
    for o in (db.get("orders") or {}).values():
        if not isinstance(o, dict):
            continue
        ouid = o.get("user_id")
        oemail = _norm_email(o.get("user_email"))
        if oemail in email_to_uid and ouid and ouid not in users:
            target_uid = email_to_uid[oemail]
            _migrate_user_files(ouid, target_uid)
            o["user_id"] = target_uid
            healed = True

    return healed


DB = load_db()
if _heal_users_integrity(DB):
    save_db(DB)

def _load_wallet_settings():
    """Restore admin-saved payment wallets after a restart/redeploy.

    Priority: DB settings (saved from Admin Panel) -> ENV -> defaults.
    Reads BOTH storage shapes: settings.payment_wallets (wallet_trc20/...)
    and settings.wallets (trc20/...), so a wallet saved by either version
    of the Admin Panel is restored.
    """
    global WALLET_TRC20, WALLET_BEP20, WALLET_ADDRESS, WALLET_NETWORK
    try:
        s = (DB.get("settings") or {}).get("payment_wallets") or {}
        w = (DB.get("settings") or {}).get("wallets") or {}
    except Exception:
        s, w = {}, {}
    trc20 = s.get("wallet_trc20") or w.get("trc20")
    bep20 = s.get("wallet_bep20") or w.get("bep20")
    network = s.get("network") or w.get("network")
    if trc20:
        WALLET_TRC20 = str(trc20).strip()
        WALLET_ADDRESS = WALLET_TRC20
    if bep20:
        WALLET_BEP20 = str(bep20).strip()
    if network:
        WALLET_NETWORK = str(network).strip()


_load_wallet_settings()


def _wallet_payload():
    """Unified wallet info for order/payment API responses."""
    return {
        "wallet": WALLET_ADDRESS,
        "wallet_address": WALLET_ADDRESS,
        "network": WALLET_NETWORK,
        "trc20": WALLET_TRC20,
        "bep20": WALLET_BEP20,
        "wallet_trc20": WALLET_TRC20,
        "wallet_bep20": WALLET_BEP20,
        "networks": ["TRC20", "BEP20"],
    }


@app.route("/api/payment/wallets", methods=["GET", "OPTIONS"])
@app.route("/api/payment/address", methods=["GET", "OPTIONS"])
@app.route("/api/payment/info", methods=["GET", "OPTIONS"])
@app.route("/api/wallet/address", methods=["GET", "OPTIONS"])
def api_payment_wallets():
    """User-facing payment wallet endpoint (login required)."""
    _origin = request.headers.get("Origin", "*")
    if request.method == "OPTIONS":
        resp = jsonify({})
        resp.status_code = 204
    elif not is_logged_in():
        resp = jsonify({"success": False,
                        "error": "Not logged in - login first, then retry payment"})
        resp.status_code = 401
    else:
        resp = jsonify({"success": True, **_wallet_payload()})
    resp.headers["Access-Control-Allow-Origin"] = _origin
    resp.headers["Access-Control-Allow-Credentials"] = "true"
    if request.method == "OPTIONS":
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, X-App-Client"
        resp.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    return resp


def _google_redirect_uri_for_page():
    """The EXACT redirect URI that must be registered in Google Cloud Console."""
    if GOOGLE_REDIRECT_URI:
        return GOOGLE_REDIRECT_URI
    try:
        root = request.url_root.rstrip("/")
        fwd_proto = (request.headers.get("X-Forwarded-Proto") or "").split(",")[0].strip().lower()
        host = (request.host or "").split(":")[0].lower()
        if root.startswith("http://") and (fwd_proto == "https" or host not in ("localhost", "127.0.0.1", "")):
            if fwd_proto == "https" or not request.host.startswith(("localhost", "127.0.0.1")):
                if fwd_proto == "https":
                    root = "https://" + root[len("http://"):]
        return root + "/auth/google/callback"
    except Exception:
        return "https://YOUR-DOMAIN/auth/google/callback"


_OAUTH_PAGE_STYLE = (
    "body{font-family:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;background:#0b0e11;"
    "color:#eaecef;display:flex;align-items:center;justify-content:center;min-height:100vh;"
    "margin:0;padding:24px}"
    ".card{max-width:640px;width:100%;background:#14181d;border:1px solid #2b3139;"
    "border-radius:14px;padding:28px}"
    "h1{margin:0 0 10px;font-size:21px;color:#f0b90b}"
    "p{line-height:1.55;margin:8px 0;color:#b7bdc6}"
    ".fix{background:rgba(240,185,11,.07);border:1px solid rgba(240,185,11,.35);"
    "border-radius:10px;padding:14px 16px;margin:14px 0;line-height:1.6;color:#eaecef}"
    "code{background:#0b0e11;border:1px solid #2b3139;border-radius:6px;padding:2px 6px;"
    "color:#f0b90b;word-break:break-all}"
    "a.btn{display:inline-block;margin-top:14px;background:#f0b90b;color:#ffffff;font-weight:700;"
    "padding:10px 18px;border-radius:8px;text-decoration:none}"
    "ul{padding-left:20px;line-height:1.7;color:#b7bdc6}"
    "table{font-size:14px}td{padding:6px 10px}"
)


def _oauth_error_page(title, message, fix_html):
    """Visible OAuth failure page - replaces the old silent ?error= redirects."""
    return render_template_string(
        """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ title }}</title><style>{{ style }}</style></head><body>
<div class="card"><h1>{{ title }}</h1><p>{{ message }}</p>
<div class="fix">{{ fix|safe }}</div>
<a class="btn" href="/auth/google">Retry Google Sign-In</a>
&nbsp;&nbsp;<a href="/auth/google/diag" style="color:#f0b90b">Open /auth/google/diag</a>
</div></body></html>""",
        title=title, style=_OAUTH_PAGE_STYLE, fix=fix_html, message=message)


@app.route("/auth/google/diag")
def google_diag():
    """Public diagnostic page for the Google OAuth setup."""
    cid = GOOGLE_CLIENT_ID or ""
    rows = [
        ("GOOGLE_CLIENT_ID", ("SET &mdash; " + cid) if cid else "NOT SET"),
        ("GOOGLE_CLIENT_SECRET", "SET" if GOOGLE_CLIENT_SECRET else
         "NOT SET &mdash; set env var GOOGLE_CLIENT_SECRET and restart"),
        ("Redirect URI used by server", _google_redirect_uri_for_page()),
    ]
    trs = "".join(
        "<tr><td style='color:#f0b90b'><b>%s</b></td><td style='word-break:break-all'>%s</td></tr>"
        % (k, v) for k, v in rows)
    fix = ("<ul>"
           "<li>Google Cloud Console &rarr; APIs &amp; Services &rarr; <b>Credentials</b> &rarr; your OAuth Client.</li>"
           "<li>Under <b>Authorized redirect URIs</b> add EXACTLY: "
           "<code><b>" + _google_redirect_uri_for_page() + "</b></code></li>"
           "<li>Save, wait ~5 minutes, then retry.</li>"
           "</ul>")
    return ("<!doctype html><html><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>Google Sign-In Setup</title><style>" + _OAUTH_PAGE_STYLE + "</style></head><body>"
            "<div class='card'><h1>Google Sign-In &mdash; Setup Status</h1>"
            "<table style='width:100%'>" + trs + "</table>"
            "<div class='fix'>" + fix + "</div>"
            "<a class='btn' href='/auth/google'>Retry Google Sign-In</a>"
            "</div></body></html>")

# ============================================================
# Database Migration (runs once at startup)
# ============================================================

def _migrate_db():
    """Fix old users and add missing fields for all accounts (including admin)."""
    fixed = 0
    for uid, user in DB.get("users", {}).items():
        if not user.get("referral_code"):
            user["referral_code"] = uid[:8].upper()
            fixed += 1
        if "referral_earnings" not in user:
            user["referral_earnings"] = 0.0
            fixed += 1
        if "referral_history" not in user:
            user["referral_history"] = []
            fixed += 1
        if "payout_wallet" not in user:
            user["payout_wallet"] = ""
            fixed += 1
        if "payout_requests" not in user:
            user["payout_requests"] = []
            fixed += 1

        if user.get("role") == "admin":
            continue

        # Skip users who actually activated a license
        if user.get("license_key"):
            continue
        sub = user.get("subscription", {})
        if not sub:
            continue
        expires_at = sub.get("expires_at")
        if not expires_at:
            continue
        # This user has an expires_at but never activated a license
        user["subscription"] = {
            "plan": "none",
            "status": "inactive",
            "started_at": sub.get("created_at", user.get("created_at", "")),
            "expires_at": None,
        }
        fixed += 1
    if fixed > 0:
        save_db(DB)
        logger.info("DB migration: fixed/updated %d user records", fixed)
    # Ensure 'orders' key exists
    if "orders" not in DB:
        DB["orders"] = {}
        save_db(DB)
        logger.info("DB migration: added 'orders' key")
    if "used_txids" not in DB:
        DB["used_txids"] = {}
        save_db(DB)

_migrate_db()

# ============================================================
# Simple in-memory rate limiter
# ============================================================

_rate_limit_store: dict[str, list] = {}
_rate_limit_lock = _threading.Lock()

def _check_rate_limit(client_key: str, max_requests: int = 30, window_seconds: int = 60) -> bool:
    """Returns True if the request is allowed, False if rate limited."""
    now = time.time()
    with _rate_limit_lock:
        timestamps = _rate_limit_store.get(client_key, [])
        # Remove old entries
        timestamps = [t for t in timestamps if now - t < window_seconds]
        if len(timestamps) >= max_requests:
            _rate_limit_store[client_key] = timestamps
            return False
        timestamps.append(now)
        _rate_limit_store[client_key] = timestamps
        return True

def _client_ip() -> str:
    """Resolve real client IP, trusting proxy headers only from local proxy."""
    remote = request.remote_addr or "unknown"
    if remote in ("127.0.0.1", "::1"):
        for hdr in ("CF-Connecting-IP", "X-Forwarded-For", "X-Real-IP"):
            raw = (request.headers.get(hdr) or "").strip()
            if raw:
                return raw.split(",")[0].strip()
    return remote

# ============================================================
# Auth helpers
# ============================================================

def is_logged_in() -> bool:
    return "user_id" in session

def is_admin() -> bool:
    if session.get("admin_authenticated"):
        return True
    user_id = session.get("user_id")
    if not user_id:
        return False
    user = DB["users"].get(user_id, {})
    return user.get("role") == "admin"

def current_user() -> Optional[dict]:
    user_id = session.get("user_id")
    if not user_id:
        return None
    return DB["users"].get(user_id)

def check_subscription(user: dict) -> dict:
    """Check user's subscription status.
    Admin users ALWAYS have active lifetime subscription."""
    if user.get("role") == "admin":
        return {"active": True, "status": "active", "days_left": 9999, "plan": "lifetime"}

    sub = user.get("subscription", {})
    if not sub:
        return {"active": False, "status": "none", "days_left": 0, "plan": "none"}

    expires_at = sub.get("expires_at")
    if not expires_at:
        return {"active": False, "status": "none", "days_left": 0, "plan": "none"}

    # Lifetime licenses never expire
    if expires_at.startswith("9999"):
        return {"active": True, "status": "active", "days_left": 9999, "plan": sub.get("plan", "lifetime")}

    try:
        expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        delta = expiry - now
        # Use total_seconds for accurate check — timedelta.days ignores hours
        is_expired = delta.total_seconds() <= 0
        days_left = max(0, delta.days)

        if is_expired:
            return {"active": False, "status": "expired", "days_left": 0,
                    "plan": sub.get("plan", "trial"), "expires_at": expires_at}

        return {"active": True, "status": "active", "days_left": days_left,
                "plan": sub.get("plan", "trial"), "expires_at": expires_at}
    except (ValueError, TypeError) as e:
        logger.error("Subscription check error: %s", e)
        return {"active": False, "status": "error", "days_left": 0, "plan": "none"}

# ============================================================
# Bot-Engine Process Manager
# ============================================================

def find_free_port() -> int:
    """Find a free port for a new bot-engine instance.
    Uses OS socket check to verify port is actually available."""
    used_ports = set()
    for proc_info in DB.get("bot_processes", {}).values():
        if proc_info.get("port"):
            used_ports.add(proc_info["port"])

    for port in range(PORT_START, PORT_END + 1):
        if port in used_ports:
            continue
        # Actually check if the port is free on the OS
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", port))
                return port
        except OSError:
            continue
    raise RuntimeError("No free ports available")

def _resolve_live_confirmed(target_testnet: bool, src: dict) -> bool:
    """Resolve live-trading confirmation flag consistently with testnet toggle."""
    if bool(target_testnet):
        return False
    if isinstance(src, dict) and "live_confirmed" in src and src["live_confirmed"] is not None:
        return bool(src["live_confirmed"])
    return True


def write_user_bot_config(user_id: str) -> str:
    """Write user's bot config to their own bot-engine config.json.

    IMPORTANT (settings-persistence fix): the bot-engine dashboard saves
    settings directly into its OWN config.json (via the SaaS proxy), so that
    file is the FRESHEST source of the user's settings. This function now
    PRESERVES that file across restarts instead of overwriting it from the
    SaaS DB (which only holds defaults). The SaaS DB is kept in sync via
    /api/config POST proxying (see _sync_engine_config_to_db).
    """
    user = DB["users"].get(user_id, {})
    config = user.get("bot_config", {})

    user_bot_dir = USER_INSTANCES_DIR / user_id
    user_bot_dir.mkdir(parents=True, exist_ok=True)
    config_path = user_bot_dir / "config.json"

    # Freshest engine settings (saved from the dashboard) — preserve these.
    existing = {}
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Could not read existing engine config for %s: %s", user_id, e)

    if existing and isinstance(existing, dict):
        bot_config = existing
        # Synchronize exchange and trading parameters from DB if updated.
        # COIN MEMORY RULE: the engine's own config file carries the user's
        # FRESHEST coin selection (every dashboard save writes it first and
        # mirrors it into the DB via the proxy). The DB copy is applied only
        # when the engine file has no coins yet, OR the DB switched to a
        # DIFFERENT exchange (then the DB coins are the only valid ones for
        # that exchange). Result: coins selected by the user survive
        # refreshes, engine respawns and redeploys until the user himself
        # selects different coins.
        _db_exchange = str(config.get("exchange") or "").lower()
        _file_exchange = str(bot_config.get("exchange") or "").lower()
        if _db_exchange:
            bot_config["exchange"] = _db_exchange
        if "testnet" in config:
            bot_config["testnet"] = bool(config["testnet"])
        bot_config["live_confirmed"] = _resolve_live_confirmed(bool(bot_config.get("testnet", True)), config)
        if "fresh_window" in config and config["fresh_window"] is not None:
            bot_config["fresh_window"] = max(2, min(8, int(config["fresh_window"]) or 2))
        if "min_ema_spread" in config and config["min_ema_spread"] is not None:
            bot_config["min_ema_spread"] = float(config["min_ema_spread"] or 0)
        if "reentry_cooldown_sec" in config and config["reentry_cooldown_sec"] is not None:
            bot_config["reentry_cooldown_sec"] = int(config["reentry_cooldown_sec"])
        if "max_concurrent_trades" in config and config["max_concurrent_trades"] is not None:
            bot_config["max_concurrent_trades"] = max(1, min(3, int(config["max_concurrent_trades"])))
        if config.get("tp_mode") == "both" and config.get("take_profit_pct") == 6 and config.get("stop_loss_pct") == 2:
            bot_config["stop_loss_pct"] = 0.2
        elif "stop_loss_pct" in config and config["stop_loss_pct"] is not None:
            try:
                bot_config["stop_loss_pct"] = max(0.05, min(50, float(config["stop_loss_pct"]) or 0.2))
            except (TypeError, ValueError):
                bot_config["stop_loss_pct"] = 0.2
        bot_config["take_profit_pct"] = 1.0
        bot_config["tp_mode"] = "fixed"
        _db_symbols = [str(s).upper().strip() for s in (config.get("symbols_list") or []) if str(s).strip()]
        _exchange_changed = bool(_db_exchange and _file_exchange and _db_exchange != _file_exchange)
        if _db_symbols and (not bot_config.get("symbols_list") or _exchange_changed):
            bot_config["symbols_list"] = _db_symbols
            bot_config["symbol"] = _db_symbols[0]

        # Ensure credentials from DB take precedence if engine has empty or stale keys.
        # decrypt_checked(): an unreadable ciphertext (ENCRYPTION_KEY changed after a
        # redeploy) must NEVER push an empty string into the engine config — that is
        # the exact mechanism that produced Binance -2014 on all symbols. Instead we
        # keep whatever the engine already has and flag api_key_invalid so the UI
        # tells the user to re-save the key.
        #
        # ---- PER-EXCHANGE CREDENTIAL MEMORY ---------------------------------
        # The engine file's api_keys slots are the freshest per-exchange
        # credentials; the DB's encrypted slots (api_keys_enc) fill in any
        # exchange the engine file does not know yet. On an exchange switch
        # between the two, the flat credentials are archived under the OLD
        # exchange and the NEW exchange's own saved set is loaded — never the
        # old behaviour of carrying one shared set across exchanges.
        _VALID_EX = ("binance", "weex", "primexbt")
        _creds_invalid = False
        _db_slots = config.get("api_keys_enc") if isinstance(config.get("api_keys_enc"), dict) else {}
        _file_slots = bot_config.get("api_keys") if isinstance(bot_config.get("api_keys"), dict) else {}
        _slots = {}
        for _ex in _VALID_EX:
            _s = dict(_file_slots.get(_ex) or {})
            _d = dict(_db_slots.get(_ex) or {})
            for _enc_f, _plain_f in (("api_key_enc", "api_key"),
                                     ("api_secret_enc", "api_secret"),
                                     ("api_passphrase_enc", "api_passphrase")):
                if _d.get(_enc_f):
                    ok, val = decrypt_checked(_d[_enc_f])
                    if ok:
                        _clean_v = str(val).strip().strip('"').strip("'")
                        if _clean_v:
                            _s[_plain_f] = _clean_v
                    else:
                        _creds_invalid = True
                        logger.error("Credential %s/%s unreadable with current ENCRYPTION_KEY "
                                     "(key changed after redeploy?). User must re-save it.", _ex, _enc_f)
            _slots[_ex] = _s

        if _exchange_changed and _file_exchange in _VALID_EX:
            # Exchange switch (DB vs engine file): archive the engine file's
            # flat credentials under the exchange they were used on, then
            # auto-load the NEW exchange's own saved credentials.
            if bot_config.get("api_key") or bot_config.get("api_secret") or bot_config.get("api_passphrase"):
                _old = dict(_slots.get(_file_exchange) or {})
                _old.setdefault("api_key", str(bot_config.get("api_key") or "").strip().strip('"').strip("'"))
                _old.setdefault("api_secret", str(bot_config.get("api_secret") or "").strip().strip('"').strip("'"))
                _old.setdefault("api_passphrase", str(bot_config.get("api_passphrase") or "").strip().strip('"').strip("'"))
                _slots[_file_exchange] = _old
            _act_new = _db_exchange if _db_exchange in _VALID_EX else "binance"
            _new = dict(_slots.get(_act_new) or {})
            bot_config["api_key"] = str(_new.get("api_key") or "")
            bot_config["api_secret"] = str(_new.get("api_secret") or "")
            bot_config["api_passphrase"] = str(_new.get("api_passphrase") or "")
        else:
            # Same exchange: DB credentials (including updates saved via Mobile
            # App or /api/bot/config) take precedence when readable; unreadable
            # ciphertexts (ENCRYPTION_KEY changed) NEVER overwrite engine keys.
            _act_ex = _db_exchange if _db_exchange in _VALID_EX else "binance"
            _act_slot = dict(_slots.get(_act_ex) or {})
            for _plain_key, _enc_key in (("api_key", "api_key_enc"),
                                         ("api_secret", "api_secret_enc"),
                                         ("api_passphrase", "api_passphrase_enc")):
                if _act_slot.get(_plain_key):
                    bot_config[_plain_key] = _act_slot[_plain_key]
                elif config.get(_enc_key):
                    ok, val = decrypt_checked(config.get(_enc_key, ""))
                    if ok:
                        _clean_v = val.strip().strip('"').strip("'")
                        if _clean_v:
                            bot_config[_plain_key] = _clean_v
                    else:
                        _creds_invalid = True
                        logger.error("Credential %s unreadable with current ENCRYPTION_KEY "
                                     "(key changed after redeploy?). User must re-save it.", _enc_key)
            if (bot_config.get("api_key") or bot_config.get("api_secret")) \
                    and not (_slots.get(_act_ex) or {}).get("api_key"):
                _slots[_act_ex] = {
                    "api_key": str(bot_config.get("api_key") or "").strip().strip('"').strip("'"),
                    "api_secret": str(bot_config.get("api_secret") or "").strip().strip('"').strip("'"),
                    "api_passphrase": str(bot_config.get("api_passphrase") or "").strip().strip('"').strip("'"),
                }
        bot_config["api_keys"] = _slots

        # Sanitize existing keys if present
        if bot_config.get("api_key"):
            bot_config["api_key"] = str(bot_config["api_key"]).strip().strip('"').strip("'")
        if bot_config.get("api_secret"):
            bot_config["api_secret"] = str(bot_config["api_secret"]).strip().strip('"').strip("'")
        if bot_config.get("api_passphrase"):
            bot_config["api_passphrase"] = str(bot_config["api_passphrase"]).strip().strip('"').strip("'")
        bot_config["api_key_invalid"] = _creds_invalid
    else:
        bot_config = {}
        _creds_invalid = False
        for _plain_key, _enc_key in (("api_key", "api_key_enc"),
                                     ("api_secret", "api_secret_enc"),
                                     ("api_passphrase", "api_passphrase_enc")):
            if config.get(_enc_key):
                ok, val = decrypt_checked(config.get(_enc_key, ""))
                if ok:
                    bot_config[_plain_key] = val.strip().strip('"').strip("'")
                else:
                    _creds_invalid = True
                    logger.error("Credential %s unreadable with current ENCRYPTION_KEY "
                                 "(key changed after redeploy?). User must re-save it.", _enc_key)
            else:
                bot_config[_plain_key] = ""

        bot_config.update({
            "exchange": config.get("exchange", "binance"),
            "testnet": config.get("testnet", True),
            "live_confirmed": _resolve_live_confirmed(bool(config.get("testnet", True)), config),
            "symbol": (config.get("symbols_list") or ["BTCUSDT"])[0],
            "symbols_list": (config.get("symbols_list") or ["BTCUSDT"]),
            "timeframe": config.get("timeframe", "5m"),
            "leverage": config.get("leverage", 10),
            "amount_mode": config.get("amount_mode", "fixed"),
            "amount": config.get("amount", 100),
            "amount_pct": config.get("amount_pct", 10),
            "stop_loss_pct": config.get("stop_loss_pct", 0.2),
            "take_profit_pct": 1.0,
            "tp_mode": "fixed",
            "mode": config.get("mode", "both"),
            "max_concurrent_trades": config.get("max_concurrent_trades", 3),
            "reentry_cooldown_sec": config.get("reentry_cooldown_sec", 180),
            "min_ema_spread": config.get("min_ema_spread", 0),
            "fresh_window": max(2, min(8, int(config.get("fresh_window", 2) or 2))),
            "auto_start": False,
            "telegram_enabled": config.get("telegram_enabled", False),
            "telegram_bot_token": decrypt(config.get("telegram_bot_token_enc", "")),
            "telegram_chat_id": config.get("telegram_chat_id", ""),
            "email_enabled": config.get("email_enabled", False),
            "email_smtp_server": "smtp.gmail.com",
            "email_smtp_port": 587,
            "email_sender": config.get("email_sender", ""),
            "email_password": decrypt(config.get("email_password_enc", "")),
            "email_receiver": config.get("email_receiver", ""),
            "whatsapp_enabled": config.get("whatsapp_enabled", False),
            "whatsapp_phone": config.get("whatsapp_phone", ""),
            "whatsapp_apikey": decrypt(config.get("whatsapp_apikey_enc", "")),
        })
        # ---- PER-EXCHANGE CREDENTIAL MEMORY (fresh instance) -----------------
        # Build the slots from the DB's encrypted per-exchange sets; the
        # legacy flat set (one shared credential group) seeds the ACTIVE
        # exchange's slot because it belonged to that exchange.
        _VALID_EX = ("binance", "weex", "primexbt")
        _db_slots = config.get("api_keys_enc") if isinstance(config.get("api_keys_enc"), dict) else {}
        _slots = {}
        for _ex in _VALID_EX:
            _d = dict(_db_slots.get(_ex) or {})
            _s = {"api_key": "", "api_secret": "", "api_passphrase": ""}
            for _enc_f, _plain_f in (("api_key_enc", "api_key"),
                                     ("api_secret_enc", "api_secret"),
                                     ("api_passphrase_enc", "api_passphrase")):
                if _d.get(_enc_f):
                    ok, val = decrypt_checked(_d[_enc_f])
                    if ok:
                        _s[_plain_f] = str(val).strip().strip('"').strip("'")
                    else:
                        _creds_invalid = True
                        logger.error("Credential %s/%s unreadable with current ENCRYPTION_KEY "
                                     "(key changed after redeploy?). User must re-save it.", _ex, _enc_f)
            _slots[_ex] = _s
        _act_ex = str(bot_config.get("exchange") or "binance").lower()
        if _act_ex not in _VALID_EX:
            _act_ex = "binance"
        if not (_slots.get(_act_ex) or {}).get("api_key") and bot_config.get("api_key"):
            _slots[_act_ex] = {
                "api_key": str(bot_config.get("api_key") or "").strip().strip('"').strip("'"),
                "api_secret": str(bot_config.get("api_secret") or "").strip().strip('"').strip("'"),
                "api_passphrase": str(bot_config.get("api_passphrase") or "").strip().strip('"').strip("'"),
            }
        bot_config["api_keys"] = _slots
        # Hydrate the flat fields from the ACTIVE exchange's own slot so the
        # engine never starts with another exchange's credentials.
        _a = dict(_slots.get(_act_ex) or {})
        bot_config["api_key"] = str(_a.get("api_key") or "")
        bot_config["api_secret"] = str(_a.get("api_secret") or "")
        bot_config["api_passphrase"] = str(_a.get("api_passphrase") or "")
        bot_config["api_key_invalid"] = _creds_invalid
    if "auto_start" not in bot_config:
        bot_config["auto_start"] = False

    # Copy bot-engine files (always sync on start to run latest code)
    for item in BOT_ENGINE_DIR.iterdir():
        if item.name in ('logs', '__pycache__', 'config.json', 'config.json.bak',
                       '.local_activation.dat', '.admin_password.txt',
                       'licenses.json', 'crash.log', 'user_configs', 'data', 'trade_history.json'):
            continue
        dest = user_bot_dir / item.name
        try:
            if item.is_dir():
                shutil.copytree(item, dest, dirs_exist_ok=True, ignore=shutil.ignore_patterns('__pycache__'))
            else:
                shutil.copy2(item, dest)
        except Exception as copy_err:
            logger.debug("Syncing file %s: %s", item.name, copy_err)

    # Atomic write — a crash mid-write must not truncate the user's only
    # copy of their engine settings (that is what reset them to defaults).
    tmp_cfg = config_path.with_suffix(".json.tmp")
    with open(tmp_cfg, "w", encoding="utf-8") as f:
        json.dump(bot_config, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_cfg, config_path)

    (user_bot_dir / "logs").mkdir(exist_ok=True)
    return str(config_path)


def _sync_engine_config_to_db(user: dict, data: dict):
    """Mirror a bot-engine /api/config POST payload into the SaaS DB.

    Called by the proxy when the dashboard inside the iframe saves settings,
    so the SaaS DB no longer goes stale (root cause of 'bot forgets settings',
    leverage resets, amount-mode resets, etc.).
    """
    config = user.setdefault("bot_config", {})
    prev_db_exchange = str(config.get("exchange") or "").lower()
    if "exchange" in data:
        ex = str(data["exchange"] or "binance").lower()
        # Keep the exchange EXACTLY as saved (binance, weex OR primexbt).
        # The old weex/else-binance mapping silently rewrote PrimeXBT
        # accounts to binance in the DB, which then "restored" the wrong
        # exchange whenever the engine's config.json was lost.
        config["exchange"] = ex if ex in ("binance", "weex", "primexbt") else "binance"
    if "testnet" in data:
        config["testnet"] = bool(data["testnet"])
    if "testnet" in data or "live_confirmed" in data:
        config["live_confirmed"] = _resolve_live_confirmed(bool(config.get("testnet", True)), data)
    new_db_exchange = str(config.get("exchange") or "binance").lower()

    # ---- PER-EXCHANGE CREDENTIAL SLOTS (encrypted at rest) -------------------
    # api_keys_enc mirrors the engine's per-exchange api_keys slots:
    #   {exchange: {"api_key_enc": ..., "api_secret_enc": ..., "api_passphrase_enc": ...}}
    # The legacy flat *_enc fields keep mirroring the ACTIVE exchange's
    # credentials so admin views and older mobile clients keep working.
    _VALID_EX = ("binance", "weex", "primexbt")
    _raw_slots = config.get("api_keys_enc") if isinstance(config.get("api_keys_enc"), dict) else {}
    slots = {k: dict(v or {}) for k, v in _raw_slots.items() if isinstance(v, dict)}

    def _enc_val(plain) -> str:
        try:
            s = str(plain or "").strip()
            return encrypt(s) if s else ""
        except Exception:
            return ""

    # Seed the ACTIVE exchange's slot from the legacy flat set ONCE (the
    # legacy set belonged to the exchange that was active when it was saved —
    # only safe while no exchange change happens in this same payload).
    if prev_db_exchange == new_db_exchange:
        _act = dict(slots.get(new_db_exchange) or {})
        if not _act.get("api_key_enc") and config.get("api_key_enc"):
            _act["api_key_enc"] = config["api_key_enc"]
            _act.setdefault("api_secret_enc", config.get("api_secret_enc") or "")
            _act.setdefault("api_passphrase_enc", config.get("api_passphrase_enc") or "")
            slots[new_db_exchange] = _act

    _stored_active = {"api_key": False, "api_secret": False, "api_passphrase": False}

    # 1) A payload may carry a full per-exchange slot map (mobile engine-sync
    #    sends api_keys). Only non-empty values are applied.
    payload_slots = data.get("api_keys") if isinstance(data.get("api_keys"), dict) else None
    if payload_slots:
        for pex, pslot in payload_slots.items():
            pex_l = str(pex or "").lower()
            if pex_l not in _VALID_EX or not isinstance(pslot, dict):
                continue
            tgt = dict(slots.get(pex_l) or {})
            for _pf in ("api_key", "api_secret", "api_passphrase"):
                _v = str(pslot.get(_pf) or "").strip()
                if _v:
                    tgt[f"{_pf}_enc"] = _enc_val(_v)
                    if pex_l == new_db_exchange:
                        _stored_active[_pf] = True
            slots[pex_l] = tgt

    # 2) Flat payload credentials (web dashboard saves / older mobile
    #    clients) are stored under the ACTIVE exchange's slot.
    for _pf in ("api_key", "api_secret", "api_passphrase"):
        _v = str(data.get(_pf) or "").strip()
        if _v:
            tgt = dict(slots.get(new_db_exchange) or {})
            tgt[f"{_pf}_enc"] = _enc_val(_v)
            slots[new_db_exchange] = tgt
            _stored_active[_pf] = True

    # 3) Live exchange switch: archive the legacy flat credentials under the
    #    OLD exchange (they belonged there), so nothing is ever lost.
    if new_db_exchange != prev_db_exchange and prev_db_exchange in _VALID_EX:
        old_slot = dict(slots.get(prev_db_exchange) or {})
        if config.get("api_key_enc") and not old_slot.get("api_key_enc"):
            old_slot["api_key_enc"] = config["api_key_enc"]
        if config.get("api_secret_enc") and not old_slot.get("api_secret_enc"):
            old_slot["api_secret_enc"] = config["api_secret_enc"]
        if config.get("api_passphrase_enc") and not old_slot.get("api_passphrase_enc"):
            old_slot["api_passphrase_enc"] = config["api_passphrase_enc"]
        slots[prev_db_exchange] = old_slot
    config["api_keys_enc"] = slots

    # Re-point the legacy flat fields to the ACTIVE exchange's slot:
    #  - on an exchange switch (pure switch re-points; possibly empty for the
    #    new exchange — the user then saves that exchange's keys once), or
    #  - when new credentials for the active exchange arrived in this payload.
    if new_db_exchange != prev_db_exchange or any(_stored_active.values()):
        act = dict(slots.get(new_db_exchange) or {})
        if new_db_exchange != prev_db_exchange and not any(_stored_active.values()):
            config["api_key_enc"] = act.get("api_key_enc") or ""
            config["api_secret_enc"] = act.get("api_secret_enc") or ""
            config["api_passphrase_enc"] = act.get("api_passphrase_enc") or ""
        else:
            if act.get("api_key_enc"):
                config["api_key_enc"] = act["api_key_enc"]
            if act.get("api_secret_enc"):
                config["api_secret_enc"] = act["api_secret_enc"]
            if act.get("api_passphrase_enc"):
                config["api_passphrase_enc"] = act["api_passphrase_enc"]
    if "symbols_list" in data and isinstance(data["symbols_list"], list):
        config["symbols_list"] = [str(s).upper().strip() for s in data["symbols_list"] if str(s).strip()]

    for k in ("timeframe", "amount_mode", "amount", "amount_pct",
              "stop_loss_pct", "tp_mode", "mode",
              "telegram_enabled", "telegram_chat_id",
              "email_enabled", "email_sender", "email_receiver",
              "whatsapp_enabled", "whatsapp_phone"):
        if k in data and data[k] is not None:
            config[k] = data[k]

    # Same clamping the bot-engine applies, so DB stays truthful.
    try:
        _ex_now = str(config.get("exchange") or "binance").lower()
        max_lev = 1000 if _ex_now == "primexbt" else (500 if _ex_now == "weex" else 125)
        config["leverage"] = max(1, min(max_lev, int(data.get("leverage") or config.get("leverage", 10))))
    except (TypeError, ValueError):
        pass
    try:
        if "amount" in data and data["amount"] is not None:
            config["amount"] = max(1, float(data["amount"]) or 100)
        if "amount_pct" in data and data["amount_pct"] is not None:
            config["amount_pct"] = max(1, min(100, float(data["amount_pct"]) or 10))
        if "stop_loss_pct" in data and data["stop_loss_pct"] is not None:
            sl = max(0.05, min(50, float(data["stop_loss_pct"]) or 0.2))
            config["stop_loss_pct"] = sl
        config["take_profit_pct"] = 1.0
        config["tp_mode"] = "fixed"
    except (TypeError, ValueError):
        pass
    try:
        if "max_concurrent_trades" in data and data["max_concurrent_trades"] is not None:
            config["max_concurrent_trades"] = max(1, min(3, int(data["max_concurrent_trades"])))
    except (TypeError, ValueError):
        pass
    try:
        if "reentry_cooldown_sec" in data and data["reentry_cooldown_sec"] is not None:
            config["reentry_cooldown_sec"] = max(0, min(7200, int(float(data["reentry_cooldown_sec"]))))
    except (TypeError, ValueError):
        pass
    try:
        if "min_ema_spread" in data and data["min_ema_spread"] is not None:
            config["min_ema_spread"] = max(0.0, min(5.0, float(data["min_ema_spread"]) or 0.0))
    except (TypeError, ValueError):
        pass
    try:
        if "fresh_window" in data and data["fresh_window"] is not None:
            config["fresh_window"] = max(2, min(8, int(data["fresh_window"]) or 2))
    except (TypeError, ValueError):
        pass
    save_db(DB)

# Track open file handles for cleanup
_bot_log_handles: dict[str, object] = {}

def _get_log_handle(user_id: str):
    """Get or create a log file handle for a user's bot process."""
    if user_id in _bot_log_handles:
        return _bot_log_handles[user_id]
    log_path = LOG_DIR / f"bot_{user_id}.log"
    handle = open(log_path, "w")
    _bot_log_handles[user_id] = handle
    return handle

def _close_log_handle(user_id: str):
    """Close and remove a log file handle."""
    handle = _bot_log_handles.pop(user_id, None)
    if handle:
        try:
            handle.close()
        except (OSError, ValueError):
            pass

def _wait_for_bot_ready(port: int, timeout: float = 12.0) -> bool:
    """Poll the bot-engine until it responds (or timeout)."""
    import urllib.request as _ur
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            req = _ur.Request(f"http://127.0.0.1:{port}/")
            with _ur.urlopen(req, timeout=1.5) as r:
                if r.status in (200, 302):
                    return True
        except urllib.error.HTTPError as he:
            if he.code in (200, 403, 302):
                return True
        except Exception:
            pass
        time.sleep(0.4)
    return False

def ensure_bot_engine_running(user_id: str) -> dict:
    """Ensure bot-engine process is running for this user.

    The critical section is serialized with _spawn_lock so concurrent
    requests (e.g. rapid duplicate page loads right after login) can never
    spawn two engines for the same user (port/PID race causing crashes).
    """
    with _spawn_lock:
        status = get_bot_status(user_id)
        if status["running"]:
            return {"success": True, "port": status["port"]}

        user = DB["users"].get(user_id)
        if not user:
            return {"success": False, "error": "User not found"}

        try:
            port = find_free_port()
        except RuntimeError as e:
            return {"success": False, "error": str(e)}

        try:
            write_user_bot_config(user_id)
        except Exception as e:
            return {"success": False, "error": f"Config write failed: {e}"}

        user_bot_dir = USER_INSTANCES_DIR / user_id
        try:
            log_handle = _get_log_handle(user_id)
            popen_kwargs = {
                "cwd": str(user_bot_dir),
                # Fix 12: pass BOT_ENGINE_TOKEN so bot engine can verify requests come from this SaaS
                "env": {**os.environ, "PORT": str(port), "HOST": "127.0.0.1",
                         "BOT_ENGINE_TOKEN": BOT_ENGINE_TOKEN},
                "stdout": log_handle,
                "stderr": subprocess.STDOUT,
            }
            if sys.platform == 'win32':
                popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | 0x00000008
            else:
                popen_kwargs["start_new_session"] = True

            proc = subprocess.Popen([sys.executable, "app.py"], **popen_kwargs)

            proc_data = {
                "pid": proc.pid,
                "port": port,
                "started_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "should_run": True,
            }
            DB.setdefault("bot_processes", {})[user_id] = proc_data
            shared = _load_bot_processes()
            shared[user_id] = proc_data
            _save_bot_processes(shared)
            save_db(DB)

            logger.info("Started bot-engine (detached) for user %s: PID=%s, port=%s", user_id, proc.pid, port)

            if not is_process_alive(proc.pid):
                log_file = LOG_DIR / f"bot_{user_id}.log"
                error_detail = ""
                try:
                    with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                        error_detail = f.read()[-500:]
                except (OSError, IOError):
                    pass
                logger.error("Bot-engine crashed immediately for %s. Log: %s", user_id, error_detail)
                DB.get("bot_processes", {}).pop(user_id, None)
                shared = _load_bot_processes()
                if user_id in shared:
                    shared.pop(user_id, None)
                    _save_bot_processes(shared)
                save_db(DB)
                return {"success": False, "error": f"Bot-engine crashed on startup. Log: {error_detail[:200]}"}

            # Wait until the engine actually answers HTTP, so the dashboard
            # iframe doesn't hit 'connection refused' right after spawn.
            if not _wait_for_bot_ready(port):
                logger.warning("Bot-engine started but not responding within 15s for %s", user_id)
                return {"success": True, "port": port, "pid": proc.pid, "starting": True}

            return {"success": True, "port": port, "pid": proc.pid}
        except Exception as e:
            logger.error("Failed to start bot-engine for %s: %s", user_id, e)
            return {"success": False, "error": str(e)}

def start_user_bot(user_id: str) -> dict:
    """Start a user's bot-engine instance."""
    with _spawn_lock:
        user = DB["users"].get(user_id)
        if not user:
            return {"success": False, "error": "User not found"}

        existing = DB.get("bot_processes", {}).get(user_id)
        if existing and existing.get("pid"):
            try:
                os.kill(existing["pid"], 0)
                return {"success": True, "port": existing["port"], "message": "Bot already running"}
            except (ProcessLookupError, PermissionError, OSError):
                pass

        config = user.get("bot_config", {})
        if not config.get("api_key_enc"):
            return {"success": False, "error": "API key not set. Please save settings first."}
        if config.get("exchange") == "weex" and not config.get("api_passphrase_enc"):
            return {"success": False, "error": "WEEX passphrase required"}
        if not config.get("symbols_list"):
            return {"success": False, "error": "Please add at least one coin"}

        try:
            port = find_free_port()
        except RuntimeError as e:
            return {"success": False, "error": str(e)}

        try:
            write_user_bot_config(user_id)
        except Exception as e:
            return {"success": False, "error": f"Config write failed: {e}"}

        user_bot_dir = USER_INSTANCES_DIR / user_id
        try:
            log_handle = _get_log_handle(user_id)
            popen_kwargs = {
                "cwd": str(user_bot_dir),
                # Fix 12: pass BOT_ENGINE_TOKEN so bot engine can verify requests come from this SaaS
                "env": {**os.environ, "PORT": str(port), "HOST": "127.0.0.1",
                         "BOT_ENGINE_TOKEN": BOT_ENGINE_TOKEN},
                "stdout": log_handle,
                "stderr": subprocess.STDOUT,
            }
            if sys.platform == 'win32':
                popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | 0x00000008
            else:
                popen_kwargs["start_new_session"] = True

            proc = subprocess.Popen([sys.executable, "app.py"], **popen_kwargs)

            proc_data = {
                "pid": proc.pid,
                "port": port,
                "started_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "should_run": True,
            }
            DB.setdefault("bot_processes", {})[user_id] = proc_data
            shared = _load_bot_processes()
            shared[user_id] = proc_data
            _save_bot_processes(shared)
            save_db(DB)
            logger.info("Started bot-engine (detached) for user %s: PID=%s, port=%s", user_id, proc.pid, port)

            if not is_process_alive(proc.pid):
                log_file = LOG_DIR / f"bot_{user_id}.log"
                error_detail = ""
                try:
                    with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                        error_detail = f.read()[-300:]
                except (OSError, IOError):
                    pass
                logger.error("Bot-engine crashed on start for %s. Log: %s", user_id, error_detail)
                DB.get("bot_processes", {}).pop(user_id, None)
                shared = _load_bot_processes()
                shared.pop(user_id, None)
                _save_bot_processes(shared)
                save_db(DB)
                return {"success": False, "error": f"Bot-engine crashed on startup. Log: {error_detail[:200]}"}

            _wait_for_bot_ready(port)
            return {"success": True, "port": port, "pid": proc.pid}
        except Exception as e:
            logger.error("Failed to start bot for %s: %s", user_id, e)
            return {"success": False, "error": str(e)}

def stop_user_bot(user_id: str) -> dict:
    """Stop a user's bot-engine instance."""
    proc_info = DB.get("bot_processes", {}).get(user_id)
    if not proc_info:
        shared = _load_bot_processes()
        proc_info = shared.get(user_id)
    if not proc_info or not proc_info.get("pid"):
        return {"success": True, "message": "Bot not running"}

    pid = proc_info["pid"]
    kill_process(pid)
    _close_log_handle(user_id)

    proc_info["should_run"] = False
    DB.get("bot_processes", {}).pop(user_id, None)
    shared = _load_bot_processes()
    shared.pop(user_id, None)
    _save_bot_processes(shared)
    save_db(DB)
    logger.info("Stopped bot-engine for user %s", user_id)
    return {"success": True, "message": "Bot stopped"}

def is_process_alive(pid: int) -> bool:
    """Check if a process is alive (cross-platform)."""
    try:
        if sys.platform == 'win32':
            import ctypes
            kernel32 = ctypes.windll.kernel32
            SYNCHRONIZE = 0x00100000
            handle = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
            if handle:
                kernel32.CloseHandle(handle)
                return True
            return False
        else:
            os.kill(pid, 0)
            return True
    except (ProcessLookupError, PermissionError, OSError):
        return False

def kill_process(pid: int):
    """Kill a process (cross-platform)."""
    try:
        if sys.platform == 'win32':
            subprocess.run(['taskkill', '/F', '/T', '/PID', str(pid)],
                          capture_output=True, timeout=5)
        else:
            os.kill(pid, signal.SIGTERM)
            time.sleep(1)
            try:
                os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, OSError):
                pass
    except (ProcessLookupError, PermissionError, OSError, subprocess.TimeoutExpired):
        pass

def get_bot_status(user_id: str) -> dict:
    """Get bot status for a user."""
    proc_info = DB.get("bot_processes", {}).get(user_id)
    if not proc_info or not proc_info.get("pid"):
        shared = _load_bot_processes()
        proc_info = shared.get(user_id)
        if proc_info:
            DB.setdefault("bot_processes", {})[user_id] = proc_info

    if not proc_info or not proc_info.get("pid"):
        return {"running": False}

    if is_process_alive(proc_info["pid"]):
        return {
            "running": True,
            "port": proc_info["port"],
            "pid": proc_info["pid"],
            "started_at": proc_info.get("started_at"),
        }
    else:
        DB.get("bot_processes", {}).pop(user_id, None)
        shared = _load_bot_processes()
        if user_id in shared:
            shared.pop(user_id, None)
            _save_bot_processes(shared)
        save_db(DB)
        return {"running": False}

def proxy_to_bot(user_id: str, method: str, path: str, body=None) -> dict:
    """Proxy a request to user's bot-engine instance."""
    status = get_bot_status(user_id)
    if not status["running"] or not status.get("port"):
        # Auto-start bot-engine instance if user has an active subscription
        user = DB.get("users", {}).get(user_id, {})
        sub = check_subscription(user)
        if sub.get("active"):
            try:
                start_res = start_user_bot(user_id)
                if start_res.get("success"):
                    status = get_bot_status(user_id)
            except Exception as _se:
                logger.warning("Auto-start bot for user %s failed: %s", user_id, _se)
        if not status["running"] or not status.get("port"):
            return {"success": False, "error": "Bot is not running"}

    try:
        url = f"http://127.0.0.1:{status['port']}{path}"
        data = json.dumps(body).encode("utf-8") if body and method != "GET" else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        # Engine rejects un-tokened /api/* calls — always identify ourselves
        req.add_header("X-Bot-Token", BOT_ENGINE_TOKEN)
        with urllib.request.urlopen(req, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {"success": False, "error": f"HTTP {e.code}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

# ============================================================
# Routes - Pages
# ============================================================

@app.route("/")
@app.route("/home")
def home():
    if request.args.get('logout') == '1':
        session.clear()

    ref_code = request.args.get('ref', '').strip().upper()
    if ref_code:
        session['referral_code'] = ref_code

    user = current_user() if is_logged_in() else None
    sub = check_subscription(user) if user else None
    active_ref = ref_code or session.get('referral_code', '')

    return render_template(
        "saas_home.html",
        user=user,
        sub=sub,
        packages=PACKAGES,
        ref_code=active_ref,
        contact_email="Weexionic.duckdns@gmail.com",
        contact_phone="+92-326-2334-043",
        wallet_address=WALLET_ADDRESS,
        wallet_network=WALLET_NETWORK
    )

@app.route("/login")
def login_page():
    if request.args.get('logout') == '1':
        session.clear()
        return render_template("saas_login.html")

    ref_code = request.args.get('ref', '').strip().upper()
    if ref_code:
        session['referral_code'] = ref_code

    if not is_logged_in():
        active_ref = ref_code or session.get('referral_code', '')
        return render_template("saas_login.html", ref_code=active_ref)

    user = current_user()
    if not user:
        session.clear()
        return render_template("saas_login.html")

    if user.get("role") == "admin":
        return redirect("/bot/")

    sub = check_subscription(user)
    if not sub["active"]:
        return render_template("saas_license.html", user=user, sub=sub)

    return redirect("/bot/")

@app.route("/license")
def license_page():
    if not is_logged_in():
        return redirect("/login")
    user = current_user()
    if not user:
        session.clear()
        return redirect("/login")
    sub = check_subscription(user)
    return render_template("saas_license.html", user=user, sub=sub)

@app.route(ADMIN_SECRET_PATH)
@app.route("/admin")
def admin_panel():
    # If accessed via plain /admin and a secret path is configured:
    # return 404 to unauthenticated scanners to hide admin presence!
    if request.path == "/admin" and ADMIN_SECRET_PATH != "/admin":
        if not is_admin():
            return "Not Found", 404

    if is_admin():
        return render_template("saas_admin.html", admin_login_required=False)
    return render_template("saas_admin.html", admin_login_required=True)

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
    return render_template("saas_legal.html", active_tab=default_tab)

@app.route("/api/debug/logs")
def list_logs():
    if not is_admin():
        return "Unauthorized", 403
    files = [f.name for f in LOG_DIR.iterdir() if f.is_file()]
    return jsonify(files)

@app.route("/api/debug/logs/saas")
def get_saas_logs():
    if not is_admin():
        return "Unauthorized", 403
    log_file = LOG_DIR / "saas.log"
    if not log_file.exists():
        return "Log file not found", 404
    with open(log_file, "r", encoding="utf-8", errors="replace") as f:
        return Response(f.read(), mimetype="text/plain")

@app.route("/api/debug/logs/<user_id>")
def get_user_bot_logs(user_id):
    if not is_admin():
        return "Unauthorized", 403
    log_file = LOG_DIR / f"bot_{user_id}.log"
    if not log_file.exists():
        return "Log file not found", 404
    with open(log_file, "r", encoding="utf-8", errors="replace") as f:
        return Response(f.read(), mimetype="text/plain")

@app.route("/favicon.ico")
def favicon():
    png_bytes = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000d49444154789c63000100000005000100"
        "0d0a2db40000000049454e44ae426082"
    )
    return Response(png_bytes, mimetype="image/png")

# ============================================================
# Auth API
# ============================================================

@app.route("/api/auth/signup", methods=["POST"])
def api_signup():
    # Rate limit signup per real client IP
    client_ip = _client_ip()
    if not _check_rate_limit(f"signup:{client_ip}", max_requests=5, window_seconds=600):
        return jsonify({"success": False, "error": "Too many signup attempts. Please wait 10 minutes."}), 429

    data = request.get_json(force=True, silent=True) or {}
    email = _norm_email(data.get("email"))
    password = data.get("password") or ""
    name = (data.get("name") or "").strip()

    if not email or not password:
        return jsonify({"success": False, "error": "Email and password are required"})
    # Fix 8: Minimum password length increased to 8
    if len(password) < 8:
        return jsonify({"success": False, "error": "Password must be at least 8 characters"})
    if "@" not in email or "." not in email:
        return jsonify({"success": False, "error": "Please enter a valid email address"})

    if _find_users_by_email(email):
        return jsonify({"success": False, "error": "This email is already registered"})

    role = "user"
    user_id = str(uuid.uuid4())
    referral_code = user_id[:8].upper()
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    # Handle referral
    ref_by_code = (data.get("referral_code") or session.get("referral_code") or "").strip().upper()
    referred_by = None
    if ref_by_code:
        for u in DB["users"].values():
            if u.get("referral_code") == ref_by_code:
                referred_by = u["id"]
                break

    # New users start with NO subscription - they need to activate a license
    # CRITICAL: expires_at must be None (not now!) so check_subscription
    # returns status='none' instead of 'expired' (days_left would be 0 if set to now)
    subscription = {
        "plan": "none",
        "status": "inactive",
        "started_at": now,
        "expires_at": None,
    }

    user = {
        "id": user_id,
        "email": email,
        "name": name or email.split("@")[0],
        "password_hash": hash_password(password),
        "role": role,
        "banned": False,
        "created_at": now,
        "subscription": subscription,
        "license_key": None,
        "referral_code": referral_code,
        "referred_by": referred_by,
        "referral_earnings": 0.0,
        "referral_history": [],
        "bot_config": _default_bot_config(),
    }
    DB["users"][user_id] = user
    save_db(DB)

    session.pop("admin_authenticated", None)
    session["user_id"] = user_id
    session.permanent = True

    logger.info("New user signup: %s (role=%s)", email, role)

    return jsonify({
        "success": True,
        "user": {"id": user_id, "email": email, "name": user["name"], "role": role},
        "subscription": user["subscription"],
        "message": "Account created! Please activate your license key to get started.",
    })


@app.route("/api/auth/login", methods=["POST"])
def api_login():
    data = request.get_json(force=True, silent=True) or {}
    email = _norm_email(data.get("email"))
    password = data.get("password") or ""

    client_ip = _client_ip()
    if (
        not _check_rate_limit(f"login:{client_ip}:{email or '_'}", max_requests=8, window_seconds=300)
        or not _check_rate_limit(f"login_ip:{client_ip}", max_requests=30, window_seconds=300)
    ):
        return jsonify({"success": False, "error": "Too many login attempts. Please wait 5 minutes."}), 429

    if not email or not password:
        return jsonify({"success": False, "error": "Email and password are required"})

    candidates = _find_users_by_email(email)
    user = None
    for cand in candidates:
        if verify_password(password, cand.get("password_hash", "")):
            user = cand
            break

    if not user:
        return jsonify({"success": False, "error": "Invalid email or password"})

    if user.get("banned"):
        return jsonify({"success": False, "error": "Account suspended. Please contact admin."})

    if user.get("role") == "admin":
        sub = user.get("subscription", {})
        if sub.get("status") != "active":
            now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            user["subscription"] = {
                "plan": "lifetime", "status": "active",
                "started_at": now, "expires_at": "9999-12-31T23:59:59Z",
            }
            save_db(DB)

    canonical_id = _dedupe_users_by_email(user["id"])
    user = DB["users"].get(canonical_id, user)

    session["user_id"] = user["id"]
    session.permanent = True

    logger.info("User login: %s (id=%s, role=%s)", email, user["id"], user.get("role"))

    return jsonify({
        "success": True,
        "user": {"id": user["id"], "email": user["email"], "name": user["name"], "role": user["role"]} if user.get('role') == 'admin' else {"id": user["id"], "email": user["email"], "name": user["name"]},
        "subscription": user.get("subscription", {}),
    })

@app.route("/api/auth/logout", methods=["POST"])
def api_logout():
    user = current_user()
    if user:
        stop_user_bot(user["id"])
    session.pop("user_id", None)
    session.pop("admin_authenticated", None)
    return jsonify({"success": True})


@app.route("/reset-password", methods=["GET"])
def reset_password_page():
    raw_token = (request.args.get("token") or "").strip()
    found = _get_valid_reset_record(raw_token)
    if found:
        _, rec = found
        return render_template(
            "saas_login.html",
            reset_token=raw_token,
            reset_valid=True,
            reset_email=rec.get("email", ""),
            reset_error="",
        )
    return render_template(
        "saas_login.html",
        reset_token=raw_token or "invalid",
        reset_valid=False,
        reset_email="",
        reset_error="Password reset link invalid ya expire ho chuka hai. Naya link request karein.",
    )


@app.route("/api/auth/forgot-password", methods=["POST"])
def api_forgot_password():
    data = request.get_json(force=True, silent=True) or {}
    payload, code = _create_and_send_password_reset(data.get("email") or "")
    return jsonify(payload), code


@app.route("/api/auth/reset-password", methods=["POST"])
def api_reset_password():
    client_ip = _client_ip()
    if not _check_rate_limit(f"reset_pw:{client_ip}", max_requests=10, window_seconds=300):
        return jsonify({"success": False, "error": "Too many password reset attempts. Please wait 5 minutes."}), 429

    data = request.get_json(force=True, silent=True) or {}
    raw_token = (data.get("token") or "").strip()
    password = data.get("password") or ""

    if len(password) < 8:
        return jsonify({"success": False, "error": "Password must be at least 8 characters"}), 400

    found = _get_valid_reset_record(raw_token)
    if not found:
        return jsonify({
            "success": False,
            "error": "Password reset link invalid ya expire ho chuka hai. Naya link request karein.",
        }), 400

    t_hash, rec = found
    uid = rec.get("user_id")
    email = _norm_email(rec.get("email"))
    user = DB.get("users", {}).get(uid)
    if not user and email:
        matches = _find_users_by_email(email)
        if matches:
            user = max(matches, key=lambda item: _user_richness_score(item))

    if not user:
        resets = _prune_expired_reset_tokens(DB)
        resets.pop(t_hash, None)
        save_db(DB)
        return jsonify({"success": False, "error": "User account not found"}), 404

    if user.get("banned"):
        return jsonify({"success": False, "error": "Account suspended. Please contact admin."}), 403

    canonical_id = _dedupe_users_by_email(user["id"], save=False)
    user = DB["users"].get(canonical_id, user)
    user["password_hash"] = hash_password(password)
    user["password_updated_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    resets = _prune_expired_reset_tokens(DB)
    user_email_norm = _norm_email(user.get("email"))
    for k, v in list(resets.items()):
        if k == t_hash or (
            isinstance(v, dict)
            and (v.get("user_id") == user["id"] or _norm_email(v.get("email")) == user_email_norm)
        ):
            resets.pop(k, None)

    save_db(DB)

    session.pop("admin_authenticated", None)
    session["user_id"] = user["id"]
    session.permanent = True

    logger.info("Password reset completed and saved for %s (id=%s)", user.get("email"), user["id"])
    return jsonify({
        "success": True,
        "email": user.get("email"),
        "message": "New password save ho gaya hai! Ab aap is password se login kar sakte hain.",
    })

@app.route("/api/auth/me", methods=["GET"])
def api_me():
    if not is_logged_in():
        return jsonify({"success": False, "error": "Not logged in"})

    user = current_user()
    if not user:
        return jsonify({"success": False, "error": "User not found"})

    user_is_admin = user.get("role") == "admin"
    sub_status = check_subscription(user)
    bot_status = get_bot_status(user["id"])

    resp_data = {
        "success": True,
        "user": {
            "id": user["id"],
            "email": user["email"],
            "name": user["name"],
        },
        "subscription": sub_status,
        "license_key": user.get("license_key"),
        "referral_code": user.get("referral_code", ""),
        "referred_by": user.get("referred_by"),
        "bot_config": {
            **user.get("bot_config", {}),
            "api_key_enc": None,
            "api_secret_enc": None,
            "api_passphrase_enc": None,
            "has_api_key": bool(user.get("bot_config", {}).get("api_key_enc")),
            "has_passphrase": bool(user.get("bot_config", {}).get("api_passphrase_enc")),
        },
        "bot_running": bot_status.get("running", False),
        "bot_port": bot_status.get("port"),
    }
    # Only expose role to admin users
    if user_is_admin:
        resp_data["user"]["role"] = "admin"

    return jsonify(resp_data)

# ============================================================
# Referral API
# ============================================================

@app.route("/api/user/referral", methods=["GET"])
def api_user_referral():
    """Return current user's referral link and stats."""
    if not is_logged_in():
        return jsonify({"success": False, "error": "Not logged in"}), 401

    user = current_user()
    if not user:
        return jsonify({"success": False, "error": "User not found"}), 404

    ref_code = user.get("referral_code", "")
    if not ref_code:
        ref_code = user["id"][:8].upper()
        user["referral_code"] = ref_code
        save_db(DB)

    # Build referral link from the current request's host
    host = request.headers.get("X-Forwarded-Host") or request.host
    proto = request.headers.get("X-Forwarded-Proto", "https" if request.is_secure else "http")
    referral_link = f"{proto}://{host}/?ref={ref_code}"

    # Count how many users this person referred
    referral_count = sum(
        1 for u in DB["users"].values()
        if u.get("referred_by") == user["id"]
    )

    # Get referred users list with detailed tree info
    referred_users = []
    referral_history = user.get("referral_history", [])
    for u in DB["users"].values():
        if u.get("referred_by") == user["id"]:
            _raw_email = u.get("email", "")
            _at_pos = _raw_email.find("@")
            if _at_pos > 2:
                _masked = _raw_email[:2] + "***" + _raw_email[_at_pos:]
            else:
                _masked = "***@***"

            u_sub = u.get("subscription", {})
            is_active = (u_sub.get("status") == "active") or bool(u.get("license_key"))
            
            # Check bonus earned from this specific user
            earned_from_user = sum(
                float(h.get("bonus_amount", 0.0))
                for h in referral_history
                if h.get("buyer_id") == u["id"] or h.get("buyer_email") == u.get("email")
            )

            referred_users.append({
                "id": u["id"][:8],
                "email": _masked,
                "name": u.get("name", "") or _masked.split("@")[0],
                "created_at": u.get("created_at", ""),
                "has_license": is_active,
                "plan": u_sub.get("plan", "none") if is_active else "none",
                "bonus_earned": earned_from_user,
            })

    total_earnings = float(user.get("referral_earnings", 0.0) or 0.0)
    payout_requests = user.get("payout_requests", [])
    total_withdrawn = sum(float(p.get("amount", 0)) for p in payout_requests if p.get("status") == "paid")
    pending_payout = sum(float(p.get("amount", 0)) for p in payout_requests if p.get("status") == "pending")
    available_balance = max(0.0, round(total_earnings - total_withdrawn - pending_payout, 2))

    return jsonify({
        "success": True,
        "user_name": user.get("name", "") or (user.get("email", "").split("@")[0] if user.get("email") else "User"),
        "user_email": user.get("email", ""),
        "license_key": user.get("license_key", ""),
        "subscription": user.get("subscription", {}),
        "referral_code": ref_code,
        "referral_link": referral_link,
        "referral_count": referral_count,
        "referral_earnings": total_earnings,
        "available_balance": available_balance,
        "total_withdrawn": total_withdrawn,
        "pending_payout": pending_payout,
        "payout_wallet": user.get("payout_wallet", ""),
        "payout_requests": payout_requests,
        "referral_history": referral_history,
        "referred_users": referred_users,
        "bonus_rates": {
            "monthly": PACKAGES.get("monthly", {}).get("referral_bonus", 2),
            "yearly": PACKAGES.get("yearly", {}).get("referral_bonus", 10),
            "lifetime": PACKAGES.get("lifetime", {}).get("referral_bonus", 50),
        },
    })


@app.route('/bot/api/user/referral', methods=['GET'])
def bot_referral_alias():
    return api_user_referral()

@app.route('/bot/api/user/payout-wallet', methods=['POST'])
def bot_payout_wallet_alias():
    return api_user_save_payout_wallet()

@app.route('/bot/api/user/request-payout', methods=['POST'])
def bot_request_payout_alias():
    return api_user_request_payout()


@app.route("/api/user/payout-wallet", methods=["POST"])
def api_user_save_payout_wallet():
    """Save or update user's USDT payout wallet address."""
    if not is_logged_in():
        return jsonify({"success": False, "error": "Not logged in"}), 401

    user = current_user()
    if not user:
        return jsonify({"success": False, "error": "User not found"}), 404

    data = request.get_json(force=True)
    wallet = (data.get("wallet_address") or "").strip()
    if not wallet or len(wallet) < 10:
        return jsonify({"success": False, "error": "Please enter a valid USDT wallet address (TRC20 or BEP20)"})

    user["payout_wallet"] = wallet
    save_db(DB)
    logger.info("User %s updated payout wallet: %s", user["email"], wallet)
    return jsonify({"success": True, "message": "Payout wallet saved successfully!", "wallet": wallet})


@app.route("/api/user/request-payout", methods=["POST"])
def api_user_request_payout():
    """User submits a withdrawal request for their referral commission."""
    if not is_logged_in():
        return jsonify({"success": False, "error": "Not logged in"}), 401

    user = current_user()
    if not user:
        return jsonify({"success": False, "error": "User not found"}), 404

    data = request.get_json(force=True)
    wallet = (data.get("wallet_address") or user.get("payout_wallet") or "").strip()
    if not wallet:
        return jsonify({"success": False, "error": "Please provide a USDT payout wallet address"})

    total_earnings = float(user.get("referral_earnings", 0.0) or 0.0)
    payout_requests = user.setdefault("payout_requests", [])
    # Atomic balance check + append: two concurrent requests must never both see
    # the same available balance (previously a race allowed 2x withdrawals)
    with _payout_lock:
        total_withdrawn = sum(float(p.get("amount", 0)) for p in payout_requests if p.get("status") == "paid")
        pending_payout = sum(float(p.get("amount", 0)) for p in payout_requests if p.get("status") == "pending")
        available_balance = max(0.0, round(total_earnings - total_withdrawn - pending_payout, 2))

        if available_balance <= 0:
            return jsonify({"success": False, "error": "No available referral commission to withdraw"})

        req_id = "PAY-" + secrets.token_hex(4).upper()
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        payout_entry = {
            "id": req_id,
            "amount": available_balance,
            "currency": "USDT",
            "wallet_address": wallet,
            "status": "pending",
            "created_at": now,
            "paid_at": None,
            "tx_hash": "",
        }
        user["payout_wallet"] = wallet
        payout_requests.append(payout_entry)
        save_db(DB)

    logger.info("User %s requested payout %s for $%s USDT to %s",
                user["email"], req_id, available_balance, wallet)
    return jsonify({
        "success": True,
        "message": f"Payout request for ${available_balance} USDT submitted! Your funds will be transferred to your wallet within 1 to 3 business days.",
        "payout": payout_entry,
    })

# ============================================================
# License API
# ============================================================

@app.route("/api/license/activate", methods=["POST"])
def api_license_activate():
    if not is_logged_in():
        return jsonify({"success": False, "error": "Not logged in"}), 401

    user = current_user()
    if not user:
        return jsonify({"success": False, "error": "User not found"}), 404

    data = request.get_json(force=True)
    key = (data.get("key") or "").strip().upper()

    if not key:
        return jsonify({"success": False, "error": "Please enter a license key"})

    lic = DB.get("licenses", {}).get(key)
    if not lic:
        return jsonify({"success": False, "error": "Invalid license key. Please check and try again."})

    if lic.get("revoked"):
        return jsonify({"success": False, "error": "This license has been revoked. Please contact admin."})

    if lic.get("used_by") and lic["used_by"] != user["id"]:
        prev = DB["users"].get(lic["used_by"], {})
        same_email = (prev.get("email") or "").lower() == (user.get("email") or "").lower()
        same_owner = (user.get("license_key") or "").upper() == key
        if not (same_email or same_owner):
            return jsonify({"success": False, "error": "This license key is already linked to another account. If it is your key, log in with the same email/Google account you used before — one key works on one account only."})
        # Same person (duplicate account record or owner re-activating):
        # allow a graceful rebind to the current account.
        logger.info("License %s rebinding to same account id=%s (email=%s)", key, user["id"], user.get("email"))

    try:
        expiry = datetime.fromisoformat(lic["expires_at"].replace("Z", "+00:00"))
        if datetime.now(timezone.utc) > expiry:
            return jsonify({"success": False, "error": "This license has expired. Please contact admin for a new license."})
    except (ValueError, TypeError):
        return jsonify({"success": False, "error": "License expiry check failed"})

    old_key = user.get("license_key")
    if old_key and old_key != key:
        old_lic = DB.get("licenses", {}).get(old_key)
        if old_lic:
            old_lic["active"] = False
            logger.info("User %s replaced old license %s with new %s", user['email'], old_key, key)

    lic["used_by"] = user["id"]
    lic["activated_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    lic["active"] = True

    now = datetime.now(timezone.utc)
    user["subscription"] = {
        "plan": lic.get("plan", "basic"),
        "status": "active",
        "started_at": now.isoformat().replace("+00:00", "Z"),
        "expires_at": lic["expires_at"],
    }
    user["license_key"] = key

    save_db(DB)
    logger.info("License %s activated for user %s", key, user['email'])

    days_left = (expiry - now).days
    return jsonify({
        "success": True,
        "message": f"License activated! {days_left} days remaining.",
        "subscription": user["subscription"],
    })

# ============================================================
# Bot Config API
# ============================================================

@app.route("/api/bot/config", methods=["GET", "POST"])
def api_bot_config():
    if not is_logged_in():
        return jsonify({"success": False, "error": "Not logged in"}), 401

    user = current_user()
    if not user:
        return jsonify({"success": False, "error": "User not found"}), 404

    if request.method == "GET":
        config = user.get("bot_config", {})
        return jsonify({
            "success": True,
            "config": {
                **config,
                "api_key_enc": None,
                "api_secret_enc": None,
                "api_passphrase_enc": None,
                "has_api_key": bool(config.get("api_key_enc")),
                "has_passphrase": bool(config.get("api_passphrase_enc")),
            }
        })

    data = request.get_json(force=True)
    config = user.setdefault("bot_config", {})

    if "exchange" in data:
        ex = str(data["exchange"] or "binance").lower()
        # Keep the exchange EXACTLY as saved (binance, weex OR primexbt).
        # The old weex/else-binance mapping silently rewrote PrimeXBT
        # accounts to binance in the DB, which then "restored" the wrong
        # exchange whenever the engine's config.json was lost.
        config["exchange"] = ex if ex in ("binance", "weex", "primexbt") else "binance"
    if "testnet" in data:
        config["testnet"] = bool(data["testnet"])
    if "testnet" in data or "live_confirmed" in data:
        config["live_confirmed"] = _resolve_live_confirmed(bool(config.get("testnet", True)), data)
    if data.get("api_key") and str(data["api_key"]).strip():
        config["api_key_enc"] = encrypt(str(data["api_key"]).strip())
    if data.get("api_secret") and str(data["api_secret"]).strip():
        config["api_secret_enc"] = encrypt(str(data["api_secret"]).strip())
    if "api_passphrase" in data:
        if data["api_passphrase"] and str(data["api_passphrase"]).strip():
            config["api_passphrase_enc"] = encrypt(str(data["api_passphrase"]).strip())
        elif data["api_passphrase"] == "":
            config["api_passphrase_enc"] = ""
    if "symbols_list" in data:
        symbols = data["symbols_list"] if isinstance(data["symbols_list"], list) else []
        config["symbols_list"] = [str(s).upper().strip() for s in symbols if str(s).strip()]
    if "timeframe" in data:
        config["timeframe"] = data["timeframe"]
    if "leverage" in data:
        _ex_now = str(config.get("exchange") or "binance").lower()
        max_lev = 1000 if _ex_now == "primexbt" else (500 if _ex_now == "weex" else 125)
        config["leverage"] = max(1, min(max_lev, int(data["leverage"]) or 10))
    if "amount_mode" in data:
        config["amount_mode"] = "percent" if data["amount_mode"] == "percent" else "fixed"
    if "amount" in data:
        config["amount"] = max(1, float(data["amount"]) or 100)
    if "amount_pct" in data:
        config["amount_pct"] = max(1, min(100, float(data["amount_pct"]) or 10))
    if "stop_loss_pct" in data:
        sl = max(0.05, min(50, float(data["stop_loss_pct"]) or 0.2))
        config["stop_loss_pct"] = sl
    config["take_profit_pct"] = 1.0
    config["tp_mode"] = "fixed"
    if "mode" in data:
        config["mode"] = data["mode"] if data["mode"] in ("long", "short", "both") else "both"
    if "max_concurrent_trades" in data:
        try:
            mct = int(data["max_concurrent_trades"])
            config["max_concurrent_trades"] = max(1, min(3, mct))
        except (ValueError, TypeError):
            config["max_concurrent_trades"] = 3
    if "reentry_cooldown_sec" in data:
        try:
            config["reentry_cooldown_sec"] = max(0, min(7200, int(float(data["reentry_cooldown_sec"]))))
        except (ValueError, TypeError):
            config["reentry_cooldown_sec"] = 180
    if "min_ema_spread" in data:
        try:
            config["min_ema_spread"] = max(0.0, min(5.0, float(data["min_ema_spread"]) or 0.0))
        except (ValueError, TypeError):
            config["min_ema_spread"] = 0.0
    if "fresh_window" in data:
        try:
            config["fresh_window"] = max(2, min(8, int(data["fresh_window"]) or 2))
        except (ValueError, TypeError):
            config["fresh_window"] = 2

    save_db(DB)
    return jsonify({
        "success": True,
        "config": {
            **config,
            "api_key_enc": None,
            "api_secret_enc": None,
            "api_passphrase_enc": None,
            "has_api_key": bool(config.get("api_key_enc")),
            "has_passphrase": bool(config.get("api_passphrase_enc")),
        }
    })

# ============================================================
# Bot Control API
# ============================================================

@app.route("/api/bot/start", methods=["POST"])
def api_bot_start():
    if not is_logged_in():
        return jsonify({"success": False, "error": "Not logged in"}), 401

    user = current_user()
    if not user:
        return jsonify({"success": False, "error": "User not found"}), 404

    sub = check_subscription(user)
    if not sub["active"]:
        return jsonify({"success": False,
                        "error": "License inactive/expired. Please contact admin for a license."}), 403

    result = start_user_bot(user["id"])
    return jsonify(result)

@app.route("/api/bot/stop", methods=["POST"])
def api_bot_stop():
    if not is_logged_in():
        return jsonify({"success": False, "error": "Not logged in"}), 401

    user = current_user()
    if not user:
        return jsonify({"success": False, "error": "User not found"}), 404

    result = stop_user_bot(user["id"])
    return jsonify(result)

@app.route("/api/bot/status", methods=["GET"])
def api_bot_status():
    if not is_logged_in():
        return jsonify({"success": False, "error": "Not logged in"}), 401

    user = current_user()
    if not user:
        return jsonify({"success": False, "error": "User not found"}), 404

    status = get_bot_status(user["id"])
    if not status["running"]:
        return jsonify({"success": True, "running": False})

    bot_data = proxy_to_bot(user["id"], "GET", "/api/status")
    bot_balance = proxy_to_bot(user["id"], "GET", "/api/balance")

    return jsonify({
        "success": True,
        "running": True,
        "port": status["port"],
        "started_at": status.get("started_at"),
        "bot_status": bot_data,
        "balance": bot_balance,
    })

@app.route("/api/bot/proxy", methods=["GET", "POST"])
def api_bot_proxy():
    if not is_logged_in():
        return jsonify({"success": False, "error": "Not logged in"}), 401

    user = current_user()
    if not user:
        return jsonify({"success": False, "error": "User not found"}), 404

    path = request.args.get("path", "/")
    # Fix 5: Validate path to prevent path traversal / SSRF
    _allowed_proxy_prefixes = ("/api/", "/socket.io", "/static/")
    if not any(path.startswith(p) for p in _allowed_proxy_prefixes):
        return jsonify({"success": False, "error": "Invalid proxy path"}), 400
    # Fix 5: Whitelist allowed HTTP methods
    method = request.args.get("method", request.method).upper()
    if method not in ("GET", "POST", "PUT", "DELETE", "PATCH"):
        return jsonify({"success": False, "error": "Invalid method"}), 400
    body = request.get_json(silent=True) if request.method == "POST" else None

    result = proxy_to_bot(user["id"], method, path, body)
    return jsonify(result)

@app.route("/api/bot/embed")
def api_bot_embed():
    if not is_logged_in():
        return jsonify({"success": False, "error": "Not logged in"}), 401

    user = current_user()
    if not user:
        return jsonify({"success": False, "error": "User not found"}), 404

    status = get_bot_status(user["id"])
    if not status["running"]:
        return jsonify({"success": False, "error": "Bot not running. Start bot first."})

    return jsonify({
        "success": True,
        "url": "/bot/",
        "port": status["port"],
    })


@app.route('/api/symbols', methods=['GET'])
def root_api_symbols_fallback():
    """Fallback proxy for /api/symbols if called directly at SaaS root."""
    user = current_user()
    if not user:
        return jsonify({"success": False, "symbols": []}), 401
    return bot_engine_proxy("api/symbols")


# ============================================================
# FULL PROXY - serves bot-engine dashboard in iframe
# ============================================================

def _is_proxy_api_request(path: str) -> bool:
    """Return True when the proxied path expects JSON/Socket.IO rather than an HTML redirect."""
    return (
        path.startswith('socket.io')
        or path.startswith('api/')
        or request.headers.get("Authorization", "").startswith("Bearer")
    )


@app.route('/bot/', methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'OPTIONS'])
@app.route('/bot/<path:path>', methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'OPTIONS'])
def bot_engine_proxy(path=''):
    user = current_user()
    if not user:
        # Mobile clients authenticate with a JWT bearer token instead of a cookie
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            claims = mobile_verify_token(auth_header[7:].strip())
            if claims:
                user = DB.get("users", {}).get(claims.get("uid", ""))
                if user and user.get("banned"):
                    user = None
    if not user:
        if _is_proxy_api_request(path):
            return jsonify({
                "success": False,
                "auth_expired": True,
                "error": "Session expired or logged out. Please refresh the page and log in again.",
            }), 401
        return redirect("/")

    sub = check_subscription(user)
    if not sub["active"]:
        # Browser clients go to the packages page; API/socket clients get a JSON 403
        if _is_proxy_api_request(path):
            return jsonify({"success": False, "error": "Subscription inactive", "subscription": sub}), 403
        return redirect("/")

    status = get_bot_status(user["id"])

    if not status["running"]:
        result = ensure_bot_engine_running(user["id"])
        if result.get("success") and result.get("port"):
            status = {"running": True, "port": result["port"]}
        else:
            if _is_proxy_api_request(path):
                return jsonify({"success": False, "status": "starting", "error": "Bot engine starting... Please refresh the page (F5)."}), 503

            return '''<html><head><meta http-equiv="refresh" content="2"></head>
            <body style="background:#0b0e11;color:#eaecef;font-family:sans-serif;text-align:center;padding:120px 20px;">
            <div style="max-width:400px;margin:0 auto;">
                <div style="width:60px;height:60px;border:4px solid #2a2e36;border-top:4px solid #f0b90b;border-radius:50%;margin:0 auto 24px;animation:spin 1s linear infinite;"></div>
                <h2 style="color:#f0b90b;margin-bottom:8px;">Bot Engine Starting...</h2>
                <p style="color:#848e9c;font-size:14px;">Connecting to bot engine. Please wait...</p>
            </div>
            <style>@keyframes spin{0%{transform:rotate(0)}100%{transform:rotate(360deg)}}</style>
            </body></html>'''

    port = status["port"]
    method = request.method

    fwd_path = path
    if fwd_path == 'socket.io':
        fwd_path = 'socket.io/'
    url = f"http://127.0.0.1:{port}/{fwd_path}"
    if request.query_string:
        url += f"?{request.query_string.decode()}"

    fwd_headers = {}
    for k, v in request.headers:
        if k.lower() not in ('host', 'cookie', 'content-length'):
            fwd_headers[k] = v
    # Fix 12: Inject the shared secret so bot-engine can verify this request
    # comes from the trusted SaaS proxy (not a direct external caller).
    fwd_headers["X-Bot-Token"] = BOT_ENGINE_TOKEN

    body = request.get_data() if method in ('POST', 'PUT', 'PATCH') else None

    # Settings persistence: mirror dashboard config saves into the SaaS DB so
    # settings survive bot-engine restarts (the DB is the admin's source of truth).
    if method == 'POST' and path.rstrip('/') == 'api/config' and body:
        try:
            payload = json.loads(body)
            _sync_engine_config_to_db(user, payload)
        except Exception as e:
            logger.warning("Could not sync engine config to DB for %s: %s", user["id"], e)

    try:
        proxy_timeout = 65 if path.startswith('socket.io') else 30
        resp = req_lib.request(method, url, headers=fwd_headers, data=body,
                               stream=True, timeout=proxy_timeout, allow_redirects=False)
    except req_lib.exceptions.ConnectionError:
        # Engine dead (stale PID/port after a restart). Clear the stale entry
        # and auto-respawn a fresh instance immediately.
        logger.warning("Bot-engine connection refused for %s (port %s). Marking stopped and auto-restarting.",
                       user["id"], port)
        DB.get("bot_processes", {}).pop(user["id"], None)
        save_db(DB)

        import threading
        def _restart_bg():
            result = ensure_bot_engine_running(user["id"])
            if not result.get("success"):
                logger.error("Auto-restart bot-engine failed for %s: %s",
                             user["id"], result.get("error"))

        threading.Thread(target=_restart_bg, daemon=True).start()

        if path.startswith('socket.io') or path.startswith('api/'):
            return jsonify({"status": "starting", "error": "Bot engine restarting... Please wait."}), 503

        return '''<html><head><meta http-equiv="refresh" content="3"></head>
        <body style="background:#0b0e11;color:#eaecef;font-family:sans-serif;text-align:center;padding:120px 20px;">
        <div style="max-width:400px;margin:0 auto;">
            <div style="width:60px;height:60px;border:4px solid #2a2e36;border-top:4px solid #f0b90b;border-radius:50%;margin:0 auto 24px;animation:spin 1s linear infinite;"></div>
            <h2 style="color:#f0b90b;margin-bottom:8px;">Bot Engine Restarting...</h2>
            <p style="color:#848e9c;font-size:14px;">Reconnecting to engine. Page will auto-refresh in 3 seconds...</p>
        </div>
        <style>@keyframes spin{0%{transform:rotate(0)}100%{transform:rotate(360deg)}}</style>
        </body></html>''', 200
    except Exception as e:
        if _is_proxy_api_request(path):
            return jsonify({"success": False, "error": f"Proxy error: {str(e)}"}), 502
        return f"Proxy error: {str(e)}", 500

    excluded = {'content-encoding', 'transfer-encoding', 'connection', 'content-length', 'keep-alive'}
    import re
    response_headers = []
    for k, v in resp.headers.items():
        if k.lower() in excluded:
            continue
        if k.lower() == 'location':
            v = re.sub(rf'^https?://127\.0\.0\.1:{port}', '/bot', v)
        response_headers.append((k, v))

    content_type = resp.headers.get('content-type', '')

    if 'text/html' in content_type:
        html = resp.content.decode('utf-8', errors='replace')
        html = html.replace('href="/static/', 'href="/bot/static/')
        html = html.replace('src="/static/', 'src="/bot/static/')
        html = html.replace("fetch('/api/", "fetch('/bot/api/")
        html = html.replace('fetch("/api/', 'fetch("/bot/api/')
        html = html.replace('fetch(`/api/', 'fetch(`/bot/api/')
        # Keep SaaS user and auth APIs pointing directly to SaaS root
        html = html.replace("fetch('/bot/api/user/", "fetch('/api/user/")
        html = html.replace('fetch("/bot/api/user/', 'fetch("/api/user/')
        html = html.replace("fetch('/bot/api/auth/", "fetch('/api/auth/")
        html = html.replace('fetch("/bot/api/auth/', 'fetch("/api/auth/')
        html = re.sub(r'io\s*\(\s*\{', "io({path: '/bot/socket.io', ", html)
        html = re.sub(r'io\s*\(\s*\)', "io({path: '/bot/socket.io'})", html)
        return Response(html.encode('utf-8'), status=resp.status_code, headers=response_headers)

    elif 'javascript' in content_type:
        js = resp.content.decode('utf-8', errors='replace')
        js = js.replace("fetch('/api/", "fetch('/bot/api/")
        js = js.replace('fetch("/api/', 'fetch("/bot/api/')
        js = js.replace('fetch(`/api/', 'fetch(`/bot/api/')
        # Keep SaaS user and auth APIs pointing directly to SaaS root
        js = js.replace("fetch('/bot/api/user/", "fetch('/api/user/")
        js = js.replace('fetch("/bot/api/user/', 'fetch("/api/user/')
        js = js.replace("fetch('/bot/api/auth/", "fetch('/api/auth/")
        js = js.replace('fetch("/bot/api/auth/', 'fetch("/api/auth/')
        js = re.sub(r'io\s*\(\s*\{', "io({path: '/bot/socket.io', ", js)
        js = re.sub(r'io\s*\(\s*\)', "io({path: '/bot/socket.io'})", js)
        return Response(js.encode('utf-8'), status=resp.status_code, headers=response_headers)

    else:
        # Deliver Socket.IO polling packets immediately (no generator overhead)
        if path.startswith('socket.io'):
            return Response(resp.content, status=resp.status_code, headers=response_headers)

        # Stream non-HTML and non-JS content (e.g. large static files)
        def generate():
            try:
                for chunk in resp.iter_content(chunk_size=4096):
                    yield chunk
            except Exception as e:
                logger.error("Proxy streaming error: %s", e)
        return Response(generate(), status=resp.status_code, headers=response_headers)

# ============================================================
# Admin API
# ============================================================

@app.route("/api/admin/login", methods=["POST"])
def api_admin_login():
    if not ADMIN_SECRET:
        return jsonify({"success": False, "error": "Admin panel is disabled. Set ADMIN_SECRET env var."})

    client_ip = _client_ip()
    if not _check_rate_limit(f"admin_login:{client_ip}", max_requests=10, window_seconds=120):
        return jsonify({"success": False, "error": "Too many admin login attempts. Please wait 2 minutes."}), 429

    data = request.get_json(force=True, silent=True) or {}
    password = (data.get("password") or "").strip()

    # Constant-time comparison to prevent timing attacks
    if not secrets.compare_digest(password, ADMIN_SECRET):
        return jsonify({"success": False, "error": "Invalid admin password"})

    # Keep any currently logged-in regular user untouched (never mutate role="admin"
    # or mix accounts); only grant admin session flag.
    current_uid = session.get("user_id")
    if current_uid and current_uid in DB.get("users", {}):
        cur_u = DB["users"][current_uid]
        session["admin_authenticated"] = True
        session.permanent = True
        logger.info("Admin session granted for logged-in user %s (%s)", cur_u.get("email"), current_uid)
        return jsonify({"success": True, "user": {"id": cur_u["id"], "email": cur_u["email"], "role": "admin"}})

    # Otherwise find or create the dedicated system admin account only
    admin_user = DB.get("users", {}).get("admin")
    if not admin_user:
        for u in DB["users"].values():
            if u.get("id") == "admin" or _norm_email(u.get("email")) == "admin@tradebot.com":
                admin_user = u
                break

    if not admin_user:
        admin_id = "admin"
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        admin_user = {
            "id": admin_id,
            "email": "admin@tradebot.com",
            "name": "Admin",
            "password_hash": hash_password(password),
            "role": "admin",
            "banned": False,
            "created_at": now,
            "subscription": {"plan": "lifetime", "status": "active", "started_at": now,
                            "expires_at": "9999-12-31T23:59:59Z"},
            "license_key": None,
            "bot_config": {},
        }
        DB["users"][admin_id] = admin_user
        save_db(DB)
        logger.info("Dedicated admin user created via admin login")

    if admin_user.get("subscription", {}).get("status") != "active":
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        admin_user["subscription"] = {
            "plan": "lifetime", "status": "active",
            "started_at": now, "expires_at": "9999-12-31T23:59:59Z",
        }
        save_db(DB)

    session["admin_authenticated"] = True
    session["user_id"] = admin_user["id"]
    session.permanent = True
    return jsonify({"success": True, "user": {"id": admin_user["id"], "email": admin_user["email"], "role": "admin"}})

@app.route("/api/admin/users", methods=["GET"])
def api_admin_users():
    if not is_admin():
        return jsonify({"success": False, "error": "Admin access required"}), 403

    users = []
    for u in DB["users"].values():
        if u.get("id") == "admin" or _norm_email(u.get("email")) == "admin@tradebot.com":
            continue
        sub = check_subscription(u)
        bot_status = get_bot_status(u["id"])
        # Count referrals
        referral_count = sum(1 for x in DB["users"].values() if x.get("referred_by") == u["id"])
        # Find who referred this user
        referrer_name = ""
        if u.get("referred_by"):
            referrer = DB["users"].get(u["referred_by"])
            if referrer:
                referrer_name = referrer.get("name", referrer.get("email", ""))
        users.append({
            "id": u["id"],
            "email": u["email"],
            "name": u.get("name", ""),
            "banned": u.get("banned", False),
            "created_at": u.get("created_at"),
            "subscription": sub,
            "license_key": u.get("license_key"),
            "referral_code": u.get("referral_code", ""),
            "referral_count": referral_count,
            "referral_earnings": float(u.get("referral_earnings", 0.0) or 0.0),
            "referred_by_name": referrer_name,
            "bot_running": bot_status.get("running", False),
            "exchange": u.get("bot_config", {}).get("exchange", "none"),
        })

    return jsonify({"success": True, "users": users})

@app.route("/api/admin/licenses", methods=["GET"])
def api_admin_list_licenses():
    if not is_admin():
        return jsonify({"success": False, "error": "Admin access required"}), 403

    licenses = list(DB.get("licenses", {}).values())
    return jsonify({"success": True, "licenses": licenses})

@app.route("/api/admin/licenses/create", methods=["POST"])
def api_admin_create_license():
    if not is_admin():
        return jsonify({"success": False, "error": "Admin access required"}), 403

    data = request.get_json(force=True)
    days = int(data.get("days", 30))
    plan = data.get("plan", "basic")
    note = data.get("note", "")

    if days <= 0:
        return jsonify({"success": False, "error": "Days must be positive"})

    parts = []
    for _ in range(4):
        parts.append(secrets.token_hex(2).upper())
    key = f"TRDBOT-{parts[0]}-{parts[1]}-{parts[2]}-{parts[3]}"

    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=days)

    lic = {
        "key": key,
        "plan": plan,
        "days": days,
        "note": note,
        "created_at": now.isoformat().replace("+00:00", "Z"),
        "expires_at": expires.isoformat().replace("+00:00", "Z"),
        "used_by": None,
        "activated_at": None,
        "active": False,
        "revoked": False,
    }

    DB.setdefault("licenses", {})[key] = lic
    save_db(DB)

    logger.info("Admin created license: %s (%dd)", key, days)
    return jsonify({"success": True, "license": lic})

@app.route("/api/admin/licenses/revoke", methods=["POST"])
def api_admin_revoke_license():
    if not is_admin():
        return jsonify({"success": False, "error": "Admin access required"}), 403

    data = request.get_json(force=True)
    key = (data.get("key") or "").strip().upper()

    lic = DB.get("licenses", {}).get(key)
    if not lic:
        return jsonify({"success": False, "error": "License not found"})

    lic["revoked"] = True
    lic["active"] = False

    if lic.get("used_by"):
        user = DB["users"].get(lic["used_by"])
        if user:
            now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            user["subscription"] = {"plan": "none", "status": "inactive",
                                   "started_at": now, "expires_at": None}
            stop_user_bot(lic["used_by"])

    save_db(DB)
    return jsonify({"success": True, "message": f"License {key} revoked"})

@app.route("/api/admin/licenses/delete", methods=["POST"])
def api_admin_delete_license():
    if not is_admin():
        return jsonify({"success": False, "error": "Admin access required"}), 403

    data = request.get_json(force=True)
    key = (data.get("key") or "").strip().upper()

    if key not in DB.get("licenses", {}):
        return jsonify({"success": False, "error": "License not found"})

    DB["licenses"].pop(key, None)
    save_db(DB)
    return jsonify({"success": True, "message": f"License {key} deleted"})

@app.route("/api/admin/ban", methods=["POST"])
def api_admin_ban():
    if not is_admin():
        return jsonify({"success": False, "error": "Admin access required"}), 403

    data = request.get_json(force=True)
    user_id = data.get("user_id")
    banned = bool(data.get("banned", False))

    user = DB["users"].get(user_id)
    if not user:
        return jsonify({"success": False, "error": "User not found"})

    if user.get("role") == "admin" and banned:
        return jsonify({"success": False, "error": "Cannot ban admin"})

    user["banned"] = banned
    if banned:
        stop_user_bot(user_id)
    save_db(DB)

    return jsonify({"success": True, "banned": banned, "message": "Banned" if banned else "Unbanned"})

@app.route("/api/admin/delete", methods=["POST"])
def api_admin_delete():
    if not is_admin():
        return jsonify({"success": False, "error": "Admin access required"}), 403

    data = request.get_json(force=True)
    user_id = data.get("user_id")

    user = DB["users"].get(user_id)
    if not user:
        return jsonify({"success": False, "error": "User not found"})

    if user.get("role") == "admin":
        return jsonify({"success": False, "error": "Cannot delete admin"})

    stop_user_bot(user_id)
    DB["users"].pop(user_id, None)
    save_db(DB)
    return jsonify({"success": True, "message": "User deleted"})

# ============================================================
# SaaS Email & Password Reset Helpers
# ============================================================

def _public_base_url() -> str:
    """Resolve external origin URL for links sent in emails (proxy-safe)."""
    explicit = (os.environ.get("PUBLIC_BASE_URL") or os.environ.get("APP_PUBLIC_URL") or "").strip().rstrip("/")
    if explicit:
        return explicit
    try:
        fwd_host = (request.headers.get("X-Forwarded-Host") or "").split(",")[0].strip()
        host = fwd_host or (request.headers.get("Host") or request.host or "").strip()
        fwd_proto = (request.headers.get("X-Forwarded-Proto") or "").split(",")[0].strip().lower()
        hostname = host.split(":")[0].lower()
        if fwd_proto in ("http", "https"):
            scheme = fwd_proto
        elif hostname and hostname not in ("localhost", "127.0.0.1", "::1"):
            scheme = "https"
        else:
            scheme = (request.scheme or "http").lower()
        if host:
            return f"{scheme}://{host}"
        return request.url_root.rstrip("/")
    except Exception:
        return "https://weexionic.duckdns.org"


def _send_email_smtp(
    to_email: str,
    subject: str,
    plain_body: str,
    html_body: Optional[str] = None,
    smtp_override: Optional[dict] = None,
) -> dict:
    """Send transactional email via configured SaaS SMTP settings."""
    smtp_cfg = dict(_get_smtp_config())
    if isinstance(smtp_override, dict):
        for k, v in smtp_override.items():
            if v not in (None, ""):
                smtp_cfg[k] = v

    smtp_user = str(smtp_cfg.get("user") or "").strip()
    smtp_pass = str(smtp_cfg.get("pass") or "").strip()
    smtp_server = str(smtp_cfg.get("server") or smtp_cfg.get("host") or "smtp.gmail.com").strip()
    try:
        smtp_port = int(smtp_cfg.get("port") or 587)
    except (ValueError, TypeError):
        smtp_port = 587

    if not smtp_user or not smtp_pass:
        logger.warning("SaaS SMTP not configured. Email (%s) not sent to %s", subject, to_email)
        return {"success": False, "error": "SMTP credentials not configured (check .env or Admin Panel)"}

    is_gmail_relay = (
        "gmail" in smtp_server.lower()
        or smtp_user.lower().endswith(("@gmail.com", "@googlemail.com"))
    )
    # Google displays 16-char App Passwords in 4-char space-separated groups
    if is_gmail_relay and " " in smtp_pass:
        compact = smtp_pass.replace(" ", "")
        if len(compact) == 16 and compact.isalnum():
            smtp_pass = compact

    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart
    from email.utils import formataddr, formatdate, make_msgid

    try:
        sender_label = str(smtp_cfg.get("sender_name") or "Weexionic Trading Bot").strip()
        raw_from = str(smtp_cfg.get("from_email") or smtp_user).strip()
        if is_gmail_relay and raw_from.lower() != smtp_user.lower():
            envelope_from = smtp_user
            header_from = smtp_user
            reply_to = raw_from
        else:
            envelope_from = raw_from
            header_from = raw_from
            reply_to = ""

        domain = envelope_from.split("@", 1)[1] if "@" in envelope_from else None
        msg = MIMEMultipart("alternative")
        msg["From"] = formataddr((sender_label, header_from))
        msg["To"] = to_email
        msg["Subject"] = subject
        msg["Date"] = formatdate(localtime=True)
        msg["Message-ID"] = make_msgid(domain=domain)
        if reply_to:
            msg["Reply-To"] = reply_to
        msg.attach(MIMEText(plain_body, "plain", "utf-8"))
        if html_body:
            msg.attach(MIMEText(html_body, "html", "utf-8"))

        if smtp_port == 465:
            with smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=15) as server:
                server.ehlo()
                server.login(smtp_user, smtp_pass)
                refused = server.sendmail(envelope_from, [to_email], msg.as_string())
        else:
            with smtplib.SMTP(smtp_server, smtp_port, timeout=15) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(smtp_user, smtp_pass)
                refused = server.sendmail(envelope_from, [to_email], msg.as_string())

        if refused:
            logger.error("SMTP refused recipient for (%s) to %s: %s", subject, to_email, refused)
            return {"success": False, "error": f"SMTP refused recipient: {refused}"}

        logger.info(
            "Transactional email sent (%s) to %s via %s:%s (from=%s)",
            subject, to_email, smtp_server, smtp_port, envelope_from,
        )
        return {"success": True}
    except Exception as e:
        logger.error("Failed to send email (%s) to %s via %s:%s: %s", subject, to_email, smtp_server, smtp_port, e)
        return {"success": False, "error": str(e)}


def _send_license_email(to_email: str, license_key: str, package_name: str, days: int):
    """Send license key to user via email after admin verifies payment."""
    days_text = "Lifetime" if days >= 9999 else f"{days} days"
    body = (
        f"Hello,\n\n"
        f"Your payment has been verified and your license key is ready!\n\n"
        f"Platform: Weexionic Automated Futures Trading Bot\n"
        f"Package: {package_name}\n"
        f"Duration: {days_text}\n"
        f"License Key: {license_key}\n\n"
        f"To activate:\n"
        f"1. Login to your account\n"
        f"2. Go to License Activation page\n"
        f"3. Paste the license key above: {license_key}\n"
        f"4. Click Activate\n\n"
        f"Thank you for choosing Weexionic Trading Bot!\n"
    )
    return _send_email_smtp(to_email, f"[Weexionic] Your License Key - {package_name}", body)


def _send_password_reset_email(to_email: str, reset_url: str, user_name: str = "") -> dict:
    """Send password reset link email for account recovery."""
    from html import escape as _html_escape
    greeting = f"Hello {user_name}," if user_name else "Hello,"
    plain_body = (
        f"{greeting}\n\n"
        f"We received a request to reset the password for your Weexionic account ({to_email}).\n\n"
        f"Click the link below to set a new password (valid for 30 minutes, single use):\n"
        f"{reset_url}\n\n"
        f"Your saved exchange API keys, license/subscription, and trade history remain safely linked to your email.\n\n"
        f"If you did not request this password reset, you can safely ignore this email.\n"
    )
    safe_greet = _html_escape(greeting)
    safe_email = _html_escape(to_email)
    safe_url = _html_escape(reset_url, quote=True)
    html_body = (
        f"<div style='font-family:Arial,sans-serif;max-width:520px;margin:auto;padding:24px;"
        f"background:#111714;color:#f3f1ea;border-radius:12px;border:1px solid #3c3215;'>"
        f"<h2 style='color:#f0b90b;margin-top:0;'>WEEXIONIC Password Reset</h2>"
        f"<p>{safe_greet}</p>"
        f"<p>Click the button below to reset the password for <strong>{safe_email}</strong>:</p>"
        f"<p style='margin:24px 0;'>"
        f"<a href='{safe_url}' style='background:#f0b90b;color:#111;font-weight:bold;"
        f"padding:12px 22px;border-radius:8px;text-decoration:none;display:inline-block;'>"
        f"Reset My Password</a></p>"
        f"<p style='font-size:12px;color:#b8b09c;'>Or copy this link:<br>{safe_url}</p>"
        f"<p style='font-size:12px;color:#b8b09c;'>Valid for 30 minutes (single use). "
        f"Your API keys, license, and trade history remain preserved on your account.</p>"
        f"</div>"
    )
    return _send_email_smtp(to_email, "[Weexionic] Reset Your Password", plain_body, html_body)


def _reset_token_hash(raw_token: str) -> str:
    return hashlib.sha256((raw_token or "").strip().encode("utf-8")).hexdigest()


def _prune_expired_reset_tokens(db: Optional[dict] = None) -> dict:
    store = db if db is not None else DB
    settings = store.setdefault("settings", {})
    if not isinstance(settings, dict):
        settings = {}
        store["settings"] = settings
    resets = settings.setdefault("password_resets", {})
    if not isinstance(resets, dict):
        resets = {}
        settings["password_resets"] = resets
    now_ts = time.time()
    for tok_hash, rec in list(resets.items()):
        if not isinstance(rec, dict) or now_ts > float(rec.get("expires_at", 0) or 0):
            resets.pop(tok_hash, None)
    return resets


def _get_valid_reset_record(raw_token: str):
    clean = (raw_token or "").strip()
    if not clean:
        return None
    t_hash = _reset_token_hash(clean)
    resets = _prune_expired_reset_tokens(DB)
    rec = resets.get(t_hash)
    if not rec:
        return None
    return t_hash, rec


def _issue_password_reset_token(user: dict) -> tuple:
    """Create and persist a 30-minute single-use password reset link for `user`."""
    canonical_id = _dedupe_users_by_email(user["id"], save=False)
    user = DB["users"].get(canonical_id, user)
    target_email = _norm_email(user.get("email"))

    resets = _prune_expired_reset_tokens(DB)
    # Keep at most 2 previous valid tokens for this user in case of rapid double-clicks
    user_tokens = [
        (k, float(v.get("created_at", 0) or 0))
        for k, v in resets.items()
        if isinstance(v, dict) and (v.get("user_id") == user["id"] or _norm_email(v.get("email")) == target_email)
    ]
    user_tokens.sort(key=lambda item: item[1])
    for old_k, _ in user_tokens[:-2]:
        resets.pop(old_k, None)

    raw_token = secrets.token_urlsafe(32)
    t_hash = _reset_token_hash(raw_token)
    now_ts = time.time()
    resets[t_hash] = {
        "user_id": user["id"],
        "email": target_email,
        "created_at": now_ts,
        "expires_at": now_ts + 1800,
    }
    save_db(DB)
    reset_url = f"{_public_base_url()}/reset-password?token={raw_token}"
    return user, target_email, t_hash, reset_url


def _create_and_send_password_reset(email_raw: str) -> tuple:
    """Create a 30-minute single-use password reset link and email it to `email_raw`."""
    email = _norm_email(email_raw)
    client_ip = _client_ip()
    if (
        not _check_rate_limit(f"forgot:{client_ip}:{email or '_'}", max_requests=5, window_seconds=900)
        or not _check_rate_limit(f"forgot_ip:{client_ip}", max_requests=15, window_seconds=900)
    ):
        return {"success": False, "error": "Too many password reset requests. Please wait 15 minutes."}, 429

    if not email or "@" not in email or "." not in email:
        return {"success": False, "error": "Please enter a valid email address"}, 400

    smtp_cfg = _get_smtp_config()
    if not smtp_cfg.get("user") or not smtp_cfg.get("pass"):
        return {
            "success": False,
            "error": "Password reset email service is not configured yet. Please configure SMTP in Admin Panel or .env.",
        }, 503

    matches = _find_users_by_email_tolerant(email)
    if not matches:
        logger.warning("Password reset requested for unregistered email: %s", email)
        return {
            "success": False,
            "error": f"No account found for '{email}'. Kripya wohi exact email enter karein jis se account banaya tha.",
        }, 404

    user = max(matches, key=lambda item: _user_richness_score(item))
    if user.get("banned"):
        return {"success": False, "error": "Account suspended. Please contact admin."}, 403

    user, target_email, t_hash, reset_url = _issue_password_reset_token(user)
    send_res = _send_password_reset_email(target_email, reset_url, user.get("name", ""))
    if not send_res.get("success"):
        resets = _prune_expired_reset_tokens(DB)
        resets.pop(t_hash, None)
        save_db(DB)
        return {
            "success": False,
            "error": f"Failed to send reset email: {send_res.get('error', 'SMTP error')}",
        }, 502

    logger.info("Password reset email sent to %s (user_id=%s)", target_email, user["id"])
    return {
        "success": True,
        "email": target_email,
        "message": f"Password reset link {target_email} par bhej diya gaya hai! Kripya Inbox aur Spam folder check karein.",
    }, 200

# ============================================================
# Google OAuth Routes
# ============================================================

@app.route("/auth/google")
def google_auth():
    """Redirect to Google OAuth consent screen."""
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        return redirect("/auth/google/diag")
    import re as _re
    import urllib.parse
    # Mobile clients come back to the app via verified App Link / native intent + msid polling
    is_mobile = request.args.get("client") == "mobile"
    msid = _re.sub(r"[^A-Za-z0-9_\-]", "", (request.args.get("msid") or "").strip())[:64]
    if is_mobile:
        session["oauth_client"] = "mobile"
        if msid:
            session["oauth_msid"] = msid
    # Generate and store OAuth state (prefix with 'm:' for mobile clients to persist across browser tabs)
    state_token = secrets.token_hex(16)
    if is_mobile:
        oauth_state = f"m:{state_token}:{msid}" if msid else f"m:{state_token}"
    else:
        oauth_state = state_token
    session["oauth_state"] = oauth_state
    redirect_uri = _google_redirect_uri_for_page()
    session["oauth_redirect_uri"] = redirect_uri
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "prompt": "select_account",
        "state": oauth_state,
    }
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params)
    return redirect(url)


@app.route("/auth/google/callback")
def google_callback():
    """Handle Google OAuth callback - create or login user."""
    import re as _re
    code = request.args.get("code")
    error = request.args.get("error")
    # Verify OAuth state to prevent CSRF attacks
    returned_state = request.args.get("state", "")
    expected_state = session.pop("oauth_state", None)
    is_mobile = bool(
        session.get("oauth_client") == "mobile"
        or returned_state.startswith("m:")
        or request.args.get("client") == "mobile"
    )
    # Extract mobile polling session id (msid) if embedded in state ("m:<hex>:<msid>")
    msid = ""
    if returned_state.startswith("m:"):
        state_parts = returned_state.split(":", 2)
        if len(state_parts) == 3:
            msid = _re.sub(r"[^A-Za-z0-9_\-]", "", state_parts[2])[:64]
    if not msid:
        msid = _re.sub(r"[^A-Za-z0-9_\-]", "", str(session.pop("oauth_msid", "") or ""))[:64]
    else:
        session.pop("oauth_msid", None)

    is_valid_state = bool(expected_state and secrets.compare_digest(returned_state, expected_state))
    if not is_valid_state and not (is_mobile and returned_state.startswith("m:") and len(returned_state) >= 18):
        logger.warning("Google OAuth state mismatch — possible CSRF attack. IP=%s", request.remote_addr)
        return _oauth_error_page(
            "Session Expired",
            "The sign-in session expired or failed its security check (state mismatch).",
            "Dobara Google Sign-In button dabao - naya session ban jayega.")

    if error:
        logger.warning("Google OAuth error: %s", error)
        return _oauth_error_page(
            "Google Sign-In Cancelled",
            "Google returned: " + str(error) + ".",
            "Agar aapne khud Cancel dabaya tha to bas dobara try karo. Baar-baar aaye to pop-up blocker check karo.")
    if not code:
        return _oauth_error_page(
            "Google Sign-In Incomplete",
            "Google did not return an authorization code.",
            "Temporary ho sakta hai - Retry dabao. Repeat ho to /auth/google/diag kholo.")

    try:
        redirect_uri = session.pop("oauth_redirect_uri", None) or _google_redirect_uri_for_page()
        # Exchange code for access token
        token_data = {
            "code": code,
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
        resp = req_lib.post("https://oauth2.googleapis.com/token", data=token_data, timeout=10)
        tokens = resp.json()
        access_token = tokens.get("access_token")
        if not access_token:
            logger.error("Google token exchange failed: %s", tokens)
            return _oauth_error_page(
                "Google token exchange failed",
                "Google accepted the sign-in but rejected the token exchange.",
                "Server ka redirect URI Google Cloud mein registered URI se match nahi karta. Is EXACT URI ko Google Cloud Console &rarr; Credentials &rarr; Authorized redirect URIs mein add karo, save karo, 5 minute wait karo, phir retry:"
                "<br><code><b>" + _google_redirect_uri_for_page() + "</b></code>")

        # Get user info from Google
        userinfo_resp = req_lib.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
        userinfo = userinfo_resp.json()
        google_email = userinfo.get("email", "").lower().strip()
        google_name = userinfo.get("name", "")
        google_picture = userinfo.get("picture", "")
        google_id = userinfo.get("id", "")

        if not google_email:
            return _oauth_error_page(
                "No Email From Google",
                "Google did not share an email address for this account.",
                "Google account mein verified email hona chahiye. Dobara try karo.")

        # SECURITY: only trust Google accounts whose email Google has verified.
        # Note: Google OAuth2 v2 /userinfo returns "verified_email": true (boolean),
        # while OIDC tokens / v3 userinfo return "email_verified": true (or string).
        # Standard @gmail.com / @googlemail.com accounts are also inherently Google-verified.
        is_verified = bool(
            userinfo.get("email_verified") in (True, "true", "1", 1)
            or userinfo.get("verified_email") in (True, "true", "1", 1)
            or str(userinfo.get("verified_email", "")).lower() == "true"
            or str(userinfo.get("email_verified", "")).lower() == "true"
            or google_email.endswith("@gmail.com")
            or google_email.endswith("@googlemail.com")
        )
        if not is_verified:
            logger.warning("Google login rejected for unverified email %s (userinfo: %s)",
                           google_email, {k: userinfo.get(k) for k in ("email", "verified_email", "email_verified")})
            return redirect("/login?error=email_not_verified")

        # Find existing user (richest primary record if duplicates exist) or create new one
        google_email_norm = _norm_email(google_email)
        matches = _find_users_by_email(google_email_norm)
        user = max(matches, key=lambda item: _user_richness_score(item)) if matches else None

        if not user:
            # Auto-create account via Google
            user_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            referral_code = user_id[:8].upper()

            ref_by_code = (session.get("referral_code") or "").strip().upper()
            referred_by = None
            if ref_by_code:
                for u in DB["users"].values():
                    if u.get("referral_code") == ref_by_code:
                        referred_by = u["id"]
                        break

            user = {
                "id": user_id,
                "email": google_email_norm,
                "name": google_name or google_email_norm.split("@")[0],
                "password_hash": "",
                "role": "user",
                "banned": False,
                "created_at": now,
                "google_id": google_id,
                "google_picture": google_picture,
                "subscription": {
                    "plan": "none", "status": "inactive",
                    "started_at": now, "expires_at": None,
                },
                "license_key": None,
                "referral_code": referral_code,
                "referred_by": referred_by,
                "referral_earnings": 0.0,
                "referral_history": [],
                "bot_config": _default_bot_config(),
            }
            DB["users"][user_id] = user
            save_db(DB)
            logger.info("New Google signup: %s (id=%s, ref_code=%s, referred_by=%s)",
                        google_email_norm, user_id, referral_code, referred_by)

        if user.get("banned"):
            return redirect("/?error=account_suspended")

        canonical_id = _dedupe_users_by_email(user["id"])
        user = DB["users"].get(canonical_id, user)

        google_changed = False
        if google_id and user.get("google_id") != google_id:
            user["google_id"] = google_id
            google_changed = True
        if google_picture and user.get("google_picture") != google_picture:
            user["google_picture"] = google_picture
            google_changed = True
        if google_changed:
            save_db(DB)

        session["user_id"] = user["id"]
        session.permanent = True
        logger.info("Google login: %s (id=%s)", google_email_norm, user["id"])

        # Mobile OAuth round-trip: return securely via single-use auth code, native intent AND msid polling
        if is_mobile:
            import urllib.parse as _up
            session.pop("oauth_client", None)
            auth_code = f"wx_{secrets.token_urlsafe(32)}"
            now_ts = time.time()
            oauth_codes = DB.setdefault("oauth_codes", {})
            for _k, _v in list(oauth_codes.items()):
                if now_ts > float((_v or {}).get("expires_at", 0)) + 60:
                    oauth_codes.pop(_k, None)
            oauth_codes[auth_code] = {
                "user_id": user["id"],
                "created_at": now_ts,
                "expires_at": now_ts + 180,  # 3 minutes TTL
                "used": False,
            }
            if msid and len(msid) >= 16:
                mobile_sessions = DB.setdefault("oauth_mobile_sessions", {})
                for _mk, _mv in list(mobile_sessions.items()):
                    if now_ts > float((_mv or {}).get("expires_at", 0)) + 60:
                        mobile_sessions.pop(_mk, None)
                mobile_sessions[msid] = {
                    "code": auth_code,
                    "user_id": user["id"],
                    "created_at": now_ts,
                    "expires_at": now_ts + 180,
                }
            save_db(DB)
            applink_url = f"https://weexionic.duckdns.org/app/oauth?code={auth_code}"
            fallback_enc = _up.quote(applink_url, safe="")
            intent_url = (
                f"intent://oauth?code={auth_code}"
                f"#Intent;scheme=weexionic;package=com.weexionic.app;"
                f"S.browser_fallback_url={fallback_enc};end"
            )
            handoff_url = f"weexionic://oauth?code={auth_code}"
            ua = (request.headers.get("User-Agent") or "").lower()
            # CRITICAL: Return an HTTP 302 redirect (NOT 200 HTML) so Chrome Android /
            # Chrome Custom Tabs preserve the user's tap gesture from Google's account
            # chooser and immediately launch com.weexionic.app without stopping in the browser!
            target_redirect = intent_url if "android" in ua else handoff_url
            return Response("", status=302, headers={
                "Location": target_redirect,
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            })
        return redirect("/")

    except Exception as e:
        logger.error("Google OAuth error: %s", e)
        return _oauth_error_page(
            "Google Sign-In Failed",
            "Something went wrong during sign-in.",
            "Details: <code>" + str(e)[:200] + "</code><br>Retry karo; repeat ho to /auth/google/diag kholo.")


@app.route("/.well-known/assetlinks.json")
def assetlinks():
    """Digital Asset Links for verified Android App Links."""
    return jsonify([
        {
            "relation": ["delegate_permission/common.handle_all_urls"],
            "target": {
                "namespace": "android_app",
                "package_name": "com.weexionic.app",
                "sha256_cert_fingerprints": [
                    "1A:2A:5D:7C:7F:51:30:68:CA:62:6D:72:24:71:DB:33:5C:76:BE:F3:39:99:C0:BE:E0:E6:9A:E6:5F:9F:27:21",
                    "15:02:DF:D3:5F:B6:33:DE:6B:EB:98:C0:59:7C:1E:5C:A0:A6:45:C7:A9:7F:A7:20:94:3B:56:45:21:8B:E7:F4",
                    "FA:C6:17:45:DC:09:03:78:6F:B9:ED:E6:2A:96:2B:39:9F:73:48:F0:BB:6F:89:9B:83:32:66:75:91:03:3B:9C",
                ],
            },
        },
        {
            "relation": ["delegate_permission/common.handle_all_urls"],
            "target": {
                "namespace": "android_app",
                "package_name": "com.exionic.trader",
                "sha256_cert_fingerprints": [
                    "15:02:DF:D3:5F:B6:33:DE:6B:EB:98:C0:59:7C:1E:5C:A0:A6:45:C7:A9:7F:A7:20:94:3B:56:45:21:8B:E7:F4",
                    "FA:C6:17:45:DC:09:03:78:6F:B9:ED:E6:2A:96:2B:39:9F:73:48:F0:BB:6F:89:9B:83:32:66:75:91:03:3B:9C",
                ],
            },
        },
    ])


@app.route("/download/apk")
def download_apk():
    """Direct APK download route for WEEXIONIC Android application."""
    apk_url = os.environ.get("APK_DOWNLOAD_URL", "https://github.com/studyinnlanguage/bot/releases/download/v2.1.3/WEEXIONIC-v2.1.3.apk")
    return redirect(apk_url)


@app.route("/app/oauth")
def app_oauth_handoff():
    """Verified App Link endpoint for mobile authentication handoff."""
    code = request.args.get("code", "")
    intent_url = f"intent://oauth?code={code}#Intent;scheme=weexionic;package=com.weexionic.app;end"
    handoff_url = f"weexionic://oauth?code={code}"
    applink_url = f"https://weexionic.duckdns.org/app/oauth?code={code}"
    return render_template(
        "saas_oauth_handoff.html",
        auth_code=code,
        intent_url=intent_url,
        handoff_url=handoff_url,
        applink_url=applink_url,
    )

# ============================================================
# Package / Payment Routes
# ============================================================

@app.route("/packages")
def packages_page():
    """Show package selection page (only for users without active subscription)."""
    if not is_logged_in():
        return redirect("/")
    user = current_user()
    if not user:
        session.clear()
        return redirect("/")
    sub = check_subscription(user)
    if sub["active"]:
        return redirect("/")
    return render_template("saas_packages.html", user=user,
                          wallet_address=WALLET_ADDRESS, wallet_network=WALLET_NETWORK)


@app.route("/payment/<order_id>")
def payment_page(order_id):
    """Show payment page for a specific order."""
    if not is_logged_in():
        return redirect("/")
    user = current_user()
    if not user:
        return redirect("/")

    order = DB.get("orders", {}).get(order_id)
    if not order or order["user_id"] != user["id"]:
        return redirect("/packages")

    return render_template("saas_payment.html", user=user, order=order,
                          wallet_trc20=WALLET_TRC20, wallet_bep20=WALLET_BEP20,
                          wallet_address=WALLET_TRC20, wallet_network=WALLET_NETWORK)


def _verify_tx_blockchain(tx_hash: str, expected_amount: float) -> tuple[bool, str]:
    """
    Verify payment on TRON (TRC20) or BSC (BEP20).
    Returns (is_verified, note).
    """
    if not tx_hash or len(tx_hash.strip()) < 10:
        return False, "Invalid transaction hash format."

    clean_tx = tx_hash.strip().lower()
    clean_tx_no_0x = clean_tx[2:] if clean_tx.startswith("0x") else clean_tx

    # 1. Double spending check
    used_txids = DB.setdefault("used_txids", {})
    if clean_tx in used_txids or clean_tx_no_0x in used_txids:
        return False, "This transaction hash has already been used for an order."

    # 2. Check TRON (TRC20) via TronScan
    try:
        tron_url = f"https://apilist.tronscanapi.com/api/transaction-info?hash={clean_tx_no_0x}"
        req = urllib.request.Request(tron_url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        with urllib.request.urlopen(req, timeout=7) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            if data.get("contractRet") == "SUCCESS" or data.get("confirmed"):
                trc20_list = data.get("trc20TransferInfo") or []
                for t in trc20_list:
                    to_addr = (t.get("to_address") or "").strip()
                    amount_str = str(t.get("amount_str") or "0")
                    decimals = int(t.get("decimals") or 6)
                    actual_amount = float(amount_str) / (10 ** decimals)
                    if to_addr.lower() == WALLET_TRC20.lower() and actual_amount >= (expected_amount - 0.5):
                        return True, f"TRON (TRC-20) verified: {actual_amount} USDT received"
    except Exception as e:
        logger.debug("TronScan check error: %s", e)

    # 3. Check BSC (BEP20) via Binance Smart Chain RPC
    try:
        bsc_tx = clean_tx if clean_tx.startswith("0x") else "0x" + clean_tx
        payload = json.dumps({
            "jsonrpc": "2.0",
            "method": "eth_getTransactionReceipt",
            "params": [bsc_tx],
            "id": 1
        }).encode("utf-8")
        req = urllib.request.Request("https://bsc-dataseed.binance.org", data=payload,
                                     headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=7) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            receipt = data.get("result")
            if receipt and receipt.get("status") == "0x1":
                logs = receipt.get("logs") or []
                target_wallet_padded = WALLET_BEP20.lower().replace("0x", "").zfill(64)
                transfer_topic = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
                for l in logs:
                    topics = l.get("topics") or []
                    if len(topics) >= 3 and topics[0].lower() == transfer_topic:
                        to_topic = topics[2].lower().replace("0x", "")
                        if to_topic == target_wallet_padded:
                            raw_data = l.get("data", "0x0")
                            raw_val = int(raw_data, 16)
                            val_usdt = raw_val / (10 ** 18)
                            if val_usdt >= (expected_amount - 0.5):
                                return True, f"BSC (BEP-20) verified: {val_usdt} USDT received"
    except Exception as e:
        logger.debug("BSC RPC check error: %s", e)

    return False, "Transaction is unconfirmed or recipient/amount does not match."


def _activate_order_and_credit_referral(order: dict, custom_days: int = None, verified_by: str = "auto") -> tuple[bool, str, dict]:
    """
    Activates user subscription, assigns license key, and immediately credits referral bonus to referrer.
    Idempotent: if the order is already verified, returns the existing license without
    creating a duplicate license or double-crediting the referrer.
    """
    if order.get("status") == "verified" and order.get("license_key"):
        return True, order["license_key"], {"success": False, "error": "Order was already activated"}
    order_id = order["id"]
    days = int(custom_days) if custom_days else order["days"]
    parts = [secrets.token_hex(2).upper() for _ in range(4)]
    license_key = f"TRDBOT-{parts[0]}-{parts[1]}-{parts[2]}-{parts[3]}"

    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=days) if days < 9999 else datetime(9999, 12, 31, tzinfo=timezone.utc)

    # 1. Create license in DB
    lic = {
        "key": license_key,
        "plan": order["package_id"],
        "days": days,
        "note": f"Order {order_id} - {order['package_name']} - {order['user_email']} ({verified_by})",
        "created_at": now.isoformat().replace("+00:00", "Z"),
        "expires_at": expires.isoformat().replace("+00:00", "Z"),
        "used_by": order["user_id"],
        "activated_at": now.isoformat().replace("+00:00", "Z"),
        "active": True,
        "revoked": False,
    }
    DB.setdefault("licenses", {})[license_key] = lic

    # 2. Update user subscription
    user = DB["users"].get(order["user_id"])
    if user:
        user["subscription"] = {
            "plan": order["package_id"],
            "status": "active",
            "started_at": now.isoformat().replace("+00:00", "Z"),
            "expires_at": expires.isoformat().replace("+00:00", "Z"),
        }
        user["license_key"] = license_key

        # 3. Referral bonus credit ($10 for 1-Year, $50 for Lifetime)
        referred_by_id = user.get("referred_by")
        if referred_by_id and referred_by_id in DB["users"]:
            referrer = DB["users"][referred_by_id]
            pkg = PACKAGES.get(order["package_id"], {})
            ref_bonus = float(pkg.get("referral_bonus") or 0.0)
            if ref_bonus > 0:
                referrer_history = referrer.setdefault("referral_history", [])
                already_credited = any(h.get("order_id") == order_id for h in referrer_history)
                if not already_credited:
                    referrer["referral_earnings"] = float(referrer.get("referral_earnings") or 0.0) + ref_bonus
                    referrer_history.append({
                        "order_id": order_id,
                        "buyer_id": user.get("id"),
                        "buyer_email": user.get("email"),
                        "buyer_name": user.get("name"),
                        "package_id": order["package_id"],
                        "package_name": order.get("package_name") or pkg.get("name", ""),
                        "bonus_amount": ref_bonus,
                        "currency": "USDT",
                        "timestamp": now.isoformat().replace("+00:00", "Z"),
                        "status": "credited",
                    })
                    logger.info("Credited $%s referral bonus to referrer %s (%s) for order %s",
                                ref_bonus, referrer.get("email"), referred_by_id, order_id)

    # 4. Mark order verified
    order["status"] = "verified"
    order["verified_at"] = now.isoformat().replace("+00:00", "Z")
    order["verified_by"] = verified_by
    order["license_key"] = license_key
    save_db(DB)

    # 5. Send license key via email
    email_res = _send_license_email(order["user_email"], license_key, order["package_name"], days)
    logger.info("Order %s verified by %s. License %s assigned to %s (Email: %s)",
                order_id, verified_by, license_key, order["user_email"], email_res)
    return True, license_key, email_res


@app.route("/api/packages", methods=["GET"])
def api_get_packages():
    """Return available packages."""
    return jsonify({"success": True, "packages": PACKAGES})


@app.route("/api/orders/create", methods=["POST"])
def api_create_order():
    """Create a new payment order for a package."""
    if not is_logged_in():
        return jsonify({"success": False, "error": "Not logged in"}), 401

    user = current_user()
    if not user:
        return jsonify({"success": False, "error": "User not found"}), 404

    sub = check_subscription(user)
    if sub["active"]:
        return jsonify({"success": False, "error": "You already have an active subscription"})

    # Check if user already has a pending/submitted order
    for oid, o in DB.get("orders", {}).items():
        if o["user_id"] == user["id"] and o["status"] in ("pending", "submitted"):
            _pl = {"success": True, "order_id": oid,
                   "message": "You already have an active order", "existing": True}
            try:
                _pl.update({k: v for k, v in _wallet_payload().items() if k != "success"})
            except Exception:
                pass
            return jsonify(_pl)

    data = request.get_json(force=True)
    package_id = data.get("package")
    if package_id not in PACKAGES:
        return jsonify({"success": False, "error": "Invalid package selected"})

    pkg = PACKAGES[package_id]
    order_id = "ORD-" + secrets.token_hex(4).upper()
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    order = {
        "id": order_id,
        "user_id": user["id"],
        "user_email": user["email"],
        "user_name": user.get("name", ""),
        "package_id": package_id,
        "package_name": pkg["name"],
        "amount": pkg["price"],
        "currency": pkg["currency"],
        "days": pkg["days"],
        "status": "pending",
        "tx_hash": "",
        "screenshot": "",
        "created_at": now,
        "submitted_at": None,
        "verified_at": None,
        "license_key": None,
        "rejection_reason": "",
    }

    DB.setdefault("orders", {})[order_id] = order
    save_db(DB)

    logger.info("Order %s created: %s by %s ($%d)", order_id, pkg["name"], user["email"], pkg["price"])
    _pl = {"success": True, "order_id": order_id, "order": order}
    try:
        _pl.update({k: v for k, v in _wallet_payload().items() if k != "success"})
    except Exception:
        pass
    return jsonify(_pl)


@app.route("/api/orders/quick-buy", methods=["POST"])
def api_quick_buy():
    """Handle 1-click order creation from Homepage for visitors or existing users."""
    data = request.get_json(force=True) or {}
    package_id = data.get("package")
    if package_id not in PACKAGES:
        return jsonify({"success": False, "error": "Invalid package selected"}), 400

    pkg = PACKAGES[package_id]

    # If user is already logged in:
    if is_logged_in():
        user = current_user()
        if not user:
            session.clear()
            return jsonify({"success": False, "error": "Session expired. Please log in again."}), 401
    else:
        email = _norm_email(data.get("email"))
        password = data.get("password") or ""
        if not email or not password:
            return jsonify({"success": False, "error": "Email and password are required"}), 400
        if "@" not in email or "." not in email:
            return jsonify({"success": False, "error": "Please enter a valid email address"}), 400

        # Rate limit quick-buy password verification per real client IP + email
        client_ip = _client_ip()
        if not _check_rate_limit(f"quick_buy:{client_ip}:{email}", max_requests=8, window_seconds=300):
            return jsonify({"success": False, "error": "Too many attempts. Please wait 5 minutes."}), 429

        # Check all records matching this email (don't stop on a passwordless duplicate)
        matches = _find_users_by_email(email)
        if matches:
            user = None
            for cand in matches:
                if verify_password(password, cand.get("password_hash", "")):
                    user = cand
                    break
            if not user:
                return jsonify({"success": False, "error": "This email already has an account. Please enter the correct password for this email."}), 401
            if user.get("banned"):
                return jsonify({"success": False, "error": "Account suspended. Please contact support."}), 403
            canonical_id = _dedupe_users_by_email(user["id"])
            user = DB["users"].get(canonical_id, user)
        else:
            # Create brand new user (same minimum as normal signup)
            if len(password) < 8:
                return jsonify({"success": False, "error": "Password must be at least 8 characters"}), 400

            user_id = str(uuid.uuid4())
            referral_code = user_id[:8].upper()
            now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

            ref_by_code = (data.get("referral_code") or session.get("referral_code") or "").strip().upper()
            referred_by = None
            if ref_by_code:
                for u in DB["users"].values():
                    if u.get("referral_code") == ref_by_code:
                        referred_by = u["id"]
                        break

            subscription = {
                "plan": "none",
                "status": "inactive",
                "started_at": now,
                "expires_at": None,
            }

            user = {
                "id": user_id,
                "email": email,
                "name": (data.get("name") or "").strip() or email.split("@")[0],
                "password_hash": hash_password(password),
                "role": "user",
                "banned": False,
                "created_at": now,
                "subscription": subscription,
                "license_key": None,
                "referral_code": referral_code,
                "referred_by": referred_by,
                "referral_earnings": 0.0,
                "referral_history": [],
                "bot_config": _default_bot_config(["BTCUSDT"]),
            }
            DB["users"][user_id] = user
            save_db(DB)

        session.pop("admin_authenticated", None)
        session["user_id"] = user["id"]
        session.permanent = True

    sub = check_subscription(user)
    if sub["active"]:
        return jsonify({"success": True, "redirect": "/bot/", "message": "You already have an active subscription"})

    # Check for existing pending/submitted order for this user
    for oid, o in DB.get("orders", {}).items():
        if o["user_id"] == user["id"] and o["status"] in ("pending", "submitted"):
            _pl = {"success": True, "order_id": oid, "redirect": f"/payment/{oid}", "existing": True}
            try:
                _pl.update({k: v for k, v in _wallet_payload().items() if k != "success"})
            except Exception:
                pass
            return jsonify(_pl)

    order_id = "ORD-" + secrets.token_hex(4).upper()
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    order = {
        "id": order_id,
        "user_id": user["id"],
        "user_email": user["email"],
        "user_name": user.get("name", ""),
        "package_id": package_id,
        "package_name": pkg["name"],
        "amount": pkg["price"],
        "currency": pkg["currency"],
        "days": pkg["days"],
        "status": "pending",
        "tx_hash": "",
        "screenshot": "",
        "created_at": now,
        "submitted_at": None,
        "verified_at": None,
        "license_key": None,
        "rejection_reason": "",
    }
    DB.setdefault("orders", {})[order_id] = order
    save_db(DB)
    logger.info("Quick buy order %s created: %s for %s ($%d)", order_id, pkg["name"], user["email"], pkg["price"])
    _pl = {"success": True, "order_id": order_id, "redirect": f"/payment/{order_id}"}
    try:
        _pl.update({k: v for k, v in _wallet_payload().items() if k != "success"})
    except Exception:
        pass
    return jsonify(_pl)


@app.route("/api/orders/submit", methods=["POST"])
def api_submit_order():
    """User submits payment proof (transaction hash + optional screenshot)."""
    if not is_logged_in():
        return jsonify({"success": False, "error": "Not logged in"}), 401

    user = current_user()
    if not user:
        return jsonify({"success": False, "error": "User not found"}), 404

    order_id = request.form.get("order_id", "").strip()
    tx_hash = request.form.get("tx_hash", "").strip()
    screenshot_file = request.files.get("screenshot")

    if not order_id:
        return jsonify({"success": False, "error": "Order ID required"})
    if not tx_hash:
        return jsonify({"success": False, "error": "Transaction hash is required"})

    order = DB.get("orders", {}).get(order_id)
    if not order or order["user_id"] != user["id"]:
        return jsonify({"success": False, "error": "Order not found"})
    if order.get("status") == "verified":
        return jsonify({
            "success": True,
            "verified": True,
            "message": "Order already verified!",
            "license_key": order.get("license_key"),
            "redirect": "/bot/",
        })
    if order["status"] not in ("pending", "submitted"):
        return jsonify({"success": False, "error": "Order cannot be modified (already processed)"})

    # Save screenshot file if provided
    screenshot_path = order.get("screenshot", "")
    if screenshot_file and screenshot_file.filename:
        allowed_exts = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
        _magic_signatures = [
            (b"\xff\xd8\xff", ".jpg"),        # JPEG
            (b"\x89PNG\r\n\x1a\n", ".png"),   # PNG
            (b"GIF87a", ".gif"),               # GIF87
            (b"GIF89a", ".gif"),               # GIF89
            (b"RIFF", ".webp"),                # WebP (4-byte prefix)
        ]
        ext = Path(screenshot_file.filename).suffix.lower()
        if ext in allowed_exts:
            screenshot_file.seek(0, 2)
            size = screenshot_file.tell()
            screenshot_file.seek(0)
            if size <= 5 * 1024 * 1024:
                header = screenshot_file.read(16)
                screenshot_file.seek(0)
                _magic_ok = any(header.startswith(sig) for sig, _ in _magic_signatures)
                if _magic_ok:
                    filename = f"{order_id}_{secrets.token_hex(4)}{ext}"
                    save_path = UPLOAD_DIR / filename
                    screenshot_file.save(str(save_path))
                    screenshot_path = filename

    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    order["tx_hash"] = tx_hash
    order["screenshot"] = screenshot_path
    order["status"] = "submitted"
    order["submitted_at"] = now
    save_db(DB)

    # Automated Blockchain Verification (atomic: verify + activate + txid record
    # under one lock so two concurrent calls can never double-activate or let one
    # tx_hash fund two orders)
    with _payment_lock:
        verified, note = _verify_tx_blockchain(tx_hash, float(order.get("amount", 79)))
        if verified:
            _, lic_key, _email_res = _activate_order_and_credit_referral(order, verified_by="auto_blockchain")
            clean_tx = tx_hash.strip().lower()
            clean_tx_no_0x = clean_tx[2:] if clean_tx.startswith("0x") else clean_tx
            DB.setdefault("used_txids", {})[clean_tx] = order_id
            DB["used_txids"][clean_tx_no_0x] = order_id
            save_db(DB)
            logger.info("Order %s AUTO-VERIFIED on blockchain for %s: %s", order_id, user["email"], note)
            return jsonify({
                "success": True,
                "verified": True,
                "auto_verified": True,
                "message": "Payment verified on blockchain! Your Bot has been activated.",
                "license_key": lic_key,
                "redirect": "/bot/",
            })

    logger.info("Order %s submitted by %s (tx=%s) - blockchain status: %s", order_id, user["email"], tx_hash[:20], note)
    return jsonify({
        "success": True,
        "verified": False,
        "message": "Payment proof submitted! Blockchain verification in progress (usually 1-2 minutes). If already confirmed on exchange, please wait a moment."
    })


@app.route("/api/orders/check-verification/<order_id>", methods=["POST", "GET"])
def api_check_order_verification(order_id):
    """Check blockchain status or re-verify order on the fly."""
    if not is_logged_in():
        return jsonify({"success": False, "error": "Not logged in"}), 401

    user = current_user()
    if not user:
        return jsonify({"success": False, "error": "User not found"}), 404

    order = DB.get("orders", {}).get(order_id)
    if not order or order["user_id"] != user["id"]:
        return jsonify({"success": False, "error": "Order not found"}), 404

    if order.get("status") == "verified":
        return jsonify({
            "success": True,
            "verified": True,
            "license_key": order.get("license_key"),
            "redirect": "/bot/",
        })

    tx_hash = order.get("tx_hash", "").strip()
    if tx_hash and order.get("status") == "submitted":
        with _payment_lock:
            verified, note = _verify_tx_blockchain(tx_hash, float(order.get("amount", 79)))
            if verified:
                _, lic_key, _email_res = _activate_order_and_credit_referral(order, verified_by="auto_blockchain")
                clean_tx = tx_hash.strip().lower()
                clean_tx_no_0x = clean_tx[2:] if clean_tx.startswith("0x") else clean_tx
                DB.setdefault("used_txids", {})[clean_tx] = order_id
                DB["used_txids"][clean_tx_no_0x] = order_id
                save_db(DB)
                logger.info("Order %s AUTO-VERIFIED on re-poll for %s: %s", order_id, user["email"], note)
                return jsonify({
                    "success": True,
                    "verified": True,
                    "license_key": lic_key,
                    "redirect": "/bot/",
                })

    return jsonify({
        "success": True,
        "verified": False,
        "status": order.get("status", "pending")
    })


@app.route("/api/orders/my", methods=["GET"])
def api_my_orders():
    """Get all orders for the current user."""
    if not is_logged_in():
        return jsonify({"success": False, "error": "Not logged in"}), 401
    user = current_user()
    if not user:
        return jsonify({"success": False, "error": "User not found"}), 404

    orders = [o for o in DB.get("orders", {}).values() if o["user_id"] == user["id"]]
    orders.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return jsonify({"success": True, "orders": orders})


@app.route("/uploads/<filename>")
def serve_upload(filename):
    """Serve uploaded payment screenshots (auth required)."""
    if not is_logged_in():
        return jsonify({"success": False, "error": "Not logged in"}), 401
    user = current_user()
    is_admin_user = user and user.get("role") == "admin"

    # Non-admin users can only see their own order screenshots
    if not is_admin_user:
        found = False
        for o in DB.get("orders", {}).values():
            if o.get("screenshot") == filename and o["user_id"] == user["id"]:
                found = True
                break
        if not found:
            return jsonify({"success": False, "error": "Access denied"}), 403

    from flask import send_from_directory
    return send_from_directory(str(UPLOAD_DIR), filename)

# ============================================================
# Admin Order Management
# ============================================================

@app.route("/api/admin/orders", methods=["GET"])
def api_admin_orders():
    """Admin: list all payment orders."""
    if not is_admin():
        return jsonify({"success": False, "error": "Admin access required"}), 403

    orders = list(DB.get("orders", {}).values())
    for o in orders:
        u = DB["users"].get(o.get("user_id"), {})
        o["user_name"] = u.get("name", "")
        o["user_email"] = u.get("email", "")
    orders.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return jsonify({"success": True, "orders": orders})


@app.route("/api/admin/orders/verify", methods=["POST"])
def api_admin_verify_order():
    """Admin: verify a payment order and auto-generate + assign license key."""
    if not is_admin():
        return jsonify({"success": False, "error": "Admin access required"}), 403

    data = request.get_json(force=True)
    order_id = data.get("order_id", "").strip()
    custom_days = data.get("days")

    order = DB.get("orders", {}).get(order_id)
    if not order:
        return jsonify({"success": False, "error": "Order not found"})
    if order["status"] not in ("submitted", "pending"):
        return jsonify({"success": False, "error": "Order already processed"})

    _, license_key, email_res = _activate_order_and_credit_referral(order, custom_days=custom_days, verified_by="admin")

    return jsonify({
        "success": True,
        "license_key": license_key,
        "email_sent": email_res.get("success", False) if isinstance(email_res, dict) else False,
        "email_error": email_res.get("error", "") if isinstance(email_res, dict) else "",
        "message": f"Order verified! License: {license_key}",
    })


@app.route("/api/admin/smtp", methods=["GET", "POST"])
def api_admin_smtp():
    """Admin: view or save SMTP settings in DB."""
    if not is_admin():
        return jsonify({"success": False, "error": "Admin access required"}), 403

    if request.method == "POST":
        data = request.get_json(force=True)
        user = str(data.get("user") or data.get("username") or "").strip()
        password = str(data.get("pass") or data.get("password") or "").strip()
        server = str(data.get("server") or data.get("host") or "smtp.gmail.com").strip()
        sender_name = str(data.get("sender_name") or "Weexionic Trading Bot").strip()
        from_email = str(data.get("from_email") or user).strip()
        try:
            port = int(data.get("port") or 587)
        except (ValueError, TypeError):
            port = 587

        settings = DB.setdefault("settings", {})
        smtp = settings.setdefault("smtp", {})
        if user:
            smtp["user"] = user
        if password:
            smtp["pass"] = password
        smtp["server"] = server
        smtp["host"] = server
        smtp["port"] = port
        smtp["sender_name"] = sender_name
        smtp["from_email"] = from_email
        save_db(DB)
        logger.info("Admin updated SMTP settings: user=%s, server=%s:%s", user, server, port)
        return jsonify({"success": True, "message": "SMTP settings saved successfully!"})

    # GET
    cfg = _get_smtp_config()
    smtp_data = {
        "configured": bool(cfg["user"] and cfg["pass"]),
        "user": cfg["user"],
        "server": cfg["server"],
        "host": cfg["server"],
        "port": cfg["port"],
        "source": cfg.get("source", "not_configured"),
        "sender_name": cfg.get("sender_name", "Weexionic Trading Bot"),
        "from_email": cfg.get("from_email", cfg["user"]),
        "has_pass": bool(cfg["pass"]),
    }
    return jsonify({
        "success": True,
        "smtp": smtp_data,
        **smtp_data
    })


@app.route("/api/admin/users/reset-link", methods=["POST"])
def api_admin_user_reset_link():
    """Admin: generate a single-use password reset link for a user (and email if SMTP configured)."""
    if not is_admin():
        return jsonify({"success": False, "error": "Admin access required"}), 403

    data = request.get_json(force=True, silent=True) or {}
    user_id = str(data.get("user_id") or "").strip()
    email_arg = _norm_email(data.get("email"))
    user = DB.get("users", {}).get(user_id) if user_id else None
    if not user and email_arg:
        matches = _find_users_by_email_tolerant(email_arg)
        if matches:
            user = max(matches, key=lambda item: _user_richness_score(item))
    if not user:
        return jsonify({"success": False, "error": "User not found"}), 404

    target_email = _norm_email(user.get("email"))
    if not target_email:
        return jsonify({"success": False, "error": "User does not have an email address"}), 400

    user, target_email, _, reset_url = _issue_password_reset_token(user)

    smtp_cfg = _get_smtp_config()
    email_sent = False
    email_error = "SMTP not configured"
    if smtp_cfg.get("user") and smtp_cfg.get("pass"):
        res = _send_password_reset_email(target_email, reset_url, user.get("name", ""))
        email_sent = bool(res.get("success"))
        email_error = "" if email_sent else str(res.get("error") or "SMTP send failed")

    logger.info("Admin issued reset link for %s (email_sent=%s)", target_email, email_sent)
    return jsonify({
        "success": True,
        "email": target_email,
        "reset_url": reset_url,
        "email_sent": email_sent,
        "email_error": email_error,
    })


@app.route("/api/admin/smtp/test", methods=["POST"])
def api_admin_test_smtp():
    """Admin: send a test email to verify SMTP configuration."""
    if not is_admin():
        return jsonify({"success": False, "error": "Admin access required"}), 403

    data = request.get_json(force=True)
    test_to = str(data.get("to") or data.get("to_email") or "").strip()
    if not test_to or "@" not in test_to:
        return jsonify({"success": False, "error": "Please enter a valid recipient email address."})

    custom_user = str(data.get("user") or data.get("username") or "").strip()
    custom_pass = str(data.get("pass") or data.get("password") or "").strip()
    custom_server = str(data.get("server") or data.get("host") or "").strip()
    custom_port = data.get("port")

    smtp_cfg = _get_smtp_config()
    override = {
        "user": custom_user or smtp_cfg["user"],
        "pass": custom_pass or smtp_cfg["pass"],
        "server": custom_server or smtp_cfg["server"],
        "host": custom_server or smtp_cfg["server"],
        "port": custom_port or smtp_cfg["port"],
    }
    if not override["user"] or not override["pass"]:
        return jsonify({"success": False, "error": "SMTP User and App Password are missing. Configure them first."})

    plain_body = (
        f"Hello,\n\n"
        f"This is a live test email from Weexionic Trading Bot.\n"
        f"Your SMTP settings are working perfectly!\n\n"
        f"Connected Server: {override['server']}:{override['port']}\n"
        f"Sender Email: {override['user']}\n"
        f"Configuration Source: {smtp_cfg.get('source', 'configured')}\n"
        f"Timestamp (UTC): {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n\n"
        f"Weexionic Trading System is ready to dispatch license keys and password reset links automatically."
    )
    res = _send_email_smtp(test_to, "[Weexionic] SMTP Test Email Successful", plain_body, smtp_override=override)
    if res.get("success"):
        return jsonify({"success": True, "message": f"Test email sent successfully to {test_to}!"})
    return jsonify({"success": False, "error": f"SMTP Error: {res.get('error', 'Unknown SMTP error')}"})


@app.route("/api/admin/orders/reject", methods=["POST"])
def api_admin_reject_order():
    """Admin: reject a payment order."""
    if not is_admin():
        return jsonify({"success": False, "error": "Admin access required"}), 403

    data = request.get_json(force=True)
    order_id = data.get("order_id", "").strip()
    reason = data.get("reason", "Payment could not be verified. Please contact support.").strip()

    order = DB.get("orders", {}).get(order_id)
    if not order:
        return jsonify({"success": False, "error": "Order not found"})
    if order["status"] not in ("submitted", "pending"):
        return jsonify({"success": False, "error": "Order already processed"})

    order["status"] = "rejected"
    order["rejection_reason"] = reason
    order["verified_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    save_db(DB)

    logger.info("Order %s REJECTED. Reason: %s", order_id, reason)
    return jsonify({"success": True, "message": f"Order rejected: {reason}"})


@app.route("/api/admin/wallet", methods=["GET", "POST"])
def api_admin_wallet():
    """Admin: get or update the payment wallet addresses."""
    if not is_admin():
        return jsonify({"success": False, "error": "Admin access required"}), 403

    global WALLET_ADDRESS, WALLET_NETWORK, WALLET_TRC20, WALLET_BEP20
    if request.method == "GET":
        return jsonify({
            "success": True,
            "wallet": WALLET_ADDRESS,
            "network": WALLET_NETWORK,
            "wallet_trc20": WALLET_TRC20,
            "wallet_bep20": WALLET_BEP20,
        })

    data = request.get_json(force=True)
    if data.get("wallet_trc20"):
        WALLET_TRC20 = data["wallet_trc20"].strip()
        WALLET_ADDRESS = WALLET_TRC20
    if data.get("wallet_bep20"):
        WALLET_BEP20 = data["wallet_bep20"].strip()
    if data.get("wallet"):
        WALLET_ADDRESS = data["wallet"].strip()
    if data.get("network"):
        WALLET_NETWORK = data["network"].strip()
    # Persist wallets so they survive restarts (previously runtime-only globals:
    # a wallet change was lost on restart and users could pay a stale address)
    # Written in BOTH storage shapes so every reader (old/new) finds its format.
    DB.setdefault("settings", {})["wallets"] = {
        "trc20": WALLET_TRC20,
        "bep20": WALLET_BEP20,
        "network": WALLET_NETWORK,
    }
    DB["settings"]["payment_wallets"] = {
        "wallet_trc20": WALLET_TRC20,
        "wallet_bep20": WALLET_BEP20,
        "network": WALLET_NETWORK,
    }
    save_db(DB)
    return jsonify({
        "success": True,
        "wallet": WALLET_ADDRESS,
        "network": WALLET_NETWORK,
        "wallet_trc20": WALLET_TRC20,
        "wallet_bep20": WALLET_BEP20,
    })


# ============================================================
# Admin Referral Payout Management
# ============================================================

@app.route("/api/admin/payouts", methods=["GET"])
def api_admin_payouts():
    """Admin: list all referral withdrawal/payout requests."""
    if not is_admin():
        return jsonify({"success": False, "error": "Admin access required"}), 403

    payouts = []
    for u in DB.get("users", {}).values():
        for p in u.get("payout_requests", []):
            item = dict(p)
            item["user_id"] = u["id"]
            item["user_email"] = u.get("email", "")
            item["user_name"] = u.get("name", "")
            payouts.append(item)

    payouts.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return jsonify({"success": True, "payouts": payouts})


@app.route("/api/admin/payouts/approve", methods=["POST"])
def api_admin_approve_payout():
    """Admin: mark a referral payout as completed/paid."""
    if not is_admin():
        return jsonify({"success": False, "error": "Admin access required"}), 403

    data = request.get_json(force=True)
    payout_id = data.get("payout_id", "").strip()
    tx_hash = data.get("tx_hash", "").strip()

    if not payout_id:
        return jsonify({"success": False, "error": "Payout ID required"})

    found = False
    for u in DB.get("users", {}).values():
        for p in u.get("payout_requests", []):
            if p.get("id") == payout_id:
                p["status"] = "paid"
                p["paid_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                if tx_hash:
                    p["tx_hash"] = tx_hash
                found = True
                break
        if found:
            break

    if not found:
        return jsonify({"success": False, "error": "Payout request not found"})

    save_db(DB)
    logger.info("Admin approved referral payout %s (tx=%s)", payout_id, tx_hash)
    return jsonify({"success": True, "message": f"Payout {payout_id} marked as paid!"})

# ============================================================
# Fix 11: Security Headers Middleware
# ============================================================

@app.after_request
def _add_security_headers(response):
    """Add standard security headers to every response."""
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    # Don't cache API responses
    if request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        response.headers["Pragma"] = "no-cache"
    return response

# ============================================================
# Graceful Shutdown
# ============================================================

def _shutdown_handler(signum, frame):
    """Gracefully stop all bot-engine processes on shutdown."""
    logger.info("Shutdown signal received - stopping all bot-engine processes...")
    for user_id in list(DB.get("bot_processes", {}).keys()):
        stop_user_bot(user_id)
    # Close all log handles
    for uid in list(_bot_log_handles.keys()):
        _close_log_handle(uid)
    sys.exit(0)

signal.signal(signal.SIGTERM, _shutdown_handler)
signal.signal(signal.SIGINT, _shutdown_handler)

# ============================================================
# Watchdog Monitor (runs in background for Gunicorn & standalone)
# ============================================================

WATCHDOG_MAX_RESTARTS = 5
_watchdog_restart_counts: dict[str, int] = {}
_watchdog_lock_file = None

def _is_watchdog_leader() -> bool:
    global _watchdog_lock_file
    try:
        lock_path = BASE_DIR / ".watchdog.lock"
        _watchdog_lock_file = open(lock_path, "w")
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(_watchdog_lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(_watchdog_lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except Exception:
        return False

def _watchdog():
    # Only single leader process across Gunicorn workers executes the watchdog loop
    if not _is_watchdog_leader():
        return
    logger.info("Watchdog thread started - monitoring bot-engine processes")
    while True:
        try:
            for user_id, proc_info in list(DB.get("bot_processes", {}).items()):
                if not proc_info.get("should_run", False):
                    continue

                pid = proc_info.get("pid")
                if not pid:
                    continue

                if not is_process_alive(pid):
                    # Check restart count
                    restart_count = _watchdog_restart_counts.get(user_id, 0)
                    if restart_count >= WATCHDOG_MAX_RESTARTS:
                        logger.error("Watchdog: user %s exceeded max restarts (%d). Stopping.",
                                   user_id, WATCHDOG_MAX_RESTARTS)
                        DB.get("bot_processes", {}).pop(user_id, None)
                        save_db(DB)
                        continue

                    logger.warning("Watchdog: bot-engine died for user %s, restarting... (attempt %d/%d)",
                                  user_id, restart_count + 1, WATCHDOG_MAX_RESTARTS)
                    old_port = proc_info.get("port")
                    DB.get("bot_processes", {}).pop(user_id, None)
                    save_db(DB)

                    result = ensure_bot_engine_running(user_id)
                    if result["success"]:
                        _watchdog_restart_counts[user_id] = restart_count + 1
                        logger.info("Watchdog: restarted bot-engine for user %s on port %s",
                                   user_id, result['port'])
                    else:
                        _watchdog_restart_counts[user_id] = restart_count + 1
                        logger.error("Watchdog: failed to restart for %s: %s",
                                    user_id, result.get("error"))
        except Exception as e:
            logger.error("Watchdog error: %s", e)

        time.sleep(30)

# Start watchdog in background thread (daemon)
_watchdog_thread = _threading.Thread(target=_watchdog, daemon=True)
_watchdog_thread.start()

# ============================================================
# Mobile API — JWT layer for the native mobile clients
# (same accounts, no admin surface, bot plane proxied server-side)
# ============================================================
from mobile_api import mobile_bp, init_module as mobile_init, mobile_verify_token

mobile_init(
    db=DB,
    save_db=save_db,
    rate_limit=_check_rate_limit,
    client_ip=_client_ip,
    dedupe_user=_dedupe_users_by_email,
    forgot_password=_create_and_send_password_reset,
    encrypt=encrypt,
    decrypt=decrypt,
    decrypt_checked=decrypt_checked,
    verify_password=verify_password,
    check_subscription=check_subscription,
    proxy_to_bot=proxy_to_bot,
    get_bot_status=get_bot_status,
    write_bot_config=write_user_bot_config,
    ensure_bot=ensure_bot_engine_running,
    start_bot=start_user_bot,
    stop_bot=stop_user_bot,
    flask_secret=_flask_secret,
    packages=PACKAGES,
    verify_tx=_verify_tx_blockchain,
    activate_order=_activate_order_and_credit_referral,
    payment_lock=_payment_lock,
    payout_lock=_payout_lock,
    wallet_trc20=WALLET_TRC20,
    wallet_bep20=WALLET_BEP20,
)
app.register_blueprint(mobile_bp)
logger.info("Mobile API registered: /api/mobile/* (JWT bearer, admin-free)")

# ============================================================
# Entry point (for standalone development execution)
# ============================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    host = os.environ.get("HOST", "0.0.0.0")
    logger.info("SaaS webapp running on port %d", port)
    from werkzeug.serving import run_simple
    run_simple(host, port, app, use_reloader=False, use_debugger=False, threaded=True)
