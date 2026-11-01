# WEEXIONIC — Security Documentation (Phase 6)

## Signing credential rotation (completed)

Both historical Android signing identities were exposed in git history
(`android-app/keystore-backup.jks` + `***REMOVED***` passwords in scripts/README;
`mobile/weexionic.keystore` + `***REMOVED***` in `mobile/build_apk.sh`).
Both are treated as **compromised and retired**:

1. A new 4096-bit release keystore (`weexionic-release-2026`) was generated
   OUTSIDE the repository and uploaded to GitHub Actions secrets
   (`ANDROID_KEYSTORE_B64`, `ANDROID_KS_PASS`, `ANDROID_KEY_ALIAS`, `ANDROID_KEY_PASS`).
2. The old WebView wrapper (`mobile/`) was deleted from the repository.
3. Git history is scrubbed (keystore blobs + password strings) via
   `git filter-repo` before this release is pushed (see commit notes).
   Anyone with an old clone must re-clone or `git fetch && git reset --hard origin/main`.
4. Release APKs from before v2.0.0 must be uninstalled before installing v2.0.0
   (signature change).

## Server-side hardening shipped in v2.0.0

- Default admin password / default encryption key remain as **fail-safe warnings**
  in code but MUST be overridden via env on production (documented in DEPLOYMENT.md).
- Google OAuth now rejects unverified emails; `google_id` binding kept.
- Payment activation + referral payouts are serialized by process-wide locks;
  activation is idempotent; `used_txids` blocks tx replay.
- Exchange API secrets: encrypted (Fernet) at rest in the SaaS DB; the engine
  config API returns only presence flags + masked previews (never raw secrets)
  to web AND mobile clients.
- Admin surface: session-cookie + `role=="admin"` only; the mobile JWT layer
  structurally cannot reach `/api/admin/*` (no cookie, separate decorator) —
  asserted by tests (`TestRoleSeparation`).
- Mobile client: HTTPS-only (no cleartext, no user-installed CA trust, no SSL bypass),
  session tokens via AsyncStorage (documented limitation — not KeyStore-class;
  no exchange secrets are ever stored on-device), refresh-token rotation +
  server-side revocation on logout.
- Rate limits: login/register/admin-login/quick-buy keyed on server-derived IP.
- `SESSION_COOKIE_SECURE` toggle for HTTPS deployments (`COOKIE_SECURE=1`).

## Remaining known risks (explicitly documented, not hidden)

1. **Default `ADMIN_SECRET`/`ENCRYPTION_KEY` fallbacks still exist in code** so a
   misconfigured fresh install keeps booting — but they log CRITICAL warnings.
   Recommend removing fallbacks entirely in a future release once the owner's
   `.env` is confirmed.
2. **No CSRF tokens** — JSON APIs are SameSite=Lax protected; multipart
   `/api/orders/submit` remains theoretically CSRF-able from a same-site form.
   Medium priority.
3. **PG mode** persists users/licenses/orders but NOT `used_txids`/`bot_processes`
   (JSON mode does). If PostgreSQL is enabled, restart wipes the replay guard —
   run JSON mode (current default) or complete the PG migration first.
4. **Socket.IO engine events** are broadcast without per-user rooms (the engine is
   a per-user private process bound to 127.0.0.1 — acceptable isolation today).
5. PrimeXBT demo `get_balance` still returns a labelled synthetic 10000 (demo only).
