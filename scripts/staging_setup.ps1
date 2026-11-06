# STAGING SETUP — Riyadh Trust Bank (v0.6) — Windows PowerShell
#
# Same as scripts/staging_setup.sh, for Fahad's Windows laptop.
# NO Docker. Dev data (data\) is NEVER touched.
#
# Usage (PowerShell, from the project root):
#   .\scripts\staging_setup.ps1            # setup only
#   .\scripts\staging_setup.ps1 -Start     # setup + start the staging API
#   .\scripts\staging_setup.ps1 -Fresh     # wipe data-staging\ first and rebuild it
#
# If Activate.ps1 errors, run once first:
#   Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
param(
    [switch]$Start,
    [switch]$Fresh
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Venv = if ($env:RTB_STAGING_VENV) { $env:RTB_STAGING_VENV } else { Join-Path $env:USERPROFILE "rtb-staging-venv" }

Write-Host "== Staging setup =="
Write-Host "Project root : $Root"
Write-Host "Staging venv : $Venv"

# 1. Fresh venv from requirements.txt --------------------------------------
if (-not (Test-Path "$Venv\Scripts\python.exe")) {
    Write-Host "-- Creating venv $Venv ..."
    python -m venv $Venv
}
& "$Venv\Scripts\Activate.ps1"
python -m pip install --quiet --upgrade pip
# CPU-only torch FIRST, from the PyTorch CPU index: the default PyPI
# torch wheel is a CUDA build (needs NVIDIA libs). Once torch is
# satisfied, requirements.txt will not re-download it.
Write-Host "-- Installing CPU-only torch (PyTorch CPU index) ..."
python -m pip install --quiet "torch==2.15.0+cpu" --index-url https://download.pytorch.org/whl/cpu
Write-Host "-- Installing backend\requirements.txt (this takes a few minutes) ..."
pip install -r "$Root\backend\requirements.txt"

$BcryptVersion = python -c "import bcrypt; print(bcrypt.__version__)"
Write-Host "-- bcrypt version in staging venv: $BcryptVersion"
if ($BcryptVersion -ne "4.0.1") {
    throw "bcrypt must be 4.0.1 (requirements.txt pin, TESTING BUG-1), got $BcryptVersion"
}
python -c "import fastapi, uvicorn, sentence_transformers; print('fastapi OK, uvicorn OK, sentence-transformers OK')"

# 2. .env.staging with a fresh secret ---------------------------------------
if (-not (Test-Path "$Root\.env.staging")) {
    Write-Host "-- Creating .env.staging from .env.staging.example ..."
    Copy-Item "$Root\.env.staging.example" "$Root\.env.staging"
}
$EnvText = Get-Content "$Root\.env.staging" -Raw
if ($EnvText -match "REPLACE-ME-WITH-A-LONG-RANDOM-SECRET") {
    Write-Host "-- Generating a fresh JWT secret for staging ..."
    Add-Type -AssemblyName System.Web
    $Secret = [System.Web.Security.Membership]::GeneratePassword(48, 8)
    # Membership passwords can contain characters that break .env parsing;
    # use URL-safe base64 instead.
    $Bytes = New-Object byte[] 36
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($Bytes)
    $Secret = [Convert]::ToBase64String($Bytes).Replace("+", "-").Replace("/", "_").Replace("=", "")
    $EnvText = $EnvText.Replace("REPLACE-ME-WITH-A-LONG-RANDOM-SECRET", $Secret)
    Set-Content "$Root\.env.staging" $EnvText -NoNewline
    Write-Host "Fresh SECRET_KEY written to .env.staging (gitignored, never shipped)."
} else {
    Write-Host "-- .env.staging already has a secret — keeping it."
}

# 3. Fresh staging data (data-staging\) -------------------------------------
$env:RTB_DATA_DIR = Join-Path $Root "data-staging"
if ($Fresh) {
    Write-Host "-- -Fresh: wiping data-staging\ ..."
    Remove-Item -Recurse -Force "$Root\data-staging" -ErrorAction SilentlyContinue
}
New-Item -ItemType Directory -Force -Path "$Root\data-staging\docs" | Out-Null
Write-Host "-- Copying the 8 synthetic PDFs into data-staging\docs\ ..."
Copy-Item "$Root\data\docs\*.pdf" "$Root\data-staging\docs\" -Force

Write-Host "-- Re-running ingestion into data-staging\ ..."
Set-Location "$Root\backend"
python -m app.services.ingestion `
    --docs ..\data-staging\docs `
    --out ..\data-staging\chunks.jsonl `
    --manifest ..\data-staging\docs_manifest.json

Write-Host "-- Seeding the 3 demo users into data-staging\users.json ..."
python ..\scripts\seed_users.py --force

Write-Host "-- Indexing chunks into data-staging\vector_store\ ..."
python ..\scripts\index_chunks.py --chunks ..\data-staging\chunks.jsonl

Set-Location $Root
Write-Host ""
Write-Host "== Staging setup DONE =="
Write-Host "  API  : http://127.0.0.1:8001  (ENV=staging, data=data-staging\)"
Write-Host "  Web  : http://127.0.0.1:3001  (after the staging frontend build)"
Write-Host "  Data : $Root\data-staging  (dev data\ untouched)"
Write-Host ""
Write-Host "Start the staging API with:"
Write-Host "  .\scripts\staging_start.ps1"
Write-Host "Then run the smoke test in another terminal:"
Write-Host "  python scripts\staging_smoke.py"

if ($Start) {
    Write-Host ""
    Write-Host "-- -Start: launching the staging API (foreground, Ctrl+C to stop) ..."
    & "$Root\scripts\staging_start.ps1"
}
