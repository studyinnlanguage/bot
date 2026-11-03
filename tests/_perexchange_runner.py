"""Runs PER-EXCHANGE CREDENTIAL scenarios against the real SaaS layer in a
dedicated process (isolated from the pytest process, same pattern as
_coin_memory_runner.py). Prints a JSON verdict on stdout.

Guarantees:
  S1  flat dashboard save on binance -> seeded into the binance slot
  S2  pure exchange switch sync (binance->weex) -> binance slot archived,
      flat re-pointed (empty for weex), weex slot untouched
  S3  weex credentials save -> stored under weex slot AND legacy flat mirror
  S4  write_user_bot_config with an engine-file exchange switch: binance
      flat creds archived into the binance slot, weex creds loaded
  S5  write_user_bot_config fresh instance: DB slots -> config slots + flat
      hydrated from the ACTIVE exchange only
"""
import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import app as saas  # noqa: E402

UID = "perex-test-user"
results = {}


def _make_env():
    tmp = Path(tempfile.mkdtemp(prefix="perex_"))
    instances = tmp / "user_instances"
    instances.mkdir()
    saas.USER_INSTANCES_DIR = instances
    users = {UID: {"bot_config": {}}}
    saas.DB = {"users": users}
    return instances, users


def _write_engine_file(instances, cfg: dict):
    d = instances / UID
    d.mkdir(parents=True, exist_ok=True)
    (d / "config.json").write_text(json.dumps(cfg), encoding="utf-8")


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


@scenario("S1_flat_save_seeds_active_slot")
def _(instances, users):
    users[UID]["bot_config"] = {"exchange": "binance", "testnet": True}
    saas._sync_engine_config_to_db(users[UID], {
        "exchange": "binance", "api_key": "BINKEY", "api_secret": "BINSEC",
    })
    bc = users[UID]["bot_config"]
    slot = (bc.get("api_keys_enc") or {}).get("binance") or {}
    assert slot.get("api_key_enc"), "binance slot key not stored"
    ok, val = saas.decrypt_checked(slot["api_key_enc"])
    assert ok and val == "BINKEY", val
    ok2, val2 = saas.decrypt_checked(slot.get("api_secret_enc", ""))
    assert ok2 and val2 == "BINSEC", val2


@scenario("S2_pure_switch_archives_old_and_repoints_flat")
def _(instances, users):
    users[UID]["bot_config"] = {
        "exchange": "binance", "testnet": True,
        "api_key_enc": saas.encrypt("BINKEY"),
        "api_secret_enc": saas.encrypt("BINSEC"),
    }
    saas._sync_engine_config_to_db(users[UID], {"exchange": "weex"})
    bc = users[UID]["bot_config"]
    # binance slot now holds the archived legacy creds
    bslot = (bc.get("api_keys_enc") or {}).get("binance") or {}
    ok, val = saas.decrypt_checked(bslot.get("api_key_enc", ""))
    assert ok and val == "BINKEY", "legacy flat creds not archived into binance slot"
    # legacy flat re-pointed to the (empty) weex slot
    assert bc.get("api_key_enc") in ("", None), bc.get("api_key_enc")
    assert bc.get("api_secret_enc") in ("", None)
    # weex slot still empty
    wslot = (bc.get("api_keys_enc") or {}).get("weex") or {}
    assert not wslot.get("api_key_enc")
    assert bc.get("exchange") == "weex"


@scenario("S3_weex_save_stored_in_weex_slot")
def _(instances, users):
    users[UID]["bot_config"] = {
        "exchange": "weex", "testnet": True,
        "api_key_enc": saas.encrypt("BINKEY"),
        "api_secret_enc": saas.encrypt("BINSEC"),
        "api_keys_enc": {"binance": {"api_key_enc": saas.encrypt("BINKEY"),
                                     "api_secret_enc": saas.encrypt("BINSEC")}},
    }
    saas._sync_engine_config_to_db(users[UID], {
        "exchange": "weex", "api_key": "WEXKEY", "api_secret": "WEXSEC",
        "api_passphrase": "WEXPASS",
    })
    bc = users[UID]["bot_config"]
    wslot = (bc.get("api_keys_enc") or {}).get("weex") or {}
    ok, val = saas.decrypt_checked(wslot.get("api_key_enc", ""))
    assert ok and val == "WEXKEY", val
    okp, valp = saas.decrypt_checked(wslot.get("api_passphrase_enc", ""))
    assert okp and valp == "WEXPASS"
    # legacy flat mirrors the active (weex) set now
    okf, valf = saas.decrypt_checked(bc.get("api_key_enc", ""))
    assert okf and valf == "WEXKEY"
    # binance slot untouched
    bslot = (bc.get("api_keys_enc") or {}).get("binance") or {}
    okb, valb = saas.decrypt_checked(bslot.get("api_key_enc", ""))
    assert okb and valb == "BINKEY", "binance slot clobbered"


@scenario("S4_write_user_config_switch_loads_new_exchange_creds")
def _(instances, users):
    _write_engine_file(instances, {
        "exchange": "binance", "testnet": True,
        "api_key": "BINKEY", "api_secret": "BINSEC",
        "symbols_list": ["BTCUSDT"], "symbol": "BTCUSDT",
    })
    users[UID]["bot_config"] = {
        "exchange": "weex", "testnet": True,
        "symbols_list": ["BTCSUSDT"],
        "api_key_enc": saas.encrypt("WEXKEY"),
        "api_secret_enc": saas.encrypt("WEXSEC"),
        "api_passphrase_enc": saas.encrypt("WEXPASS"),
        "api_keys_enc": {"weex": {"api_key_enc": saas.encrypt("WEXKEY"),
                                  "api_secret_enc": saas.encrypt("WEXSEC"),
                                  "api_passphrase_enc": saas.encrypt("WEXPASS")}},
    }
    saas.write_user_bot_config(UID)
    cfg = _read_engine_file(instances)
    assert cfg["exchange"] == "weex"
    assert cfg["api_key"] == "WEXKEY", cfg.get("api_key")
    assert cfg["api_secret"] == "WEXSEC"
    assert cfg["api_passphrase"] == "WEXPASS"
    # the old binance flat creds were archived into the binance slot
    bslot = (cfg.get("api_keys") or {}).get("binance") or {}
    assert bslot.get("api_key") == "BINKEY", bslot
    assert bslot.get("api_secret") == "BINSEC"


@scenario("S4b_switch_without_new_exchange_creds_clears_flat")
def _(instances, users):
    _write_engine_file(instances, {
        "exchange": "binance", "testnet": True,
        "api_key": "BINKEY", "api_secret": "BINSEC",
        "symbols_list": ["BTCUSDT"], "symbol": "BTCUSDT",
    })
    users[UID]["bot_config"] = {"exchange": "weex", "testnet": True}
    saas.write_user_bot_config(UID)
    cfg = _read_engine_file(instances)
    assert cfg["exchange"] == "weex"
    assert cfg["api_key"] == "", "old exchange creds must not leak into weex"
    assert cfg["api_secret"] == ""
    bslot = (cfg.get("api_keys") or {}).get("binance") or {}
    assert bslot.get("api_key") == "BINKEY", "binance creds lost on switch"


@scenario("S5_fresh_instance_builds_slots_from_db")
def _(instances, users):
    users[UID]["bot_config"] = {
        "exchange": "primexbt", "testnet": True,
        "symbols_list": ["XAU/USD"],
        "api_keys_enc": {
            "binance": {"api_key_enc": saas.encrypt("BINKEY"),
                        "api_secret_enc": saas.encrypt("BINSEC")},
            "primexbt": {"api_key_enc": saas.encrypt("pxk_PXKEY"),
                         "api_secret_enc": saas.encrypt("PXSEC")},
        },
    }
    saas.write_user_bot_config(UID)
    cfg = _read_engine_file(instances)
    assert cfg["exchange"] == "primexbt"
    assert cfg["api_key"] == "pxk_PXKEY", cfg.get("api_key")
    assert cfg["api_secret"] == "PXSEC"
    slots = cfg.get("api_keys") or {}
    assert slots.get("binance", {}).get("api_key") == "BINKEY"
    assert slots.get("primexbt", {}).get("api_key") == "pxk_PXKEY"
    assert slots.get("weex", {}).get("api_key", "") == ""


@scenario("S6_legacy_flat_fresh_instance_seeds_active_slot")
def _(instances, users):
    users[UID]["bot_config"] = {
        "exchange": "binance", "testnet": True,
        "symbols_list": ["BTCUSDT"],
        "api_key_enc": saas.encrypt("BINKEY"),
        "api_secret_enc": saas.encrypt("BINSEC"),
    }
    saas.write_user_bot_config(UID)
    cfg = _read_engine_file(instances)
    assert cfg["api_key"] == "BINKEY"
    assert (cfg.get("api_keys") or {}).get("binance", {}).get("api_key") == "BINKEY"


for _fn in list(SCENARIOS):
    _fn()

verdict = {"all_pass": all(v == "PASS" for v in results.values()), "results": results}
print("PEREX_JSON:" + json.dumps(verdict))
sys.exit(0 if verdict["all_pass"] else 1)
