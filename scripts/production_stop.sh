#!/usr/bin/env bash
# PRODUCTION STOP — Riyadh Trust Bank (v0.8)
#
# Stops the production API (:8000) and web UI (:3000) by port.
# Best-effort: uses fuser if present, else lsof. Nothing is deleted —
# data-prod/ and the venv stay, so start again with
# ./scripts/production_start.sh.
#
# Usage:  ./scripts/production_stop.sh
set -u

for port in 8000 3000; do
    if command -v fuser >/dev/null 2>&1; then
        if fuser "$port/tcp" >/dev/null 2>&1; then
            echo "Stopping whatever listens on :$port ..."
            fuser -k "$port/tcp" >/dev/null 2>&1 || true
        else
            echo "Nothing listening on :$port."
        fi
    elif command -v lsof >/dev/null 2>&1; then
        pid="$(lsof -t -i ":$port" 2>/dev/null | head -n 1)"
        if [ -n "$pid" ]; then
            echo "Stopping PID $pid on :$port ..."
            kill "$pid" 2>/dev/null || true
        else
            echo "Nothing listening on :$port."
        fi
    else
        echo "WARNING: neither fuser nor lsof found — stop the servers with Ctrl+C in their terminals."
    fi
done
echo "Production stopped (ports 8000 + 3000 free if anything was running)."
