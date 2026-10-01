#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../frontend"
npm install
if curl -fsS http://127.0.0.1:8000/api/health >/dev/null 2>&1; then
  echo "后端健康检查通过：http://127.0.0.1:8000/api/health"
else
  echo "警告：未检测到后端服务。请先在另一个终端运行 scripts/start_backend.sh。"
fi
exec npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
