"""Backup the production data directory — Production (v0.8).

Usage (from the project root):
    python scripts/backup.py                 # backs up data-prod/
    python scripts/backup.py --data-dir data-staging   # any data dir
    python scripts/backup.py --out-dir backups

Creates backups/rtb-prod-backup-YYYYMMDD-HHMMSS.zip containing the
whole data dir: users.json (bcrypt hashes), audit.jsonl, conversations,
feedback, refresh tokens, docs manifest + chunks + vector store index.
The zip NEVER contains .env files or secrets — secrets live in
.env.production (gitignored, backed up separately by hand if needed).

Keep the last 7 backups; older ones are deleted automatically
(--keep N to change). Run before every upgrade and weekly (see
docs/PRODUCTION.md § Backup & restore).
"""
import argparse
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Back up the production data directory.")
    parser.add_argument("--data-dir", default="data-prod",
                        help="Data directory to back up (default data-prod)")
    parser.add_argument("--out-dir", default="backups",
                        help="Where to write the zip (default backups/)")
    parser.add_argument("--keep", type=int, default=7,
                        help="How many recent backups to keep (default 7)")
    args = parser.parse_args()

    data_dir = (ROOT / args.data_dir).resolve()
    if not data_dir.exists():
        print(f"ERROR: data dir not found: {data_dir} — run production setup first.")
        return 2
    out_dir = (ROOT / args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    name = f"rtb-prod-backup-{stamp}.zip"
    out_path = out_dir / name
    files = [p for p in sorted(data_dir.rglob("*")) if p.is_file()]
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in files:
            zf.write(p, p.relative_to(data_dir))
    size_mb = out_path.stat().st_size / (1024 * 1024)
    print(f"Backup written: {out_path} ({len(files)} files, {size_mb:.2f} MB)")
    # Rotation: keep the newest N backups.
    backups = sorted(out_dir.glob("rtb-prod-backup-*.zip"))
    for old in backups[:-args.keep] if len(backups) > args.keep else []:
        old.unlink()
        print(f"Rotated out old backup: {old.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
