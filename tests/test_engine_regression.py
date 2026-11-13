"""Bot-engine regression tests (B1/B2/B3/B16/S3) — runs the engine as a real
subprocess on a random port with a temp copy, then exercises the HTTP API."""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
ENGINE_SRC = REPO / "bot-engine"


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="module")
def engine():
    port = _free_port()
    tmp = Path(tempfile.gettempdir()) / "wx_engine_test"
    if tmp.exists():
        shutil.rmtree(tmp, ignore_errors=True)
    shutil.copytree(ENGINE_SRC, tmp, ignore=shutil.ignore_patterns(
        "logs", "data", "__pycache__", "*.pyc", "user_instances", "venv", ".git"))
    cfg = {
        "api_key": "TESTKEY123456", "api_secret": "TESTSECRET789",
        "exchange": "binance", "testnet": True, "symbol": "BTCUSDT",
        "symbols_list": ["BTCUSDT", "ETHUSDT"], "timeframe": "5m",
        "leverage": 10, "amount_mode": "fixed", "amount": 100, "amount_pct": 10,
        "stop_loss_pct": 2, "take_profit_pct": 2, "trailing_roe_pct": 100.0,
        "tp_mode": "fixed", "mode": "both", "auto_start": False,
        "telegram_enabled": False, "telegram_bot_token": "", "telegram_chat_id": "",
        "email_enabled": False, "email_smtp_server": "smtp.gmail.com",
        "email_smtp_port": 587, "email_sender": "", "email_password": "",
        "email_receiver": "", "whatsapp_enabled": False, "whatsapp_phone": "",
        "whatsapp_apikey": "", "max_concurrent_trades": 3,
        "min_ema_spread": 0, "fresh_window": 8,
    }
    (tmp / "config.json").write_text(json.dumps(cfg))
    env = {**os.environ, "PORT": str(port), "HOST": "127.0.0.1",
           "BOT_ENGINE_TOKEN": "test-token-123",
           "PYTHONPATH": str(tmp)}
    log_file = open(tmp / "test_engine.log", "w", encoding="utf-8")
    proc = subprocess.Popen([sys.executable, "app.py"], cwd=tmp, env=env,
                            stdout=log_file, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{port}"
    hdr = {"X-Bot-Token": "test-token-123"}
    # wait for boot
    for _ in range(60):
        try:
            urllib.request.urlopen(f"{base}/favicon.ico", timeout=2)
            break
        except Exception:
            time.sleep(0.5)
    yield base, hdr
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
    log_file.close()


def _get(base, path, hdr):
    req = urllib.request.Request(base + path, headers=hdr)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")


class TestEngineApi:
    def test_positions_without_symbol_no_500(self, engine):
        """B1: /api/positions without ?symbol= must return 200, never 500."""
        base, hdr = engine
        code, body = _get(base, "/api/positions", hdr)
        assert code == 200, body
        assert body["success"] is True
        assert isinstance(body["positions"], list)
        assert len(body["positions"]) >= 1  # BTCUSDT, ETHUSDT
        assert {p["symbol"] for p in body["positions"]} == {"BTCUSDT", "ETHUSDT"}

    def test_config_get_strips_secrets(self, engine):
        """S3: GET /api/config must never return raw secrets."""
        base, hdr = engine
        code, body = _get(base, "/api/config", hdr)
        assert code == 200
        assert "api_key" not in body, "raw api_key leaked!"
        assert "api_secret" not in body, "raw api_secret leaked!"
        assert "api_passphrase" not in body
        assert "email_password" not in body
        assert "telegram_bot_token" not in body
        assert "whatsapp_apikey" not in body
        assert body["has_api_key"] is True
        assert body["api_key_masked"] == "TEST***3456"

    def test_trades_bad_limit_no_500(self, engine):
        """B16: /api/trades?limit=abc must return 200 with defaults."""
        base, hdr = engine
        code, body = _get(base, "/api/trades?limit=abc", hdr)
        assert code == 200
        assert body["success"] is True
        assert "stats" in body

    def test_status_before_first_tick_no_500(self, engine):
        """B3: /api/status polled immediately after boot must not 500."""
        base, hdr = engine
        code, body = _get(base, "/api/status", hdr)
        assert code == 200, body
        assert "running" in body
        assert "workers" in body

    def test_api_requires_token(self, engine):
        base, hdr = engine
        try:
            urllib.request.urlopen(base + "/api/status", timeout=10)
            code = 200
        except urllib.error.HTTPError as e:
            code = e.code
        assert code == 403, "engine API must reject un-tokened requests"

    def test_close_all_without_positions_ok(self, engine):
        """B2 regression guard: close_all path must not raise NameError(time)."""
        base, hdr = engine
        req = urllib.request.Request(base + "/api/close_all", method="POST",
                                     headers={**hdr, "Content-Type": "application/json"},
                                     data=b"{}")
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                code, body = r.status, json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            code, body = e.code, json.loads(e.read().decode() or "{}")
        # with no positions the engine still responds cleanly (200) — no NameError 500
        assert code == 200, body
        assert body["success"] is True

    def test_fresh_window_2_to_8_clamped_and_persisted(self, engine):
        """Fresh Cross Window option in Manual Engine must accept 2..8 and clamp out-of-range values."""
        base, hdr = engine

        def _post_cfg(patch):
            req = urllib.request.Request(
                base + "/api/config", method="POST",
                headers={**hdr, "Content-Type": "application/json"},
                data=json.dumps(patch).encode(),
            )
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.status, json.loads(r.read().decode())

        code, body = _post_cfg({"fresh_window": 4, "min_ema_spread": 0.25})
        assert code == 200 and body["config"]["fresh_window"] == 4
        assert abs(body["config"]["min_ema_spread"] - 0.25) < 1e-9

        code, body = _post_cfg({"fresh_window": 25})
        assert code == 200 and body["config"]["fresh_window"] == 8

        code, body = _post_cfg({"fresh_window": 1})
        assert code == 200 and body["config"]["fresh_window"] == 2

    def test_take_profit_strictly_locked_at_1_pct_against_stale_cache(self, engine):
        """Even if a stale cached browser JS or old DB sends take_profit_pct=0.2 (old 1:1),
        /api/config must strictly lock take_profit_pct to 1.0% while keeping stop_loss_pct=0.2%."""
        base, hdr = engine
        req = urllib.request.Request(
            base + "/api/config", method="POST",
            headers={**hdr, "Content-Type": "application/json"},
            data=json.dumps({"stop_loss_pct": 0.2, "take_profit_pct": 0.2}).encode(),
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            code, body = r.status, json.loads(r.read().decode())
        assert code == 200
        assert abs(body["config"]["stop_loss_pct"] - 0.2) < 1e-9
        assert abs(body["config"]["take_profit_pct"] - 1.0) < 1e-9

    def test_custom_sl_spread_and_candles_persist_and_live_sync(self, engine):
        """User must be able to adjust fresh_window (2..8), stop_loss_pct, and min_ema_spread
        freely from the dashboard, have them persist across restarts, and live-sync to workers."""
        base, hdr = engine
        req = urllib.request.Request(
            base + "/api/config", method="POST",
            headers={**hdr, "Content-Type": "application/json"},
            data=json.dumps({
                "stop_loss_pct": 0.35,
                "min_ema_spread": 0.08,
                "fresh_window": 5,
                "take_profit_pct": 0.2,  # even if stale payload sends 0.2, TP stays 1.0
            }).encode(),
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            code, body = r.status, json.loads(r.read().decode())
        assert code == 200
        assert abs(body["config"]["stop_loss_pct"] - 0.35) < 1e-9
        assert abs(body["config"]["min_ema_spread"] - 0.08) < 1e-9
        assert body["config"]["fresh_window"] == 5
        assert abs(body["config"]["take_profit_pct"] - 1.0) < 1e-9

        # Verify config.json persisted custom values & survives a fresh load_config() import
        tmp = Path(tempfile.gettempdir()) / "wx_engine_test"
        saved = json.loads((tmp / "config.json").read_text(encoding="utf-8"))
        assert abs(saved["stop_loss_pct"] - 0.35) < 1e-9
        assert abs(saved["min_ema_spread"] - 0.08) < 1e-9
        assert saved["fresh_window"] == 5
        assert abs(saved["take_profit_pct"] - 1.0) < 1e-9

        chk = subprocess.run(
            [sys.executable, "-c",
             f"import sys, json; sys.path.insert(0, {str(tmp)!r}); import app; c = app.load_config(); print(json.dumps({{"
             "'sl': c['stop_loss_pct'], 'tp': c['take_profit_pct'], "
             "'sp': c['min_ema_spread'], 'fw': c['fresh_window']}))"],
            cwd=tmp, capture_output=True, text=True, timeout=15,
        )
        assert chk.returncode == 0, chk.stderr
        reloaded = json.loads(chk.stdout.strip().splitlines()[-1])
        assert abs(reloaded["sl"] - 0.35) < 1e-9
        assert abs(reloaded["tp"] - 1.0) < 1e-9
        assert abs(reloaded["sp"] - 0.08) < 1e-9
        assert reloaded["fw"] == 5

    def test_unknown_api_route_returns_json_not_html(self, engine):
        """Unknown /api/* paths must return JSON 404, never Flask <!doctype html>."""
        base, hdr = engine
        code, body = _get(base, "/api/does_not_exist_xyz", hdr)
        assert code == 404
        assert body["success"] is False
        assert "404" in body["error"]


