"""Tests for PrimeXBT PXTrader 2.0 integration, DEMO/LIVE separation, and single-use OAuth code exchange."""

import sys
import time
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bot-engine"))
sys.path.insert(0, str(ROOT))

from bot.primexbt_trader import PrimeXBTTrader


class TestPrimeXBTIntegration:
    """PrimeXBT PXTrader 2.0 authentication, diagnostics, and DEMO/LIVE isolation."""

    def test_primexbt_hmac_auth_detection(self):
        config = {
            "api_key": "px_test_api_key_12345",
            "api_secret": "px_secret_hmac_key_9876543210",
            "testnet": True,
        }
        trader = PrimeXBTTrader(config)
        assert trader.auth_mode == "hmac"
        assert trader.has_valid_auth is True
        assert trader.environment == "DEMO"
        assert trader.testnet is True

    def test_primexbt_sign_request_hmac(self):
        config = {
            "api_key": "px_test_key",
            "api_secret": "px_test_secret_12345678",
            "testnet": True,
        }
        trader = PrimeXBTTrader(config)
        headers = trader._sign_request("POST", "/v3/trading/orders/market/place", body_bytes=b'{"symbol":"BTC/USD"}')
        assert headers["X-API-KEY"] == "px_test_key"
        assert "X-API-TIMESTAMP" in headers
        assert "X-API-SIGNATURE" in headers
        assert len(headers["X-API-SIGNATURE"]) > 20

    def test_primexbt_binance_key_diagnostic(self):
        # 64-char alphanumeric string resembling a Binance API key
        binance_key = "a" * 64
        config = {
            "api_key": binance_key,
            "api_secret": "some_secret_key_value",
            "testnet": True,
        }
        trader = PrimeXBTTrader(config)
        diag = trader.test_connection()
        assert diag["success"] is False
        assert "Error -2014" in diag["error"]
        assert "Binance" in diag["cause"]

    def test_primexbt_demo_virtual_balance(self):
        # DEMO mode without API keys loaded
        config = {"api_key": "", "api_secret": "", "testnet": True}
        trader = PrimeXBTTrader(config)
        assert trader.environment == "DEMO"
        # In DEMO mode, returns virtual balance of $10,200
        bal = trader.get_balance()
        assert bal == 10200.0

    def test_primexbt_live_isolation_blocks_trading_without_keys(self):
        # LIVE mode without API keys loaded
        config = {"api_key": "", "api_secret": "", "testnet": False}
        trader = PrimeXBTTrader(config)
        assert trader.environment == "LIVE"
        assert trader.get_balance() == 0.0
        assert trader.get_balance_or_none() is None

        # Placing a live order must be strictly REFUSED without valid keys
        res = trader.place_order("BTC/USD", "BUY", 0.01)
        assert res["success"] is False
        assert "LIVE order blocked" in res["error"]
        assert res["environment"] == "LIVE"

    def test_primexbt_demo_simulated_order(self):
        # DEMO mode order placement returns simulated demo execution
        config = {"api_key": "", "api_secret": "", "testnet": True}
        trader = PrimeXBTTrader(config)
        res = trader.place_order("BTC/USD", "BUY", 0.05)
        assert res["success"] is True
        assert res["demo"] is True
        assert res["environment"] == "DEMO"
        assert res["order_id"].startswith("demo_px_")


class TestOAuthAndWalletEnhancements:
    """OAuth single-use code exchange and wallet address defaults."""

    @pytest.fixture
    def app_client(self):
        import app as saas_app
        saas_app.app.config["TESTING"] = True
        with saas_app.app.test_client() as client:
            yield client, saas_app

    def test_packages_returns_default_wallets(self, app_client):
        client, _ = app_client
        res = client.get("/api/mobile/packages")
        assert res.status_code == 200
        data = res.get_json()
        assert data["success"] is True
        wallets = data["wallets"]
        assert len(wallets.get("trc20", "")) >= 20
        assert len(wallets.get("bep20", "")) >= 20
        assert wallets["trc20"].startswith("T")
        assert wallets["bep20"].startswith("0x")

    def test_oauth_code_single_use_exchange(self, app_client):
        client, saas_app = app_client
        # Setup a dummy user and code in DB
        user_id = "test-user-oauth-123"
        saas_app.DB["users"][user_id] = {
            "id": user_id,
            "email": "oauth_user@weexionic.com",
            "name": "OAuth User",
            "role": "user",
            "banned": False,
            "subscription": {"plan": "lifetime", "status": "active"},
        }
        auth_code = "wx_test_auth_code_secret_token_123"
        saas_app.DB.setdefault("oauth_codes", {})[auth_code] = {
            "user_id": user_id,
            "created_at": time.time(),
            "expires_at": time.time() + 180,
            "used": False,
        }

        # 1. First exchange must succeed
        res = client.post("/api/mobile/auth/exchange-code", json={"code": auth_code})
        assert res.status_code == 200
        data = res.get_json()
        assert data["success"] is True
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["user"]["email"] == "oauth_user@weexionic.com"

        # 2. Second exchange with same code must be rejected (single-use)
        res_dup = client.post("/api/mobile/auth/exchange-code", json={"code": auth_code})
        assert res_dup.status_code == 400
        assert "already been used" in res_dup.get_json()["error"]

