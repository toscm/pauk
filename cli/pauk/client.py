"""Thin typed wrapper around the pauk HTTP API.

The read-heavy GETs the picker, quiz and stats screens repeat are
served through a small stale-while-revalidate cache (see cache.py):
a cache hit returns the last payload instantly — so the UI paints
without a network round trip — and a stale entry is refreshed in a
background thread for next time. The API stays the source of truth;
every write busts the cache. Set PAUK_NO_CACHE (or pass
`cache=False`) to bypass it entirely.
"""

from __future__ import annotations

import os
import threading
from typing import Any, Iterator

import httpx

from pauk.cache import Cache

# How long a cached GET is served without any refresh, then how long
# it may still be served while a background refresh runs. Kept short:
# the payloads change rarely but the cache is only an accelerator.
_TTL = {
    "/quiz/dirs": 60.0,
    "/dirs": 60.0,
    "/stats": 30.0,
    "/quiz/cards": 15.0,   # weighted-random: a short window, then reshuffle
}
_DEFAULT_TTL = 30.0


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.status = status
        self.code = code


class Client:
    def __init__(self, server: str, token: str, cache: bool = True):
        base_url = server.rstrip("/") + "/api/v1"
        self._http = httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=30.0,
            # keep the TLS connection warm between requests: httpx's
            # default 5s expiry would drop it while the user reads the
            # home screen, forcing a cold handshake on the first quiz
            limits=httpx.Limits(max_keepalive_connections=5, keepalive_expiry=60.0),
        )
        enabled = cache and not os.environ.get("PAUK_NO_CACHE")
        self._cache = Cache(f"{base_url}\0{token}", enabled=enabled)
        self._revalidating: set[str] = set()
        self._lock = threading.Lock()

    def _call(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self._http.request(method, path, **kwargs)
        if response.status_code == 204:
            return None
        try:
            data = response.json()
        except ValueError:
            response.raise_for_status()
            raise
        if response.status_code >= 400:
            error = data.get("error", {})
            raise ApiError(
                response.status_code,
                error.get("code", "unknown"),
                error.get("message", response.text),
            )
        return data

    # --- cache plumbing ---------------------------------------------
    def _cached_get(self, path: str, params: dict | None = None) -> Any:
        """A GET served stale-while-revalidate. On a hit the cached
        payload is returned at once; if it is older than the path's TTL
        a background thread refreshes it for next time."""
        if not self._cache.enabled:
            return self._call("GET", path, params=params or {})
        key = Cache.key("GET", path, params)
        hit = self._cache.get(key)
        if hit is not None:
            value, age = hit
            if age >= _TTL.get(path, _DEFAULT_TTL):
                self._revalidate(key, path, params)
            return value
        value = self._call("GET", path, params=params or {})
        self._cache.set(key, value, path)
        return value

    def _revalidate(self, key: str, path: str, params: dict | None) -> None:
        with self._lock:
            if key in self._revalidating:
                return  # a refresh for this key is already in flight
            self._revalidating.add(key)

        def worker() -> None:
            try:
                value = self._call("GET", path, params=params or {})
                self._cache.set(key, value, path)
            except Exception:  # noqa: BLE001 - background best-effort
                pass
            finally:
                with self._lock:
                    self._revalidating.discard(key)

        threading.Thread(target=worker, daemon=True).start()

    def _invalidate(self, paths: set[str] | None = None) -> None:
        """Bust the cache after a write. `paths` limits it to those
        request paths; None clears everything for this identity."""
        if paths is None:
            self._cache.clear()
        else:
            self._cache.clear_paths(paths)

    def prewarm(self) -> None:
        """Fire the first real requests in the background so the opening
        screen isn't waiting on a cold connection: `health` warms the
        TLS connection the pool then reuses, and `quiz_dirs` fills the
        picker's cache before it is asked for."""
        def worker() -> None:
            try:
                self.health()
            except Exception:  # noqa: BLE001
                pass
            try:
                self.quiz_dirs()
            except Exception:  # noqa: BLE001
                pass

        threading.Thread(target=worker, daemon=True).start()

    # --- health -----------------------------------------------------
    def health(self) -> dict:
        return self._call("GET", "/health")

    # --- dirs -------------------------------------------------------
    def list_dirs(self, parent_id: int | None = None) -> list[dict]:
        params = {} if parent_id is None else {"parent": parent_id}
        return self._cached_get("/dirs", params)["items"]

    def resolve_dir(self, path: str) -> dict:
        return self._call("GET", "/dirs/resolve", params={"path": path})

    def create_dir(self, name: str, parent_id: int | None = None) -> dict:
        body: dict[str, Any] = {"name": name}
        if parent_id is not None:
            body["parent_id"] = parent_id
        result = self._call("POST", "/dirs", json=body)
        self._invalidate()
        return result

    def delete_dir(self, dir_id: int, force: bool = False) -> None:
        params = {"force": "1"} if force else {}
        self._call("DELETE", f"/dirs/{dir_id}", params=params)
        self._invalidate()

    def link_dir(self, parent_id: int, child_id: int) -> None:
        self._call("PUT", f"/dirs/{parent_id}/dirs/{child_id}")
        self._invalidate()

    def link_card(self, dir_id: int, card_id: int) -> None:
        self._call("PUT", f"/dirs/{dir_id}/cards/{card_id}")
        self._invalidate()

    def unlink_card(self, dir_id: int, card_id: int) -> None:
        self._call("DELETE", f"/dirs/{dir_id}/cards/{card_id}")
        self._invalidate()

    # --- cards ------------------------------------------------------
    def iter_cards(self, **filters: Any) -> Iterator[dict]:
        cursor = None
        while True:
            params = {k: v for k, v in filters.items() if v is not None}
            if cursor:
                params["cursor"] = cursor
            data = self._call("GET", "/cards", params=params)
            yield from data["items"]
            cursor = data["next_cursor"]
            if cursor is None:
                return

    def get_card(self, card_id: int) -> dict:
        return self._call("GET", f"/cards/{card_id}")

    def create_card(self, body: dict) -> dict:
        result = self._call("POST", "/cards", json=body)
        self._invalidate()
        return result

    def update_card(self, card_id: int, body: dict) -> dict:
        result = self._call("PATCH", f"/cards/{card_id}", json=body)
        self._invalidate()
        return result

    def delete_card(self, card_id: int) -> None:
        self._call("DELETE", f"/cards/{card_id}")
        self._invalidate()

    # --- quiz -------------------------------------------------------
    def quiz_cards(self, dir_id: int | None, recursive: bool, n: int) -> list[dict]:
        params: dict[str, Any] = {"n": n}
        if dir_id is not None:
            params["dir"] = dir_id
            if recursive:
                params["recursive"] = "1"
        return self._cached_get("/quiz/cards", params)["items"]

    def answer(self, card_id: int, payload: dict) -> dict:
        result = self._call("POST", f"/cards/{card_id}/answer", json=payload)
        # a logged review shifts selection weights, deck performance and
        # stats — everything the cached reads compute
        self._invalidate()
        return result

    def quiz_dirs(self) -> list[dict]:
        return self._cached_get("/quiz/dirs")["items"]

    def start_run(self, dir_id: int | None, total: int, ranked: bool = True) -> dict:
        """Returns {'id', 'best'} where best is the current record
        for this (dir, total) or None."""
        result = self._call(
            "POST", "/quiz/runs",
            json={"dir_id": dir_id, "total": total, "ranked": ranked},
        )
        # a started run only bumps the picker's popularity sort; leave
        # the card batch cached so the quiz about to begin paints at once
        self._invalidate({"/quiz/dirs"})
        return result

    def finish_run(self, run_id: int, correct: int, total: int, ranked: bool | None = None) -> dict:
        body: dict = {"correct": correct, "total": total}
        if ranked is not None:
            body["ranked"] = ranked   # False marks an abandoned run
        return self._call("PATCH", f"/quiz/runs/{run_id}", json=body)

    def quest_run(self, card_id: int, success: bool, messages_used: int) -> dict:
        result = self._call(
            "POST", f"/cards/{card_id}/quest-run",
            json={"success": success, "messages_used": messages_used},
        )
        self._invalidate()
        return result

    def route_run(self, card_id: int, success: bool, km: int) -> dict:
        result = self._call(
            "POST", f"/cards/{card_id}/route-run",
            json={"success": success, "km": km},
        )
        self._invalidate()
        return result

    def self_grade(self, card_id: int, correct: bool) -> dict:
        result = self._call(
            "POST", f"/cards/{card_id}/self-grade",
            json={"correct": correct},
        )
        self._invalidate()
        return result

    def close(self) -> None:
        self._http.close()

    # --- media ------------------------------------------------------
    def upload_media(self, path) -> dict:
        from pathlib import Path

        path = Path(path)
        with open(path, "rb") as fh:
            result = self._call(
                "POST", "/media", files={"file": (path.name, fh.read())}
            )
        self._invalidate()
        return result

    def list_media(self) -> list[dict]:
        return self._call("GET", "/media")["items"]

    def delete_media(self, media_id: int) -> None:
        self._call("DELETE", f"/media/{media_id}")
        self._invalidate()

    def get_bytes(self, url: str) -> bytes:
        # reuse the authenticated client's connection pool (keep-alive)
        # so repeated image fetches skip the TLS handshake
        response = self._http.get(url, headers={})
        response.raise_for_status()
        return response.content

    def stats(self, dir_id: int | None = None, recursive: bool = True) -> dict:
        params: dict[str, Any] = {}
        if dir_id is not None:
            params["dir"] = dir_id
            if recursive:
                params["recursive"] = "1"
        return self._cached_get("/stats", params)
