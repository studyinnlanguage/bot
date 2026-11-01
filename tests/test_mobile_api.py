"""Mobile API + RBAC + payment integrity tests.

Runs against the real SaaS app in-process (Flask test client).
Backs up / restores database.json so tests never damage real data.
"""
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
os.chdir(REPO)

_DB_FILE = REPO / "database.json"


@pytest.fixture(scope="module")
def client():
    # backup real database.json
    backup = None
    if _DB_FILE.exists():
        backup = _DB_FILE.read_text()
        _DB_FILE.unlink()
    os.environ.setdefault("ADMIN_SECRET", "test-admin-secret-pytest")
    import app as saas
    import mobile_api
    saas.app.config["TESTING"] = True
    # Rate limiting is correct production behavior but makes test batches trip
    # 429 (all tests share one remote_addr) — disable for this suite.
    permissive = lambda *a, **k: True
    saas._check_rate_limit = permissive
    mobile_api._cfg["rate_limit"] = permissive
    with saas.app.test_client() as c:
        yield c, saas
    if backup is not None:
        _DB_FILE.write_text(backup)
    elif _DB_FILE.exists():
        _DB_FILE.unlink()


def _register(client, email, password="testpass123"):
    r = client.post("/api/mobile/auth/register",
                    json={"email": email, "password": password, "name": "T"})
    assert r.status_code == 201, r.data
    return r.get_json()


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
class TestAuth:
    def test_register_and_me(self, client):
        c, _ = client
        data = _register(c, "auth1@test.com")
        assert data["access_token"] and data["refresh_token"]
        r = c.get("/api/mobile/auth/me", headers=_auth(data["access_token"]))
        body = r.get_json()
        assert body["success"] is True
        assert body["user"]["email"] == "auth1@test.com"
        assert body["user"]["role"] == "user"

    def test_duplicate_register_rejected(self, client):
        c, _ = client
        _register(c, "auth2@test.com")
        r = c.post("/api/mobile/auth/register",
                   json={"email": "auth2@test.com", "password": "testpass123"})
        assert r.status_code == 409

    def test_weak_password_rejected(self, client):
        c, _ = client
        r = c.post("/api/mobile/auth/register",
                   json={"email": "auth3@test.com", "password": "short"})
        assert r.status_code == 400

    def test_login_wrong_password(self, client):
        c, _ = client
        _register(c, "auth4@test.com")
        r = c.post("/api/mobile/auth/login",
                   json={"email": "auth4@test.com", "password": "wrongpass1"})
        assert r.status_code == 401

    def test_me_requires_token(self, client):
        c, _ = client
        r = c.get("/api/mobile/auth/me")
        assert r.status_code == 401

    def test_refresh_and_logout_blocklist(self, client):
        c, _ = client
        data = _register(c, "auth5@test.com")
        r = c.post("/api/mobile/auth/refresh", json={"refresh_token": data["refresh_token"]})
        assert r.get_json()["success"] is True
        # logout revokes the refresh token server-side
        c.post("/api/mobile/auth/logout", json={"refresh_token": data["refresh_token"]})
        r = c.post("/api/mobile/auth/refresh", json={"refresh_token": data["refresh_token"]})
        assert r.status_code == 401

    def test_garbage_token_rejected(self, client):
        c, _ = client
        r = c.get("/api/mobile/auth/me", headers=_auth("abc.def.ghi"))
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# RBAC — admin endpoints must be unreachable with mobile JWTs
# ---------------------------------------------------------------------------
class TestRoleSeparation:
    def test_admin_apis_reject_mobile_jwt(self, client):
        c, _ = client
        data = _register(c, "rbac1@test.com")
        for path in ("/api/admin/users", "/api/admin/orders", "/api/admin/licenses",
                     "/api/admin/payouts", "/api/admin/smtp", "/api/admin/wallet"):
            r = c.get(path, headers=_auth(data["access_token"]))
            assert r.status_code == 403, path

    def test_admin_actions_reject_mobile_jwt(self, client):
        c, saas = client
        data = _register(c, "rbac2@test.com")
        r = c.post("/api/admin/licenses/create", headers=_auth(data["access_token"]),
                   json={"days": 30, "plan": "pro"})
        assert r.status_code == 403

    def test_mobile_layer_has_no_admin_routes(self, client):
        c, _ = client
        data = _register(c, "rbac3@test.com")
        for path in ("/api/mobile/admin/users", "/api/mobile/admin/orders"):
            r = c.get(path, headers=_auth(data["access_token"]))
            assert r.status_code == 404, path


# ---------------------------------------------------------------------------
# Subscription + license flow
# ---------------------------------------------------------------------------
class TestSubscription:
    def test_bot_plane_gated_without_subscription(self, client):
        c, _ = client
        data = _register(c, "sub1@test.com")
        r = c.get("/api/mobile/bot/status", headers=_auth(data["access_token"]))
        assert r.status_code == 403

    def test_license_activation_full_flow(self, client):
        c, saas = client
        data = _register(c, "sub2@test.com")
        # admin creates a license
        c.post("/api/admin/login", json={"password": saas.ADMIN_SECRET})
        r = c.post("/api/admin/licenses/create",
                   json={"days": 30, "plan": "yearly", "note": "pytest"})
        key = r.get_json()["license"]["key"]
        # mobile activates
        r = c.post("/api/mobile/license/activate", headers=_auth(data["access_token"]),
                   json={"key": key})
        body = r.get_json()
        assert body["success"] is True, body
        assert body["subscription"]["active"] is True
        # second activation of same key by same account is fine, other account is not
        other = _register(c, "sub3@test.com")
        r = c.post("/api/mobile/license/activate", headers=_auth(other["access_token"]),
                   json={"key": key})
        assert r.status_code == 403

    def test_bot_plane_open_after_activation(self, client):
        c, saas = client
        data = _register(c, "sub4@test.com")
        c.post("/api/admin/login", json={"password": saas.ADMIN_SECRET})
        key = c.post("/api/admin/licenses/create", json={"days": 7, "plan": "pro"}).get_json()["license"]["key"]
        c.post("/api/mobile/license/activate", headers=_auth(data["access_token"]), json={"key": key})
        r = c.get("/api/mobile/bot/status", headers=_auth(data["access_token"]))
        body = r.get_json()
        # engine not started yet — must be a clean structured response, not 403
        assert body["success"] is True
        assert body["engine_running"] is False


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------
class TestConfigValidation:
    def test_save_and_read_config(self, client):
        c, _ = client
        data = _register(c, "cfg1@test.com")
        r = c.post("/api/mobile/bot/config", headers=_auth(data["access_token"]),
                   json={"symbols_list": ["btcusdt", "ethusdt"], "leverage": 20,
                         "stop_loss_pct": 1.5, "timeframe": "5m", "mode": "long"})
        body = r.get_json()
        assert body["success"] is True
        assert body["config"]["symbols_list"] == ["BTCUSDT", "ETHUSDT"]
        assert body["config"]["leverage"] == 20
        assert body["config"]["take_profit_pct"] == 1.5  # strict 1:1
        assert "api_key" not in body["config"]  # never echoed

    def test_leverage_clamped_by_exchange(self, client):
        c, _ = client
        data = _register(c, "cfg2@test.com")
        r = c.post("/api/mobile/bot/config", headers=_auth(data["access_token"]),
                   json={"exchange": "binance", "leverage": 5000})
        assert r.get_json()["config"]["leverage"] == 125
        r = c.post("/api/mobile/bot/config", headers=_auth(data["access_token"]),
                   json={"exchange": "primexbt", "leverage": 5000})
        assert r.get_json()["config"]["leverage"] == 1000

    def test_bad_exchange_rejected(self, client):
        c, _ = client
        data = _register(c, "cfg3@test.com")
        r = c.post("/api/mobile/bot/config", headers=_auth(data["access_token"]),
                   json={"exchange": "binan"})
        assert r.status_code == 400

    def test_invalid_leverage_type_400(self, client):
        c, _ = client
        data = _register(c, "cfg4@test.com")
        r = c.post("/api/mobile/bot/config", headers=_auth(data["access_token"]),
                   json={"leverage": "abc"})
        assert r.status_code == 400

    def test_keys_stored_encrypted_not_plaintext(self, client):
        c, saas = client
        data = _register(c, "cfg5@test.com")
        c.post("/api/mobile/bot/config", headers=_auth(data["access_token"]),
               json={"api_key": "MYKEY123", "api_secret": "MYSECRET456"})
        user = saas.DB["users"][data["user"]["id"]]
        assert user["bot_config"]["api_key_enc"] != "MYKEY123"
        assert "MYKEY123" not in json.dumps(user["bot_config"])
        assert saas.decrypt(user["bot_config"]["api_key_enc"]) == "MYKEY123"


# ---------------------------------------------------------------------------
# Payment integrity (idempotency / race protection)
# ---------------------------------------------------------------------------
class TestPayments:
    def test_order_create_and_list(self, client):
        c, _ = client
        data = _register(c, "pay1@test.com")
        r = c.post("/api/mobile/orders/create", headers=_auth(data["access_token"]),
                   json={"package_id": "yearly"})
        assert r.status_code == 201
        order_id = r.get_json()["order"]["id"]
        r = c.get("/api/mobile/orders/my", headers=_auth(data["access_token"]))
        assert any(o["id"] == order_id for o in r.get_json()["orders"])

    def test_second_pending_order_blocked(self, client):
        c, _ = client
        data = _register(c, "pay2@test.com")
        c.post("/api/mobile/orders/create", headers=_auth(data["access_token"]),
               json={"package_id": "yearly"})
        r = c.post("/api/mobile/orders/create", headers=_auth(data["access_token"]),
                   json={"package_id": "lifetime"})
        assert r.status_code == 409

    def test_activation_idempotent_no_double_license(self, client):
        c, saas = client
        data = _register(c, "pay3@test.com")
        c.post("/api/admin/login", json={"password": saas.ADMIN_SECRET})
        key = c.post("/api/admin/licenses/create", json={"days": 30, "plan": "pro"}).get_json()["license"]["key"]
        c.post("/api/mobile/license/activate", headers=_auth(data["access_token"]), json={"key": key})
        user = saas.DB["users"][data["user"]["id"]]
        # simulate the order-activation path running twice (double-click / race)
        order = {"id": "ORD-RACETEST", "user_id": user["id"], "user_email": user["email"],
                 "package_id": "yearly", "package_name": "1-Year", "days": 365,
                 "status": "submitted"}
        saas._activate_order_and_credit_referral(order, verified_by="test")
        n_licenses_before = len(saas.DB["licenses"])
        again = saas._activate_order_and_credit_referral(order, verified_by="test")
        n_licenses_after = len(saas.DB["licenses"])
        assert n_licenses_before == n_licenses_after  # no duplicate license
        assert order["status"] == "verified"

    def test_used_txid_blocks_replay(self, client):
        c, saas = client
        tx = "0x" + "ab" * 32
        saas.DB.setdefault("used_txids", {})[tx] = "ORD-SOMEONE"
        verified, _note = saas._verify_tx_blockchain(tx, 79)
        assert verified is False  # replay rejected outright

    def test_payout_atomicity(self, client):
        c, saas = client
        data = _register(c, "pay4@test.com")
        user = saas.DB["users"][data["user"]["id"]]
        user["referral_earnings"] = 50.0
        hdrs = _auth(data["access_token"])
        r = c.post("/api/mobile/user/request-payout", headers=hdrs,
                   json={"wallet_address": "TWd4WrZ9wn84f5x1hZhL4DHvk738ns5jwb"})
        assert r.get_json()["success"] is True
        # second request while the first is pending must fail (no double spend)
        r = c.post("/api/mobile/user/request-payout", headers=hdrs,
                   json={"wallet_address": "TWd4WrZ9wn84f5x1hZhL4DHvk738ns5jwb"})
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# Referral
# ---------------------------------------------------------------------------
class TestReferral:
    def test_referral_code_and_link(self, client):
        c, _ = client
        data = _register(c, "ref1@test.com")
        r = c.get("/api/mobile/user/referral", headers=_auth(data["access_token"]))
        body = r.get_json()
        assert body["referral_code"]
        assert data["user"]["id"][:8].upper() == body["referral_code"]

    def test_referred_user_tracking(self, client):
        c, _ = client
        referrer = _register(c, "ref2@test.com")
        code = referrer["user"]["id"][:8].upper()
        r = c.post("/api/mobile/auth/register",
                   json={"email": "ref3@test.com", "password": "testpass123",
                         "referral_code": code})
        assert r.status_code == 201
        r = c.get("/api/mobile/user/referral", headers=_auth(referrer["access_token"]))
        assert len(r.get_json()["referred_users"]) == 1
