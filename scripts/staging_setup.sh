#!/usr/bin/env bash
# STAGING SETUP — Riyadh Trust Bank Enterprise Intelligence Platform (v0.6)
#
# Creates a staging environment that mirrors production as closely as
# possible, locally, $0: same code as dev, but separate ports
# (API :8001, web :3001), separate data (data-staging/), separate
# database file, DEBUG off, fresh JWT secret.
#
# NO Docker, NO cloud, NO public URL. Dev data (data/) is NEVER touched.
#
# Usage (Linux / this VM):
#   ./scripts/staging_setup.sh            # setup only, then start it yourself
#   ./scripts/staging_setup.sh --start    # setup + start the staging API (foreground)
#   ./scripts/staging_setup.sh --fresh    # wipe data-staging/ first and rebuild it
#
# What it does:
#   1. Fresh venv ~/rtb-staging-venv from backend/requirements.txt
#      (verifies bcrypt==4.0.1 — TESTING BUG-1: passlib breaks with
#      bcrypt >= 4.1; a drifted venv fails 33 tests with a 72-byte error)
#   2. .env.staging from .env.staging.example, fresh random SECRET_KEY
#      on first run (never committed — .env.staging is gitignored)
#   3. data-staging/: copies the 8 synthetic PDFs, re-runs ingestion
#      (fresh chunks + manifest), seeds the 3 demo users, indexes the
#      vector store — all inside data-staging/, dev data untouched
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="${RTB_STAGING_VENV:-$HOME/rtb-staging-venv}"
START=false
FRESH=false
for arg in "$@"; do
    case "$arg" in
        --start) START=true ;;
        --fresh) FRESH=true ;;
        *) echo "Unknown argument: $arg (use --start and/or --fresh)"; exit 2 ;;
    esac
done

echo "== Staging setup =="
echo "Project root : $ROOT"
echo "Staging venv : $VENV"

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
# CPU-only torch FIRST, from the PyTorch CPU index: the default PyPI
# torch wheel is a CUDA build (needs NVIDIA libs) and its download
# stalls on this VM. Once torch is satisfied, requirements.txt will
# not re-download it.
echo "-- Installing CPU-only torch (PyTorch CPU index) ..."
python -m pip install --quiet --resume-retries 10 "torch==2.15.0+cpu" \
    --index-url https://download.pytorch.org/whl/cpu
echo "-- Installing backend/requirements.txt (this takes a few minutes) ..."
python -m pip install --resume-retries 10 -r "$ROOT/backend/requirements.txt"

BCRYPT_VERSION="$(python -c "import bcrypt; print(bcrypt.__version__)")"
echo "-- bcrypt version in staging venv: $BCRYPT_VERSION"
if [ "$BCRYPT_VERSION" != "4.0.1" ]; then
    echo "ERROR: bcrypt must be 4.0.1 (requirements.txt pin, TESTING BUG-1), got $BCRYPT_VERSION"
    exit 1
fi
python -c "import fastapi, uvicorn, sentence_transformers; print('fastapi OK, uvicorn OK, sentence-transformers OK')"

# 2. .env.staging with a fresh secret --------------------------------------
if [ ! -f "$ROOT/.env.staging" ]; then
    echo "-- Creating .env.staging from .env.staging.example ..."
    cp "$ROOT/.env.staging.example" "$ROOT/.env.staging"
fi
if grep -q "REPLACE-ME-WITH-A-LONG-RANDOM-SECRET" "$ROOT/.env.staging"; then
    echo "-- Generating a fresh JWT secret for staging ..."
    python - "$ROOT/.env.staging" <<'PYEOF'
import secrets
import sys

path = sys.argv[1]
text = open(path, encoding="utf-8").read()
text = text.replace("REPLACE-ME-WITH-A-LONG-RANDOM-SECRET", secrets.token_urlsafe(48))
open(path, "w", encoding="utf-8").write(text)
print("Fresh SECRET_KEY written to .env.staging (gitignored, never shipped).")
PYEOF
else
    echo "-- .env.staging already has a secret — keeping it."
fi

# 3. Fresh staging data (data-staging/) ------------------------------------
# Load the staging env so the seed step uses the staging SECRET_KEY
# (not the dev default) and DATABASE_URL.
set -a
# shellcheck source=/dev/null
. "$ROOT/.env.staging"
set +a
export RTB_DATA_DIR="$ROOT/data-staging"
export ENVIRONMENT=staging
if [ "$FRESH" = true ]; then
    echo "-- --fresh: wiping data-staging/ ..."
    rm -rf "$ROOT/data-staging"
fi
mkdir -p "$ROOT/data-staging/docs"
echo "-- Copying the 8 synthetic PDFs into data-staging/docs/ ..."
cp "$ROOT"/data/docs/*.pdf "$ROOT/data-staging/docs/"

echo "-- Re-running ingestion into data-staging/ ..."
cd "$ROOT/backend"
python -m app.services.ingestion \
    --docs ../data-staging/docs \
    --out ../data-staging/chunks.jsonl \
    --manifest ../data-staging/docs_manifest.json

echo "-- Seeding the 3 demo users into data-staging/users.json ..."
python ../scripts/seed_users.py --force

echo "-- Indexing chunks into data-staging/vector_store/ ..."
python ../scripts/index_chunks.py --chunks ../data-staging/chunks.jsonl

echo ""
echo "== Staging setup DONE =="
echo "  API  : http://127.0.0.1:8001  (ENV=staging, data=data-staging/)"
echo "  Web  : http://127.0.0.1:3001  (after the staging frontend build)"
echo "  Data : $ROOT/data-staging  (dev data/ untouched)"
echo ""
echo "Start the staging API with:"
echo "  ./scripts/staging_start.sh"
echo "Then run the smoke test in another terminal:"
echo "  python scripts/staging_smoke.py"
echo "Or do both now:  ./scripts/staging_setup.sh --start"

if [ "$START" = true ]; then
    echo ""
    echo "-- --start: launching the staging API (foreground, Ctrl+C to stop) ..."
    exec "$ROOT/scripts/staging_start.sh"
fi
