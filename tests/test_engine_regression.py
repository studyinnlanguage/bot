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
