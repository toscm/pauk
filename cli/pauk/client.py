"""Thin typed wrapper around the pauk HTTP API."""

from __future__ import annotations

from typing import Any, Iterator

import httpx


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.status = status
        self.code = code


class Client:
    def __init__(self, server: str, token: str):
        self._http = httpx.Client(
            base_url=server.rstrip("/") + "/api/v1",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30.0,
        )

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

    # --- health -----------------------------------------------------
    def health(self) -> dict:
        return self._call("GET", "/health")

    # --- dirs -------------------------------------------------------
    def list_dirs(self, parent_id: int | None = None) -> list[dict]:
        params = {} if parent_id is None else {"parent": parent_id}
        return self._call("GET", "/dirs", params=params)["items"]

    def resolve_dir(self, path: str) -> dict:
        return self._call("GET", "/dirs/resolve", params={"path": path})

    def create_dir(self, name: str, parent_id: int | None = None) -> dict:
        body: dict[str, Any] = {"name": name}
        if parent_id is not None:
            body["parent_id"] = parent_id
        return self._call("POST", "/dirs", json=body)

    def delete_dir(self, dir_id: int, force: bool = False) -> None:
        params = {"force": "1"} if force else {}
        self._call("DELETE", f"/dirs/{dir_id}", params=params)

    def link_dir(self, parent_id: int, child_id: int) -> None:
        self._call("PUT", f"/dirs/{parent_id}/dirs/{child_id}")

    def link_card(self, dir_id: int, card_id: int) -> None:
        self._call("PUT", f"/dirs/{dir_id}/cards/{card_id}")

    def unlink_card(self, dir_id: int, card_id: int) -> None:
        self._call("DELETE", f"/dirs/{dir_id}/cards/{card_id}")

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
        return self._call("POST", "/cards", json=body)

    def update_card(self, card_id: int, body: dict) -> dict:
        return self._call("PATCH", f"/cards/{card_id}", json=body)

    def delete_card(self, card_id: int) -> None:
        self._call("DELETE", f"/cards/{card_id}")

    # --- quiz -------------------------------------------------------
    def quiz_cards(self, dir_id: int | None, recursive: bool, n: int) -> list[dict]:
        params: dict[str, Any] = {"n": n}
        if dir_id is not None:
            params["dir"] = dir_id
            if recursive:
                params["recursive"] = "1"
        return self._call("GET", "/quiz/cards", params=params)["items"]

    def answer(self, card_id: int, payload: dict) -> dict:
        return self._call("POST", f"/cards/{card_id}/answer", json=payload)

    def quiz_dirs(self) -> list[dict]:
        return self._call("GET", "/quiz/dirs")["items"]

    def start_run(self, dir_id: int | None, total: int, ranked: bool = True) -> dict:
        """Returns {'id', 'best'} where best is the current record
        for this (dir, total) or None."""
        return self._call(
            "POST", "/quiz/runs",
            json={"dir_id": dir_id, "total": total, "ranked": ranked},
        )

    def finish_run(self, run_id: int, correct: int, total: int, ranked: bool | None = None) -> dict:
        body: dict = {"correct": correct, "total": total}
        if ranked is not None:
            body["ranked"] = ranked   # False marks an abandoned run
        return self._call("PATCH", f"/quiz/runs/{run_id}", json=body)

    def quest_run(self, card_id: int, success: bool, messages_used: int) -> dict:
        return self._call(
            "POST", f"/cards/{card_id}/quest-run",
            json={"success": success, "messages_used": messages_used},
        )

    def route_run(self, card_id: int, success: bool, km: int) -> dict:
        return self._call(
            "POST", f"/cards/{card_id}/route-run",
            json={"success": success, "km": km},
        )

    def close(self) -> None:
        self._http.close()

    # --- media ------------------------------------------------------
    def upload_media(self, path) -> dict:
        from pathlib import Path

        path = Path(path)
        with open(path, "rb") as fh:
            return self._call(
                "POST", "/media", files={"file": (path.name, fh.read())}
            )

    def list_media(self) -> list[dict]:
        return self._call("GET", "/media")["items"]

    def delete_media(self, media_id: int) -> None:
        self._call("DELETE", f"/media/{media_id}")

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
        return self._call("GET", "/stats", params=params)
