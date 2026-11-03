"""Per-exchange credential slots — pure helpers.

THE PROBLEM (user report): the bot stored ONE flat credential set
(api_key / api_secret / api_passphrase) shared by ALL exchanges. When the
user switched Binance -> WEEX / PrimeXBT:
  * the Binance credentials were silently reused on the new exchange
    (PrimeXBT even detects the 64-char Binance format and rejects it with
    "API-key format invalid", i.e. the "length doesn't match" error),
  * and saving the new exchange's credentials OVERWROTE the old exchange's
    credentials (same flat fields), so switching back meant re-entering
    everything again.

THE FIX: credentials are remembered PER EXCHANGE in a slot map:

    config["api_keys"] = {
        "binance":  {"api_key": "...", "api_secret": "...", "api_passphrase": ""},
        "weex":     {"api_key": "...", "api_secret": "...", "api_passphrase": "..."},
        "primexbt": {"api_key": "...", "api_secret": "...", "api_passphrase": ""},
    }

The FLAT fields (config["api_key"] / api_secret / api_passphrase) remain the
LIVE credentials of the ACTIVE exchange — every existing consumer (engine,
traders, start gate, mobile proxy) keeps reading them unchanged. The slots
only add memory:

  * save  -> typed credentials are stored in the ACTIVE exchange's slot
             (and mirrored to the flat fields),
  * switch-> the outgoing flat credentials are archived into the slot of the
             exchange they were used on (legacy migration), then the flat
             fields are hydrated from the NEW exchange's slot.

All functions are pure dict manipulators (no Flask / no I/O) so they can be
unit-tested in isolation and reused by the SaaS layer.
"""
from __future__ import annotations

EXCHANGES = ("binance", "weex", "primexbt")

_CRED_FIELDS = ("api_key", "api_secret", "api_passphrase")


def clean_cred(value) -> str:
    """Normalize a credential string: str(), strip whitespace/quotes."""
    try:
        return str(value or "").strip().strip('"').strip("'")
    except Exception:  # pragma: no cover - defensive
        return ""


def normalize_cred_slots(slots) -> dict:
    """Return a well-formed {exchange: {field: str}} slot map."""
    out: dict = {}
    src = slots if isinstance(slots, dict) else {}
    for ex in EXCHANGES:
        raw = src.get(ex) if isinstance(src.get(ex), dict) else {}
        out[ex] = {f: clean_cred(raw.get(f)) for f in _CRED_FIELDS}
    # Tolerate unknown exchange keys by folding them into the closest match
    # (they are simply ignored — never propagated).
    return out


def slot_has_creds(slot: dict) -> bool:
    """True when a slot holds at least a usable key+secret pair."""
    if not isinstance(slot, dict):
        return False
    return bool(clean_cred(slot.get("api_key")) and clean_cred(slot.get("api_secret")))


def slot_any_creds(cfg: dict) -> bool:
    """True when ANY exchange slot holds credentials."""
    for slot in (cfg.get("api_keys") or {}).values():
        if slot_has_creds(slot):
            return True
    return False


def resolve_exchange(value, default: str = "binance") -> str:
    ex = str(value or default).lower().strip()
    return ex if ex in EXCHANGES else default


def store_creds_in_slot(cfg: dict, exchange: str, api_key=None,
                        api_secret=None, api_passphrase=None) -> None:
    """Write non-empty credentials into the exchange's slot (never wipes)."""
    ex = resolve_exchange(exchange)
    slots = normalize_cred_slots(cfg.get("api_keys"))
    slot = slots[ex]
    if clean_cred(api_key):
        slot["api_key"] = clean_cred(api_key)
    if clean_cred(api_secret):
        slot["api_secret"] = clean_cred(api_secret)
    if clean_cred(api_passphrase):
        slot["api_passphrase"] = clean_cred(api_passphrase)
    slots[ex] = slot
    cfg["api_keys"] = slots


def archive_flat_into_slot(cfg: dict, exchange: str) -> None:
    """Remember the current flat credentials as the saved credentials of the
    exchange they were being used on (legacy one-set migration). Existing
    slot values win — an empty flat set never erases a saved slot."""
    if not (clean_cred(cfg.get("api_key")) or clean_cred(cfg.get("api_secret"))
            or clean_cred(cfg.get("api_passphrase"))):
        return
    ex = resolve_exchange(exchange)
    slots = normalize_cred_slots(cfg.get("api_keys"))
    slot = slots[ex]
    if clean_cred(cfg.get("api_key")) and not slot["api_key"]:
        slot["api_key"] = clean_cred(cfg.get("api_key"))
    if clean_cred(cfg.get("api_secret")) and not slot["api_secret"]:
        slot["api_secret"] = clean_cred(cfg.get("api_secret"))
    if clean_cred(cfg.get("api_passphrase")) and not slot["api_passphrase"]:
        slot["api_passphrase"] = clean_cred(cfg.get("api_passphrase"))
    slots[ex] = slot
    cfg["api_keys"] = slots


def hydrate_flat_from_slot(cfg: dict, exchange: str) -> None:
    """Make the flat fields reflect the credentials saved for `exchange`.
    This is the core of per-exchange memory: switching exchange auto-loads
    that exchange's own saved credentials (or clears the flat fields when
    that exchange has none — the old behaviour of reusing the previous
    exchange's keys is exactly what caused the -2014 / length errors)."""
    ex = resolve_exchange(exchange)
    slots = normalize_cred_slots(cfg.get("api_keys"))
    slot = slots[ex]
    cfg["api_key"] = slot["api_key"]
    cfg["api_secret"] = slot["api_secret"]
    cfg["api_passphrase"] = slot["api_passphrase"]


def merge_external_slots(cfg: dict, external) -> None:
    """Merge a payload-supplied per-exchange slot map (e.g. from the mobile
    API sync) into cfg's slots. Only non-empty values are applied so a
    partial payload can never wipe saved credentials."""
    if not isinstance(external, dict):
        return
    slots = normalize_cred_slots(cfg.get("api_keys"))
    changed = False
    for ex, slot in external.items():
        ex_l = resolve_exchange(ex, default="")
        if not ex_l or not isinstance(slot, dict):
            continue
        for field in _CRED_FIELDS:
            val = clean_cred(slot.get(field))
            if val and val != slots[ex_l][field]:
                slots[ex_l][field] = val
                changed = True
    if changed:
        cfg["api_keys"] = slots


def saved_exchanges_summary(cfg: dict) -> dict:
    """Per-exchange saved-credential summary safe to expose to any client
    (presence flags only — never the secrets themselves)."""
    slots = normalize_cred_slots(cfg.get("api_keys"))
    summary: dict = {}
    for ex in EXCHANGES:
        slot = slots[ex]
        summary[ex] = {
            "has_api_key": bool(slot["api_key"]),
            "has_api_secret": bool(slot["api_secret"]),
            "has_passphrase": bool(slot["api_passphrase"]),
            "ready": bool(slot["api_key"] and slot["api_secret"]
                          and (ex != "weex" or slot["api_passphrase"])),
        }
    return summary
