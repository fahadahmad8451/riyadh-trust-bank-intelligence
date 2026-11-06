# PRODUCTION SETUP — Riyadh Trust Bank Enterprise Intelligence Platform (v0.8)
#
# Creates the LOCAL production environment on this Windows PC ($0 cost):
# same code as dev/staging, but production mode — API :8000, web :3000,
# data in data-prod\, DEBUG off, fresh JWT secret, NO demo accounts.
#
# NO Docker, NO cloud, NO public URL. Dev data (data\) and staging
# data (data-staging\) are NEVER touched.
#
# Usage (PowerShell, from the project root):
#   .\scripts\production_setup.ps1            # setup only
#   .\scripts\production_setup.ps1 -Start     # setup + start the production API
#   .\scripts\production_setup.ps1 -Fresh     # wipe data-prod\ first and rebuild it
#
# If Activate.ps1 errors, run first:
#   Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
param(
    [switch]$Start,
    [switch]$Fresh
)

$ErrorActionPreference = "Stop"
$ROOT = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$VENV = if ($env:RTB_PROD_VENV) { $env:RTB_PROD_VENV } else { Join-Path $env:USERPROFILE "rtb-prod-venv" }

Write-Host "== Production setup =="
Write-Host "Project root    : $ROOT"
Write-Host "Production venv : $VENV"

# 1. Fresh venv from requirements.txt --------------------------------------
if (-not (Test-Path (Join-Path $VENV "Scripts\python.exe"))) {
    Write-Host "-- Creating venv $VENV ..."
    python -m venv $VENV
}
& (Join-Path $VENV "Scripts\Activate.ps1")
python -m pip install --quiet --upgrade pip
# CPU-only torch FIRST, from the PyTorch CPU index (same reason as staging).
Write-Host "-- Installing CPU-only torch (PyTorch CPU index) ..."
python -m pip install --quiet --resume-retries 10 "torch==2.15.0+cpu" --index-url https://download.pytorch.org/whl/cpu
Write-Host "-- Installing backend\requirements.txt (this takes a few minutes) ..."
python -m pip install --resume-retries 10 -r (Join-Path $ROOT "backend\requirements.txt")

$bcryptVersion = python -c "import bcrypt; print(bcrypt.__version__)"
Write-Host "-- bcrypt version in production venv: $bcryptVersion"
if ($bcryptVersion -ne "4.0.1") {
    Write-Host "ERROR: bcrypt must be 4.0.1 (requirements.txt pin, TESTING BUG-1), got $bcryptVersion"
    exit 1
}
python -c "import fastapi, uvicorn, sentence_transformers; print('fastapi OK, uvicorn OK, sentence-transformers OK')"

# 2. .env.production with a fresh secret ------------------------------------
$envFile = Join-Path $ROOT ".env.production"
if (-not (Test-Path $envFile)) {
    Write-Host "-- Creating .env.production from .env.production.example ..."
    Copy-Item (Join-Path $ROOT ".env.production.example") $envFile
}
$content = Get-Content $envFile -Raw
if ($content -match "REPLACE-ME-WITH-A-LONG-RANDOM-SECRET") {
    Write-Host "-- Generating a fresh JWT secret for production ..."
    $secret = python -c "import secrets; print(secrets.token_urlsafe(64))"
    $content = $content -replace "REPLACE-ME-WITH-A-LONG-RANDOM-SECRET", $secret.Trim()
    Set-Content $envFile $content -NoNewline
    Write-Host "Fresh SECRET_KEY written to .env.production (gitignored, never shipped)."
} else {
    Write-Host "-- .env.production already has a secret — keeping it."
}

# 3. Fresh production data (data-prod\) -------------------------------------
# Load the production env so ingestion/indexing use the production secret.
foreach ($line in (Get-Content $envFile)) {
    if ($line -match "^\s*#" -or $line -notmatch "=") { continue }
    $k, $v = $line.Split("=", 2)
    # Strip surrounding double quotes (e.g. DATABASE_URL="sqlite:///...").
    [Environment]::SetEnvironmentVariable($k.Trim(), $v.Trim().Trim('"'), "Process")
}
$env:RTB_DATA_DIR = Join-Path $ROOT "data-prod"
$env:ENVIRONMENT = "production"
if ($Fresh) {
    Write-Host "-- -Fresh: wiping data-prod\ ..."
    Remove-Item -Recurse -Force (Join-Path $ROOT "data-prod") -ErrorAction SilentlyContinue
}
New-Item -ItemType Directory -Force (Join-Path $ROOT "data-prod\docs") | Out-Null
Write-Host "-- Copying the 8 synthetic PDFs into data-prod\docs\ ..."
Copy-Item (Join-Path $ROOT "data\docs\*.pdf") (Join-Path $ROOT "data-prod\docs\")

Write-Host "-- Re-running ingestion into data-prod\ ..."
Set-Location (Join-Path $ROOT "backend")
python -m app.services.ingestion --docs ..\data-prod\docs --out ..\data-prod\chunks.jsonl --manifest ..\data-prod\docs_manifest.json

Write-Host "-- Indexing chunks into data-prod\vector_store\ ..."
python ..\scripts\index_chunks.py --chunks ..\data-prod\chunks.jsonl

Write-Host "-- Demo users are NOT seeded in production (RTB_DEMO_ACCOUNTS=0)."
Write-Host "   Create the first admin with:"
Write-Host "     python ..\scripts\create_admin.py --email you@bank.local"

# 4. Production frontend build ----------------------------------------------
if (Get-Command npm -ErrorAction SilentlyContinue) {
    Write-Host "-- Building the production frontend (VITE_API_URL=http://127.0.0.1:8000) ..."
    Set-Location (Join-Path $ROOT "frontend")
    npm install --no-audit --no-fund
    $env:VITE_API_URL = "http://127.0.0.1:8000"
    npm run build
    Write-Host "-- Frontend built into frontend\dist\"
} else {
    Write-Host "WARNING: npm not found — frontend build skipped. Install Node.js 20+"
    Write-Host "and run: cd frontend; npm install; npm run build"
}

Set-Location $ROOT
Write-Host ""
Write-Host "== Production setup DONE =="
Write-Host "  API  : http://127.0.0.1:8000  (ENV=production, data=data-prod\)"
Write-Host "  Web  : http://localhost:3000   (after: .\scripts\production_start_web.ps1)"
Write-Host "  Data : $ROOT\data-prod  (dev + staging data untouched)"
Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. Create the first admin:  python scripts\create_admin.py --email you@bank.local"
Write-Host "  2. Start the API:           .\scripts\production_start.ps1"
Write-Host "  3. Start the web UI:        .\scripts\production_start_web.ps1"
Write-Host "  4. Smoke test:              python scripts\production_smoke.py"

if ($Start) {
    Write-Host ""
    Write-Host "-- -Start: launching the production API (foreground, Ctrl+C to stop) ..."
    & (Join-Path $ROOT "scripts\production_start.ps1")
}
