# PRODUCTION START (WEB) — Riyadh Trust Bank (v0.8)
#
# Serves the production frontend build (frontend\dist\, built by
# scripts\production_setup.ps1 with VITE_API_URL=http://127.0.0.1:8000)
# on http://localhost:3000. Foreground — Ctrl+C stops it.
# Run in a second terminal next to .\scripts\production_start.ps1.
#
# Usage:  .\scripts\production_start_web.ps1
$ErrorActionPreference = "Stop"
$ROOT = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

if (-not (Test-Path (Join-Path $ROOT "frontend\dist\index.html"))) {
    Write-Host "ERROR: frontend\dist\ not built — run .\scripts\production_setup.ps1 first"
    Write-Host "(or: cd frontend; `$env:VITE_API_URL='http://127.0.0.1:8000'; npm run build)"
    exit 1
}

Write-Host "Production web UI on http://localhost:3000 (serving frontend\dist\)"
Write-Host "  API must be running: .\scripts\production_start.ps1  (port 8000)"
Set-Location (Join-Path $ROOT "frontend")
npx vite preview --port 3000
