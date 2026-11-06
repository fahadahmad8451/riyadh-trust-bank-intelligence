"""Production healthcheck — exit 0 if the API is healthy, else 1.

Usage:
    python scripts/healthcheck.py                  # http://127.0.0.1:8000
    python scripts/healthcheck.py --port 8001      # staging API
    python scripts/healthcheck.py --url http://127.0.0.1:8000/api/v1/health

Prints one line (status, environment, version, uptime) and exits 0
only when the response is HTTP 200 with data.status == "ok". No
dependencies beyond the standard library, so it runs in any venv —
or with plain `python3` on the monitoring machine. Use it in a
scheduled task / cron as the Monitoring-phase probe (see
docs/PRODUCTION.md § Monitoring).
"""
import argparse
import json
import sys
import urllib.error
import urllib.request


def main() -> int:
    parser = argparse.ArgumentParser(description="Check the RTB API health endpoint.")
    parser.add_argument("--port", type=int, default=8000, help="API port (default 8000)")
    parser.add_argument("--url", default=None, help="Full health URL (overrides --port)")
    parser.add_argument("--timeout", type=float, default=5.0, help="Request timeout in seconds")
    args = parser.parse_args()

    url = args.url or f"http://127.0.0.1:{args.port}/api/v1/health"
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=args.timeout) as res:
            body = json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        print(f"UNHEALTHY: {url} returned HTTP {exc.code}")
        return 1
    except Exception as exc:  # noqa: BLE001 — any failure means unhealthy
        print(f"UNHEALTHY: {url} unreachable ({exc})")
        return 1
    data = body.get("data", {}) if isinstance(body, dict) else {}
    if body.get("success") is True and data.get("status") == "ok":
        print(f"HEALTHY: {url} — env={data.get('environment')} "
              f"version={data.get('version')} uptime={data.get('uptime_seconds')}s "
              f"vector_store={data.get('vector_store', {}).get('status')}")
        return 0
    print(f"UNHEALTHY: {url} returned unexpected body: {body}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
