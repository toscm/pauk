#!/usr/bin/env python3
"""Prune pauk database dumps per the retention policy
(docs/deployment.md): keep a dump iff

- it is at most 7 days old, or
- its day of month is 1, 8, 15, or 22 and it is at most 35
  days old, or
- its day of month is 1 and it is at most 366 days old.

Filenames: pauk-YYYY-MM-DD*.sql.gz (suffixes like -predeploy
count as dumps of that day). Usage: prune_backups.py DIR
[--dry-run] [--today YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

PATTERN = re.compile(r"^pauk-(\d{4}-\d{2}-\d{2}).*\.sql\.gz$")


def keep(dump_date: dt.date, today: dt.date) -> bool:
    age = (today - dump_date).days
    if age < 0:
        return True  # clock skew: never delete "future" dumps
    if age <= 7:
        return True
    if dump_date.day in (1, 8, 15, 22) and age <= 35:
        return True
    if dump_date.day == 1 and age <= 366:
        return True
    return False


def prune(directory: Path, today: dt.date, dry_run: bool) -> list[Path]:
    deleted = []
    for path in sorted(directory.iterdir()):
        match = PATTERN.match(path.name)
        if not match:
            continue
        dump_date = dt.date.fromisoformat(match.group(1))
        if keep(dump_date, today):
            continue
        deleted.append(path)
        if dry_run:
            print(f"would delete {path.name}")
        else:
            path.unlink()
            print(f"deleted {path.name}")
    return deleted


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--today", type=dt.date.fromisoformat, default=dt.date.today())
    args = parser.parse_args()
    if not args.directory.is_dir():
        print(f"not a directory: {args.directory}", file=sys.stderr)
        return 1
    prune(args.directory, args.today, args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
