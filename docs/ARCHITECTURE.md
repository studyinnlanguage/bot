# WEEXIONIC Mobile — Architecture & Plan (Phase 2)

## 1. Technology choice (documented reason)

**React Native 0.76.5 + TypeScript** (bare workflow, no Expo runtime):

- Single codebase → Android APK/AAB **and** an iOS project that builds under Xcode
  (owner has no macOS CI; `ios/` is delivered build-ready).
- Real native views (no WebView) — charts rendered with `react-native-svg`, realtime
  via `socket.io-client`, storage via `AsyncStorage`.
- Team-size reality: RN ecosystem is the maintainable path for one developer + CI.

Dependencies kept minimal on purpose (build reliability): react-navigation
(native-stack + bottom-tabs), react-native-screens, react-native-safe-area-context,
react-native-svg, react-native-qrcode-svg, @react-native-async-storage/async-storage,
socket.io-client.

## 2. Server connection (invisible to users)

- Production base URL baked into `src/config/env.ts` → `https://weexionic.duckdns.org`
  (the platform's existing production host, confirmed from prior native app source).
- Environments: `__DEV__` builds may point to a dev host via `WEEXIONIC_DEV_URL`
  env at bundle time; release builds compile with the production URL only.
- HTTPS only: `android:usesCleartextTraffic=false`, no user-installed-CA trust,
  no SSL-bypass anywhere in the app.
- Users never see URLs, ports or IPs. Install → Open → Register/Login → Use.

## 3. Authentication & session flow

```
Splash ── has token? ── GET /api/mobile/auth/me ── valid? ──► App Tabs
   │                        │ 401 → refresh → login
   └► Login/Register ◄──────┘
Google: system browser → GET /auth/google?client=mobile →
        SaaS OAuth → redirect weexionic://oauth?token=<JWT> → app captures (Linking)
```

- **JWT access token (12h) + refresh token (30d)** issued by the SaaS from the SAME
  user accounts (`users` table). No duplicate identity, web & mobile share accounts.
- Stored via AsyncStorage (documented limitation: not KeyStore-grade; exchange API
  secrets are NEVER stored on device — they live encrypted in the SaaS DB).
- Logout destroys refresh token server-side (blocklist row) + clears device storage.

## 4. Role-based access (server-side, per requirement)

- Mobile JWTs carry `role` claim. `/api/admin/*` endpoints remain **session-cookie
  authenticated and additionally verify `users.role=="admin"`** — a bearer JWT can
  never reach them (different auth mechanism; decorators reject non-cookie sessions).
- The mobile app contains **zero admin screens, navigation, or API calls**.
- Admin panel stays web-only at `ADMIN_SECRET_PATH` exactly as today.

## 5. Screen ↔ API mapping (feature-complete)

| Screen | Data source |
|---|---|
| Splash | token validation (`GET /api/mobile/auth/me`) |
| Login / Register | `POST /api/mobile/auth/login|register`, Google deep-link flow |
| Cockpit | `GET /api/mobile/bot/status` (engine status+balance aggregate) + Socket.IO `status,balance,indicators,chart_data,signal,position` via JWT socket path; controls `start/stop/force_stop/close` |
| Vault | `GET /api/mobile/bot/positions` (+per-symbol), `POST close/close_all` w/ confirm |
| Ledger | `GET /api/mobile/bot/trades?limit&symbol`, filters, stats, clear |
| Engine | `GET/POST /api/mobile/bot/config` (every field incl. WEEX passphrase, min_ema_spread, fresh_window, max_concurrent_trades), `POST leverage`, `POST test_connection`, `GET symbols` |
| Radar | notification fields via config, `POST test_notification` |
| Pulse | Socket.IO `log` stream |
| Account | `GET /api/mobile/auth/me`, subscription, `POST /api/mobile/license/activate`, packages+orders+payment (order create, tx submit + screenshot upload, verification poll, QR), referral + payout wallet + withdraw |

## 6. Realtime plan

Socket.IO client → `https://host/bot/socket.io` with `extraHeaders: {Authorization:
Bearer <jwt>}` (the SaaS `/bot/` proxy is extended to accept the mobile JWT **for the
socket path and API proxy only**; admin & SaaS pages remain cookie-only).
Reconnect: exponential backoff, stale-data badges after 15s silence, transparent
resubscribe.

## 7. Security design

- No cleartext HTTP; certificate errors fail closed.
- JWT secrets server-side only; refresh rotation on reuse; tokens short-lived.
- Exchange API keys never leave the server (engine config GET strips secrets — fixed
  in this release); the app shows masked values only.
- New Android release keystore generated **outside the repo**, injected via GitHub
  Actions secrets; old keystores + passwords scrubbed from git history (rotation).
- Payment flows untouched (same server logic); no fabricated success states.

## 8. Testing strategy

- **Backend**: pytest suite covering mobile auth (register/login/refresh/me/logout),
  RBAC (JWT vs admin routes), bot proxy auth + isolation (two users → two engines),
  config secret stripping, payment idempotency, payout locking, engine fixes
  (positions, close, status race), license activation edge cases.
- **Web regression**: boot both apps, exercise every page/route, confirm no changed
  behavior for browser clients.
- **Mobile**: build gate (assembleRelease must succeed), unit tests for API client &
  reducers where feasible, manual device checklist shipped in docs.
- **Integration**: end-to-end against locally-run SaaS + engine with fake keys
  (testnet), exercising login → config → start → status → positions → history.

## 9. Delivery order

Phase 3 backend → Phase 4 app → Phase 5 tests → Phase 6 security (keystore rotation,
history scrub, CI secrets) → Phase 7 builds (release APK + AAB + iOS config) → docs.
