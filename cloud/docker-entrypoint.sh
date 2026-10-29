#!/bin/sh
# Weexionic Cloud container entrypoint
# 1. Make sure the SQLite data directory exists (mount a Coolify volume here
#    at /app/data to keep users/trades persistent across redeploys)
# 2. Sync the Prisma schema (creates tables on a fresh DB, no-op otherwise)
# 3. Start the Next.js standalone server on $PORT (default 5000)
set -e

mkdir -p /app/data

echo "[wx-entrypoint] Syncing database schema ..."
prisma db push --schema ./prisma/schema.prisma --skip-generate --accept-data-loss

echo "[wx-entrypoint] Starting Weexionic Cloud on 0.0.0.0:${PORT:-5000}"
exec node server.js
