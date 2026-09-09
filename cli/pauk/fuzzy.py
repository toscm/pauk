"""Tiny fuzzy matcher for the quiz picker: case-insensitive
subsequence match, tighter matches rank first."""

from __future__ import annotations

from typing import Callable, TypeVar

T = TypeVar("T")


def match_span(query: str, text: str) -> int | None:
    """Length of the shortest window of text containing query as a
    subsequence, or None if it is not one."""
    query = query.lower()
    text = text.lower()
    if not query:
        return 0
    best = None
    for start in range(len(text)):
        if text[start] != query[0]:
            continue
        pos = start
        ok = True
        for ch in query[1:]:
            pos = text.find(ch, pos + 1)
            if pos == -1:
                ok = False
                break
        if ok:
            span = pos - start + 1
            if best is None or span < best:
                best = span
    return best


def fuzzy_filter(query: str, items: list[T], key: Callable[[T], str]) -> list[T]:
    scored = []
    for index, item in enumerate(items):
        span = match_span(query, key(item))
        if span is not None:
            scored.append((span, index, item))
    scored.sort(key=lambda entry: (entry[0], entry[1]))
    return [item for _, _, item in scored]
