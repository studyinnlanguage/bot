"""Runs COIN MEMORY scenarios in a dedicated process (isolated from the
pytest process so importing the real app.py never pollutes other tests).
Prints a JSON verdict on stdout."""
import json
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "bot-engine"))
sys.path.insert(0, str(REPO))  # repo app.py wins over bot-engine/app.py

import app as saas  # noqa: E402

UID = "coinmem-test-user"
results = {}


def _make_env():
    tmp = Path(tempfile.mkdtemp(prefix="coinmem_"))
    instances = tmp / "user_instances"
    instances.mkdir()
    saas.USER_INSTANCES_DIR = instances
    users = {UID: {"bot_config": {}}}
    saas.DB = {"users": users}
    return instances, users


def _write_engine_file(instances, coins, exchange="binance"):
    d = instances / UID
    d.mkdir(parents=True, exist_ok=True)
    (d / "config.json").write_text(json.dumps({
        "exchange": exchange, "testnet": True,
        "symbol": coins[0] if coins else "BTCUSDT",
        "symbols_list": coins,
    }), encoding="utf-8")


def _read_engine_file(instances):
    return json.loads((instances / UID / "config.json").read_text(encoding="utf-8"))


def scenario(name):
    def deco(fn):
        def run():
            instances, users = _make_env()
            try:
                fn(instances, users)
                results[name] = "PASS"
            except AssertionError as e:
                results[name] = f"FAIL: {e}"
            except Exception as e:  # noqa: BLE001
                results[name] = f"ERROR: {type(e).__name__}: {e}"
        run.__name__ = name
        SCENARIOS.append(run)
        return run
    return deco


SCENARIOS: list = []


@scenario("user_coins_not_clobbered_by_stale_db")
def _(instances, users):
    """THE reported bug: engine file has user's coins, DB has stale 3 wrong
    coins -> user's coins must survive the respawn rebuild."""
    _write_engine_file(instances, ["DOGEUSDT", "XRPUSDT"])
    users[UID]["bot_config"] = {
        "exchange": "binance", "testnet": True,
        "symbols_list": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
    }
    saas.write_user_bot_config(UID)
    cfg = _read_engine_file(instances)
    assert cfg["symbols_list"] == ["DOGEUSDT", "XRPUSDT"], cfg["symbols_list"]


@scenario("db_coins_used_when_engine_file_missing")
def _(instances, users):
    _write_engine_file(instances, ["SOLUSDT", "BNBUSDT"])
    (instances / UID / "config.json").unlink()  # fresh instance after deploy
    users[UID]["bot_config"] = {
        "exchange": "binance", "testnet": True,
        "symbols_list": ["SOLUSDT", "BNBUSDT"],
    }
    saas.write_user_bot_config(UID)
    cfg = _read_engine_file(instances)
    assert cfg["symbols_list"] == ["SOLUSDT", "BNBUSDT"]
    assert cfg["symbol"] == "SOLUSDT"


@scenario("empty_db_symbols_fall_back_to_default")
def _(instances, users):
    users[UID]["bot_config"] = {"exchange": "binance", "testnet": True, "symbols_list": []}
    saas.write_user_bot_config(UID)
    cfg = _read_engine_file(instances)
    assert cfg["symbols_list"] == ["BTCUSDT"], cfg["symbols_list"]
    assert cfg["symbol"] == "BTCUSDT"


@scenario("exchange_switch_adopts_db_coins")
def _(instances, users):
    _write_engine_file(instances, ["DOGEUSDT", "XRPUSDT"], exchange="binance")
    users[UID]["bot_config"] = {
        "exchange": "primexbt", "testnet": True,
        "symbols_list": ["XAU/USD", "BTC/USD"],
    }
    saas.write_user_bot_config(UID)
    cfg = _read_engine_file(instances)
    assert cfg["exchange"] == "primexbt"
    assert cfg["symbols_list"] == ["XAU/USD", "BTC/USD"]
    assert cfg["symbol"] == "XAU/USD"


@scenario("empty_engine_file_coins_get_db_coins")
def _(instances, users):
    _write_engine_file(instances, [])
    users[UID]["bot_config"] = {
        "exchange": "binance", "testnet": True,
        "symbols_list": ["ETHUSDT"],
    }
    saas.write_user_bot_config(UID)
    cfg = _read_engine_file(instances)
    assert cfg["symbols_list"] == ["ETHUSDT"], cfg["symbols_list"]


for _fn in list(SCENARIOS):
    _fn()

# cleanup temp dirs created via _make_env
verdict = {"all_pass": all(v == "PASS" for v in results.values()), "results": results}
print("COINMEM_JSON:" + json.dumps(verdict))
sys.exit(0 if verdict["all_pass"] else 1)
