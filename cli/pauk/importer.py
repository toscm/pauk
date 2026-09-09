"""Import a content JSON file (dirs, dir_links, cards) via the API.

Idempotent: dirs are created only if missing, cards are skipped
when a card with the same question_md already exists.
"""

from __future__ import annotations

import json
from pathlib import Path

from pauk.client import ApiError, Client


def import_file(client: Client, path: Path, echo=print) -> tuple[int, int]:
    data = json.loads(path.read_text(encoding="utf-8"))
    dir_ids = _ensure_dirs(client, data.get("dirs", []))
    for link in data.get("dir_links", []):
        parent_id = dir_ids.get(link["parent"]) or client.resolve_dir(link["parent"])["id"]
        child_id = dir_ids.get(link["child"]) or client.resolve_dir(link["child"])["id"]
        try:
            client.link_dir(parent_id, child_id)
        except ApiError as e:
            if e.code != "conflict":
                raise

    existing = {card["question_md"]: card for card in client.iter_cards()}
    created = skipped = linked = 0
    for card in data.get("cards", []):
        target_ids = [dir_ids[p] for p in card.get("dirs", [])]
        present = existing.get(card["question_md"])
        if present is not None:
            skipped += 1
            # keep directory links up to date for existing cards
            have = {d["id"] for d in present["dirs"]}
            for dir_id in target_ids:
                if dir_id not in have:
                    client.link_card(dir_id, present["id"])
                    linked += 1
            continue
        body = {k: v for k, v in card.items() if k != "dirs"}
        body["dirs"] = target_ids
        client.create_card(body)
        existing[card["question_md"]] = {"id": None, "dirs": [
            {"id": i} for i in target_ids
        ]}
        created += 1
    echo(f"imported {created} cards, skipped {skipped} existing, added {linked} links")
    return created, skipped


def _ensure_dirs(client: Client, paths: list[str]) -> dict[str, int]:
    """Create missing dirs mkdir -p style; return path -> id."""
    ids: dict[str, int] = {}
    for path in sorted(paths, key=lambda p: p.count("/")):
        parent_path, _, name = path.rpartition("/")
        parent_id = ids.get(parent_path) if parent_path else None
        if parent_path and parent_id is None:
            parent_id = client.resolve_dir(parent_path)["id"]
            ids[parent_path] = parent_id
        try:
            ids[path] = client.resolve_dir(path)["id"]
        except ApiError as e:
            if e.code != "not_found":
                raise
            ids[path] = client.create_dir(name, parent_id)["id"]
    return ids
