"""Interactive quiz picker: a favorites list and a collapsible
directory tree, driven by arrow keys.

Plain text only — no curses, no box-drawing characters — so the
output survives terminal resizes. On a TTY the previous frame is
erased with ANSI cursor movement; on a pipe (tests) frames are
simply printed one after another.

Keys: Up/Down move, Enter starts, Tab switches favorites/tree,
Esc goes back. Tree view: Right enters a directory, Left leaves
it. Favorites view: typing filters (fuzzy), Backspace deletes.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field

from pauk.fuzzy import fuzzy_filter

BACK = object()
ALL_CARDS = object()


@dataclass
class PickerState:
    view: str = "fav"                 # "fav" | "tree"
    expanded: set = field(default_factory=set)
    cursor: int = 0
    query: str = ""


def _read_key(stream) -> str:
    ch = stream.read(1)
    if ch == "":
        return "esc"  # EOF: leave instead of spinning
    if ch == "\x1b":
        if stream.isatty():
            import select

            if not select.select([stream], [], [], 0.05)[0]:
                return "esc"  # lone Escape key
        nxt = stream.read(1)
        if nxt != "[":
            return "esc"
        code = stream.read(1)
        return {"A": "up", "B": "down", "C": "right", "D": "left"}.get(code, "esc")
    if ch in ("\r", "\n"):
        return "enter"
    if ch in ("\x7f", "\x08"):
        return "backspace"
    if ch == "\t":
        return "tab"
    return ch


class _RawInput:
    """cbreak mode on a TTY; plain reads on a pipe."""

    def __enter__(self):
        self.restore = None
        if sys.stdin.isatty():
            import termios
            import tty

            fd = sys.stdin.fileno()
            self.restore = (fd, termios.tcgetattr(fd))
            tty.setcbreak(fd)
        return self

    def __exit__(self, *exc):
        if self.restore is not None:
            import termios

            termios.tcsetattr(self.restore[0], termios.TCSADRAIN, self.restore[1])


def _children(entries: list[dict], path: str) -> list[dict]:
    prefix = path + "/"
    return sorted(
        (e for e in entries
         if e["path"].startswith(prefix) and "/" not in e["path"][len(prefix):]),
        key=lambda e: e["path"],
    )


def _tree_rows(entries: list[dict], expanded: set) -> list[dict]:
    rows: list[dict] = []

    def walk(entry: dict, depth: int) -> None:
        kids = _children(entries, entry["path"])
        rows.append({
            "entry": entry,
            "depth": depth,
            "has_children": bool(kids),
            "expanded": entry["path"] in expanded,
        })
        if kids and entry["path"] in expanded:
            for kid in kids:
                walk(kid, depth + 1)

    for top in sorted(
        (e for e in entries if "/" not in e["path"]), key=lambda e: e["path"]
    ):
        walk(top, 0)
    return rows


def _fav_rows(entries: list[dict], query: str) -> list[dict]:
    ordered = sorted(entries, key=lambda e: (-e["runs"], e["path"]))
    if query:
        ordered = fuzzy_filter(query, ordered, key=lambda e: e["path"])
        return [{"entry": e} for e in ordered[:15]]
    return [{"entry": None}] + [{"entry": e} for e in ordered[:15]]


def _label(row: dict, view: str) -> str:
    entry = row["entry"]
    if entry is None:
        return "all cards"
    extra = f", best {entry['best']['correct']}/{entry['best']['total']}" if entry["best"] else ""
    if view == "fav":
        return f"{entry['path']} ({entry['cards_total']} cards{extra})"
    marker = " "
    if row["has_children"]:
        marker = "-" if row["expanded"] else "+"
    return f"{'  ' * row['depth']}{marker} {entry['name']} ({entry['cards_total']} cards{extra})"


def pick(entries: list[dict], state: PickerState, out=None):
    """Return ALL_CARDS, a directory path (str), or BACK."""
    out = out or sys.stdout
    tty = sys.stdout.isatty()
    last_lines = 0

    def render(rows: list[dict]) -> None:
        nonlocal last_lines
        lines = []
        if state.view == "fav":
            title = "Choose a quiz — favorites first"
            if state.query:
                title += f" (filter: {state.query})"
            keys = "keys: up/down, Enter start, Tab tree view, type to filter, Esc back"
        else:
            title = "Choose a quiz — directory tree"
            keys = "keys: up/down, right enter dir, left leave, Enter start, Tab favorites, Esc back"
        lines.append(title)
        for i, row in enumerate(rows):
            cursor = ">" if i == state.cursor else " "
            lines.append(f"{cursor} {_label(row, state.view)}")
        if not rows:
            lines.append("  (no match)")
        lines.append(keys)
        frame = "\n".join(lines)
        if tty and last_lines:
            out.write(f"\x1b[{last_lines}A\x1b[J")
        out.write(frame + "\n")
        out.flush()
        last_lines = len(lines)

    with _RawInput():
        while True:
            rows = (
                _fav_rows(entries, state.query)
                if state.view == "fav"
                else _tree_rows(entries, state.expanded)
            )
            state.cursor = max(0, min(state.cursor, len(rows) - 1))
            render(rows)
            key = _read_key(sys.stdin)
            if key == "esc":
                return BACK
            if key == "up":
                state.cursor -= 1
            elif key == "down":
                state.cursor += 1
            elif key == "tab":
                state.view = "tree" if state.view == "fav" else "fav"
                state.cursor = 0
            elif key == "enter":
                if not rows:
                    continue
                entry = rows[state.cursor]["entry"]
                return ALL_CARDS if entry is None else entry["path"]
            elif state.view == "tree" and key in ("right", "left") and rows:
                row = rows[state.cursor]
                path = row["entry"]["path"]
                if key == "right" and row["has_children"]:
                    state.expanded.add(path)
                elif key == "left":
                    if row["expanded"]:
                        state.expanded.discard(path)
                    elif "/" in path:
                        parent = path.rsplit("/", 1)[0]
                        for i, candidate in enumerate(rows):
                            if candidate["entry"]["path"] == parent:
                                state.cursor = i
                                break
            elif state.view == "fav":
                if key == "backspace":
                    state.query = state.query[:-1]
                    state.cursor = 0
                elif len(key) == 1 and key.isprintable():
                    state.query += key
                    state.cursor = 0
