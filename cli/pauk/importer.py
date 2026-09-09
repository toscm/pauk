"""Import a content JSON file (dirs, dir_links, cards) via the API.

Idempotent: dirs are created only if missing, cards are skipped
when a card with the same question_md already exists.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from pauk.client import ApiError, Client

# "media:<relative path>" inside a markdown link target: the file
# (relative to the content JSON) is uploaded and the reference is
# replaced by the served URL. Server-side sha256 dedup makes this
# idempotent.
MEDIA_RE = re.compile(r"media:([^)\s]+)")


def import_file(client: Client, path: Path, echo=print) -> tuple[int, int]:
    data = json.loads(path.read_text(encoding="utf-8"))
    _resolve_media(client, data.get("cards", []), path.parent, echo)
    dir_ids = _ensure_dirs(client, data.get("dirs", []))
    for link in data.get("dir_links", []):
        parent_id = dir_ids.get(link["parent"]) or client.resolve_dir(link["parent"])["id"]
        child_id = dir_ids.get(link["child"]) or client.resolve_dir(link["child"])["id"]
        try:
            client.link_dir(parent_id, child_id)
        except ApiError as e:
            if e.code != "conflict":
                raise

    # dedup key: question_md for normal cards, scenario_md for quests
    # (a quest's scenario becomes its question_md server-side)
    existing = {_dedup_key(card): card for card in client.iter_cards()}
    created = skipped = linked = 0
    for card in data.get("cards", []):
        target_ids = [dir_ids[p] for p in card.get("dirs", [])]
        key = _dedup_key(card)
        present = existing.get(key)
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
        existing[key] = {"id": None, "dirs": [{"id": i} for i in target_ids]}
        created += 1
    echo(f"imported {created} cards, skipped {skipped} existing, added {linked} links")
    return created, skipped


def _dedup_key(card: dict) -> str:
    return card.get("question_md") or card.get("scenario_md") or ""


def _resolve_media(client: Client, cards: list[dict], base: Path, echo) -> None:
    """Upload every `media:<path>` reference (path relative to the
    content JSON's directory) and replace it with the served URL,
    in question_md and in mc option text_md. Idempotent via
    server-side sha256 dedup."""
    uploaded: dict[str, str] = {}

    def substitute(text: str) -> str:
        for rel in set(MEDIA_RE.findall(text)):
            if rel not in uploaded:
                file = (base / rel).resolve()
                if not file.is_file():
                    raise FileNotFoundError(f"media file not found: {file}")
                uploaded[rel] = client.upload_media(file)["url"]
            text = text.replace(f"media:{rel}", uploaded[rel])
        return text

    for card in cards:
        if "question_md" in card:
            card["question_md"] = substitute(card["question_md"])
        for option in card.get("options", []):
            option["text_md"] = substitute(option["text_md"])
    if uploaded:
        echo(f"uploaded {len(uploaded)} media files")


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
