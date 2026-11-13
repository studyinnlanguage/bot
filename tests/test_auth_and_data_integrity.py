"""Regression tests for email+password auth integrity, duplicate-account merges,
admin session isolation, reverse-proxy rate limiting, and DB backup/JSONB handling.
"""
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
_DB_FILE = REPO / "database.json"
_DB_BAK = _DB_FILE.with_suffix(".json.bak")


@pytest.fixture
def saas_env(tmp_path):
    """Provide isolated SaaS Flask test client + app module, restoring real files."""
    sys.path.insert(0, str(REPO))
    old_cwd = os.getcwd()
    os.chdir(REPO)

    if "app" in sys.modules and not hasattr(sys.modules["app"], "DB"):
        del sys.modules["app"]

    backup = _DB_FILE.read_text(encoding="utf-8") if _DB_FILE.exists() else None
    bak_backup = _DB_BAK.read_text(encoding="utf-8") if _DB_BAK.exists() else None

    os.environ["ADMIN_SECRET"] = "test-admin-secret-auth-suite"
    import app as saas
    import mobile_api

    orig_db = json.loads(json.dumps(saas.DB))
    orig_rate_limit = saas._check_rate_limit
    orig_mobile_rl = mobile_api._cfg.get("rate_limit")
    orig_save_hook = saas.save_db
    orig_admin_secret = saas.ADMIN_SECRET
    created_uids = []

    saas.app.config["TESTING"] = True
    saas.ADMIN_SECRET = "test-admin-secret-auth-suite"
    saas._rate_limit_store.clear()
    saas.DB.clear()
    saas.DB.update({
        "users": {},
        "licenses": {},
        "orders": {},
        "bot_processes": {},
        "used_txids": {},
        "oauth_codes": {},
        "settings": {},
    })
    saas.save_db(saas.DB)

    with saas.app.test_client() as client:
        yield client, saas, mobile_api, created_uids

    # Clean up test instance/config artifacts
    for uid in created_uids:
        inst = saas.USER_INSTANCES_DIR / uid
        if inst.exists():
            shutil.rmtree(inst, ignore_errors=True)
        cfg = saas.USER_CONFIGS_DIR / f"{uid}.json"
        if cfg.exists():
            cfg.unlink(missing_ok=True)

    saas.ADMIN_SECRET = orig_admin_secret
    saas._check_rate_limit = orig_rate_limit
    if orig_mobile_rl is not None:
        mobile_api._cfg["rate_limit"] = orig_mobile_rl
    saas.save_db = orig_save_hook
    saas._rate_limit_store.clear()
    saas.DB.clear()
    saas.DB.update(orig_db)

    if backup is not None:
        _DB_FILE.write_text(backup, encoding="utf-8")
    elif _DB_FILE.exists():
        _DB_FILE.unlink()

    if bak_backup is not None:
        _DB_BAK.write_text(bak_backup, encoding="utf-8")
    elif _DB_BAK.exists():
        _DB_BAK.unlink()

    os.chdir(old_cwd)


class TestEmailNormalizationAndLogin:
    def test_case_and_whitespace_login_and_duplicate_signup_blocked(self, saas_env):
        c, saas, _, _ = saas_env
        r = c.post("/api/auth/signup", json={
            "email": "TraderOne@Example.COM",
            "password": "StrongPassword1!",
            "name": "Trader One",
        })
        assert r.status_code == 200
        assert r.get_json()["success"] is True

        # Mixed-case + leading/trailing spaces must still log in
        r2 = c.post("/api/auth/login", json={
            "email": "  traderone@example.com  ",
            "password": "StrongPassword1!",
        })
        assert r2.status_code == 200
        assert r2.get_json()["success"] is True

        # Mobile login with mixed case also succeeds
        r3 = c.post("/api/mobile/auth/login", json={
            "email": "TRADERONE@example.com",
            "password": "StrongPassword1!",
        })
        assert r3.status_code == 200
        assert r3.get_json()["success"] is True

        # Duplicate signup with different case must be rejected
        r4 = c.post("/api/auth/signup", json={
            "email": "TRADERONE@example.com",
            "password": "AnotherPassword2!",
        })
        assert r4.get_json()["success"] is False
        assert "already registered" in r4.get_json()["error"].lower()

    def test_login_page_template_enforces_8_char_minimum(self, saas_env):
        c, _, _, _ = saas_env
        resp = c.get("/login")
        html = resp.get_data(as_text=True)
        assert resp.status_code == 200
        assert 'minlength="8"' in html
        assert "min 8 chars" in html
        assert "minlength=\"6\"" not in html


class TestDuplicateMergeAndIntegrity:
    def test_passwordless_google_stub_before_password_user_merges_cleanly(self, saas_env):
        c, saas, _, created_uids = saas_env
        uid_google = "test-dup-google-1"
        uid_email = "test-dup-email-2"
        created_uids.extend([uid_google, uid_email])

        # Prepare orphaned instance file under google duplicate id
        g_inst = saas.USER_INSTANCES_DIR / uid_google
        g_inst.mkdir(parents=True, exist_ok=True)
        (g_inst / "bot_config.json").write_text('{"exchange":"bybit"}', encoding="utf-8")

        # Insert passwordless Google stub FIRST so naive loop would fail password check
        saas.DB["users"][uid_google] = {
            "id": uid_google,
            "email": "collide@example.com",
            "name": "Collide Google",
            "password_hash": "",
            "google_id": "gid_collide_99",
            "role": "user",
            "banned": False,
            "created_at": "2026-01-01T00:00:00Z",
            "subscription": {
                "plan": "yearly",
                "status": "active",
                "started_at": "2026-01-01T00:00:00Z",
                "expires_at": "2027-01-01T00:00:00Z",
            },
            "license_key": "LIC-COLLIDE-1",
            "referral_earnings": 5.0,
            "referral_history": [{"order_id": "ORD-G1", "amount": 5.0}],
            "bot_config": {"api_keys_enc": {"bybit": {"api_key_enc": "enc_bybit"}}},
        }
        saas.DB["users"][uid_email] = {
            "id": uid_email,
            "email": "Collide@Example.COM",
            "name": "Collide Email",
            "password_hash": saas.hash_password("MyPass1234!"),
            "role": "user",
            "banned": False,
            "created_at": "2026-02-01T00:00:00Z",
            "subscription": {"plan": "none", "status": "inactive", "started_at": "2026-02-01T00:00:00Z", "expires_at": None},
            "license_key": None,
            "referral_earnings": 10.0,
            "referral_history": [{"order_id": "ORD-E1", "amount": 10.0}],
            "payout_requests": [{"id": "PAY-1", "amount": 10.0}],
            "bot_config": {"api_keys_enc": {"binance": {"api_key_enc": "enc_binance"}}},
        }
        saas.DB["licenses"]["LIC-COLLIDE-1"] = {"key": "LIC-COLLIDE-1", "used_by": uid_google, "plan": "yearly"}
        saas.DB["orders"]["ORD-G1"] = {"id": "ORD-G1", "user_id": uid_google, "user_email": "collide@example.com"}
        saas.DB["orders"]["ORD-E1"] = {"id": "ORD-E1", "user_id": uid_email, "user_email": "collide@example.com"}

        # Login with email + password MUST succeed even with Google stub listed first
        r = c.post("/api/auth/login", json={"email": "collide@example.com", "password": "MyPass1234!"})
        body = r.get_json()
        assert body["success"] is True

        # Only one user remains, with BOTH password, google_id, license, orders, keys, files, and referrals
        remaining = [u for u in saas.DB["users"].values() if saas._norm_email(u.get("email")) == "collide@example.com"]
        assert len(remaining) == 1
        kept = remaining[0]
        kid = kept["id"]

        assert saas.verify_password("MyPass1234!", kept["password_hash"])
        assert kept["google_id"] == "gid_collide_99"
        assert kept["subscription"]["status"] == "active"
        assert kept["license_key"] == "LIC-COLLIDE-1"
        assert saas.DB["licenses"]["LIC-COLLIDE-1"]["used_by"] == kid
        assert saas.DB["orders"]["ORD-G1"]["user_id"] == kid
        assert saas.DB["orders"]["ORD-E1"]["user_id"] == kid
        assert kept["bot_config"]["api_keys_enc"]["bybit"]["api_key_enc"] == "enc_bybit"
        assert kept["bot_config"]["api_keys_enc"]["binance"]["api_key_enc"] == "enc_binance"
        assert kept["referral_earnings"] == 15.0
        assert len(kept["referral_history"]) == 2
        assert len(kept["payout_requests"]) == 1
        assert (saas.USER_INSTANCES_DIR / kid / "bot_config.json").exists()

        # Subsequent mobile login also works on the surviving canonical account
        rm = c.post("/api/mobile/auth/login", json={"email": "collide@example.com", "password": "MyPass1234!"})
        assert rm.status_code == 200
        assert rm.get_json()["user"]["id"] == kid

    def test_empty_email_records_never_merged_together(self, saas_env):
        _, saas, _, _ = saas_env
        saas.DB["users"]["empty1"] = {"id": "empty1", "email": "", "name": "E1", "bot_config": {}}
        saas.DB["users"]["empty2"] = {"id": "empty2", "email": "", "name": "E2", "bot_config": {}}
        saas._dedupe_users_by_email("empty1", save=False)
        assert "empty1" in saas.DB["users"]
        assert "empty2" in saas.DB["users"]

    def test_heal_users_integrity_merges_and_reattaches_orphaned_orders(self, saas_env):
        _, saas, _, created_uids = saas_env
        created_uids.extend(["orphan-uid-old", "uid-keep-1"])
        old_inst = saas.USER_INSTANCES_DIR / "orphan-uid-old"
        old_inst.mkdir(parents=True, exist_ok=True)
        (old_inst / "bot_state.json").write_text('{"trades":[]}', encoding="utf-8")

        db_mock = {
            "users": {
                "uid-keep-1": {
                    "id": "uid-keep-1",
                    "email": " HealMe@Example.COM ",
                    "password_hash": saas.hash_password("Pass12345!"),
                    "subscription": {"plan": "monthly", "status": "active"},
                    "bot_config": {},
                },
                "uid-dup-2": {
                    "id": "uid-dup-2",
                    "email": "healme@example.com",
                    "password_hash": "",
                    "google_id": "gid_heal_2",
                    "bot_config": {"exchange": "okx"},
                },
            },
            "licenses": {},
            "orders": {
                "ORD-ORPHAN": {
                    "id": "ORD-ORPHAN",
                    "user_id": "orphan-uid-old",
                    "user_email": "HEALME@example.com",
                }
            },
            "bot_processes": {},
        }
        assert saas._heal_users_integrity(db_mock) is True
        assert list(db_mock["users"].keys()) == ["uid-keep-1"]
        assert db_mock["users"]["uid-keep-1"]["email"] == "healme@example.com"
        assert db_mock["users"]["uid-keep-1"]["google_id"] == "gid_heal_2"
        assert db_mock["orders"]["ORD-ORPHAN"]["user_id"] == "uid-keep-1"
        assert (saas.USER_INSTANCES_DIR / "uid-keep-1" / "bot_state.json").exists()


class TestAdminLoginIsolation:
    def test_admin_login_never_mutates_regular_user_role_or_hijacks_accounts(self, saas_env):
        c, saas, _, _ = saas_env
        # Seed a stale regular user who previously got role="admin" on legacy builds
        saas.DB["users"]["stale-promoted"] = {
            "id": "stale-promoted",
            "email": "staleuser@example.com",
            "name": "Stale User",
            "password_hash": saas.hash_password("UserPass99!"),
            "role": "admin",
            "banned": False,
            "subscription": {"plan": "none", "status": "inactive"},
            "bot_config": {},
        }
        # Sign up as regular user
        r = c.post("/api/auth/signup", json={
            "email": "regular@example.com",
            "password": "RegularPass1!",
            "name": "Regular User",
        })
        reg_uid = r.get_json()["user"]["id"]

        # Elevate session with admin password
        ra = c.post("/api/admin/login", json={"password": saas.ADMIN_SECRET})
        assert ra.get_json()["success"] is True

        # Regular user's stored role MUST remain "user"
        assert saas.DB["users"][reg_uid]["role"] == "user"

        # Regular user + stale user must still appear in admin user list
        ru = c.get("/api/admin/users")
        assert ru.status_code == 200
        emails = {u["email"] for u in ru.get_json()["users"]}
        assert "regular@example.com" in emails
        assert "staleuser@example.com" in emails

        # Logout clears admin_authenticated as well as user_id
        c.post("/api/auth/logout")
        assert c.get("/api/admin/users").status_code == 403

        # Fresh anonymous admin login goes ONLY to dedicated admin@tradebot.com, never stale-promoted
        ra2 = c.post("/api/admin/login", json={"password": saas.ADMIN_SECRET})
        body2 = ra2.get_json()
        assert body2["success"] is True
        assert body2["user"]["id"] == "admin"
        assert body2["user"]["email"] == "admin@tradebot.com"


class TestProxyRateLimiting:
    def test_forwarded_ips_and_emails_rate_limited_independently(self, saas_env):
        c, saas, _, _ = saas_env
        c.post("/api/auth/signup", json={"email": "victim@example.com", "password": "GoodPassword1!"})
        c.post("/api/auth/signup", json={"email": "other@example.com", "password": "GoodPassword2!"})
        c.post("/api/auth/logout")

        # 8 bad attempts for victim from proxy IP 1.2.3.4 trip rate limit ONLY for (1.2.3.4, victim)
        for _ in range(8):
            c.post(
                "/api/auth/login",
                json={"email": "victim@example.com", "password": "wrong"},
                headers={"X-Forwarded-For": "1.2.3.4"},
            )
        locked = c.post(
            "/api/auth/login",
            json={"email": "victim@example.com", "password": "GoodPassword1!"},
            headers={"X-Forwarded-For": "1.2.3.4"},
        )
        assert locked.status_code == 429

        # Different user behind same reverse proxy IP is NOT locked out
        other_ok = c.post(
            "/api/auth/login",
            json={"email": "other@example.com", "password": "GoodPassword2!"},
            headers={"X-Forwarded-For": "1.2.3.4"},
        )
        assert other_ok.status_code == 200
        assert other_ok.get_json()["success"] is True

        # Victim from another IP (CF-Connecting-IP) is NOT locked out either
        victim_other_ip = c.post(
            "/api/auth/login",
            json={"email": "victim@example.com", "password": "GoodPassword1!"},
            headers={"CF-Connecting-IP": "5.6.7.8"},
        )
        assert victim_other_ip.status_code == 200
        assert victim_other_ip.get_json()["success"] is True


class TestDatabaseIntegrity:
    def test_parse_json_column_preserves_lists_and_dicts(self, saas_env):
        _, saas, _, _ = saas_env
        assert saas._parse_json_column('[{"id": 1}]', list) == [{"id": 1}]
        assert saas._parse_json_column([{"id": 2}], list) == [{"id": 2}]
        assert saas._parse_json_column("bad-json", list) == []
        assert saas._parse_json_column('{"a": 1}', dict) == {"a": 1}
        assert saas._parse_json_column(None, list) == []

    def test_backup_created_on_save_and_restored_when_primary_corrupt(self, saas_env):
        _, saas, _, _ = saas_env
        sample = {
            "users": {"u1": {"id": "u1", "email": "saved@example.com"}},
            "licenses": {},
            "orders": {},
            "bot_processes": {},
            "used_txids": {},
            "settings": {},
        }
        saas.save_db(sample)
        sample["users"]["u1"]["name"] = "Updated"
        saas.save_db(sample)  # creates .json.bak of previous good save

        assert _DB_BAK.exists()
        _DB_FILE.write_text("{corrupt-truncated-json", encoding="utf-8")

        loaded = saas._load_json_db()
        assert loaded["users"]["u1"]["email"] == "saved@example.com"


class TestPasswordResetAndLiveConfig:
    def test_forgot_password_requires_smtp_and_never_leaks_token(self, saas_env, monkeypatch):
        c, saas, _, created_uids = saas_env
        for var in (
            "SAAS_SMTP_USER", "SAAS_SMTP_PASS",
            "SMTP_USER", "SMTP_PASS", "SMTP_PASSWORD",
            "EMAIL_USER", "EMAIL_PASSWORD",
            "MAIL_USERNAME", "MAIL_PASSWORD",
            "GMAIL_USER", "GMAIL_APP_PASS",
        ):
            monkeypatch.delenv(var, raising=False)

        r = c.post("/api/auth/signup", json={
            "email": "ResetUser@Example.COM",
            "password": "OldPassword1!",
            "name": "Reset User",
        })
        assert r.status_code == 200
        created_uids.append(r.get_json()["user"]["id"])
        c.post("/api/auth/logout")

        resp = c.post("/api/auth/forgot-password", json={"email": "resetuser@example.com"})
        assert resp.status_code == 503
        body = resp.get_json()
        assert body["success"] is False
        assert "smtp" in body["error"].lower()
        assert not saas.DB.get("settings", {}).get("password_resets")

    def test_forgot_and_reset_password_preserves_api_keys_subscription_and_trade_history(self, saas_env, monkeypatch):
        import re
        c, saas, _, created_uids = saas_env

        # 1. User creates email + password account
        r = c.post("/api/auth/signup", json={
            "email": "TraderReset@Example.COM",
            "password": "InitialPass123!",
            "name": "Mudassar",
        })
        assert r.status_code == 200
        uid = r.get_json()["user"]["id"]
        created_uids.append(uid)

        # 2. Seed saved subscription, license, order, encrypted API keys, config.json & trade_history.json
        user = saas.DB["users"][uid]
        user["subscription"] = {
            "active": True,
            "plan": "monthly",
            "status": "active",
            "expires_at": "2027-01-01T00:00:00Z",
        }
        user["license_key"] = "WX-RESET-9999"
        user["bot_config"] = {
            "exchange": "binance",
            "testnet": False,
            "live_confirmed": True,
            "leverage": 50,
            "stop_loss_pct": 0.4,
            "api_key_enc": saas.encrypt("REAL_BINANCE_KEY_XYZ"),
            "api_secret_enc": saas.encrypt("REAL_BINANCE_SECRET_XYZ"),
            "api_keys_enc": {
                "binance": {
                    "api_key": saas.encrypt("REAL_BINANCE_KEY_XYZ"),
                    "api_secret": saas.encrypt("REAL_BINANCE_SECRET_XYZ"),
                }
            },
        }
        saas.DB["orders"]["ord_reset_1"] = {
            "id": "ord_reset_1",
            "user_id": uid,
            "plan": "monthly",
            "amount": 19,
            "status": "approved",
        }
        saas.DB["settings"]["smtp"] = {
            "host": "smtp.gmail.com",
            "port": 587,
            "user": "bot@weexionic.test",
            "pass": "app-secret-pw",
        }
        saas.save_db(saas.DB)
        cfg_path = saas.write_user_bot_config(uid)

        hist_dir = saas.USER_INSTANCES_DIR / uid / "data"
        hist_dir.mkdir(parents=True, exist_ok=True)
        hist_file = hist_dir / "trade_history.json"
        sample_trades = [
            {"id": "t1", "symbol": "BTCUSDT", "side": "LONG", "pnl_usdt": 14.5, "exit_reason": "TAKE PROFIT HIT"}
        ]
        hist_file.write_text(json.dumps(sample_trades), encoding="utf-8")

        c.post("/api/auth/logout")

        # 3. Capture outgoing SMTP email from both web & mobile forgot-password endpoints
        sent_emails = []

        def fake_send_email_smtp(to_email, subject, plain_body, html_body=None):
            sent_emails.append({
                "to": to_email,
                "subject": subject,
                "plain": plain_body,
                "html": html_body or "",
            })
            return {"success": True, "message": "Email sent"}

        monkeypatch.setattr(saas, "_send_email_smtp", fake_send_email_smtp)

        fp = c.post(
            "/api/auth/forgot-password",
            json={"email": "  traderreset@example.com  "},
            headers={"Host": "weexionic.example.com", "X-Forwarded-For": "203.0.113.10"},
        )
        assert fp.status_code == 200
        assert fp.get_json()["success"] is True
        assert len(sent_emails) == 1
        assert sent_emails[0]["to"] == "traderreset@example.com"
        assert "Mudassar" in sent_emails[0]["html"]

        match = re.search(r"https?://[^/\s]+(/reset-password\?token=([A-Za-z0-9_\-]+))", sent_emails[0]["plain"])
        assert match, f"Expected reset link in email body, got: {sent_emails[0]['plain']}"
        reset_path, raw_token = match.group(1), match.group(2)

        # Mobile endpoint also dispatches reset email cleanly
        fp_mobile = c.post(
            "/api/mobile/auth/forgot-password",
            json={"email": "TraderReset@example.com"},
            headers={"X-Forwarded-For": "203.0.113.11"},
        )
        assert fp_mobile.status_code == 200
        assert len(sent_emails) == 2

        # Raw token must NEVER be stored unhashed in DB["settings"]["password_resets"]
        stored_resets = saas.DB["settings"]["password_resets"]
        assert raw_token not in json.dumps(stored_resets)
        assert saas._reset_token_hash(raw_token) in stored_resets

        # 4. Reset page renders email context cleanly
        page = c.get(reset_path)
        assert page.status_code == 200
        html_text = page.get_data(as_text=True)
        assert "traderreset@example.com" in html_text
        assert 'id="resetForm"' in html_text

        # Too-short password rejected
        bad_len = c.post("/api/auth/reset-password", json={"token": raw_token, "password": "short"})
        assert bad_len.status_code == 400

        # 5. Save new password -> succeeds, persists DB, invalidates tokens, keeps user assets
        rp = c.post("/api/auth/reset-password", json={
            "token": raw_token,
            "password": "BrandNewPassword9!",
        })
        assert rp.status_code == 200
        rp_body = rp.get_json()
        assert rp_body["success"] is True
        assert rp_body["email"] == "traderreset@example.com"
        assert saas.DB["settings"]["password_resets"] == {}

        # Token is single-use: second submit and GET must reject
        reuse = c.post("/api/auth/reset-password", json={
            "token": raw_token,
            "password": "AnotherPassword9!",
        })
        assert reuse.status_code == 400
        expired_page = c.get(reset_path)
        assert expired_page.status_code == 200
        expired_html = expired_page.get_data(as_text=True)
        assert 'id="resetForm"' not in expired_html
        assert "invalid ya expire" in expired_html.lower()

        # 6. Old password no longer works; new password logs in on BOTH web and mobile
        c.post("/api/auth/logout")
        old_login = c.post("/api/auth/login", json={
            "email": "traderreset@example.com",
            "password": "InitialPass123!",
        })
        assert old_login.get_json()["success"] is False

        mob_old = c.post("/api/mobile/auth/login", json={
            "email": "traderreset@example.com",
            "password": "InitialPass123!",
        })
        assert mob_old.status_code == 401
        assert mob_old.get_json()["success"] is False

        new_login = c.post("/api/auth/login", json={
            "email": "  TraderReset@Example.COM ",
            "password": "BrandNewPassword9!",
        })
        assert new_login.status_code == 200
        assert new_login.get_json()["success"] is True

        mob_login = c.post("/api/mobile/auth/login", json={
            "email": "traderreset@example.com",
            "password": "BrandNewPassword9!",
        })
        assert mob_login.status_code == 200
        assert mob_login.get_json()["success"] is True

        # 7. Reload DB from disk to verify everything persisted (email, API keys, subscription, orders, trades)
        persisted_db = saas._load_json_db()
        saved_user = persisted_db["users"][uid]
        assert saved_user["email"] == "traderreset@example.com"
        assert saved_user["license_key"] == "WX-RESET-9999"
        assert saved_user["subscription"]["plan"] == "monthly"
        assert saas.decrypt(saved_user["bot_config"]["api_key_enc"]) == "REAL_BINANCE_KEY_XYZ"
        assert saas.decrypt(saved_user["bot_config"]["api_keys_enc"]["binance"]["api_secret"]) == "REAL_BINANCE_SECRET_XYZ"
        assert persisted_db["orders"]["ord_reset_1"]["user_id"] == uid
        assert json.loads(hist_file.read_text(encoding="utf-8")) == sample_trades
        assert json.loads(Path(cfg_path).read_text(encoding="utf-8"))["live_confirmed"] is True

    def test_live_confirmed_persists_when_switching_between_demo_and_live(self, saas_env):
        c, saas, _, created_uids = saas_env
        r = c.post("/api/auth/signup", json={
            "email": "LiveConf@Example.COM",
            "password": "LiveConfPass1!",
            "name": "Live User",
        })
        assert r.status_code == 200
        uid = r.get_json()["user"]["id"]
        created_uids.append(uid)

        # Save live config via SaaS /api/bot/config
        res_live = c.post("/api/bot/config", json={
            "exchange": "weex",
            "testnet": False,
        })
        assert res_live.status_code == 200
        assert saas.DB["users"][uid]["bot_config"]["testnet"] is False
        assert saas.DB["users"][uid]["bot_config"]["live_confirmed"] is True

        cfg_path = saas.write_user_bot_config(uid)
        cfg_data = json.loads(Path(cfg_path).read_text(encoding="utf-8"))
        assert cfg_data["testnet"] is False
        assert cfg_data["live_confirmed"] is True

        # Switch back to Demo -> live_confirmed clears to False automatically
        res_demo = c.post("/api/bot/config", json={"testnet": True})
        assert res_demo.status_code == 200
        assert saas.DB["users"][uid]["bot_config"]["testnet"] is True
        assert saas.DB["users"][uid]["bot_config"]["live_confirmed"] is False

        # Sync engine payload with testnet=False & explicit live_confirmed=True -> persists to DB
        saas._sync_engine_config_to_db(saas.DB["users"][uid], {
            "exchange": "binance",
            "testnet": False,
            "live_confirmed": True,
        })
        assert saas.DB["users"][uid]["bot_config"]["exchange"] == "binance"
        assert saas.DB["users"][uid]["bot_config"]["testnet"] is False
        assert saas.DB["users"][uid]["bot_config"]["live_confirmed"] is True

    def test_unknown_email_returns_404_instead_of_fake_success(self, saas_env, monkeypatch):
        c, saas, _, _ = saas_env
        for var in ("SAAS_SMTP_USER", "SAAS_SMTP_PASS", "SMTP_USER", "SMTP_PASS"):
            monkeypatch.delenv(var, raising=False)
        saas.DB["settings"]["smtp"] = {
            "host": "smtp.gmail.com",
            "port": 587,
            "user": "bot@weexionic.test",
            "pass": "app-secret-pw",
        }
        res = c.post("/api/auth/forgot-password", json={"email": "missing_user@gmail.com"})
        assert res.status_code == 404
        body = res.get_json()
        assert body["success"] is False
        assert "no account found" in body["error"].lower()

    def test_gmail_dot_alias_matches_account_for_password_reset(self, saas_env, monkeypatch):
        import re
        c, saas, _, created_uids = saas_env
        r = c.post("/api/auth/signup", json={
            "email": "muhammad.ahmer0002@gmail.com",
            "password": "OldPassword1!",
            "name": "Ahmer",
        })
        assert r.status_code == 200
        created_uids.append(r.get_json()["user"]["id"])
        saas.DB["settings"]["smtp"] = {
            "host": "smtp.gmail.com",
            "port": 587,
            "user": "bot@weexionic.test",
            "pass": "app-secret-pw",
        }
        sent = []
        monkeypatch.setattr(saas, "_send_email_smtp", lambda to, subj, plain, html=None: (sent.append((to, plain)) or {"success": True}))
        c.post("/api/auth/logout")

        fp = c.post("/api/auth/forgot-password", json={"email": "muhammadahmer0002@gmail.com"})
        assert fp.status_code == 200
        assert fp.get_json()["email"] == "muhammad.ahmer0002@gmail.com"
        assert len(sent) == 1
        assert sent[0][0] == "muhammad.ahmer0002@gmail.com"
        m = re.search(r"(/reset-password\?token=([A-Za-z0-9_\-]+))", sent[0][1])
        assert m
        rp = c.post("/api/auth/reset-password", json={"token": m.group(2), "password": "NewPassword9!"})
        assert rp.status_code == 200

    def test_smtp_sets_date_msgid_and_gmail_app_password_and_from_envelope(self, saas_env, monkeypatch):
        import smtplib
        _, saas, _, _ = saas_env
        saas.DB["settings"]["smtp"] = {
            "host": "smtp.gmail.com",
            "port": 587,
            "user": "relay@gmail.com",
            "pass": "abcd efgh ijkl mnop",
            "from_email": "support@weexionic.com",
            "sender_name": "Weexionic Bot",
        }
        captured = {}

        class FakeSMTP:
            def __init__(self, host, port, timeout=15):
                captured["host"] = host
                captured["port"] = port
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def ehlo(self):
                captured["ehlo"] = True
            def starttls(self):
                captured["starttls"] = True
            def login(self, user, pw):
                captured["login_user"] = user
                captured["login_pw"] = pw
            def sendmail(self, envelope_from, rcpts, raw_msg):
                captured["envelope_from"] = envelope_from
                captured["rcpts"] = rcpts
                captured["raw_msg"] = raw_msg
                return {}

        monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
        res = saas._send_email_smtp("dest@gmail.com", "Test Subject", "Hello plain")
        assert res["success"] is True
        assert captured["login_pw"] == "abcdefghijklmnop"
        assert captured["envelope_from"] == "relay@gmail.com"
        assert captured["rcpts"] == ["dest@gmail.com"]
        assert "Date:" in captured["raw_msg"]
        assert "Message-ID:" in captured["raw_msg"]
        assert "Reply-To: support@weexionic.com" in captured["raw_msg"]

    def test_admin_issue_reset_link_works_with_or_without_smtp(self, saas_env, monkeypatch):
        c, saas, _, created_uids = saas_env
        for var in ("SAAS_SMTP_USER", "SAAS_SMTP_PASS", "SMTP_USER", "SMTP_PASS"):
            monkeypatch.delenv(var, raising=False)
        r = c.post("/api/auth/signup", json={
            "email": "AdminReset@Example.com",
            "password": "StartPassword1!",
            "name": "Target",
        })
        assert r.status_code == 200
        uid = r.get_json()["user"]["id"]
        created_uids.append(uid)

        # Non-admin must be forbidden
        unauth = c.post("/api/admin/users/reset-link", json={"user_id": uid})
        assert unauth.status_code == 403

        # Admin issues reset link even without SMTP configured
        c.post("/api/admin/login", json={"password": saas.ADMIN_SECRET})
        res = c.post("/api/admin/users/reset-link", json={"user_id": uid})
        assert res.status_code == 200
        body = res.get_json()
        assert body["success"] is True
        assert body["email"] == "adminreset@example.com"
        assert body["email_sent"] is False
        assert "/reset-password?token=" in body["reset_url"]

        token = body["reset_url"].split("token=")[-1]
        c.post("/api/auth/logout")
        rp = c.post("/api/auth/reset-password", json={"token": token, "password": "AdminResetPass9!"})
        assert rp.status_code == 200
        assert c.post("/api/auth/login", json={
            "email": "adminreset@example.com",
            "password": "AdminResetPass9!",
        }).get_json()["success"] is True



