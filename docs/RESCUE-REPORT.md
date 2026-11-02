# Rescue Report Summary - 2026-11-02

Head: `93562da` (on top of `0d1ae4d`, `8e289ed`, origin/main `47ddb3e`).
Pre-rescue state: branch `rescue/backup-pre-exchange-fix`, tag `last-known-working-pre-rescue`.

## Production incident root causes

| Symptom | Root cause | Fix |
| --- | --- | --- |
| Binance `-2015` on startup | Valid-shape key rejected: TESTNET env with real (mainnet) key, or missing Futures permission | `validate_credentials()` at save-time + pre-flight; per-env human messages |
| Binance `-2014` on all symbols after Save | `ENCRYPTION_KEY` regenerated on redeploy (ephemeral FS) -> `decrypt()` silently returned `""` -> empty key sent | `decrypt_checked()` + `api_key_invalid` flag; empty key never pushed; set `ENCRYPTION_KEY` env var |
| Workers start then immediately die | Workers spawned before any auth check; leverage thread killed the bot on first auth failure | Pre-flight gate in `start()`: zero workers unless the read-only signed validation passes |
| Fake "Connected" states | Status derived from market data only | `connection{}` block: market_data / api_auth / balance_access / trading_permission / env |
| Real-funds risk | No explicit live unlock | `live_confirmed` config + red confirmation checkbox required for LIVE start |

## Adapter interface (uniform, per exchange - no shared auth code)

`connect/authenticate` (ctor + normalization) - `validate_credentials()` (read-only signed) -
`test_connection()` - `get_balance()` - `get_klines()` - `get_mark_price()` - `get_symbol_filters()` -
`set_leverage()` - `place/cancel orders` - `get_position()` - `close_position()` - `env_label()`.

Live verification 2026-11-02: Binance testnet `-2014` (empty/label key) vs `-2015` (valid-shape unknown key)
reproduced; PrimeXBT `/v3/trading/*` live with `X-API-KEY/TIMESTAMP/SIGNATURE` scheme, dead `/v2` confirmed;
WEEX geo-blocked from sandbox (503) - acceptance to run from production.

## Tests

- `tests/test_exchange_adapters.py` - 29 passed (normalization, signing vectors, mocked -2014/-2015,
  pre-flight gate, live-lock, duplicate workers, factory dispatch)
- `tests/test_engine_regression.py` - 6 passed
- `tests/test_mobile_api.py` - 25 passed

## Owner actions (deploy)

1. Push `main` (see DEPLOY-README in the rescue zip / RESCUE-COMMITS.patch).
2. Set env vars: `ENCRYPTION_KEY`, `ADMIN_SECRET`, `BOT_ENGINE_TOKEN`.
3. Redeploy; users re-save API keys once; run demo acceptance per exchange before LIVE.

Full narrative: `WEEXIONIC-RESCUE-REPORT-2026-11-02.docx` (delivered with the rescue package).
