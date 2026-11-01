# WEEXIONIC — Deployment & Operations

## Server (owner's VPS)

```bash
# 0) one-time: rotate the compromised defaults BEFORE going live
#    .env on the server must set:
#      ADMIN_SECRET=<long random>          # never keep the old default
#      ENCRYPTION_KEY=<32+ random chars>   # encrypts users' exchange API keys
#      FLASK_SECRET=<random>               # or rely on .flask_secret file
#      COOKIE_SECURE=1                     # session cookies only over HTTPS
#      GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / GOOGLE_REDIRECT_URI  (optional)
#      BOT_ENGINE_TOKEN=<random>           # SaaS↔engine shared secret

# 1) pull & restart
git fetch && git reset --hard origin/main   # first time after the history scrub
pip install -r requirements.txt
pm2 restart weexionic || pm2 start "gunicorn -w 1 --threads 16 --worker-class gthread -b 0.0.0.0:5000 app:app" --name weexionic
```

**HTTPS is mandatory for production** (mobile app refuses cleartext): terminate TLS
at Cloudflare/Nginx and keep `COOKIE_SECURE=1`. The mobile client is compiled
against `https://weexionic.duckdns.org` — keep that host valid.

## Database
- Default: `database.json` (atomic writes + in-memory cache). Single gunicorn worker REQUIRED.
- Optional: set `DATABASE_URL` (PostgreSQL) — schema auto-created. NOTE: `used_txids`,
  SMTP settings, wallets and bot-process registry are persisted for the JSON store and
  `settings`/`wallets` now also persist via DB; for PG deployments run one worker only.

## Mobile app
- Users install the APK from the GitHub Release (or Play Store via the AAB).
- No configuration: server URL is compiled into the binary.
- Play Store: upload `app-release.aab`, keep the release keystore safe (loss = cannot update).

## Monitoring & backup
- `logs/saas.log` (SaaS) + `logs/bot_<user_id>.log` (per-user engines) — not committed to git.
- Backup: `database.json`, `.flask_secret`, `.env`, `uploads/`, `keys/` (owner-side keystore copy).
- Rollback: `git checkout <previous-tag> && pm2 restart weexionic`.

## Admin (web only)
- Panel: `https://<host>/x7k2-admin` (or `ADMIN_SECRET_PATH`).
- Login with `ADMIN_SECRET`. Admin functions (users, licenses, orders, payouts,
  SMTP, wallets) are NOT exposed to the mobile app — mobile JWTs are rejected
  by every admin route (server-side role check, verified by tests).
