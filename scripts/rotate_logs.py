"""Log rotation + retention — v0.9.

Rotates the append-only JSONL logs when they pass 10,000 lines:

    metrics.jsonl, audit.jsonl, alerts.jsonl, conversations.jsonl

Rotation: the OLDEST lines are moved into a gzipped archive
<data-dir>/archives/<name>-YYYYMMDD-HHMMSS.jsonl.gz and the file
keeps the newest 5,000 lines. At most 7 archives are kept per file;
older archives are deleted. Retention policy (see
docs/MONITORING.md § Retention): 10k live lines + 7 archives per
file, roughly 35k–70k lines of history per log.

Run by hand, or weekly from Task Scheduler / cron:

    python scripts/rotate_logs.py                    # data-prod
    python scripts/rotate_logs.py --data-dir data    # dev
    python scripts/rotate_logs.py --max-lines 5000 --keep 5

Standard library only. Never deletes the live file — only archives
and old archives. Prints what it did, one line per file.
"""
import argparse
import gzip
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

MAX_LINES = 10_000
KEEP_LINES = 5_000
KEEP_ARCHIVES = 7
ROTATABLE = ("metrics.jsonl", "audit.jsonl", "alerts.jsonl", "conversations.jsonl")


def rotate_file(path: Path, max_lines: int, keep_lines: int,
                keep_archives: int) -> str:
    """Rotate one JSONL file. Returns a human-readable summary line."""
    if not path.exists():
        return f"{path.name}: no file, skipped"
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    if len(lines) <= max_lines:
        return f"{path.name}: {len(lines)} lines, no rotation needed"
    archive_dir = path.parent / "archives"
    archive_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    archive = archive_dir / f"{path.stem}-{stamp}.jsonl.gz"
    overflow = lines[: len(lines) - keep_lines]
    with gzip.open(archive, "wt", encoding="utf-8") as gz:
        gz.writelines(overflow)
    path.write_text("".join(lines[len(lines) - keep_lines :]), encoding="utf-8")
    # Retention: keep only the newest `keep_archives` archives.
    pattern = f"{path.stem}-*.jsonl.gz"
    archives = sorted(archive_dir.glob(pattern))
    deleted = 0
    while len(archives) > keep_archives:
        archives.pop(0).unlink()
        deleted += 1
    msg = (f"{path.name}: {len(lines)} lines -> archived "
           f"{len(overflow)} lines to {archive.name}, kept {keep_lines}")
    if deleted:
        msg += f", deleted {deleted} old archive(s)"
    return msg


def main() -> int:
    parser = argparse.ArgumentParser(description="Rotate RTB JSONL logs.")
    parser.add_argument("--data-dir", default="data-prod",
                        help="Runtime data dir, relative to project root (default data-prod)")
    parser.add_argument("--max-lines", type=int, default=MAX_LINES)
    parser.add_argument("--keep-lines", type=int, default=KEEP_LINES)
    parser.add_argument("--keep-archives", type=int, default=KEEP_ARCHIVES)
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    if not data_dir.is_absolute():
        data_dir = ROOT / data_dir
    for name in ROTATABLE:
        print(" ", rotate_file(data_dir / name, args.max_lines,
                               args.keep_lines, args.keep_archives))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
