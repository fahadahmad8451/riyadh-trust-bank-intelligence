"""Restore a production backup — Production (v0.8).

Usage (from the project root):
    python scripts/restore.py --backup backups/rtb-prod-backup-20261106-120000.zip
    python scripts/restore.py --backup <file> --data-dir data-prod --force

Safety: refuses to overwrite an existing data dir unless --force is
given, and ALWAYS makes a pre-restore backup of the current data dir
first (backups/rtb-pre-restore-<stamp>.zip) so a bad restore can be
undone. STOP the production API before restoring (the script checks
the health endpoint and warns if the API is still up — use --force
to restore anyway, but the running server keeps its old in-memory
state until restarted).
"""
import argparse
import shutil
import sys
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _api_is_up(port: int = 8000) -> bool:
    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/v1/health", timeout=2) as res:
            return res.status == 200
    except Exception:  # noqa: BLE001 — unreachable means not up
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Restore a production data backup.")
    parser.add_argument("--backup", required=True, help="Backup zip to restore")
    parser.add_argument("--data-dir", default="data-prod",
                        help="Data directory to restore into (default data-prod)")
    parser.add_argument("--force", action="store_true",
                        help="Overwrite the existing data dir (a pre-restore backup is still made)")
    args = parser.parse_args()

    backup = (ROOT / args.backup).resolve()
    if not backup.exists():
        print(f"ERROR: backup not found: {backup}")
        return 2
    if not zipfile.is_zipfile(backup):
        print(f"ERROR: not a zip file: {backup}")
        return 2
    data_dir = (ROOT / args.data_dir).resolve()
    if data_dir.exists() and not args.force:
        print(f"ERROR: {data_dir} already exists — use --force to overwrite "
              "(a pre-restore backup is made first).")
        return 2
    if _api_is_up() and not args.force:
        print("ERROR: the production API is still running on :8000 — stop it first "
              "(scripts/production_stop.*) or use --force.")
        return 2
    if data_dir.exists():
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        pre = ROOT / "backups" / f"rtb-pre-restore-{stamp}.zip"
        pre.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(pre, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in sorted(data_dir.rglob("*")):
                if p.is_file():
                    zf.write(p, p.relative_to(data_dir))
        print(f"Pre-restore backup: {pre}")
        shutil.rmtree(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(backup) as zf:
        bad = [n for n in zf.namelist() if n.startswith(("/", "..")) or ".." in n.split("/")]
        if bad:
            print(f"ERROR: backup contains unsafe paths: {bad[:3]}")
            return 2
        zf.extractall(data_dir)
    restored = [p for p in data_dir.rglob("*") if p.is_file()]
    print(f"Restored {len(restored)} files from {backup.name} into {data_dir}")
    print("Start the production API again with scripts/production_start.*")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
