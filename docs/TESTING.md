# WEEXIONIC Testing Report (Phase 5–6)

## Automated backend tests — PASSED 31/31

`pytest tests/ -q` → **31 passed** (tests/test_mobile_api.py + tests/test_engine_regression.py)

| Suite | Tests | Result |
|---|---|---|
| Auth (register/login/me/refresh/logout/garbage-token) | 7 | ✅ all pass |
| Role separation (JWT vs admin routes, no mobile admin surface) | 3 | ✅ all pass |
| Subscription & license flow (gate, activation, cross-account rejection) | 3 | ✅ all pass |
| Config validation (save/read, leverage clamps, bad exchange, bad types, encrypted keys) | 5 | ✅ all pass |
| Payment integrity (order create/list, single pending order, double-activation idempotency, txid replay block, payout atomicity) | 5 | ✅ all pass |
| Referral (code/link, referred-user tracking) | 2 | ✅ all pass |
| Engine regression (B1 positions, S3 secret strip, B16 limit guard, B3 status race, 403 auth, B2 close_all) | 6 | ✅ all pass |

Multi-user isolation is covered by: engine-per-user process spawn verified in the
SaaS (each `/api/mobile/bot/*` call resolves the caller's own engine via
`proxy_to_bot(user_id)`; test `test_bot_plane_open_after_activation` + admin RBAC
tests exercise the boundary).

## Bugs fixed in this release (verified by tests where marked)

| Bug | Fix | Test |
|---|---|---|
| Engine `/api/positions` 500 without `?symbol=` (B1) | `_symbols_list()` fallback | ✅ test |
| Engine `NameError: time` in close/close_all (B2) | `import time` | ✅ test |
| Engine `/api/status` 500 race before first tick (B3) | `last_check` init | ✅ test |
| `trades_today` persistence dead (B4) | use `history` | manual |
| Binance/WEEX test_connection always "success" (B5) | error propagation | manual (needs live keys) |
| PrimeXBT close result shape (B7) | handled by caller unpack | manual |
| WEEX raw balance logged at INFO (B7-sec) | debug level | code |
| SaaS `/api/bot/status`+`/api/bot/proxy` always 403 (S7) | X-Bot-Token injected | ✅ via /api/mobile/bot/status test |
| Watchdog dead — `DATA_DIR` NameError (S8) | `BASE_DIR` | boot log |
| Payment double-activation race (S5) | `_payment_lock` + idempotent activate | ✅ test |
| One tx funding many orders (S5) | txid recorded inside lock | ✅ test |
| Referral double-withdrawal race (S6) | `_payout_lock` | ✅ test |
| Google login without `email_verified` (S4) | verification enforced | code (needs OAuth env) |
| Auto-verify crashed after blockchain success (unpack 3-tuple) | unpack fixed | ✅ tests (flow) |
| Engine GET /api/config leaked ALL secrets (S3) | strip + has_* flags | ✅ test |
| SaaS config POST response leaked api_key/passphrase | strip | ✅ test |
| quick-buy brute-force oracle + 6-char password (S13) | rate limit + 8-char + generic msg | code |
| Admin login XFF spoof (S12) | remote_addr only | code |
| Wallets lost on restart (S15) | persisted to DB settings | code |
| Bad numerics → 500 (S16) | ValueError/TypeError → 400 handler | ✅ test |
| Admin panel stored XSS (S10) | `esc()` on all user data | code |
| Session cookie `Secure` flag (S14) | `COOKIE_SECURE=1` env for HTTPS prod | code |

## Mobile build

- TypeScript compiles clean (`tsc --noEmit`: 0 errors).
- Debug APK build: executed (Gradle 8.10.2, RN 0.76.5, all native modules autolinked).
- Release APK/AAB: built in CI with injected signing key (workflow ready + secrets set).

## NOT tested here (honest limitations)

- **Live exchange trading** — requires the owner's real API keys; testnet paths
  were exercised with dummy keys (connection honestly fails, engine idles safely).
- **Real-device UI testing** — no Android device in this environment; install the
  APK and walk the checklist below.
- **iOS build** — no macOS; project is delivered, build documented in BUILD.md.
- **Google OAuth round-trip on device** — requires `GOOGLE_CLIENT_ID/SECRET/REDIRECT_URI`
  set on the server + the deep link; code path follows the previously-proven
  `weexionic://oauth` flow.

## Device QA checklist for the owner

1. Install APK → splash → login screen (no server URL screen — ever).
2. Register → lands on Cockpit with STOPPED pill + TESTNET badge.
3. Engine tab: pick WEEX, save keys → has-key placeholders show "Saved — enter to replace".
4. Test Connection → honest result (fails with fake keys, succeeds with real).
5. Start bot → Cockpit shows RUNNING, workers spawn, chart streams.
6. Vault with no positions → "No open positions"; with a position → close flow asks confirm.
7. Ledger shows engine-recorded trades + stats; filters work.
8. Pulse streams logs live.
9. Account → Plans → create order → payment sheet (QR + txid) → poll.
10. Account → Referrals → link/code/earnings; wallet save + withdraw.
11. Kill network mid-session → stale badge, reconnection on network return.
12. Web login with the SAME account works and shows the same bot state.
