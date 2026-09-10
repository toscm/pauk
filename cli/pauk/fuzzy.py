"""Fuzzy matcher for the quiz picker.

A query is split on whitespace into independent tokens; an item
matches only if EVERY token is a (case-insensitive) subsequence of
its text, in any order. So "verb ital" keeps only items matching
both "verb" and "ital". Results rank by total tightness (the sum
of each token's shortest matching window), tightest first.
"""

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


def match_score(query: str, text: str) -> int | None:
    """Total tightness if every whitespace-separated token of query
    matches text as a subsequence (order-independent); else None."""
    tokens = query.split()
    if not tokens:
        return 0
    total = 0
    for token in tokens:
        span = match_span(token, text)
        if span is None:
            return None
        total += span
    return total


def fuzzy_filter(query: str, items: list[T], key: Callable[[T], str]) -> list[T]:
    scored = []
    for index, item in enumerate(items):
        score = match_score(query, key(item))
        if score is not None:
            scored.append((score, index, item))
    scored.sort(key=lambda entry: (entry[0], entry[1]))
    return [item for _, _, item in scored]
