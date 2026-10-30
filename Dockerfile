# ═══════════════════════════════════════════════════════════════════
# Weexionic — MERGED deployment (ONE container, ONE port, ONE domain)
#
#   ┌──────────────────────────────────────────────────────┐
#   │  Next.js frontend  (public :5000)                     │
#   │    - new Weexionic web dashboard                      │
#   │    - /api/* gateway → proxies the REAL bot backend    │
#   │    - rewrites  → classic bot pages (license,          │
#   │      packages, payment, admin, /home classic view)    │
#   ├──────────────────────────────────────────────────────┤
#   │  Flask SaaS backend (internal 127.0.0.1:5001)         │
#   │    - the ORIGINAL bot app.py (untouched strategy)     │
#   │    - users, licenses, referral, payouts, admin        │
#   │    - spawns per-user bot-engine processes             │
#   │      (EMA 8/13/21/55 REAL trading engine)             │
#   └──────────────────────────────────────────────────────┘
#
# Port stays 5000 so the existing Coolify domain mapping keeps working.
# All persistent state lives on the /app/data volume.
# ═══════════════════════════════════════════════════════════════════

# ── Stage 1: build the Next.js frontend ─────────────────────────────
# (Debian — glibc — so the standalone output's native binaries match the
#  Python-slim runtime stage below; alpine/musl binaries would NOT run here.)
FROM node:22-bookworm-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends openssl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /build
ENV NEXT_TELEMETRY_DISABLED=1

# 1) Install pinned dependencies first (cached layer)
COPY cloud/package.json cloud/package-lock.json ./
RUN npm ci --no-audit --no-fund

# 2) Copy the app source, generate the Prisma client, build
COPY cloud/ ./
RUN npx prisma generate && npm run build

# ── Stage 2: runtime — Python (real bot) + Node (frontend) ─────────
FROM python:3.11-slim-bookworm AS runtime

ENV NODE_MAJOR=22
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates curl gnupg openssl \
 && install -d -m 0755 /etc/apt/keyrings \
 && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
      | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
 && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_22.x nodistro main" \
      > /etc/apt/sources.list.d/nodesource.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends nodejs \
 && rm -rf /var/lib/apt/lists/* \
 && npm install -g prisma@6.19.2 --no-audit --no-fund

# Real bot Python dependencies (SaaS + per-user engines)
COPY requirements.txt /tmp/req-saas.txt
COPY bot-engine/requirements.txt /tmp/req-engine.txt
RUN cat /tmp/req-saas.txt /tmp/req-engine.txt | grep -vE '^\s*#|^\s*$' | sort -u > /tmp/req-all.txt \
 && pip install --no-cache-dir -r /tmp/req-all.txt

# ── Copy the REAL bot (strategy code untouched) ─────────────────────
WORKDIR /app
COPY app.py                    saas/app.py
COPY templates/                saas/templates/
COPY static/                   saas/static/
COPY bot-engine/               saas/bot-engine/
COPY cloud/scripts/migrate_cloud_users.py saas/scripts/migrate_cloud_users.py

# ── Copy the built frontend ─────────────────────────────────────────
COPY --from=builder /build/.next/standalone cloud/
COPY --from=builder /build/.next/static     cloud/.next/static
COPY --from=builder /build/public           cloud/public
COPY --from=builder /build/prisma           cloud/prisma
COPY cloud/docker-entrypoint.sh entrypoint.sh

RUN chmod +x ./entrypoint.sh \
 && mkdir -p /app/data/logs /app/data/instances /app/data/user_configs \
 && python3 -m py_compile saas/app.py

# ── Environment (stable across redeploys) ───────────────────────────
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=5000 \
    HOSTNAME=0.0.0.0 \
    HOST=127.0.0.1 \
    SAAS_PORT=5001 \
    INTERNAL_API=http://127.0.0.1:5001 \
    DATABASE_URL=file:/app/data/prod.db \
    CLOUD_DB_FILE=/app/data/prod.db \
    SAAS_DB_FILE=/app/data/database.json \
    SAAS_LOG_DIR=/app/data/logs \
    SAAS_INSTANCES_DIR=/app/data/instances \
    SAAS_USER_CONFIGS_DIR=/app/data/user_configs \
    SAAS_BOT_PROCESSES_FILE=/app/data/.bot_processes.json \
    BOT_ENGINE_DIR=/app/saas/bot-engine \
    FLASK_SECRET=wx-flask-9f4c2a7e51d84b6fa0c3e7d12b584af6c9d0e3b17a5c8f24d6e91b3a70c5f281 \
    BOT_ENGINE_TOKEN=wx-engine-t0ken-4b7d91e2a6c840f5b3d7e1a9c2f60845d7e3b1a9f5c8d204b6e7a1c3f9d50278 \
    ENCRYPTION_KEY=wx-enc-key-3f8a1c6e9d2b45708a3c6f9e1d4b7a2c5e8f1b4d7a0c3e6f9b2d5a8c1e4f7b0d \
    GOOGLE_CLIENT_ID=250359861566-clo6fnhv3nunfjpchs1hfulj96jp72kv.apps.googleusercontent.com \
    GOOGLE_CLIENT_IDS=250359861566-clo6fnhv3nunfjpchs1hfulj96jp72kv.apps.googleusercontent.com \
    APP_SHA256=A9E2C70C583657EDBAA0E9CCEFA73D1BBACC112A452669175C85E2C415E9EF74

VOLUME /app/data

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=6s --start-period=60s --retries=4 \
  CMD curl -fsS "http://127.0.0.1:${PORT:-5000}/api/health" >/dev/null 2>&1 || exit 1

ENTRYPOINT ["./entrypoint.sh"]
