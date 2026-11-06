#!/usr/bin/env bash
# PRODUCTION START (WEB) — Riyadh Trust Bank (v0.8)
#
# Serves the production frontend build (frontend/dist/, built by
# scripts/production_setup.sh with VITE_API_URL=http://127.0.0.1:8000)
# on http://localhost:3000. Foreground — Ctrl+C stops it.
# Run in a second terminal next to ./scripts/production_start.sh.
#
# Usage:  ./scripts/production_start_web.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [ ! -f "$ROOT/frontend/dist/index.html" ]; then
    echo "ERROR: frontend/dist/ not built — run ./scripts/production_setup.sh first"
    echo "(or: cd frontend && VITE_API_URL=http://127.0.0.1:8000 npm run build)"
    exit 1
fi

echo "Production web UI on http://localhost:3000 (serving frontend/dist/)"
echo "  API must be running: ./scripts/production_start.sh  (port 8000)"
cd "$ROOT/frontend"
exec npx vite preview --port 3000
