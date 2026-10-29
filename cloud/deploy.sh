#!/usr/bin/env bash
# Weexionic Cloud — ek-click deploy script (Ubuntu VPS)
set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
PORT="${PORT:-3000}"

echo "=========================================="
echo "  WEEXIONIC CLOUD — Deploy shuru"
echo "  Folder: $ROOT"
echo "=========================================="

command -v node >/dev/null 2>&1 || { echo "❌ Node.js nahi mila. Node 20+ install karein:"; echo "   curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash - && sudo apt install -y nodejs"; exit 1; }
echo "✔ Node $(node -v)"

# 1) .env (pehli dafa) — DB ka ABSOLUTE path khud likh deta hoon
mkdir -p db
if [ ! -f .env ]; then
  cat > .env <<EOF
DATABASE_URL=file:$ROOT/db/weexionic.db
# Google login (GOOGLE-SETUP.md dekhein) — client ID milne par # hata do:
# GOOGLE_CLIENT_IDS=your-web-client-id.apps.googleusercontent.com
# Android App Links verification:
APP_SHA256=A9E2C70C583657EDBAA0E9CCEFA73D1BBACC112A452669175C85E2C415E9EF74
EOF
  echo "✔ .env ban gayi (DB path auto-set)"
else
  echo "• .env pehle se hai — as-is use kar raha hoon"
fi

# 2) Dependencies
echo "→ npm install (5-10 min lag sakta hai)..."
npm install --no-audit --no-fund

# 3) Prisma
npx prisma generate
npx prisma db push --accept-data-loss
echo "✔ Database ready"

# 4) Build
npm run build
echo "✔ Build complete"

# 5) Start (pm2 ho to pm2 se, warna nohup)
if command -v pm2 >/dev/null 2>&1; then
  pm2 delete weexionic-cloud 2>/dev/null || true
  pm2 start "npm run start -- -p $PORT" --name weexionic-cloud --cwd "$ROOT"
  pm2 save
  echo "✔ pm2 se start ho gaya (name: weexionic-cloud)"
else
  pkill -f "next-server\|server.js" 2>/dev/null || true
  nohup npm run start -- -p $PORT > weexionic.log 2>&1 &
  sleep 3
  echo "✔ background mein start ho gaya (log: weexionic.log)"
  echo "  (Reboot-proof ke liye: sudo npm i -g pm2 && pm2 start 'npm run start -- -p $PORT' --name weexionic-cloud)"
fi

echo ""
echo "=========================================="
echo "  VERIFY: curl http://localhost:$PORT/api/health"
echo "  Expected: {\"ok\":true,\"name\":\"weexionic-cloud\",\"api\":2}"
echo "=========================================="
