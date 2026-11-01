# WEEXIONIC — Full Repository Audit (Phase 1)

> Generated from source-level inspection of every relevant file (SaaS backend, bot-engine,
> web frontend, admin panel, exchange adapters, mobile artifacts, CI). Every finding cites
> `file:line`. This document is the foundation for the mobile rebuild — nothing below is
> speculation.

## 1. Repository structure

```
app.py                 # SaaS monolith (3,806 ln): auth, subscriptions, payments, referrals,
                       # admin, per-user bot-engine spawning, reverse proxy
bot-engine/            # Flask + Socket.IO trading engine (spawned per user)
  app.py               # X-Bot-Token-protected API + dashboard (1,009 ln)
  bot/engine.py        # BotEngine + SymbolWorker (2,263 ln)
  bot/strategy.py      # EMAQuadStrategy (EMA 8/13/21/55)
  bot/indicators.py    # indicator set
  bot/trader.py        # BinanceFuturesTrader (binance-futures-connector)
  bot/weex_trader.py   # WEEXFuturesTrader (OKX-style HMAC, passphrase required)
  bot/primexbt_trader.py # PrimeXBTTrader (Ed25519, v3 API, Yahoo fallback data)
  bot/history.py       # JSON trade history (data/trade_history.json)
  bot/notifier.py      # Telegram / Email / WhatsApp(CallMeBot)
  static/              # dashboard UI (7-tab gold-dark redesign)
templates/             # SaaS pages: home, login, packages, payment, license, admin, legal
mobile/                # OLD Android WebView wrapper (package ai.weexionic.app) — TO BE REPLACED
mobile/build_apk.sh    # dependency-free APK pipeline (aapt2/ecj/d8/apksigner)
.github/workflows/     # build-apk.yml (manual toolchain CI)
Dockerfile, Procfile, railway.json, install.sh, requirements.txt
```

**Deployment model**: owner's server runs the SaaS (gunicorn 1 worker × 16 threads or
dev server). Each user gets a private bot-engine process in `user_instances/<user_id>/`
on a 127.0.0.1 port (5001–5999), reached only through the SaaS reverse proxy `/bot/*`
which injects the `X-Bot-Token` shared secret after session + subscription checks.
**Users never touch the engine directly.**

## 2. Feature inventory (user-facing)

| Area | Features (existing, verified in code) | Backend surface |
|---|---|---|
| Auth | email+password signup/login, Google OAuth, logout, rate limits | `POST /api/auth/signup|login|logout`, `GET /api/auth/me`, `GET /auth/google(+callback)` |
| Account | profile, subscription status/expiry, license activation | `GET /api/auth/me`, `POST /api/license/activate` |
| Bot control | start/stop/status, engine config read/write, quick leverage, force stop | `POST /api/bot/start|stop`, `GET /api/bot/status`, `GET/POST /api/bot/config`, `POST /api/bot/proxy` |
| Cockpit (dashboard) | candle chart + EMA 8/13/21/55, live signals, indicators, balance, workers telemetry, start/stop, manual close, force reset | `GET /bot/api/*` via proxy + Socket.IO `log,status,indicators,chart_data,signal,position,balance,trades_updated` |
| Vault (positions) | open positions w/ entry/mark/size/lev/PnL/TP/SL, close one / close all | `GET /bot/api/positions?symbol=`, `POST /bot/api/close`, `POST /bot/api/close_all` |
| Ledger (history) | trade history, filters, stats, clear | `GET /bot/api/trades`, `POST /bot/api/trades/clear` |
| Engine (config) | exchange (binance/weex/primexbt), testnet, API keys (+WEEX passphrase), symbols, timeframe, leverage 1–{125,500,1000}, amount fixed/%, SL%, 1:1 TP, mode long/short/both, max concurrent 1–3, min EMA spread, fresh window | `GET/POST /bot/api/config`, `POST /bot/api/leverage`, `POST /bot/api/test_connection`, `GET /bot/api/symbols` |
| Radar (alerts) | Telegram / Email SMTP / WhatsApp(CallMeBot) config + test | `POST /bot/api/test_notification` (+config fields) |
| Pulse (logs) | live engine logs | Socket.IO `log` |
| Subscription | packages (yearly $79 / lifetime $500), USDT TRC20/BEP20 payment orders, tx submit + screenshot, auto on-chain verification, re-poll | `GET /api/packages`, `POST /api/orders/create|submit|check-verification/<id>`, `GET /api/orders/my` |
| Referrals | code/link, referred users, earnings ($10/$50 per activation), payout wallet, withdrawal request, history | `GET /api/user/referral`, `POST /api/user/payout-wallet`, `POST /api/user/request-payout` |
| Admin (WEB ONLY) | login via shared secret, users ban/delete, licenses create/revoke/delete, orders verify/reject, SMTP, wallets, payouts approve, logs | `/api/admin/*` (session + `role=="admin"`) |

## 3. API inventory (mobile-relevant contract)

Root plane (SaaS, cookie session): `/api/auth/*`, `/api/license/activate`, `/api/packages`,
`/api/orders/*`, `/api/user/referral`, `/api/user/payout-wallet`, `/api/user/request-payout`.

Bot plane (through `/bot/*` reverse proxy; proxy injects `X-Bot-Token`; socket.io at
`/bot/socket.io`): `/bot/api/config` (GET/POST), `/bot/api/start|stop|force_stop|leverage|
active_symbol|close|close_all|test_connection|test_notification|preview`, `/bot/api/status|
positions|trades|balance|symbols|price|test_chart`, `/bot/api/trades/clear`.

Engine `GET /api/config` response currently **leaks secrets** — see §6 (must be fixed
before mobile ships).

Socket.IO payloads (engine → clients): `log{level,msg}`, `status{running,trades_today,
exchange,symbols[],timeframe,leverage,amount_mode,amount,amount_pct,stop_loss_pct,
take_profit_pct,tp_mode,mode,testnet,workers{...}}`, `balance{balance,exchange,testnet,demo}`,
`indicators{symbol,ema_8,ema_13,ema_21,ema_55,signal,close,...}`, `chart_data{symbol,
candles[],emas{}}`, `signal{symbol,signal,reason,emas}`, `position{symbol,side,size,
entry_price,mark_price,unrealized_pnl,leverage,tp_price,sl_price,...}`,
`trades_updated{trades[],stats}`.

## 4. Data & persistence

- In-memory dict `DB` (app.py:798) → PostgreSQL (`DATABASE_URL`) or `database.json`.
  Tables: `users` (bot_config JSONB w/ Fernet-encrypted exchange keys, subscription,
  referral fields, payout_requests), `licenses`, `orders`. `app.py:393–514`.
- NOT persisted in PG mode: `used_txids` (payment replay guard), `settings` (SMTP),
  `bot_processes` → reset/lost on restart (bug S9 below).
- Engine state per user: `user_instances/<uid>/config.json` (plaintext keys), trade
  history JSON, logs.

## 5. Authentication & authorization analysis

- Passwords: werkzeug pbkdf2:sha256:260000 (+legacy salt$sha256 accepted).
- Sessions: Flask signed cookie 7d, HttpOnly, SameSite=Lax; **no `Secure` flag**.
- Google: manual OAuth2 code flow; **no `email_verified` check** (takeover risk).
- Admin: `users.role=="admin"`; promotion by posting shared `ADMIN_SECRET` to
  `/api/admin/login` (default password hardcoded).
- **Mobile plan**: JWT bearer blueprint (`/api/mobile/*`) issuing short-lived tokens
  derived from the SAME user accounts (no duplicate identity); bot plane reached via
  JWT-authenticated proxy; admin endpoints untouched and web-only; admin APIs
  unreachable with mobile tokens (different auth mechanism + explicit role checks).

## 6. Bug list (engine)

| ID | Severity | Finding | Fix |
|---|---|---|---|
| B1 | critical | `/api/positions` & `/api/position` 500 without `?symbol=` (`ENGINE.symbols` doesn't exist, app.py:530) | use `_symbols_list()` |
| B2 | critical | `NameError: time` in `/api/close` (app.py:633,732) — manual close succeeds then 500s; `close_all` reports failure for successful closes | `import time` |
| B3 | high | `/api/status` 500 race: `worker.last_check` unset before first tick (engine.py:2258) | init in `__init__` |
| B4 | medium | `trades_today` persistence dead (`self.trade_history` typo, engine.py:2228) | use `self.history` |
| B5 | high | Binance/WEEX `test_connection` always success (get_balance swallows errors → 0.0) | propagate failures |
| B6 | medium | PrimeXBT paper `get_balance` returns fake 10000 | keep `demo:true` label; document |
| B7 | medium | PrimeXBT close fallback result lacks `success` key → success treated as failure | normalize result |
| B8 | medium | PrimeXBT qty hardcoded 4-dp (ignores qty_step) | use symbol filters |
| B9 | low | WEEX `set_leverage` 27-request spray + false success cache | single canonical attempt + honest failure |
| B10 | medium | `get_active_positions()` iterates `self.workers` without lock → RuntimeError during config saves | lock |
| B11 | low | `DefaultPos.mark_price` always 0.0 → UI PnL blank on fetch failure | pass mark_price |
| B12 | medium | POST accepts `tp_mode:trailing|ema_reversal` but loader force-reverts to `fixed` (silent change) | document + honest response |
| B13 | low | SL-min log shows corrected value, hides original | log original |
| B14 | low | `stop()` restarts monitor that `/api/stop` immediately kills | don't restart in stop() |
| B15 | low | `auto_start` config never read (engine) | document (SaaS controls start) |
| B16 | low | `/api/trades` `int(limit)` unguarded; `status()` default tp_mode `both` vs enforced `fixed` | guard + align |

## 7. Security findings (SaaS + engine + frontend)

| ID | Severity | Finding |
|---|---|---|
| S1 | critical | Hardcoded default admin password in app.py/install.sh/README (removed & scrubbed in v2.0.0) |
| S2 | critical | Default `ENCRYPTION_KEY` fallback (app.py:186–190) |
| S3 | critical | Engine `GET /api/config` returns plaintext `api_key/api_secret/api_passphrase/email_password/telegram_bot_token/whatsapp_apikey` (bot-engine/app.py:236–245) |
| S4 | critical | Google OAuth: no `email_verified` check; `google_id` mismatch silently overwritten (app.py:2779–2790, 2844–2846) |
| S5 | critical | Payment double-activation race (`/api/orders/submit` vs `/api/orders/check-verification`) + `used_txids` check-then-set race → one tx can fund multiple orders |
| S6 | high | Referral withdrawal race (no lock, app.py:1950–1973); no payout reject endpoint |
| S7 | high | `proxy_to_bot()` sends no `X-Bot-Token` → `/api/bot/status`, `/api/bot/proxy` always 403 when token set (app.py:1413–1432) |
| S8 | high | Watchdog dead: `DATA_DIR` undefined (app.py:3736) → crashed engines never auto-restarted by watchdog |
| S9 | high | PG mode loses `used_txids`/`settings`/`bot_processes` on restart → tx replay + duplicate engines |
| S10 | high | Stored XSS in admin panel (tx_hash, names, wallet, reasons → innerHTML, saas_admin.html:370–687) |
| S11 | medium | No CSRF tokens (mitigated by SameSite=Lax for JSON; multipart endpoint exposed) |
| S12 | medium | Rate limits keyed on `remote_addr` (collective lockout behind proxy) + admin login trusts spoofable `X-Forwarded-For` |
| S13 | medium | `/api/orders/quick-buy`: unauthenticated password oracle, enumeration, 6-char minimum |
| S14 | medium | `SESSION_COOKIE_SECURE` unset (cleartext cookie on HTTP deploys) |
| S15 | medium | Admin wallet changes runtime-only (never persisted) → users may pay stale address |
| S16 | medium | Unvalidated numerics → 500s (api_bot_config, orders days, trades limit) |
| S17 | low | Referral link from `X-Forwarded-Host` verbatim; `stop_user_bot` PID kill w/o ownership check; GET state-change on check-verification; TRON −0.5 tolerance; legacy weak hashes |
| S18 | high | Mobile/CI: signing keystore + passwords committed to repo (`mobile/weexionic.keystore`, `mobile/build_apk.sh`; plus historical `android-app/keystore-backup.jks`, `***REMOVED***` in scripts/README) — **treated as compromised; rotation + history scrub mandatory** |
| S19 | medium | Old wrapper: `usesCleartextTraffic`, trust-all-SSL option — removed entirely in native rebuild |

## 8. Prior architecture notes (from git history)

A native Java Android app (`com.weexionic.app`, v3.7.0, branches `backup-pre-revert-*`)
existed previously: cookie-session auth, **baked-in server `https://weexionic.duckdns.org`**,
deep-link Google OAuth (`weexionic://oauth`), polling `/api/bot/proxy` snapshot. This
confirms (a) the production base URL, (b) that deep-link OAuth round-trip works with the
current SaaS when enabled.

## 9. Missing implementations (must NOT be invented)

- iOS app (no macOS in build env) — project + config delivered; build requires Xcode.
- Real-device testing matrix — requires physical devices.
- Play Store submission — AAB produced; submission is owner's step.
- Live exchange trading verification — requires owner's API credentials; testnet paths
  exercised where available (Binance testnet, WEEX demo).
