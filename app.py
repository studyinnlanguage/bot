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
import threading as _threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from flask import Flask, jsonify, render_template, request, Response, session, redirect, url_for
import urllib.request
import urllib.error
import requests as req_lib

# ============================================================
# Setup
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
BOT_ENGINE_DIR = BASE_DIR / "bot-engine"
DB_FILE = BASE_DIR / "database.json"

# PostgreSQL is the PRIMARY database when DATABASE_URL is set
# (recommended on Railway / VPS). Without it, the app transparently
# falls back to the local database.json file so it still runs anywhere.
# 'bot_processes' is runtime-only state (pid/port) and is never persisted.
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    psycopg2 = None
    psycopg2.extras = None
PG_ENABLED = bool(DATABASE_URL) and psycopg2 is not None
LOG_DIR = BASE_DIR / "logs"
USER_CONFIGS_DIR = BASE_DIR / "user_configs"
USER_INSTANCES_DIR = BASE_DIR / "user_instances"
LOG_DIR.mkdir(exist_ok=True)
USER_CONFIGS_DIR.mkdir(exist_ok=True)
USER_INSTANCES_DIR.mkdir(exist_ok=True)

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
app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET", secrets.token_hex(32))
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=7)

# ============================================================
# Configuration
# ============================================================

# Admin password - MUST be set via ADMIN_SECRET env var.
# No default. If not set, admin login is DISABLED.
ADMIN_SECRET = os.environ.get("ADMIN_SECRET", "")
if not ADMIN_SECRET:
    logger.error("ADMIN_SECRET env var NOT SET! Admin panel login is DISABLED.")
    logger.error("Set it like:  set ADMIN_SECRET=your_password  (Windows)")
    logger.error("          or:  export ADMIN_SECRET=your_password  (Linux/Mac)")

# Encryption key for API keys (32 bytes, base64-encoded for Fernet)
_ENCRYPTION_RAW = os.environ.get("ENCRYPTION_KEY", "tradebot-cloud-encryption-key-CHANGE-ME-32-chars")
# Derive a valid 32-byte key
_ENCRYPTION_KEY_BYTES = hashlib.sha256(_ENCRYPTION_RAW.encode("utf-8")).digest()

# Port range for per-user bot-engine instances
PORT_START = 5001
PORT_END = 5999

# Payment wallet (set via env vars in production)
WALLET_ADDRESS = os.environ.get("PAYMENT_WALLET", "YOUR_USDT_WALLET_ADDRESS_HERE")
WALLET_NETWORK = os.environ.get("PAYMENT_NETWORK", "TRC20 (USDT)")

# Google OAuth (set via env vars)
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.environ.get("GOOGLE_REDIRECT_URI", "")

# SaaS email (for sending license keys to users after payment verification)
SAAS_SMTP_SERVER = os.environ.get("SAAS_SMTP_SERVER", "smtp.gmail.com")
SAAS_SMTP_PORT = int(os.environ.get("SAAS_SMTP_PORT", 587))
SAAS_SMTP_USER = os.environ.get("SAAS_SMTP_USER", "")
SAAS_SMTP_PASS = os.environ.get("SAAS_SMTP_PASS", "")

# Upload directory for payment screenshots
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

# Package definitions
PACKAGES = {
    "monthly": {"name": "Monthly", "price": 29, "days": 30, "currency": "USDT", "popular": False},
    "yearly": {"name": "Yearly", "price": 79, "days": 365, "currency": "USDT", "popular": True},
    "lifetime": {"name": "Lifetime", "price": 499, "days": 9999, "currency": "USDT", "popular": False},
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

def decrypt(cipher_text: str) -> str:
    if not cipher_text:
        return ""
    try:
        f = _get_fernet()
        return f.decrypt(cipher_text.encode("utf-8")).decode("utf-8")
    except Exception as e:
        logger.error("Decryption failed: %s", e)
        return ""

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    hashed = hashlib.sha256((salt + password).encode()).hexdigest()
    return f"{salt}${hashed}"

def verify_password(password: str, stored: str) -> bool:
    try:
        salt, hashed = stored.split("$")
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
                        subscription JSONB DEFAULT '{}'::jsonb,
                        license_key VARCHAR(50),
                        referral_code VARCHAR(50),
                        referred_by VARCHAR(36),
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
                    "subscription": "JSONB DEFAULT '{}'::jsonb",
                    "license_key": "VARCHAR(50)",
                    "referral_code": "VARCHAR(50)",
                    "referred_by": "VARCHAR(36)",
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
    db = {"users": {}, "licenses": {}, "orders": {}, "bot_processes": {}}
    if DB_FILE.exists():
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            for section in ("users", "licenses", "orders"):
                db[section] = data.get(section, {})
            logger.info("Loaded database.json (%d users)", len(db["users"]))
        except (json.JSONDecodeError, OSError) as e:
            logger.error("DB load failed: %s", e)
    return db

def _parse_json_column(val):
    if val is None:
        return {}
    if isinstance(val, dict):
        return val
    if isinstance(val, str):
        try:
            return json.loads(val)
        except json.JSONDecodeError:
            pass
    return {}

def _load_pg_db() -> dict:
    db = {"users": {}, "licenses": {}, "orders": {}, "bot_processes": {}}
    _pg_init()
    conn = _pg_connect()
    try:
        with conn.cursor() as cur:
            # Load users
            cur.execute("SELECT id, email, name, password_hash, role, banned, created_at, subscription, license_key, referral_code, referred_by, bot_config FROM users")
            user_rows = cur.fetchall()
            for r in user_rows:
                db["users"][r[0]] = {
                    "id": r[0],
                    "email": r[1],
                    "name": r[2],
                    "password_hash": r[3],
                    "role": r[4],
                    "banned": r[5],
                    "created_at": r[6],
                    "subscription": _parse_json_column(r[7]),
                    "license_key": r[8],
                    "referral_code": r[9],
                    "referred_by": r[10],
                    "bot_config": _parse_json_column(r[11])
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

def load_db() -> dict:
    """Load the DB — PostgreSQL when available, else database.json."""
    if PG_ENABLED:
        try:
            db = _load_pg_db()
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
                        # 1. Sync Users
                        user_ids = []
                        for uid, u in (db.get("users") or {}).items():
                            user_ids.append(uid)
                            cur.execute("""
                                INSERT INTO users (id, email, name, password_hash, role, banned, created_at, subscription, license_key, referral_code, referred_by, bot_config)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                                ON CONFLICT (id) DO UPDATE SET
                                    email = EXCLUDED.email,
                                    name = EXCLUDED.name,
                                    password_hash = EXCLUDED.password_hash,
                                    role = EXCLUDED.role,
                                    banned = EXCLUDED.banned,
                                    created_at = EXCLUDED.created_at,
                                    subscription = EXCLUDED.subscription,
                                    license_key = EXCLUDED.license_key,
                                    referral_code = EXCLUDED.referral_code,
                                    referred_by = EXCLUDED.referred_by,
                                    bot_config = EXCLUDED.bot_config
                            """, (
                                u.get("id"),
                                u.get("email"),
                                u.get("name"),
                                u.get("password_hash"),
                                u.get("role", "user"),
                                u.get("banned", False),
                                u.get("created_at"),
                                psycopg2.extras.Json(u.get("subscription", {})),
                                u.get("license_key"),
                                u.get("referral_code"),
                                u.get("referred_by"),
                                psycopg2.extras.Json(u.get("bot_config", {}))
                            ))
                        if user_ids:
                            cur.execute("DELETE FROM users WHERE id NOT IN %s", (tuple(user_ids),))
                        else:
                            cur.execute("DELETE FROM users")

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
                return
            except Exception as e:
                logger.error("PostgreSQL save failed (%s) — writing database.json fallback", e)
        try:
            with open(DB_FILE, "w", encoding="utf-8") as f:
                json.dump(db, f, indent=2, ensure_ascii=False)
        except OSError as e:
            logger.error("DB save failed: %s", e)

DB = load_db()

# ============================================================
# Database Migration (runs once at startup)
# ============================================================

def _migrate_db():
    """Fix old users and add missing fields."""
    fixed = 0
    for uid, user in DB.get("users", {}).items():
        if user.get("role") == "admin":
            continue
        # Skip users who actually activated a license
        if user.get("license_key"):
            # Still add referral_code if missing
            if not user.get("referral_code"):
                user["referral_code"] = uid[:8].upper()
                fixed += 1
            continue
        sub = user.get("subscription", {})
        if not sub:
            continue
        expires_at = sub.get("expires_at")
        if not expires_at:
            # Add referral_code if missing
            if not user.get("referral_code"):
                user["referral_code"] = uid[:8].upper()
            continue
        # This user has an expires_at but never activated a license
        # — they were created by the old buggy code. Reset them.
        user["subscription"] = {
            "plan": "none",
            "status": "inactive",
            "started_at": sub.get("created_at", user.get("created_at", "")),
            "expires_at": None,
        }
        if not user.get("referral_code"):
            user["referral_code"] = uid[:8].upper()
        fixed += 1
    if fixed > 0:
        save_db(DB)
        logger.info("DB migration: fixed %d orphan user(s) with bogus expires_at", fixed)
    # Ensure 'orders' key exists
    if "orders" not in DB:
        DB["orders"] = {}
        save_db(DB)
        logger.info("DB migration: added 'orders' key")

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

# ============================================================
# Auth helpers
# ============================================================

def is_logged_in() -> bool:
    return "user_id" in session

def is_admin() -> bool:
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
        # Fall back to decrypted SaaS credentials only when the engine lost them.
        if not bot_config.get("api_key"):
            bot_config["api_key"] = decrypt(config.get("api_key_enc", ""))
        if not bot_config.get("api_secret"):
            bot_config["api_secret"] = decrypt(config.get("api_secret_enc", ""))
        if not bot_config.get("api_passphrase"):
            bot_config["api_passphrase"] = decrypt(config.get("api_passphrase_enc", ""))
    else:
        api_key = decrypt(config.get("api_key_enc", ""))
        api_secret = decrypt(config.get("api_secret_enc", ""))
        api_passphrase = decrypt(config.get("api_passphrase_enc", ""))

        bot_config = {
            "api_key": api_key,
            "api_secret": api_secret,
            "api_passphrase": api_passphrase,
            "exchange": config.get("exchange", "binance"),
            "testnet": config.get("testnet", True),
            "symbol": (config.get("symbols_list", ["BTCUSDT"]) or ["BTCUSDT"])[0],
            "symbols_list": config.get("symbols_list", ["BTCUSDT"]),
            "timeframe": config.get("timeframe", "5m"),
            "leverage": config.get("leverage", 10),
            "amount_mode": config.get("amount_mode", "fixed"),
            "amount": config.get("amount", 100),
            "amount_pct": config.get("amount_pct", 10),
            "stop_loss_pct": config.get("stop_loss_pct", 2),
            "take_profit_pct": config.get("take_profit_pct", 6),
            "tp_mode": config.get("tp_mode", "both"),
            "mode": config.get("mode", "both"),
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
        }
    if "auto_start" not in bot_config:
        bot_config["auto_start"] = False

    # Copy bot-engine files (always sync on start to run latest code)
    for item in BOT_ENGINE_DIR.iterdir():
        if item.name in ('logs', '__pycache__', 'config.json', 'config.json.bak',
                       '.local_activation.dat', '.admin_password.txt',
                       'licenses.json', 'crash.log', 'user_configs'):
            continue
        dest = user_bot_dir / item.name
        if item.is_dir():
            if dest.exists():
                shutil.rmtree(dest, ignore_errors=True)
            shutil.copytree(item, dest, ignore=shutil.ignore_patterns('__pycache__'))
        else:
            shutil.copy2(item, dest)

    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(bot_config, f, indent=2, ensure_ascii=False)

    (user_bot_dir / "logs").mkdir(exist_ok=True)
    return str(config_path)


def _sync_engine_config_to_db(user: dict, data: dict):
    """Mirror a bot-engine /api/config POST payload into the SaaS DB.

    Called by the proxy when the dashboard inside the iframe saves settings,
    so the SaaS DB no longer goes stale (root cause of 'bot forgets settings',
    leverage resets, amount-mode resets, etc.).
    """
    config = user.setdefault("bot_config", {})
    if "exchange" in data:
        config["exchange"] = "weex" if data["exchange"] == "weex" else "binance"
    if "testnet" in data:
        config["testnet"] = bool(data["testnet"])
    if data.get("api_key") and str(data["api_key"]).strip():
        config["api_key_enc"] = encrypt(str(data["api_key"]).strip())
    if data.get("api_secret") and str(data["api_secret"]).strip():
        config["api_secret_enc"] = encrypt(str(data["api_secret"]).strip())
    if "api_passphrase" in data:
        if data["api_passphrase"] and str(data["api_passphrase"]).strip():
            config["api_passphrase_enc"] = encrypt(str(data["api_passphrase"]).strip())
        elif data["api_passphrase"] == "":
            config["api_passphrase_enc"] = ""
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
        max_lev = 500 if config.get("exchange") == "weex" else 125
        config["leverage"] = max(1, min(max_lev, int(data.get("leverage") or config.get("leverage", 10))))
    except (TypeError, ValueError):
        pass
    try:
        if "amount" in data and data["amount"] is not None:
            config["amount"] = max(1, float(data["amount"]) or 100)
        if "amount_pct" in data and data["amount_pct"] is not None:
            config["amount_pct"] = max(1, min(100, float(data["amount_pct"]) or 10))
        if "stop_loss_pct" in data and data["stop_loss_pct"] is not None:
            sl = max(0.5, min(50, float(data["stop_loss_pct"]) or 2))
            config["stop_loss_pct"] = sl
            config["take_profit_pct"] = sl * 3
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

def _wait_for_bot_ready(port: int, timeout: float = 15.0) -> bool:
    """Poll the bot-engine /api/status until it responds (or timeout)."""
    import urllib.request as _ur
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with _ur.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(1)
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
                "env": {**os.environ, "PORT": str(port), "HOST": "127.0.0.1"},
                "stdout": log_handle,
                "stderr": subprocess.STDOUT,
            }
            if sys.platform == 'win32':
                popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | 0x00000008
            else:
                popen_kwargs["start_new_session"] = True

            proc = subprocess.Popen([sys.executable, "app.py"], **popen_kwargs)

            DB.setdefault("bot_processes", {})[user_id] = {
                "pid": proc.pid,
                "port": port,
                "started_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "should_run": True,
            }
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
                "env": {**os.environ, "PORT": str(port), "HOST": "127.0.0.1"},
                "stdout": log_handle,
                "stderr": subprocess.STDOUT,
            }
            if sys.platform == 'win32':
                popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | 0x00000008
            else:
                popen_kwargs["start_new_session"] = True

            proc = subprocess.Popen([sys.executable, "app.py"], **popen_kwargs)

            DB.setdefault("bot_processes", {})[user_id] = {
                "pid": proc.pid,
                "port": port,
                "started_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "should_run": True,
            }
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
    if not proc_info or not proc_info.get("pid"):
        return {"success": True, "message": "Bot not running"}

    pid = proc_info["pid"]
    kill_process(pid)
    _close_log_handle(user_id)

    proc_info["should_run"] = False
    DB.get("bot_processes", {}).pop(user_id, None)
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
        save_db(DB)
        return {"running": False}

def proxy_to_bot(user_id: str, method: str, path: str, body=None) -> dict:
    """Proxy a request to user's bot-engine instance."""
    status = get_bot_status(user_id)
    if not status["running"] or not status.get("port"):
        return {"success": False, "error": "Bot is not running"}

    try:
        url = f"http://127.0.0.1:{status['port']}{path}"
        data = json.dumps(body).encode("utf-8") if body and method != "GET" else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json")
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
def index():
    if request.args.get('logout') == '1':
        session.clear()
        return render_template("saas_login.html")

    if not is_logged_in():
        ref_code = request.args.get('ref', '')
        return render_template("saas_login.html", ref_code=ref_code)

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

@app.route("/admin")
def admin_panel():
    if is_admin():
        return render_template("saas_admin.html", admin_login_required=False)
    if is_logged_in():
        # Regular users must never see the admin panel (or its login form).
        return redirect("/")
    return render_template("saas_admin.html", admin_login_required=True)

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
    data = request.get_json(force=True)
    email = (data.get("email") or "").strip().lower()
    password = data.get("password", "")
    name = (data.get("name") or "").strip()

    if not email or not password:
        return jsonify({"success": False, "error": "Email and password are required"})
    if len(password) < 6:
        return jsonify({"success": False, "error": "Password must be at least 6 characters"})
    if "@" not in email or "." not in email:
        return jsonify({"success": False, "error": "Please enter a valid email address"})

    for u in DB["users"].values():
        if u.get("email") == email:
            return jsonify({"success": False, "error": "This email is already registered"})

    role = "user"
    user_id = str(uuid.uuid4())
    referral_code = user_id[:8].upper()
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    # Handle referral
    ref_by_code = (data.get("referral_code") or "").strip().upper()
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
        "bot_config": {
            "exchange": "binance",
            "testnet": True,
            "symbols_list": [],
            "timeframe": "5m",
            "leverage": 10,
            "amount_mode": "fixed",
            "amount": 100,
            "amount_pct": 10,
            "stop_loss_pct": 2,
            "take_profit_pct": 6,
            "tp_mode": "both",
            "mode": "both",
            "api_key_enc": "",
            "api_secret_enc": "",
            "api_passphrase_enc": "",
        },
    }
    DB["users"][user_id] = user
    save_db(DB)

    session["user_id"] = user_id
    session.permanent = True

    logger.info("New user signup: %s (role=%s)", email, role)

    return jsonify({
        "success": True,
        "user": {"id": user_id, "email": email, "name": user["name"], "role": role},
        "subscription": user["subscription"],
        "message": "Account created! Please activate your license key to get started.",
    })

def _dedupe_users_by_email(keep_id: str):
    """Merge duplicate user records sharing the same email into `keep_id`.

    A duplicate record is the ONLY way a user logging in with their own email
    can hit 'license already activated by another user': the login loop simply
    returns whichever same-email record comes first, and the license may be
    bound to the other record. Duplicates can appear if an account was ever
    created twice for the same email (Google auto-signup racing a manual
    signup, admin bootstrap, restored DB snapshot, etc.).
    """
    keep = DB["users"].get(keep_id)
    if not keep:
        return
    keep_email = (keep.get("email") or "").lower()
    for uid, u in list(DB["users"].items()):
        if uid == keep_id or (u.get("email") or "").lower() != keep_email:
            continue
        merged = False
        if u.get("license_key") and not keep.get("license_key"):
            keep["license_key"] = u["license_key"]
            lic = DB.get("licenses", {}).get(u["license_key"])
            if lic:
                lic["used_by"] = keep_id
            merged = True
        if (u.get("subscription") or {}).get("status") == "active" and \
                (keep.get("subscription") or {}).get("status") != "active":
            keep["subscription"] = u["subscription"]
            merged = True
        for k, v in (u.get("bot_config") or {}).items():
            if v and not keep.setdefault("bot_config", {}).get(k):
                keep["bot_config"][k] = v
                merged = True
        if merged:
            logger.info("Merged duplicate account %s (id=%s) into %s (id=%s)",
                        u.get("email"), uid, keep.get("email"), keep_id)
        del DB["users"][uid]
    save_db(DB)


@app.route("/api/auth/login", methods=["POST"])
def api_login():
    data = request.get_json(force=True)
    email = (data.get("email") or "").strip().lower()
    password = data.get("password", "")

    if not email or not password:
        return jsonify({"success": False, "error": "Email and password are required"})

    user = None
    for u in DB["users"].values():
        if u.get("email") == email:
            user = u
            break

    if not user or not verify_password(password, user.get("password_hash", "")):
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

    _dedupe_users_by_email(user["id"])

    session["user_id"] = user["id"]
    session.permanent = True

    logger.info("User login: %s (role=%s)", email, user.get('role'))

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
    return jsonify({"success": True})

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
    # Build referral link from the current request's host
    host = request.host
    referral_link = f"http://{host}/?ref={ref_code}" if ref_code else ""

    # Count how many users this person referred
    referral_count = sum(
        1 for u in DB["users"].values()
        if u.get("referred_by") == user["id"]
    )

    # Get referred users list
    referred_users = []
    for u in DB["users"].values():
        if u.get("referred_by") == user["id"]:
            referred_users.append({
                "email": u["email"],
                "name": u.get("name", ""),
                "created_at": u.get("created_at", ""),
                "has_license": bool(u.get("license_key")),
            })

    return jsonify({
        "success": True,
        "referral_code": ref_code,
        "referral_link": referral_link,
        "referral_count": referral_count,
        "referred_users": referred_users,
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
        config["exchange"] = "weex" if data["exchange"] == "weex" else "binance"
    if "testnet" in data:
        config["testnet"] = bool(data["testnet"])
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
        max_lev = 500 if config.get("exchange") == "weex" else 125
        config["leverage"] = max(1, min(max_lev, int(data["leverage"]) or 10))
    if "amount_mode" in data:
        config["amount_mode"] = "percent" if data["amount_mode"] == "percent" else "fixed"
    if "amount" in data:
        config["amount"] = max(1, float(data["amount"]) or 100)
    if "amount_pct" in data:
        config["amount_pct"] = max(1, min(100, float(data["amount_pct"]) or 10))
    if "stop_loss_pct" in data:
        sl = max(0.5, min(50, float(data["stop_loss_pct"]) or 2))
        config["stop_loss_pct"] = sl
        config["take_profit_pct"] = sl * 3
    if "tp_mode" in data:
        tp_mode = str(data["tp_mode"]).lower()
        if tp_mode not in ("fixed", "ema_reversal", "both"):
            tp_mode = "both"
        config["tp_mode"] = tp_mode
    if "mode" in data:
        config["mode"] = data["mode"] if data["mode"] in ("long", "short", "both") else "both"

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
    method = request.args.get("method", request.method).upper()
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


# ============================================================
# FULL PROXY - serves bot-engine dashboard in iframe
# ============================================================

@app.route('/bot/', methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'OPTIONS'])
@app.route('/bot/<path:path>', methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'OPTIONS'])
def bot_engine_proxy(path=''):
    if not is_logged_in():
        return redirect("/")

    user = current_user()
    if not user:
        session.clear()
        return redirect("/")

    sub = check_subscription(user)
    if not sub["active"]:
        return redirect("/")

    status = get_bot_status(user["id"])

    if not status["running"]:
        import threading
        def _start_bg():
            result = ensure_bot_engine_running(user["id"])
            if not result["success"]:
                logger.error("Background bot-engine start failed for %s: %s",
                           user["id"], result.get("error"))

        bg = threading.Thread(target=_start_bg, daemon=True)
        bg.start()

        return '''<html><head><meta http-equiv="refresh" content="3"></head>
        <body style="background:#0b0e11;color:#eaecef;font-family:sans-serif;text-align:center;padding:120px 20px;">
        <div style="max-width:400px;margin:0 auto;">
            <div style="width:60px;height:60px;border:4px solid #2a2e36;border-top:4px solid #f0b90b;border-radius:50%;margin:0 auto 24px;animation:spin 1s linear infinite;"></div>
            <h2 style="color:#f0b90b;margin-bottom:8px;">Bot Engine Starting...</h2>
            <p style="color:#848e9c;font-size:14px;">Please wait 3-5 seconds. Page will auto-refresh.</p>
            <p style="color:#5e6673;font-size:12px;margin-top:16px;">First load takes a few seconds. Next loads will be instant.</p>
        </div>
        <style>@keyframes spin{0%{transform:rotate(0)}100%{transform:rotate(360deg)}}</style>
        </body></html>'''

    port = status["port"]
    method = request.method

    url = f"http://127.0.0.1:{port}/{path}"
    if request.query_string:
        url += f"?{request.query_string.decode()}"

    fwd_headers = {}
    for k, v in request.headers:
        if k.lower() not in ('host', 'cookie', 'content-length'):
            fwd_headers[k] = v

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
        resp = req_lib.request(method, url, headers=fwd_headers, data=body,
                               stream=True, timeout=30, allow_redirects=False)
    except req_lib.exceptions.ConnectionError:
        # Engine dead (stale PID/port after a restart). Clear the stale entry
        # so the next request respawns a fresh instance instead of looping.
        logger.warning("Bot-engine connection refused for %s (port %s). Marking stopped.",
                       user["id"], port)
        DB.get("bot_processes", {}).pop(user["id"], None)
        save_db(DB)
        return "Bot engine not responding. It is being restarted — refresh the page.", 502
    except Exception as e:
        return f"Proxy error: {str(e)}", 500

    excluded = {'content-encoding', 'transfer-encoding', 'connection', 'content-length', 'keep-alive'}
    response_headers = [(k, v) for k, v in resp.headers.items() if k.lower() not in excluded]

    content_type = resp.headers.get('content-type', '')

    if 'text/html' in content_type:
        html = resp.content.decode('utf-8', errors='replace')
        html = html.replace('href="/static/', 'href="/bot/static/')
        html = html.replace('src="/static/', 'src="/bot/static/')
        html = html.replace("fetch('/api/", "fetch('/bot/api/")
        html = html.replace('fetch("/api/', 'fetch("/bot/api/')
        import re
        html = re.sub(r'io\s*\(\s*\{', "io({path: '/bot/socket.io', ", html)
        html = re.sub(r'io\s*\(\s*\)', "io({path: '/bot/socket.io'})", html)
        # Inject SaaS bar — Admin link ONLY visible to admin users
        user_is_admin = user and user.get('role') == 'admin'
        admin_btn = '<a href="/admin" style="background:rgba(246,70,93,0.2);color:#f6465d;border:1px solid #f6465d;padding:6px 14px;border-radius:6px;text-decoration:none;font-size:12px;font-family:sans-serif;">Admin</a>' if user_is_admin else ''
        saas_bar = f'''
<div style="position:fixed;top:10px;right:10px;z-index:99999;display:flex;gap:8px;">
  {admin_btn}
  <button onclick="fetch('/api/auth/logout',{{method:'POST'}}).then(()=>window.location.href='/?logout=1')" style="background:#f6465d;color:white;border:none;padding:6px 14px;border-radius:6px;cursor:pointer;font-size:12px;font-family:sans-serif;">Logout</button>
</div>
'''
        html = html.replace('</body>', saas_bar + '</body>')
        return Response(html.encode('utf-8'), status=resp.status_code, headers=response_headers)

    elif 'javascript' in content_type:
        js = resp.content.decode('utf-8', errors='replace')
        js = js.replace("fetch('/api/", "fetch('/bot/api/")
        js = js.replace('fetch("/api/', 'fetch("/bot/api/')
        import re
        js = re.sub(r'io\s*\(\s*\{', "io({path: '/bot/socket.io', ", js)
        js = re.sub(r'io\s*\(\s*\)', "io({path: '/bot/socket.io'})", js)
        return Response(js.encode('utf-8'), status=resp.status_code, headers=response_headers)

    else:
        # Stream non-HTML and non-JS content (e.g. Socket.IO polling, static files)
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

    data = request.get_json(force=True)
    password = data.get("password", "")

    if password != ADMIN_SECRET:
        return jsonify({"success": False, "error": "Invalid admin password"})

    admin_user = None
    for u in DB["users"].values():
        if u.get("role") == "admin":
            admin_user = u
            break

    if not admin_user:
        admin_id = str(uuid.uuid4())
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
        logger.info("Admin user created via admin login")

    if admin_user.get("subscription", {}).get("status") != "active":
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        admin_user["subscription"] = {
            "plan": "lifetime", "status": "active",
            "started_at": now, "expires_at": "9999-12-31T23:59:59Z",
        }
        save_db(DB)

    session["user_id"] = admin_user["id"]
    session.permanent = True
    return jsonify({"success": True, "user": {"id": admin_user["id"], "email": admin_user["email"], "role": "admin"}})

@app.route("/api/admin/users", methods=["GET"])
def api_admin_users():
    if not is_admin():
        return jsonify({"success": False, "error": "Admin access required"}), 403

    users = []
    for u in DB["users"].values():
        if u.get("role") == "admin":
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
# SaaS Email Helper
# ============================================================

def _send_license_email(to_email: str, license_key: str, package_name: str, days: int):
    """Send license key to user via email after admin verifies payment."""
    if not SAAS_SMTP_USER or not SAAS_SMTP_PASS:
        logger.warning("SaaS SMTP not configured. License email not sent to %s", to_email)
        return {"success": False, "error": "SMTP not configured"}

    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    try:
        msg = MIMEMultipart("alternative")
        msg["From"] = SAAS_SMTP_USER
        msg["To"] = to_email
        msg["Subject"] = f"[TradeBot] Your License Key - {package_name}"

        days_text = "Lifetime" if days >= 9999 else f"{days} days"
        body = (
            f"Hello,\n\n"
            f"Your payment has been verified and your license key is ready!\n\n"
            f"Package: {package_name}\n"
            f"Duration: {days_text}\n"
            f"License Key: {license_key}\n\n"
            f"To activate:\n"
            f"1. Login to TradeBot SaaS\n"
            f"2. Go to License Activation page\n"
            f"3. Paste the license key above\n"
            f"4. Click Activate\n\n"
            f"Thank you for choosing TradeBot!\n"
        )
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP(SAAS_SMTP_SERVER, SAAS_SMTP_PORT, timeout=15) as server:
            server.starttls()
            server.login(SAAS_SMTP_USER, SAAS_SMTP_PASS)
            server.sendmail(SAAS_SMTP_USER, to_email, msg.as_string())

        logger.info("License email sent to %s", to_email)
        return {"success": True}
    except Exception as e:
        logger.error("Failed to send license email to %s: %s", to_email, e)
        return {"success": False, "error": str(e)}

# ============================================================
# Google OAuth Routes
# ============================================================

@app.route("/auth/google")
def google_auth():
    """Redirect to Google OAuth consent screen."""
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        return redirect("/?error=google_not_configured")
    import urllib.parse
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "prompt": "select_account",
    }
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params)
    return redirect(url)


@app.route("/auth/google/callback")
def google_callback():
    """Handle Google OAuth callback - create or login user."""
    code = request.args.get("code")
    error = request.args.get("error")

    if error:
        logger.warning("Google OAuth error: %s", error)
        return redirect("/?error=google_auth_failed")
    if not code:
        return redirect("/?error=no_code")

    try:
        # Exchange code for access token
        token_data = {
            "code": code,
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri": GOOGLE_REDIRECT_URI,
            "grant_type": "authorization_code",
        }
        resp = req_lib.post("https://oauth2.googleapis.com/token", data=token_data, timeout=10)
        tokens = resp.json()
        access_token = tokens.get("access_token")
        if not access_token:
            logger.error("Google token exchange failed: %s", tokens)
            return redirect("/?error=token_exchange_failed")

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
            return redirect("/?error=no_email_from_google")

        # Find existing user or create new one
        user = None
        for u in DB["users"].values():
            if u.get("email") == google_email:
                user = u
                break

        if not user:
            # Auto-create account via Google
            user_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            user = {
                "id": user_id,
                "email": google_email,
                "name": google_name or google_email.split("@")[0],
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
                "bot_config": {
                    "exchange": "binance", "testnet": True, "symbols_list": [],
                    "timeframe": "5m", "leverage": 10, "amount_mode": "fixed",
                    "amount": 100, "amount_pct": 10, "stop_loss_pct": 2,
                    "take_profit_pct": 6, "tp_mode": "both", "mode": "both",
                    "api_key_enc": "", "api_secret_enc": "", "api_passphrase_enc": "",
                },
            }
            DB["users"][user_id] = user
            save_db(DB)
            logger.info("New Google signup: %s (id=%s)", google_email, user_id)

        if user.get("banned"):
            return redirect("/?error=account_suspended")

        if user.get("google_id") != google_id:
            user["google_id"] = google_id  # keep the account bound to this Google id
            save_db(DB)

        _dedupe_users_by_email(user["id"])

        session["user_id"] = user["id"]
        session.permanent = True
        logger.info("Google login: %s", google_email)
        return redirect("/")

    except Exception as e:
        logger.error("Google OAuth error: %s", e)
        return redirect("/?error=oauth_failed")

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
                          wallet_address=WALLET_ADDRESS, wallet_network=WALLET_NETWORK)


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
            return jsonify({"success": True, "order_id": oid,
                           "message": "You already have an active order", "existing": True})

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
    return jsonify({"success": True, "order_id": order_id, "order": order})


@app.route("/api/orders/submit", methods=["POST"])
def api_submit_order():
    """User submits payment proof (transaction hash + screenshot)."""
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
        return jsonify({"success": False, "error": "Transaction hash / Order number is required"})

    order = DB.get("orders", {}).get(order_id)
    if not order or order["user_id"] != user["id"]:
        return jsonify({"success": False, "error": "Order not found"})
    if order["status"] not in ("pending", "submitted"):
        return jsonify({"success": False, "error": "Order cannot be modified (already processed)"})

    # Save screenshot file
    screenshot_path = order.get("screenshot", "")
    if screenshot_file and screenshot_file.filename:
        allowed = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
        ext = Path(screenshot_file.filename).suffix.lower()
        if ext not in allowed:
            return jsonify({"success": False, "error": "Only image files allowed (JPG, PNG, GIF, WebP)"})
        screenshot_file.seek(0, 2)
        size = screenshot_file.tell()
        screenshot_file.seek(0)
        if size > 5 * 1024 * 1024:
            return jsonify({"success": False, "error": "Screenshot too large (max 5MB)"})
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

    logger.info("Order %s submitted by %s (tx=%s)", order_id, user["email"], tx_hash[:20])
    return jsonify({"success": True, "message": "Payment proof submitted. Waiting for admin verification."})


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

    # Generate license key
    days = int(custom_days) if custom_days else order["days"]
    parts = [secrets.token_hex(2).upper() for _ in range(4)]
    license_key = f"TRDBOT-{parts[0]}-{parts[1]}-{parts[2]}-{parts[3]}"

    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=days) if days < 9999 else datetime(9999, 12, 31, tzinfo=timezone.utc)

    # Create license in DB
    lic = {
        "key": license_key,
        "plan": order["package_id"],
        "days": days,
        "note": f"Order {order_id} - {order['package_name']} - {order['user_email']}",
        "created_at": now.isoformat().replace("+00:00", "Z"),
        "expires_at": expires.isoformat().replace("+00:00", "Z"),
        "used_by": order["user_id"],
        "activated_at": now.isoformat().replace("+00:00", "Z"),
        "active": True,
        "revoked": False,
    }
    DB.setdefault("licenses", {})[license_key] = lic

    # Update user subscription
    user = DB["users"].get(order["user_id"])
    if user:
        user["subscription"] = {
            "plan": order["package_id"],
            "status": "active",
            "started_at": now.isoformat().replace("+00:00", "Z"),
            "expires_at": expires.isoformat().replace("+00:00", "Z"),
        }
        user["license_key"] = license_key

    # Update order
    order["status"] = "verified"
    order["verified_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    order["license_key"] = license_key
    save_db(DB)

    # Send license key via email
    email_result = _send_license_email(order["user_email"], license_key,
                                       order["package_name"], days)

    logger.info("Order %s VERIFIED. License %s assigned to %s. Email sent: %s",
                order_id, license_key, order["user_email"], email_result.get("success"))

    return jsonify({
        "success": True,
        "license_key": license_key,
        "message": f"Order verified! License: {license_key}",
        "email_sent": email_result.get("success", False),
    })


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
    """Admin: get or update the payment wallet address."""
    if not is_admin():
        return jsonify({"success": False, "error": "Admin access required"}), 403

    global WALLET_ADDRESS, WALLET_NETWORK
    if request.method == "GET":
        return jsonify({"success": True, "wallet": WALLET_ADDRESS, "network": WALLET_NETWORK})

    data = request.get_json(force=True)
    if data.get("wallet"):
        WALLET_ADDRESS = data["wallet"]
    if data.get("network"):
        WALLET_NETWORK = data["network"]
    return jsonify({"success": True, "wallet": WALLET_ADDRESS, "network": WALLET_NETWORK})

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
# Entry point
# ============================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    host = os.environ.get("HOST", "0.0.0.0")
    logger.info("SaaS webapp running on port %d", port)

    # Watchdog thread - keeps bot-engine alive with MAX_RESTART limit
    WATCHDOG_MAX_RESTARTS = 5
    _watchdog_restart_counts: dict[str, int] = {}

    def _watchdog():
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

    watchdog_thread = _threading.Thread(target=_watchdog, daemon=True)
    watchdog_thread.start()

    from werkzeug.serving import run_simple
    run_simple(host, port, app, use_reloader=False, use_debugger=False, threaded=True)
