#!/bin/bash
# Weexionic MERGED container entrypoint
# 1. Prepare the data volume
# 2. Sync the (legacy cloud) Prisma schema — keeps old accounts readable
# 3. Import cloud accounts into the real bot DB (idempotent)
# 4. Start the REAL bot backend (Flask SaaS, internal :5001)
# 5. Start the Next.js frontend (public :5000, waits for Flask)
set -e

echo "[wx] ─────────────────────────────────────────────"
echo "[wx]  Weexionic merged deployment starting"
echo "[wx]    frontend :5000  +  real bot backend :5001"
echo "[wx] ─────────────────────────────────────────────"

mkdir -p /app/data /app/data/logs /app/data/instances /app/data/user_configs

echo "[wx] Syncing cloud (legacy) DB schema ..."
(cd /app/cloud && prisma db push --schema ./prisma/schema.prisma --skip-generate --accept-data-loss) || \
  echo "[wx] WARN: prisma db push failed (continuing — bot DB is the source of truth)"

echo "[wx] Importing cloud accounts into the bot DB (one-time, idempotent) ..."
python3 /app/saas/scripts/migrate_cloud_users.py || echo "[wx] WARN: migration skipped"

echo "[wx] Starting REAL bot backend (Flask SaaS) on 127.0.0.1:${SAAS_PORT} ..."
(cd /app/saas && HOST=127.0.0.1 PORT="${SAAS_PORT}" python3 app.py >> /app/data/logs/saas.log 2>&1) &
FLASK_PID=$!

# If Flask ever dies, stop the whole container so Coolify restarts it clean
(
  while kill -0 "$FLASK_PID" 2>/dev/null; do sleep 10; done
  echo "[wx] FATAL: bot backend exited — restarting container"
  kill -TERM 1
) &

# Wait for the backend to answer
for i in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:${SAAS_PORT}/api/health" >/dev/null 2>&1 || \
     curl -fsS "http://127.0.0.1:${SAAS_PORT}/" >/dev/null 2>&1; then
    echo "[wx] Bot backend is UP (took ${i}s)"
    break
  fi
  if ! kill -0 "$FLASK_PID" 2>/dev/null; then
    echo "[wx] FATAL: bot backend died during startup — last log lines:"
    tail -n 30 /app/data/logs/saas.log || true
    exit 1
  fi
  sleep 1
done

echo "[wx] Starting Weexionic frontend on 0.0.0.0:${PORT:-5000}"
cd /app/cloud
exec node server.js
