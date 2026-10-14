#!/usr/bin/env python3
"""Count the rows per table in a mysqldump file (plain or .gz)
by parsing its INSERT statements, without a database.

scripts/restore-local.sh compares these counts with the restored
tables. Usage: dump_row_counts.py DUMP  (prints "table count" lines)
"""

from __future__ import annotations

import gzip
import re
import sys
from collections import Counter
from pathlib import Path

INSERT = re.compile(r"^INSERT INTO `([^`]+)` VALUES\s*")


def count_tuples(values: str) -> int:
    """Number of top-level (...) tuples in the VALUES part of one
    INSERT statement. Quoted strings may contain parentheses, quotes
    escaped as \\' or '', and backslash escapes."""
    count = depth = 0
    quote = None
    i = 0
    while i < len(values):
        c = values[i]
        if quote:
            if c == "\\":
                i += 1
            elif c == quote:
                if i + 1 < len(values) and values[i + 1] == quote:
                    i += 1
                else:
                    quote = None
        elif c in "'\"":
            quote = c
        elif c == "(":
            if depth == 0:
                count += 1
            depth += 1
        elif c == ")":
            depth -= 1
        i += 1
    return count


def row_counts(lines) -> Counter:
    """Rows per table over the lines of a dump. A statement may be on
    one line (mysqldump) or one tuple per line (mariadb-dump 11.x),
    and a big table spans several statements. Strings in a dump never
    contain raw newlines, so a line ending in ";" ends the statement."""
    counts: Counter = Counter()
    table = None
    parts: list[str] = []
    for line in lines:
        line = line.rstrip("\r\n")
        if table is None:
            m = INSERT.match(line)
            if not m:
                continue
            table, line = m.group(1), line[m.end():]
        parts.append(line)
        if line.endswith(";"):
            counts[table] += count_tuples("\n".join(parts))
            table, parts = None, []
    return counts


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    path = Path(argv[1])
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8", errors="surrogateescape") as f:
        counts = row_counts(f)
    for table in sorted(counts):
        print(table, counts[table])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
