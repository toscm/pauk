"""A tiny on-disk stale-while-revalidate cache for read-heavy GETs.

The picker, quiz, and stats screens repeat a handful of GETs
(`/quiz/dirs`, `/dirs`, `/quiz/cards`, `/stats`). Over a remote
IONOS round trip those dominate the "feels slow" startup, yet their
payloads change rarely. This cache lets the client hand back the
last payload instantly and refresh it in the background, so the UI
paints without waiting on the network.

It is deliberately minimal: one small JSON file per entry under
`~/.cache/pauk/<identity>/` (honouring `XDG_CACHE_HOME`), no DB, no
dependency. The API stays the source of truth — this is only an
accelerator, busted on every write (see client.py).

Cache keys are scoped to an identity hash of the server URL + token
so different servers or users never read each other's data.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any


def cache_root() -> Path:
    """The pauk cache directory, honouring XDG_CACHE_HOME. Read at
    call time so tests (and the env escape hatch) can redirect it."""
    base = os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache")
    return Path(base) / "pauk"


def clear_all() -> Path:
    """Remove the whole pauk cache (all identities). Returns the dir
    that was cleared (whether or not it existed)."""
    root = cache_root()
    shutil.rmtree(root, ignore_errors=True)
    return root


def _identity_hash(identity: str) -> str:
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]


class Cache:
    """A per-identity file cache. `enabled=False` makes every method a
    no-op so the client can transparently bypass it."""

    def __init__(self, identity: str, enabled: bool = True):
        self.enabled = enabled
        # the token never hits the filesystem in the clear: only a hash
        # of (server + token) names the per-identity sub-directory
        self._dir = cache_root() / _identity_hash(identity)

    @staticmethod
    def key(method: str, path: str, params: dict | None) -> str:
        """A stable key for a request (order-independent params)."""
        blob = json.dumps(
            [method, path, params or {}], sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def _file(self, key: str) -> Path:
        return self._dir / f"{key}.json"

    def get(self, key: str) -> tuple[Any, float] | None:
        """Return (value, age_seconds) for a cached entry, or None on a
        miss or an unreadable/corrupt file."""
        if not self.enabled:
            return None
        try:
            raw = self._file(key).read_text(encoding="utf-8")
            entry = json.loads(raw)
            return entry["value"], max(0.0, time.time() - entry["ts"])
        except (OSError, ValueError, KeyError):
            return None

    def set(self, key: str, value: Any, path: str) -> None:
        """Store a value. `path` is kept so path-scoped invalidation can
        find the entry without decoding the hashed filename."""
        if not self.enabled:
            return
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            entry = {"ts": time.time(), "path": path, "value": value}
            target = self._file(key)
            # atomic write so a concurrent background refresh never
            # exposes a half-written file
            tmp = target.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(entry), encoding="utf-8")
            os.replace(tmp, target)
        except OSError:
            pass  # a cache we cannot write to is simply a slower cache

    def clear(self) -> None:
        """Drop every entry for this identity."""
        if not self.enabled:
            return
        shutil.rmtree(self._dir, ignore_errors=True)

    def clear_paths(self, paths: set[str]) -> None:
        """Drop only entries recorded for the given request paths."""
        if not self.enabled:
            return
        try:
            files = list(self._dir.glob("*.json"))
        except OSError:
            return
        for file in files:
            try:
                if json.loads(file.read_text(encoding="utf-8")).get("path") in paths:
                    file.unlink()
            except (OSError, ValueError):
                pass
