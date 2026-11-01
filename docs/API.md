# WEEXIONIC Mobile API Reference (v2)

Base URL (compiled into the app): `https://weexionic.duckdns.org`
Authentication: `Authorization: Bearer <access_token>` (JWT HS256, 12h).
Refresh: 30-day token via `POST /api/mobile/auth/refresh`.
Errors: `{ "success": false, "error": "..." }` with proper HTTP status.

## Auth
| Method | Path | Body | Notes |
|---|---|---|---|
| POST | /api/mobile/auth/register | `{email, password, name?, referral_code?}` | 201 → tokens + user |
| POST | /api/mobile/auth/login | `{email, password}` | rate-limited 5/5min/IP |
| POST | /api/mobile/auth/refresh | `{refresh_token}` | rotates tokens |
| POST | /api/mobile/auth/google | `{id_token, referral_code?}` | Google ID token (audience-checked, email_verified enforced) |
| POST | /api/mobile/auth/logout | `{refresh_token}` | blocklists refresh token |
| GET | /api/mobile/auth/me | — | user + subscription + bot_config flags |

Google round-trip (browser deep-link): `GET /auth/google?client=mobile` →
consent → `weexionic://oauth?token=...&refresh_token=...`.

## Bot plane (all proxy to the caller's private engine; X-Bot-Token injected server-side)
| Method | Path | Body / Query |
|---|---|---|
| GET | /api/mobile/bot/status | — (engine status + balance + subscription) |
| POST | /api/mobile/bot/start / stop / force_stop | — |
| GET/POST | /api/mobile/bot/config | full config schema (secrets write-only; responses carry has_* flags only) |
| GET | /api/mobile/bot/positions | `?symbol=` optional |
| GET | /api/mobile/bot/trades | `?limit=1..500&symbol=` |
| POST | /api/mobile/bot/trades/clear | — |
| POST | /api/mobile/bot/close | `{symbol}` |
| POST | /api/mobile/bot/close_all | — |
| GET | /api/mobile/bot/symbols / balance / test_chart / price | `?symbol=` |
| POST | /api/mobile/bot/leverage | `{leverage, symbol?}` |
| POST | /api/mobile/bot/active_symbol | `{symbol}` |
| POST | /api/mobile/bot/test_connection / test_notification | — |

Realtime: Socket.IO at `/bot/socket.io` (Bearer header in `extraHeaders`),
server events: `log, status, balance, indicators, chart_data, signal, position,
trades_updated` (payload shapes in docs/AUDIT.md §3).

## Account / subscription / payments
| Method | Path | Notes |
|---|---|---|
| GET | /api/mobile/packages | package list + payment wallets |
| POST | /api/mobile/license/activate | `{key}` → activates subscription |
| POST | /api/mobile/orders/create | `{package_id}` → pending order (one at a time) |
| GET | /api/mobile/orders/my | order history |
| POST | /api/mobile/orders/submit | multipart: order_id, tx_hash, screenshot? (≤5MB, magic-byte checked) → auto on-chain verification |
| POST | /api/mobile/orders/check-verification/:id | re-poll blockchain |
| GET | /api/mobile/user/referral | link/code/earnings/history |
| POST | /api/mobile/user/payout-wallet | `{wallet_address}` |
| POST | /api/mobile/user/request-payout | withdraws FULL available balance (locked) |

## Admin surface (mobile): **NONE by design**
`/api/admin/*` remains web-only (session cookie + role check). Mobile tokens are
rejected with 403 — covered by automated tests.
