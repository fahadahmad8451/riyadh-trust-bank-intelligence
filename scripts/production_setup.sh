#!/usr/bin/env bash
# PRODUCTION SETUP — Riyadh Trust Bank Enterprise Intelligence Platform (v0.8)
#
# Creates the LOCAL production environment on this machine ($0 cost):
# same code as dev/staging, but production mode — API :8000, web :3000,
# data in data-prod/, DEBUG off, fresh JWT secret, NO demo accounts.
#
# NO Docker, NO cloud, NO public URL. Dev data (data/) and staging
# data (data-staging/) are NEVER touched.
#
# Usage (Linux / this VM):
#   ./scripts/production_setup.sh            # setup only
#   ./scripts/production_setup.sh --start    # setup + start the production API
#   ./scripts/production_setup.sh --fresh    # wipe data-prod/ first and rebuild it
#
# What it does:
#   1. Fresh venv ~/rtb-prod-venv from backend/requirements.txt
#      (verifies bcrypt==4.0.1 — TESTING BUG-1)
#   2. .env.production from .env.production.example, fresh random
#      SECRET_KEY on first run (never committed — .env.production
#      is gitignored). RTB_DEMO_ACCOUNTS=0 is set in the example.
#   3. data-prod/: copies the 8 synthetic PDFs, re-runs ingestion
#      (fresh chunks + manifest), indexes the vector store — all
#      inside data-prod/. Demo users are NOT seeded (production
#      refuses them); create the first admin afterwards with:
#        python scripts/create_admin.py --email you@bank.local
#   4. Production frontend build (VITE_API_URL=http://127.0.0.1:8000)
#      into frontend/dist/ — skipped with a warning if node/npm is missing.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="${RTB_PROD_VENV:-$HOME/rtb-prod-venv}"
START=false
FRESH=false
for arg in "$@"; do
    case "$arg" in
        --start) START=true ;;
        --fresh) FRESH=true ;;
        *) echo "Unknown argument: $arg (use --start and/or --fresh)"; exit 2 ;;
    esac
done

echo "== Production setup =="
echo "Project root : $ROOT"
echo "Production venv : $VENV"

# 1. Fresh venv from requirements.txt -------------------------------------
if [ ! -x "$VENV/bin/python" ]; then
    echo "-- Creating venv $VENV ..."
    python3 -m venv "$VENV"
fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"
python -m pip install --quiet --upgrade pip
# pip unpacks big wheels into TMPDIR — /tmp on this VM is only 512 MB
# and the torch wheel is ~540 MB, so point it at the home dir.
export TMPDIR="${TMPDIR:-$HOME/rtb-tmp}"
mkdir -p "$TMPDIR"
# CPU-only torch FIRST, from the PyTorch CPU index (same reason as staging).
echo "-- Installing CPU-only torch (PyTorch CPU index) ..."
python -m pip install --quiet --resume-retries 10 "torch==2.15.0+cpu" \
    --index-url https://download.pytorch.org/whl/cpu
echo "-- Installing backend/requirements.txt (this takes a few minutes) ..."
python -m pip install --resume-retries 10 -r "$ROOT/backend/requirements.txt"

BCRYPT_VERSION="$(python -c "import bcrypt; print(bcrypt.__version__)")"
echo "-- bcrypt version in production venv: $BCRYPT_VERSION"
if [ "$BCRYPT_VERSION" != "4.0.1" ]; then
    echo "ERROR: bcrypt must be 4.0.1 (requirements.txt pin, TESTING BUG-1), got $BCRYPT_VERSION"
    exit 1
fi
python -c "import fastapi, uvicorn, sentence_transformers; print('fastapi OK, uvicorn OK, sentence-transformers OK')"

# 2. .env.production with a fresh secret -----------------------------------
if [ ! -f "$ROOT/.env.production" ]; then
    echo "-- Creating .env.production from .env.production.example ..."
    cp "$ROOT/.env.production.example" "$ROOT/.env.production"
fi
if grep -q "REPLACE-ME-WITH-A-LONG-RANDOM-SECRET" "$ROOT/.env.production"; then
    echo "-- Generating a fresh JWT secret for production ..."
    python - "$ROOT/.env.production" <<'PYEOF'
import secrets
import sys

path = sys.argv[1]
text = open(path, encoding="utf-8").read()
text = text.replace("REPLACE-ME-WITH-A-LONG-RANDOM-SECRET", secrets.token_urlsafe(64))
open(path, "w", encoding="utf-8").write(text)
print("Fresh SECRET_KEY written to .env.production (gitignored, never shipped).")
PYEOF
else
    echo "-- .env.production already has a secret — keeping it."
fi

# 3. Fresh production data (data-prod/) ------------------------------------
# Load the production env so ingestion/indexing use the production
# SECRET_KEY and DATABASE_URL (not the dev default).
set -a
# shellcheck source=/dev/null
. "$ROOT/.env.production"
set +a
export RTB_DATA_DIR="$ROOT/data-prod"
export ENVIRONMENT=production
if [ "$FRESH" = true ]; then
    echo "-- --fresh: wiping data-prod/ ..."
    rm -rf "$ROOT/data-prod"
fi
mkdir -p "$ROOT/data-prod/docs"
echo "-- Copying the 8 synthetic PDFs into data-prod/docs/ ..."
cp "$ROOT"/data/docs/*.pdf "$ROOT/data-prod/docs/"

echo "-- Re-running ingestion into data-prod/ ..."
cd "$ROOT/backend"
python -m app.services.ingestion \
    --docs ../data-prod/docs \
    --out ../data-prod/chunks.jsonl \
    --manifest ../data-prod/docs_manifest.json

echo "-- Indexing chunks into data-prod/vector_store/ ..."
python ../scripts/index_chunks.py --chunks ../data-prod/chunks.jsonl

echo "-- Demo users are NOT seeded in production (RTB_DEMO_ACCOUNTS=0)."
echo "   Create the first admin with:"
echo "     python ../scripts/create_admin.py --email you@bank.local"

# 4. Production frontend build ---------------------------------------------
if command -v npm >/dev/null 2>&1; then
    echo "-- Building the production frontend (VITE_API_URL=http://127.0.0.1:8000) ..."
    cd "$ROOT/frontend"
    npm install --no-audit --no-fund
    VITE_API_URL=http://127.0.0.1:8000 npm run build
    echo "-- Frontend built into frontend/dist/"
else
    echo "WARNING: npm not found — frontend build skipped. Install Node.js 20+"
    echo "and run: cd frontend && npm install && npm run build"
fi

echo ""
echo "== Production setup DONE =="
echo "  API  : http://127.0.0.1:8000  (ENV=production, data=data-prod/)"
echo "  Web  : http://localhost:3000   (after: ./scripts/production_start_web.sh)"
echo "  Data : $ROOT/data-prod  (dev + staging data untouched)"
echo ""
echo "Next steps:"
echo "  1. Create the first admin:  python scripts/create_admin.py --email you@bank.local"
echo "  2. Start the API:           ./scripts/production_start.sh"
echo "  3. Start the web UI:        ./scripts/production_start_web.sh"
echo "  4. Smoke test:              python scripts/production_smoke.py"
echo "Or do 2 now:  ./scripts/production_setup.sh --start"

if [ "$START" = true ]; then
    echo ""
    echo "-- --start: launching the production API (foreground, Ctrl+C to stop) ..."
    exec "$ROOT/scripts/production_start.sh"
fi
