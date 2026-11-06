# STAGING START — Riyadh Trust Bank (v0.6) — Windows PowerShell
#
# Starts the staging API on :8001 with staging env from .env.staging.
# Foreground — Ctrl+C stops it. Dev (port 8000) is NOT touched.
#
# Usage (PowerShell, from the project root):
#   .\scripts\staging_start.ps1
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Venv = if ($env:RTB_STAGING_VENV) { $env:RTB_STAGING_VENV } else { Join-Path $env:USERPROFILE "rtb-staging-venv" }

if (-not (Test-Path "$Root\.env.staging")) {
    throw "$Root\.env.staging not found — run .\scripts\staging_setup.ps1 first."
}
if (-not (Test-Path "$Venv\Scripts\python.exe")) {
    throw "Staging venv not found at $Venv — run .\scripts\staging_setup.ps1 first."
}

# Load staging env (SECRET_KEY, DATABASE_URL, CORS_ORIGINS, ...).
Get-Content "$Root\.env.staging" | ForEach-Object {
    $Line = $_.Trim()
    if ($Line -and -not $Line.StartsWith("#")) {
        $Key, $Value = $Line.Split("=", 2)
        [Environment]::SetEnvironmentVariable($Key.Trim(), $Value.Trim(), "Process")
    }
}
$env:RTB_DATA_DIR = Join-Path $Root "data-staging"
$env:ENVIRONMENT = "staging"

Write-Host "Staging API starting on http://127.0.0.1:8001"
Write-Host "  ENVIRONMENT=$env:ENVIRONMENT  RTB_DATA_DIR=$env:RTB_DATA_DIR"
Write-Host "  DATABASE_URL=$env:DATABASE_URL"
Write-Host "  (dev on :8000 is untouched — both can run side by side)"
Set-Location "$Root\backend"
& "$Venv\Scripts\Activate.ps1"
& "$Venv\Scripts\python.exe" -m uvicorn app.main:app --port 8001
