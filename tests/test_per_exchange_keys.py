"""PER-EXCHANGE CREDENTIAL MEMORY tests.

The reported bug: ONE flat credential set was shared by all exchanges.
Switching Binance -> WEEX/PrimeXBT reused the wrong keys ("API-key format
invalid" / key length mismatch) and saving the new exchange's keys wiped the
old exchange's keys, forcing full re-entry every time.

Guarantees under test:
  P1  cred_slots helpers: store/switch/archive/hydrate semantics
  P2  SaaS layer (runner): slot seeding, switch archiving, respawn rebuild
  P3  engine HTTP API: the exact user journey — save Binance keys, switch to
      WEEX (enter WEEX keys once), switch back to Binance -> Binance keys are
      still there; PrimeXBT (never configured) correctly reports no keys.
  P4  secrets (incl. the api_keys slot map) never leak through GET /api/config
"""
import importlib.util
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
ENGINE_SRC = REPO / "bot-engine"
RUNNER = REPO / "tests" / "_perexchange_runner.py"


# ---------------------------------------------------------------------------
# P1 — pure cred_slots helper semantics (loaded without the heavy bot package)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def cs():
    spec = importlib.util.spec_from_file_location(
        "cred_slots", ENGINE_SRC / "bot" / "cred_slots.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_p1_store_and_switch_roundtrip(cs):
    cfg = {"exchange": "binance", "api_key": "BINKEY", "api_secret": "BINSEC"}
    # save WEEX creds while active on WEEX
    cs.store_creds_in_slot(cfg, "weex", "WEXKEY", "WEXSEC", "WEXPASS")
    assert cfg["api_keys"]["weex"]["api_key"] == "WEXKEY"
    # switch to WEEX: archive binance flat, hydrate weex slot
    cs.archive_flat_into_slot(cfg, "binance")
    cs.hydrate_flat_from_slot(cfg, "weex")
    assert cfg["api_key"] == "WEXKEY"
    assert cfg["api_passphrase"] == "WEXPASS"
    # switch back: binance keys restored, weex slot intact
    cs.archive_flat_into_slot(cfg, "weex")
    cs.hydrate_flat_from_slot(cfg, "binance")
    assert cfg["api_key"] == "BINKEY"
    assert cfg["api_keys"]["weex"]["api_key"] == "WEXKEY"


def test_p1_pure_switch_without_saved_creds_clears_flat(cs):
    cfg = {"exchange": "binance", "api_key": "BINKEY", "api_secret": "BINSEC"}
    cs.archive_flat_into_slot(cfg, "binance")
    cs.hydrate_flat_from_slot(cfg, "primexbt")
    assert cfg["api_key"] == "" and cfg["api_secret"] == ""
    assert cfg["api_keys"]["binance"]["api_key"] == "BINKEY"


def test_p1_merge_never_wipes(cs):
    cfg = {"exchange": "weex",
           "api_keys": {"weex": {"api_key": "WEXKEY", "api_secret": "WEXSEC"}}}
    cs.merge_external_slots(cfg, {"weex": {"api_key": "NEWKEY"},
                                  "unknown_ex": {"api_key": "X"}})
    assert cfg["api_keys"]["weex"]["api_key"] == "NEWKEY"
    assert cfg["api_keys"]["weex"]["api_secret"] == "WEXSEC"
    assert "unknown_ex" not in cfg["api_keys"]
    cs.merge_external_slots(cfg, "not-a-dict")
    cs.merge_external_slots(cfg, {"weex": "not-a-dict"})


def test_p1_summary_flags(cs):
    cfg = {"api_keys": {"binance": {"api_key": "K", "api_secret": "S"},
                        "weex": {"api_key": "K2", "api_secret": "S2",
                                 "api_passphrase": "P"}}}
    s = cs.saved_exchanges_summary(cfg)
    assert s["binance"]["ready"] is True
    assert s["weex"]["ready"] is True
    assert s["primexbt"]["ready"] is False
    assert s["binance"]["has_passphrase"] is False


# ---------------------------------------------------------------------------
# P2 — SaaS layer scenarios (isolated subprocess runner)
# ---------------------------------------------------------------------------

def test_p2_saas_per_exchange_scenarios():
    proc = subprocess.run(
        [sys.executable, str(RUNNER)],
        cwd=str(REPO), capture_output=True, text=True, timeout=300,
    )
    line = next((l for l in proc.stdout.splitlines() if l.startswith("PEREX_JSON:")), None)
    assert line is not None, (
        f"runner produced no verdict\nstdout:\n{proc.stdout[-2000:]}\nstderr:\n{proc.stderr[-2000:]}")
    verdict = json.loads(line[len("PEREX_JSON:"):])
    for name, res in verdict["results"].items():
        assert res == "PASS", f"{name}: {res}"
    assert verdict["all_pass"] is True


# ---------------------------------------------------------------------------
# P3/P4 — engine HTTP integration (real engine subprocess)
# ---------------------------------------------------------------------------

def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="module")
def engine():
    port = _free_port()
    tmp = Path(tempfile.gettempdir()) / "wx_engine_perex"
    if tmp.exists():
        shutil.rmtree(tmp, ignore_errors=True)
    shutil.copytree(ENGINE_SRC, tmp, ignore=shutil.ignore_patterns(
        "logs", "data", "__pycache__", "*.pyc", "user_instances", "venv", ".git"))
    # LEGACY config: one flat credential set on binance, NO slots yet —
    # exactly the state of every existing user before this fix.
    cfg = {
        "api_key": "BINKEYLEGACY1234", "api_secret": "BINSECLEGACY5678",
        "exchange": "binance", "testnet": True, "symbol": "BTCUSDT",
        "symbols_list": ["BTCUSDT"], "timeframe": "5m",
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
    log_file = open(tmp / "test_perex.log", "w", encoding="utf-8")
    proc = subprocess.Popen([sys.executable, "app.py"], cwd=tmp, env=env,
                            stdout=log_file, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{port}"
    hdr = {"X-Bot-Token": "test-token-123"}
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
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")


def _post(base, path, hdr, payload):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(base + path, headers={**hdr, "Content-Type": "application/json"},
                                 data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")


def test_p4_get_config_hides_slots_and_reports_saved_map(engine):
    """GET /api/config must expose saved_exchanges presence flags but never
    the raw credential slot map."""
    base, hdr = engine
    code, body = _get(base, "/api/config", hdr)
    assert code == 200
    assert "api_key" not in body and "api_secret" not in body
    assert "api_keys" not in body, "raw per-exchange slot map leaked!"
    assert body["has_api_key"] is True  # legacy flat creds still honoured
    sv = body["saved_exchanges"]
    assert set(sv) == {"binance", "weex", "primexbt"}
    assert sv["binance"]["has_api_key"] is False  # slots not built yet (legacy)


def test_p3_full_switch_journey(engine):
    """THE user journey: binance keys saved -> switch WEEX (save WEEX keys
    once) -> switch back binance (keys intact) -> WEEX (keys intact) ->
    PrimeXBT (never configured -> no keys) -> back to Binance (still fine)."""
    base, hdr = engine

    # 1) Legacy binance keys are live and get archived on first switch.
    code, body = _post(base, "/api/config", hdr,
                       {"exchange": "weex", "api_key": "WEXKEY01",
                        "api_secret": "WEXSECRET01", "api_passphrase": "WEXPASS01"})
    assert code == 200 and body.get("success") is True, body
    code, body = _get(base, "/api/config", hdr)
    sv = body["saved_exchanges"]
    assert sv["weex"]["ready"] is True, sv
    assert sv["binance"]["has_api_key"] is True, "legacy binance creds lost on switch"
    assert body["has_api_key"] is True  # WEEX keys now live

    # 2) Pure switch back to Binance: legacy keys auto-restored.
    code, body = _post(base, "/api/config", hdr, {"exchange": "binance"})
    assert code == 200 and body.get("success") is True, body
    code, body = _get(base, "/api/config", hdr)
    assert body["has_api_key"] is True, "binance creds not restored on switch back"
    assert body["saved_exchanges"]["binance"]["has_api_key"] is True

    # 3) Switch to WEEX again: WEEX keys remembered (no re-entry needed).
    code, body = _post(base, "/api/config", hdr, {"exchange": "weex"})
    assert code == 200 and body.get("success") is True, body
    code, body = _get(base, "/api/config", hdr)
    assert body["has_api_key"] is True
    assert body["has_api_passphrase"] is True

    # 4) PrimeXBT was never configured: switching must NOT reuse other keys.
    code, body = _post(base, "/api/config", hdr, {"exchange": "primexbt"})
    assert code == 200 and body.get("success") is True, body
    code, body = _get(base, "/api/config", hdr)
    assert body["has_api_key"] is False, "foreign keys leaked into PrimeXBT slot"

    # 5) Back to Binance one last time: still intact.
    code, body = _post(base, "/api/config", hdr, {"exchange": "binance"})
    assert code == 200 and body.get("success") is True, body
    code, body = _get(base, "/api/config", hdr)
    assert body["has_api_key"] is True
    assert body["api_key_masked"].startswith("BINK"), body.get("api_key_masked")

    # 6) WEEX passphrase requirement: pure switch to WEEX keeps the passphrase.
    code, body = _post(base, "/api/config", hdr, {"exchange": "weex"})
    assert code == 200
    code, body = _get(base, "/api/config", hdr)
    assert body["has_api_passphrase"] is True
