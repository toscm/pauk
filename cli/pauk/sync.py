"""Clone a collection to editable markdown files and upload
locally-authored cards back.

`clone` dumps every card to `<dir>/cards/<id>.md` (YAML
frontmatter + a markdown body) and downloads referenced media
into `<dir>/media/`, rewriting image links to local relative
paths so the tree is self-contained.

`upload` is create-only: a card file without an `id` (or
`id: new`/blank) becomes a new card; a file with an existing
`id` is skipped. It never updates or deletes server cards.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from pauk.client import ApiError, Client

# A media URL served by the API: ".../media/<sha>.<ext>". We match
# the whole URL so it can be rewritten to a local "media/<file>"
# reference on clone.
MEDIA_URL_RE = re.compile(r"https?://[^\s)\"']+/media/[^\s)\"']+")

# Local media references that `upload` resolves and uploads:
#   - "media:<relpath>"  (import-style, relative to the card file)
#   - "media/<file>"     (what `clone` writes) as a markdown link
#     target, i.e. inside "](...)"
LOCAL_MEDIA_RE = re.compile(r"media:([^)\s\"']+)|\]\((media/[^)\s\"']+)\)")

# Per card type, the frontmatter fields we carry besides id/type/dirs.
# The body of the file holds question_md (scenario_md for quest).
TYPE_FIELDS = {
    "mc": ["options"],
    "text": ["accepted_answers"],
    "match": ["pairs"],
    "quest": ["role_prompt", "success_criteria", "max_messages", "lang"],
    "route": ["graph_name", "start_node", "goal_node"],
    "recall": ["answer_md"],
}


# --- clone ----------------------------------------------------------
def clone(client: Client, dest: Path, echo=print) -> int:
    """Write every card to dest/cards/<id>.md and download media.
    Returns the number of cards written."""
    cards_dir = dest / "cards"
    media_dir = dest / "media"
    cards_dir.mkdir(parents=True, exist_ok=True)

    id_to_path = {d["id"]: d["path"] for d in client.quiz_dirs()}

    downloaded: dict[str, str] = {}  # url -> local filename

    def localize(text: str) -> str:
        for url in set(MEDIA_URL_RE.findall(text)):
            if url not in downloaded:
                name = url.rsplit("/", 1)[-1]
                media_dir.mkdir(parents=True, exist_ok=True)
                (media_dir / name).write_bytes(client.get_bytes(url))
                downloaded[url] = name
            text = text.replace(url, f"media/{downloaded[url]}")
        return text

    count = 0
    for card in client.iter_cards():
        _write_card(cards_dir, card, id_to_path, localize)
        count += 1

    if downloaded:
        echo(f"downloaded {len(downloaded)} media files")
    _write_readme(dest)
    echo(f"cloned {count} cards to {dest}")
    return count


def _write_card(cards_dir: Path, card: dict, id_to_path: dict, localize) -> None:
    card_type = card["type"]
    dirs = [id_to_path.get(d["id"], d["name"]) for d in card.get("dirs", [])]
    front: dict[str, Any] = {
        "id": card["id"],
        "type": card_type,
        "dirs": dirs,
    }

    if card_type == "quest":
        body = localize(card.get("scenario_md", ""))
    else:
        body = localize(card.get("question_md", ""))

    for field in TYPE_FIELDS.get(card_type, []):
        if field not in card:
            continue
        value = card[field]
        if field == "options":
            front["options"] = [
                {"text": localize(o["text_md"]), "correct": bool(o["correct"])}
                for o in value
            ]
        elif field == "pairs":
            front["pairs"] = [
                {"left": p["left_md"], "right": p["right_md"]} for p in value
            ]
        else:
            front[field] = value

    (cards_dir / f"{card['id']}.md").write_text(
        _dump_frontmatter(front) + body.rstrip("\n") + "\n",
        encoding="utf-8",
    )


def _dump_frontmatter(front: dict) -> str:
    text = yaml.safe_dump(
        front, sort_keys=False, allow_unicode=True, default_flow_style=False
    )
    return f"---\n{text}---\n\n"


# --- upload ---------------------------------------------------------
def upload(client: Client, src: Path, echo=print) -> tuple[int, int]:
    """Create cards from src/cards/*.md that have no id. Files with
    an id are skipped (upload is create-only). Returns
    (created, skipped)."""
    cards_dir = src / "cards"
    if not cards_dir.is_dir():
        raise FileNotFoundError(f"no cards/ directory in {src}")

    files = sorted(cards_dir.glob("*.md"))
    parsed = [(f, _parse_file(f)) for f in files]

    new_cards = [(f, fm, body) for f, (fm, body) in parsed if _is_new(fm)]
    skipped = len(parsed) - len(new_cards)

    if not new_cards:
        echo(
            f"created 0 cards, skipped {skipped} "
            f"(existing cards are never updated or deleted)"
        )
        return 0, skipped

    # mkdir -p every referenced directory path
    all_dirs = sorted({d for _, fm, _ in new_cards for d in fm.get("dirs", [])})
    dir_ids = _ensure_dirs(client, all_dirs)

    # content dedup guards against re-creating a card whose question
    # already exists on the server (e.g. a copied file), mirroring
    # `pauk import`.
    existing = {_dedup_key(c): c["id"] for c in client.iter_cards()}

    created = 0
    for file, front, body in new_cards:
        uploaded: dict[str, str] = {}
        body = _upload_refs(client, body, file.parent.parent, uploaded)
        key = body
        if key in existing:
            # already on the server: adopt its id, stop recreating it
            _stamp_id(file, existing[key])
            skipped += 1
            continue
        card_body = _build_body(front, body)
        card_body["dirs"] = [dir_ids[p] for p in front.get("dirs", [])]
        new_card = client.create_card(card_body)
        existing[key] = new_card["id"]
        _stamp_id(file, new_card["id"])
        created += 1

    echo(
        f"created {created} cards, skipped {skipped} "
        f"(existing cards are never updated or deleted)"
    )
    return created, skipped


def _is_new(front: dict) -> bool:
    ident = front.get("id")
    return ident in (None, "", "new") or (
        isinstance(ident, str) and ident.strip() == ""
    )


def _build_body(front: dict, body: str) -> dict:
    card_type = front["type"]
    out: dict[str, Any] = {"type": card_type}
    if card_type == "quest":
        out["scenario_md"] = body
    else:
        out["question_md"] = body

    for field in TYPE_FIELDS.get(card_type, []):
        if field not in front:
            continue
        value = front[field]
        if field == "options":
            out["options"] = [
                {"text_md": o["text"], "correct": bool(o.get("correct", False))}
                for o in value
            ]
        elif field == "pairs":
            out["pairs"] = [
                {"left_md": p["left"], "right_md": p["right"]} for p in value
            ]
        else:
            out[field] = value
    return out


def _upload_refs(client: Client, text: str, base: Path, uploaded: dict) -> str:
    """Upload each local media reference and substitute the served
    URL. Handles both "media:<path>" and "](media/<file>)" forms;
    server-side sha256 dedup keeps it idempotent."""

    def resolve(rel: str) -> str:
        if rel not in uploaded:
            file = (base / rel).resolve()
            if not file.is_file():
                raise FileNotFoundError(f"media file not found: {file}")
            uploaded[rel] = client.upload_media(file)["url"]
        return uploaded[rel]

    def repl(match: re.Match) -> str:
        if match.group(1) is not None:  # media:<path>
            return resolve(match.group(1))
        rel = match.group(2)  # media/<file> inside ](...)
        return f"]({resolve(rel)})"

    return LOCAL_MEDIA_RE.sub(repl, text)


def _stamp_id(file: Path, card_id: int) -> None:
    """Write the server id back into the file's frontmatter so a
    re-upload skips it."""
    front, body = _parse_file(file)
    front["id"] = card_id
    # keep id/type/dirs first for readability
    ordered = {k: front[k] for k in ("id", "type", "dirs") if k in front}
    ordered.update({k: v for k, v in front.items() if k not in ordered})
    file.write_text(
        _dump_frontmatter(ordered) + body.rstrip("\n") + "\n", encoding="utf-8"
    )


# --- shared helpers -------------------------------------------------
def _parse_file(file: Path) -> tuple[dict, str]:
    text = file.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise ValueError(f"{file}: missing YAML frontmatter")
    # split off the frontmatter between the first two "---" lines
    parts = re.split(r"^---\s*$\n?", text, maxsplit=2, flags=re.MULTILINE)
    # parts == ['', '<yaml>', '<body>']
    if len(parts) < 3:
        raise ValueError(f"{file}: malformed frontmatter")
    front = yaml.safe_load(parts[1]) or {}
    body = parts[2].lstrip("\n")
    return front, body


def _dedup_key(card: dict) -> str:
    return card.get("question_md") or card.get("scenario_md") or ""


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


README = """\
# pauk collection

This directory is a local, editable dump of your pauk cards,
written by `pauk clone` and uploadable with `pauk upload`.

## Layout

- `cards/<id>.md` — one card per file.
- `media/` — images and other media referenced by the cards.

## Card file format

Each card is a markdown file with a YAML frontmatter header and
a markdown body. The body is the question (for a quest card it
is the scenario). Example:

    ---
    id: 17
    type: mc
    dirs:
      - bio/cells
    options:
      - text: Mitochondrium
        correct: true
      - text: Ribosom
        correct: false
    ---
    What does ![m](media/ab12ef.png) show?

Frontmatter fields:

- `id` — the server id. Leave it out (or set `id: new`) to
  create a NEW card on upload.
- `type` — one of mc, text, match, quest, route, recall.
- `dirs` — list of directory paths the card belongs to
  (created mkdir -p style on upload).
- type-specific fields:
  - mc: `options` (each `text` + `correct`)
  - text: `accepted_answers` (list of strings)
  - match: `pairs` (each `left` + `right`)
  - quest: `role_prompt`, `success_criteria`, `max_messages`,
    `lang` (the body is the scenario)
  - route: `graph_name`, `start_node`, `goal_node`
  - recall: `answer_md` (the reference answer; the body is the
    question)

Image links use a relative `media/<file>` path so the tree is
self-contained. When authoring a new card you may also use the
import-style `media:<relative-path>` reference.

## Editing and uploading

To add cards, create new `*.md` files (in `cards/`) without an
`id`, then run:

    pauk upload <this-directory>

Upload is CREATE-ONLY. Files that already carry an `id` are
skipped; edits to an existing card and deletions are NOT synced
to the server in this version. A freshly created card gets its
new `id` written back into its file, so re-running `upload`
creates nothing new.
"""


def _write_readme(dest: Path) -> None:
    (dest / "README.md").write_text(README, encoding="utf-8")
