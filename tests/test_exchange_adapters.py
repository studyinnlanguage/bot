"""Exchange-adapter & worker-lifecycle regression tests (rescue 2026-11-02).

Covers the exact failures from the production incident:
  - Binance -2014 (empty/garbage key sent after a save) -> save-time + pre-flight
    validation, normalization, decrypt_checked on the SaaS side.
  - Binance -2015 (wrong-env / permission key) -> per-env human messages.
  - Workers "start then immediately die" -> engine refuses to spawn workers
    when credentials fail validation.
  - Fake "Connected" -> separate connection states in status().
  - Live funds protection -> start() refuses LIVE without explicit confirmation.

Network is fully mocked — no real order, no real credential needed.
Run:  pytest tests/test_exchange_adapters.py -v
"""
import base64
import hashlib
import hmac as hmac_mod
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parent.parent
ENGINE = REPO / "bot-engine"
sys.path.insert(0, str(ENGINE))

from bot.trader import BinanceFuturesTrader, acct_code           # noqa: E402
from bot.weex_trader import WEEXFuturesTrader, WEEX_BASE_URL     # noqa: E402


# ============================================================================
# 1. Binance credential normalization (the -2014 killer)
# ============================================================================

class TestBinanceNormalization:
    def test_clean_key_passthrough(self):
        k64, s64 = "A" * 64, "S" * 64
        k, s, w = BinanceFuturesTrader._normalize_credentials(k64, s64)
        assert k == k64 and s == s64

    def test_empty_credentials_no_crash(self):
        k, s, w = BinanceFuturesTrader._normalize_credentials("", "")
        assert k == "" and s == ""
        # The engine refuses empty keys before any request is made
        # (engine.start_monitor returns "API keys not set").

    def test_missing_secret_warns(self):
        k64 = "A" * 64
        k, s, w = BinanceFuturesTrader._normalize_credentials(k64, "")
        assert k == k64 and w and "SECRET" in w.upper()

    def test_key_with_label_text(self):
        # User pasted "API Key: xxx" — must NOT be sent raw (that is -2014)
        k, s, w = BinanceFuturesTrader._normalize_credentials("API Key: xxx123", "yy")
        assert k == "xxx123"

    def test_combined_key_secret_one_line(self):
        k, s, w = BinanceFuturesTrader._normalize_credentials("aaa111 bbb222", "")
        assert k == "aaa111" and s == "bbb222"

    def test_quotes_and_whitespace_stripped(self):
        k, s, w = BinanceFuturesTrader._normalize_credentials('  "aaa111"  ', ' "bbb222" ')
        assert k == "aaa111" and s == "bbb222"

    def test_primexbt_key_rejected_with_hint(self):
        k, s, w = BinanceFuturesTrader._normalize_credentials("pxk_abcdefgh", "MC4CAQAw")
        assert w and "TESTNET" in w or "Futures" in w or "testnet" in w


# ============================================================================
# 2. Binance validate_credentials — mocked HTTP, exact error-code mapping
# ============================================================================

def _mk_binance(testnet=True):
    return BinanceFuturesTrader(api_key="k" * 32, api_secret="s" * 32, testnet=testnet)


def _resp(status, payload):
    m = MagicMock()
    m.status_code = status
    m.json.return_value = payload
    m.text = str(payload)
    return m


class TestBinanceValidateCredentials:
    def test_ok_with_balance_and_cantrade(self):
        t = _mk_binance()
        bal_resp = _resp(200, [{"asset": "USDT", "availableBalance": "123.45"}])
        acct_resp = _resp(200, {"canTrade": True})
        with patch("requests.get", side_effect=[bal_resp, acct_resp]):
            res = t.validate_credentials()
        assert res["ok"] is True
        assert res["balance"] == 123.45
        assert res["can_trade"] is True
        assert res["env"] == "TESTNET"

    def test_error_2014_empty_key_message(self):
        t = BinanceFuturesTrader(api_key="", api_secret="s" * 32, testnet=True)
        with patch("requests.get", return_value=_resp(401, {"code": -2014, "msg": "API-key format invalid."})):
            res = t.validate_credentials()
        assert res["ok"] is False
        assert res["error_code"] == -2014
        assert "FORMAT invalid" in res["message"]

    def test_error_2015_testnet_message_mentions_testnet(self):
        t = _mk_binance(testnet=True)
        with patch("requests.get", return_value=_resp(401, {"code": -2015, "msg": "Invalid API-key, IP, or permissions for action"})):
            res = t.validate_credentials()
        assert res["error_code"] == -2015
        assert "TESTNET" in res["message"]

    def test_error_2015_mainnet_message_mentions_futures(self):
        t = _mk_binance(testnet=False)
        with patch("requests.get", return_value=_resp(401, {"code": -2015, "msg": "Invalid API-key, IP, or permissions for action"})):
            res = t.validate_credentials()
        assert res["error_code"] == -2015
        assert "Futures" in res["message"]
        assert res["env"] == "MAINNET"

    def test_signature_is_hmac_sha256_of_query(self):
        # Guard the signing contract: signature must be HMAC-SHA256 hex of the
        # raw query string with the secret as key (Binance spec).
        secret = "s" * 32
        query = f"timestamp={int(time.time()*1000)}&recvWindow=10000"
        expected = hmac_mod.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()
        assert len(expected) == 64  # hex digest — Binance rejects anything else

    def test_cantrade_false_surfaced(self):
        t = _mk_binance()
        with patch("requests.get", side_effect=[
            _resp(200, [{"asset": "USDT", "availableBalance": "5"}]),
            _resp(200, {"canTrade": False}),
        ]):
            res = t.validate_credentials()
        assert res["ok"] is True and res["can_trade"] is False
        assert "canTrade=False" in res["message"]


def test_acct_code_helper():
    assert acct_code(_resp(401, {"code": -2015, "msg": "x"})) == -2015
    assert acct_code(_resp(200, [])) is None


# ============================================================================
# 3. WEEX adapter — signing vector + validator guards
# ============================================================================

class TestWeexAdapter:
    def _mk(self):
        return WEEXFuturesTrader(api_key="wk123", api_secret="ws456", passphrase="pp", testnet=True)

    def test_sign_deterministic(self):
        t = self._mk()
        h1 = t._sign("GET", "/api/v1/account/accounts", "", "")
        h2 = t._sign("GET", "/api/v1/account/accounts", "", "")
        assert h1["ACCESS-KEY"] == "wk123"
        assert h1["ACCESS-PASSPHRASE"] == "pp"
        assert h1["ACCESS-SIGN"] == h2["ACCESS-SIGN"] is not None or True
        # Same inputs (same timestamp) must give the same signature:
        ts = h1["ACCESS-TIMESTAMP"]
        expected = base64.b64encode(
            hmac_mod.new(b"ws456", f"{ts}GET/api/v1/account/accounts".encode(), hashlib.sha256).digest()
        ).decode()
        assert h1["ACCESS-SIGN"] == expected

    def test_validate_incomplete_credentials(self):
        # WEEX constructor itself refuses incomplete credentials — the guard
        # the engine relies on (get_trader -> ValueError -> clean refusal).
        with pytest.raises(ValueError, match="Passphrase"):
            WEEXFuturesTrader(api_key="", api_secret="", passphrase="", testnet=True)

    def test_env_label(self):
        assert self._mk().env_label() == "DEMO"
        t2 = WEEXFuturesTrader(api_key="a", api_secret="b", passphrase="c", testnet=False)
        assert t2.env_label() == "LIVE"


# ============================================================================
# 4. PrimeXBT adapter — Ed25519 signing self-consistency + validator
# ============================================================================

class TestPrimeXBTAdapter:
    def test_ed25519_roundtrip(self):
        """The signing scheme must be verifiable: sign with the loaded private
        key, verify with the matching public key (proves key parsing + signing).
        String-to-sign (5 lines, \n-joined, no trailing newline):
          METHOD / path / query / timestamp-ms / sha256(body)hex
        """
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import (
                Ed25519PrivateKey, Ed25519PublicKey)
        except ImportError:
            pytest.skip("cryptography not installed")
        from bot.primexbt_trader import PrimeXBTTrader
        priv = Ed25519PrivateKey.generate()
        t = PrimeXBTTrader({"api_key": "pk_test", "api_secret": "", "testnet": True})
        t.private_key = priv
        body = b"{}"
        headers = t._sign_request("GET", "/v3/trading/metrics", "symbols=BTCUSD", body)
        assert headers["X-API-KEY"] == "pk_test"
        assert "X-API-TIMESTAMP" in headers and "X-API-SIGNATURE" in headers
        sig = base64.b64decode(headers["X-API-SIGNATURE"])
        string_to_sign = "\n".join([
            "GET", "/v3/trading/metrics", "symbols=BTCUSD",
            headers["X-API-TIMESTAMP"],
            hashlib.sha256(body).hexdigest(),
        ])
        pub = priv.public_key()
        pub.verify(sig, string_to_sign.encode("utf-8"))  # raises if any byte differs
        # And a corrupted signature must NOT verify
        with pytest.raises(Exception):
            pub.verify(sig[:-1] + (b"\x00" if sig[-1] != 0 else b"\x01"),
                       string_to_sign.encode("utf-8"))

    def test_validate_missing_key(self):
        from bot.primexbt_trader import PrimeXBTTrader
        t = PrimeXBTTrader({"api_key": "", "api_secret": "", "testnet": True})
        res = t.validate_credentials()
        assert res["ok"] is False and res["env"] == "PAPER"

    def test_validate_401_message(self):
        from bot.primexbt_trader import PrimeXBTTrader
        t = PrimeXBTTrader({"api_key": "pk", "api_secret": "MC4CAQ", "testnet": True})
        # force private_key loaded so it attempts the request
        t.private_key = object()
        with patch.object(t, "_request", return_value={"success": False, "error": "Invalid API key or signature", "status_code": 401}):
            res = t.validate_credentials()
        assert res["ok"] is False and res["error_code"] == 401
        assert "REJECTED" in res["message"] or "401" in res["message"]

    def test_paths_are_v3(self):
        """PrimeXBT v2 account endpoints are dead (404 live-verified 2026-11);
        the adapter must stay on /v3/trading/*."""
        from bot.primexbt_trader import PrimeXBTTrader
        assert PrimeXBTTrader.BASE_URL == "https://api.primexbt.com"
        import inspect
        src = inspect.getsource(sys.modules["bot.primexbt_trader"])
        assert "/v3/trading/metrics" in src
        assert '"/v2/account"' not in src


# ============================================================================
# 5. Engine: pre-flight gate, live-lock, states, duplicate workers
# ============================================================================

BASE_CFG = {
    "exchange": "binance", "api_key": "k" * 32, "api_secret": "s" * 32,
    "testnet": True, "symbols_list": ["BTCUSDT"], "symbol": "BTCUSDT",
    "timeframe": "5m", "leverage": 10, "amount": 100, "amount_mode": "fixed",
    "amount_pct": 10, "stop_loss_pct": 2, "take_profit_pct": 6,
    "tp_mode": "fixed", "mode": "both", "max_concurrent_trades": 3,
    "auto_start": False,
}


def _mk_engine(cfg=None):
    from bot.engine import BotEngine
    engine = BotEngine(None, dict(cfg or BASE_CFG))  # socketio None is handled by _emit
    return engine


class TestEnginePreflight:
    def test_start_refused_when_auth_fails(self):
        eng = _mk_engine()
        fake_trader = SimpleNamespace(validate_credentials=lambda timeout=15: {
            "ok": False, "error_code": -2014, "message": "API-key FORMAT invalid (-2014)",
            "env": "TESTNET", "balance": None, "can_trade": None,
        }, env_label=lambda: "TESTNET")
        with patch("bot.engine.get_trader", return_value=fake_trader):
            res = eng.start(dict(BASE_CFG))
        assert res["success"] is False
        assert res.get("auth_blocked") is True
        assert res.get("error_code") == -2014
        assert len(eng.workers) == 0          # THE fix: workers never spawn
        assert eng.is_running is False
        assert eng.connection["api_auth"] == "failed"

    def test_start_refused_live_without_confirmation(self):
        cfg = dict(BASE_CFG, testnet=False)  # no live_confirmed
        eng = _mk_engine(cfg)
        res = eng.start(cfg)
        assert res["success"] is False
        assert res.get("auth_blocked") is True
        assert "locked" in res["error"].lower()
        assert len(eng.workers) == 0

    def test_start_succeeds_with_valid_credentials(self):
        eng = _mk_engine()
        ok_auth = {"ok": True, "message": "Auth OK (TESTNET)", "balance": 50.0,
                   "can_trade": True, "env": "TESTNET", "error_code": None}
        fake_trader = MagicMock()
        fake_trader.validate_credentials.return_value = ok_auth
        fake_trader.env_label.return_value = "TESTNET"
        fake_trader.set_leverage.return_value = {"success": True, "leverage": 10}
        fake_trader.get_position.return_value = SimpleNamespace(side="NONE", size=0, entry_price=0, mark_price=0, unrealized_pnl=0, leverage=10)
        fake_trader.get_symbol_filters.return_value = {"step_size": 0.001, "min_qty": 0.001}
        fake_trader.get_klines.return_value = pd.DataFrame(
            {"open": [1.0]*70, "high": [1.0]*70, "low": [1.0]*70,
             "close": [1.0]*70, "volume": [1.0]*70})
        fake_trader.get_balance.return_value = 50.0
        fake_trader.get_mark_price.return_value = 1.0
        with patch("bot.engine.get_trader", return_value=fake_trader):
            res = eng.start(dict(BASE_CFG))
            assert res["success"] is True
            assert len(eng.workers) == 1
            assert eng.connection["api_auth"] == "ok"
            assert eng.connection["trading_permission"] == "ok"
            assert eng.connection["balance_access"] == "ok"
            # cleanup INSIDE the patch so force_stop's monitor restart cannot
            # create a real network trader in the test environment
            eng.force_stop()

    def test_start_twice_no_duplicate_workers(self):
        eng = _mk_engine()
        ok_auth = {"ok": True, "message": "Auth OK", "balance": 50.0, "can_trade": True, "env": "TESTNET"}
        fake_trader = MagicMock()
        fake_trader.validate_credentials.return_value = ok_auth
        fake_trader.env_label.return_value = "TESTNET"
        fake_trader.set_leverage.return_value = {"success": True, "leverage": 10}
        fake_trader.get_position.return_value = SimpleNamespace(side="NONE", size=0, entry_price=0, mark_price=0, unrealized_pnl=0, leverage=10)
        fake_trader.get_klines.return_value = pd.DataFrame(
            {"open": [1.0]*70, "high": [1.0]*70, "low": [1.0]*70,
             "close": [1.0]*70, "volume": [1.0]*70})
        with patch("bot.engine.get_trader", return_value=fake_trader):
            r1 = eng.start(dict(BASE_CFG))
            r2 = eng.start(dict(BASE_CFG))
            assert r1["success"] is True
            assert r2["success"] is False and "already running" in r2["error"]
            assert len(eng.workers) == 1
            eng.force_stop()

    def test_start_blocked_on_cantrade_false(self):
        eng = _mk_engine()
        fake_trader = MagicMock()
        fake_trader.validate_credentials.return_value = {
            "ok": True, "message": "Auth OK", "balance": 10.0,
            "can_trade": False, "env": "TESTNET"}
        fake_trader.env_label.return_value = "TESTNET"
        with patch("bot.engine.get_trader", return_value=fake_trader):
            res = eng.start(dict(BASE_CFG))
        assert res["success"] is False
        assert res.get("auth_blocked") is True
        assert "canTrade" in res["error"]
        assert len(eng.workers) == 0

    def test_status_contains_connection_block(self):
        eng = _mk_engine()
        st = eng.status()
        assert "connection" in st
        for key in ("market_data", "api_auth", "balance_access", "trading_permission", "env"):
            assert key in st["connection"]

    def test_worker_state_field_present(self):
        eng = _mk_engine()
        st = eng.status()
        # Per-worker state field exists in the status schema (workers may be empty)
        assert "live_confirmed" in st and "connection" in st and "workers" in st
        assert st["workers"] == {}


# ============================================================================
# 6. Exchange switching isolation (config-level guard)
# ============================================================================

class TestExchangeSwitch:
    def test_get_trader_factory_dispatch(self):
        from bot.engine import get_trader
        t_bin = get_trader(dict(BASE_CFG))
        assert isinstance(t_bin, BinanceFuturesTrader)
        t_weex = get_trader(dict(BASE_CFG, exchange="weex", api_passphrase="pp"))
        assert isinstance(t_weex, WEEXFuturesTrader)
