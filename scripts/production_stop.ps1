# PRODUCTION STOP — Riyadh Trust Bank (v0.8)
#
# Stops the production API (:8000) and web UI (:3000) by port.
# Nothing is deleted — data-prod\ and the venv stay, so start again
# with .\scripts\production_start.ps1.
#
# Usage:  .\scripts\production_stop.ps1
foreach ($port in 8000, 3000) {
    $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($conn) {
        $pid = $conn.OwningProcess | Select-Object -First 1
        Write-Host "Stopping PID $pid on :$port ..."
        Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
    } else {
        Write-Host "Nothing listening on :$port."
    }
}
Write-Host "Production stopped (ports 8000 + 3000 free if anything was running)."
