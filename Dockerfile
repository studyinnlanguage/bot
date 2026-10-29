# ═══════════════════════════════════════════════════════════════════
# Weexionic Cloud dashboard — production image
#
# Builds the Next.js app in cloud/ (register/login, Google auth,
# referral system, Quad-Trend engine, wallet).
#
# NOTE: the old Flask trading bot Dockerfile is preserved as
#       Dockerfile.flaskbot (point Coolify at it to roll back).
#
# Port stays 5000 (same as the old bot) so existing Coolify domain /
# port mappings keep working without any changes.
# ═══════════════════════════════════════════════════════════════════

# ── Stage 1: build ──────────────────────────────────────────────────
FROM node:22-alpine AS builder

RUN apk add --no-cache libc6-compat openssl

WORKDIR /build

ENV NEXT_TELEMETRY_DISABLED=1

# 1) Install pinned dependencies first (cached layer)
COPY cloud/package.json cloud/package-lock.json ./
RUN npm ci --no-audit --no-fund

# 2) Copy the app source, generate the Prisma client, build
COPY cloud/ ./
RUN npx prisma generate && npm run build

# ── Stage 2: slim runtime ───────────────────────────────────────────
FROM node:22-alpine AS runner

# openssl/libc6-compat for Prisma engines; global prisma CLI so the
# entrypoint can sync the SQLite schema on every boot (idempotent)
RUN apk add --no-cache openssl libc6-compat \
 && npm install -g prisma@6.19.2 --no-audit --no-fund

WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=5000 \
    HOSTNAME=0.0.0.0 \
    DATABASE_URL=file:/app/data/prod.db \
    GOOGLE_CLIENT_IDS=250359861566-clo6fnhv3nunfjpchs1hfulj96jp72kv.apps.googleusercontent.com \
    APP_SHA256=A9E2C70C583657EDBAA0E9CCEFA73D1BBACC112A452669175C85E2C415E9EF74

COPY --from=builder /build/.next/standalone ./
COPY --from=builder /build/.next/static ./.next/static
COPY --from=builder /build/public ./public
COPY --from=builder /build/prisma ./prisma
COPY cloud/docker-entrypoint.sh ./entrypoint.sh

RUN chmod +x ./entrypoint.sh && mkdir -p /app/data

# Mount a Coolify persistent volume on /app/data to survive redeploys
VOLUME /app/data

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s --start-period=45s --retries=3 \
  CMD wget -qO- "http://127.0.0.1:${PORT:-5000}/api/health" >/dev/null 2>&1 || exit 1

ENTRYPOINT ["./entrypoint.sh"]
