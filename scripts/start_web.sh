#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

cd "$ROOT_DIR/frontend"
npm install
npm run build

cd "$ROOT_DIR/backend"
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install -q -r requirements.txt
python -m app.init_db

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"
exec uvicorn app.main:app --host "$HOST" --port "$PORT"
