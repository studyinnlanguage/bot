#!/usr/bin/env python3
"""
migrate_cloud_users.py — one-time import of Weexionic Cloud (demo dashboard)
accounts into the REAL bot SaaS database (database.json).

Runs at container start (entrypoint) BEFORE Flask boots. Idempotent: users
whose email already exists in the bot DB are skipped.

Imported per user:
  - email, name, password hash (Cloud Node-scrypt format — Flask's
    verify_password was extended to accept it)
  - referral code + referred-by mapping
  - subscription from plan/planValidUntil (active trial → active sub)

Demo-only artifacts ($10 paper credits, paper trade history) are NOT
imported — the real referral ledger starts clean, exactly as the owner
requested ("bot ka asli referral system").
"""

import json
import os
import sqlite3
import sys
import uuid
from datetime import datetime, timezone

CLOUD_DB = os.environ.get("CLOUD_DB_FILE", "/app/data/prod.db")
SAAS_DB = os.environ.get("SAAS_DB_FILE", "/app/data/database.json")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def default_bot_config() -> dict:
    return {
        "exchange": "binance", "testnet": True, "symbols_list": ["BTCUSDT"],
        "timeframe": "5m", "leverage": 10, "amount_mode": "fixed",
        "amount": 100, "amount_pct": 10, "stop_loss_pct": 2,
        "take_profit_pct": 6, "tp_mode": "both", "mode": "both",
        "max_concurrent_trades": 3,
        "api_key_enc": "", "api_secret_enc": "", "api_passphrase_enc": "",
    }


def load_saas_db() -> dict:
    if os.path.exists(SAAS_DB):
        try:
            with open(SAAS_DB, "r", encoding="utf-8") as f:
                db = json.load(f)
            if isinstance(db, dict):
                db.setdefault("users", {})
                db.setdefault("licenses", {})
                db.setdefault("orders", {})
                db.setdefault("tokens", {})
                db.setdefault("bot_processes", {})
                return db
        except (json.JSONDecodeError, OSError):
            pass
    return {"users": {}, "licenses": {}, "orders": {}, "tokens": {}, "bot_processes": {}}


def save_saas_db(db: dict) -> None:
    tmp = SAAS_DB + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=2, ensure_ascii=False)
    os.replace(tmp, SAAS_DB)


def main() -> int:
    if not os.path.exists(CLOUD_DB):
        print(f"[migrate] No cloud DB at {CLOUD_DB} — nothing to import.")
        return 0

    db = load_saas_db()
    existing_emails = {(u.get("email") or "").lower() for u in db["users"].values()}

    try:
        conn = sqlite3.connect(f"file:{CLOUD_DB}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, email, passwordHash, name, createdAt, plan, planValidUntil,"
            " referralCode, referredBy, walletBalance, lifetimeEarn, friendsInvited"
            " FROM User"
        ).fetchall()
    except sqlite3.Error as e:
        print(f"[migrate] Cloud DB unreadable ({e}) — skipping import.")
        return 0

    # Map cloud user ids → emails so referredBy can be re-pointed later
    cloud_email_by_id = {r["id"]: (r["email"] or "").lower() for r in rows}
    flask_id_by_email = {}
    for uid, u in db["users"].items():
        flask_id_by_email[(u.get("email") or "").lower()] = uid

    imported, skipped = 0, 0
    pending_refs = []  # (new_user_id, cloud_referredBy_id)

    for r in rows:
        email = (r["email"] or "").strip().lower()
        if not email:
            continue
        if email in existing_emails:
            skipped += 1
            continue

        uid = str(uuid.uuid4())
        created = (str(r["createdAt"] or ""))[:19]
        try:
            created_iso = datetime.fromisoformat(created).isoformat().replace("+00:00", "Z")
        except ValueError:
            created_iso = now_iso()

        valid_until = r["planValidUntil"]
        sub = {"plan": "none", "status": "inactive", "started_at": created_iso, "expires_at": None}
        if valid_until:
            try:
                exp = datetime.fromisoformat(str(valid_until).replace("Z", "+00:00"))
                if exp.timestamp() > datetime.now(timezone.utc).timestamp():
                    sub = {
                        "plan": "trial",
                        "status": "active",
                        "started_at": created_iso,
                        "expires_at": exp.isoformat().replace("+00:00", "Z"),
                    }
            except ValueError:
                pass

        user = {
            "id": uid,
            "email": email,
            "name": (r["name"] or email.split("@")[0]).strip(),
            # Cloud Node-scrypt hash ("salt:hex") — Flask verify_password
            # accepts this format directly.
            "password_hash": r["passwordHash"] or "",
            "role": "user",
            "banned": False,
            "created_at": created_iso,
            "subscription": sub,
            "license_key": None,
            "referral_code": (r["referralCode"] or uid[:8].upper()),
            "referred_by": None,          # patched after all users are imported
            "referral_earnings": 0.0,     # real ledger starts clean (demo credits dropped)
            "referral_history": [],
            "payout_wallet": "",
            "payout_requests": [],
            "bot_config": default_bot_config(),
            "migrated_from_cloud": True,
        }
        db["users"][uid] = user
        flask_id_by_email[email] = uid
        existing_emails.add(email)
        if r["referredBy"]:
            pending_refs.append((uid, r["referredBy"]))
        imported += 1

    # Re-point referred_by to the migrated inviter (when both exist)
    for uid, cloud_ref in pending_refs:
        inviter_email = cloud_email_by_id.get(cloud_ref)
        if inviter_email and inviter_email in flask_id_by_email:
            db["users"][uid]["referred_by"] = flask_id_by_email[inviter_email]

    if imported:
        save_saas_db(db)
    conn.close()
    print(f"[migrate] Cloud users imported: {imported}, already present: {skipped}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
