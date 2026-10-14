"""Organize the collection: edit a card in $EDITOR, link and unlink
cards and directories, move them.

Directories form a DAG (docs/architecture.md): a card can sit in
several directories and a directory under several parents. So a
"move" is always one edge: link into the new parent, then unlink
from the old one. Which old edge is meant must be unambiguous: for a
directory the source path names it (`a/b/c` leaves `a/b`), for a
card in several directories `--from` has to.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable

from rich.markup import escape

from pauk.client import ApiError, Client
from pauk.sync import TYPE_FIELDS, build_body, card_to_text, parse_card_text

NAME_RE = re.compile(r"^[a-z0-9-]+$")


class OrganizeError(Exception):
    """A refused request, with a message for the user."""


# --- edit -----------------------------------------------------------
def editor_command() -> list[str]:
    """$EDITOR, then $VISUAL, then notepad (Windows) or vi."""
    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL")
    if not editor:
        return ["notepad" if os.name == "nt" else "vi"]
    if os.name == "nt":
        # posix=False keeps backslashes in Windows paths; drop the quotes
        return [part.strip('"') for part in shlex.split(editor, posix=False)]
    return shlex.split(editor)


def run_editor(text: str, name: str) -> str:
    """Open `text` in the editor as a file called `name` and return
    what it holds when the editor exits."""
    with tempfile.TemporaryDirectory(prefix="pauk-edit-") as tmp:
        path = Path(tmp) / name
        path.write_text(text, encoding="utf-8")
        result = subprocess.run([*editor_command(), str(path)])
        if result.returncode != 0:
            raise OrganizeError(f"the editor exited with status {result.returncode}")
        # utf-8-sig: Notepad may add a byte order mark
        return path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")


def edit_card(
    client: Client,
    card_id: int,
    echo: Callable[[str], Any] = print,
    confirm: Callable[[str], bool] = lambda prompt: False,
    editor: Callable[[str, str], str] = run_editor,
) -> dict | None:
    """Round-trip a card through the editor (the `pauk clone` file
    format) and PATCH only the fields that changed. An unchanged file
    changes nothing; an invalid one (or one the API rejects) is
    reported and, if `confirm` says so, reopened with the edits kept.
    Returns the updated card, or None when nothing was changed."""
    card = client.get_card(card_id)
    id_to_path = {d["id"]: d["path"] for d in client.quiz_dirs()}
    original = card_to_text(card, id_to_path)
    text = original
    while True:
        text = editor(text, f"pauk-card-{card_id}.md")
        if text == original:
            echo("file unchanged; card not modified")
            return None
        try:
            changes = card_changes(client, card, original, text)
            if not changes:
                echo("no changes; card not modified")
                return None
            updated = client.update_card(card_id, changes)
        except (OrganizeError, ApiError) as e:
            echo(f"[red]invalid:[/red] {escape(str(e))}")
            if confirm("Reopen the editor?"):
                continue
            echo("aborted; card not modified")
            return None
        echo(f"updated card #{card_id}: {', '.join(sorted(changes))}")
        return updated


def card_changes(client: Client, card: dict, original: str, text: str) -> dict:
    """The PATCH body for the fields that differ between the card
    file as written (`original`) and as edited (`text`)."""
    try:
        front, body = parse_card_text(text)
    except ValueError as e:
        raise OrganizeError(str(e)) from None
    old_front, old_body = parse_card_text(original)
    card_type = card["type"]
    if front.get("id") != card["id"]:
        raise OrganizeError(f"id must stay {card['id']}")
    if front.get("type") != card_type:
        raise OrganizeError(f"type must stay {card_type} (the API cannot change a card's type)")
    allowed = {"id", "type", "dirs", *TYPE_FIELDS.get(card_type, [])}
    unknown = sorted(set(front) - allowed)
    if unknown:
        raise OrganizeError(f"unknown field(s) for a {card_type} card: {', '.join(unknown)}")
    removed = sorted(k for k in set(old_front) - set(front) if k in TYPE_FIELDS.get(card_type, []))
    if removed:
        # a field cannot be cleared by deleting it; the API would keep the old value
        raise OrganizeError(f"field(s) removed: {', '.join(removed)}; edit their value instead")
    if not body.strip():
        raise OrganizeError("the question (the text below the frontmatter) must not be empty")
    _check_shapes(front)

    new = build_body(front, body.rstrip("\n"))
    old = build_body(old_front, old_body.rstrip("\n"))
    changes = {k: v for k, v in new.items() if k != "type" and v != old.get(k)}
    if front.get("dirs", []) != old_front.get("dirs", []):
        dir_ids = [_dir_id(client, path) for path in front.get("dirs") or []]
        if set(dir_ids) != {d["id"] for d in card.get("dirs", [])}:
            changes["dirs"] = dir_ids
    return changes


def _check_shapes(front: dict) -> None:
    """Catch the YAML slips build_body would trip over."""
    if not isinstance(front.get("dirs", []), list) or not all(isinstance(d, str) for d in front.get("dirs") or []):
        raise OrganizeError("dirs must be a list of directory paths")
    shapes = {"options": ("text",), "pairs": ("left", "right")}
    for field, keys in shapes.items():
        if field not in front:
            continue
        value = front[field]
        if not isinstance(value, list) or not all(isinstance(v, dict) and all(k in v for k in keys) for v in value):
            raise OrganizeError(f"{field} must be a list of entries with {' and '.join(keys)}")
    answers = front.get("accepted_answers", [])
    if not isinstance(answers, list):
        raise OrganizeError("accepted_answers must be a list")


def _dir_id(client: Client, path: str) -> int:
    try:
        return client.resolve_dir(path.strip("/"))["id"]
    except ApiError as e:
        if e.code == "not_found":
            raise OrganizeError(f"no directory {path} (create it with `pauk mkdir`)") from None
        raise


# --- link, unlink, move --------------------------------------------
def parse_source(client: Client, ref: str) -> tuple[str, Any]:
    """A card id or a directory path: ('card', id) or ('dir', path).
    `#17` is always a card and `name/` always a directory; a bare
    number that is also a top-level directory name is refused."""
    if ref.startswith("#") and ref[1:].isdigit():
        return "card", int(ref[1:])
    if ref.endswith("/"):
        return "dir", ref.strip("/")
    if ref.isdigit():
        try:
            client.resolve_dir(ref)
        except ApiError as e:
            if e.code != "not_found":
                raise
            return "card", int(ref)
        raise OrganizeError(f"'{ref}' is both a card id and a directory; write #{ref} for the card or {ref}/ for the directory")
    return "dir", ref.strip("/")


def link(client: Client, source: str, dest: str, echo=print) -> None:
    """Add a card (or a directory) to directory `dest` as well."""
    kind, ref = parse_source(client, source)
    dest_id = _dir_id(client, dest)
    if kind == "card":
        client.get_card(ref)  # 404 for an unknown card
        client.link_card(dest_id, ref)
        echo(f"linked card #{ref} into {dest}")
    else:
        client.link_dir(dest_id, _dir_id(client, ref))
        echo(f"linked {ref}/ into {dest}")


def unlink(client: Client, source: str, dest: str, echo=print) -> None:
    """Remove a card (or a directory) from directory `dest` only."""
    kind, ref = parse_source(client, source)
    dest_id = _dir_id(client, dest)
    if kind == "card":
        card = client.get_card(ref)
        dirs = {d["id"] for d in card["dirs"]}
        if dest_id not in dirs:
            raise OrganizeError(f"card #{ref} is not in {dest}")
        client.unlink_card(dest_id, ref)
        echo(f"unlinked card #{ref} from {dest}")
        if dirs == {dest_id}:
            echo("the card is now in no directory (unfiled)")
        return
    directory = client.get_dir(_dir_id(client, ref))
    parents = {p["id"] for p in directory["parents"]}
    if dest_id not in parents:
        raise OrganizeError(f"{ref} is not a subdirectory of {dest}")
    if parents == {dest_id}:
        _check_top_level_free(client, directory)
    client.unlink_dir(dest_id, directory["id"])
    echo(f"unlinked {ref}/ from {dest}")
    if parents == {dest_id}:
        echo(f"{directory['name']}/ is now a top-level directory")


def move(client: Client, source: str, dest: str, from_dir: str | None = None, echo=print) -> None:
    """Move a card or a directory: link into the new parent, then
    unlink from the old one."""
    kind, ref = parse_source(client, source)
    if kind == "card":
        _move_card(client, ref, dest, from_dir, echo)
    elif from_dir is not None:
        raise OrganizeError("--from applies to cards only; a directory's source path already names the parent it leaves")
    else:
        _move_dir(client, ref, dest, echo)


def _move_card(client: Client, card_id: int, dest: str, from_dir: str | None, echo) -> None:
    if dest.strip("/") == "":
        raise OrganizeError("a card has no top level; use `pauk unlink` to take it out of a directory")
    card = client.get_card(card_id)
    dest_id = _dir_id(client, dest)
    paths = {d["id"]: d["path"] for d in client.quiz_dirs()}
    dirs = [d["id"] for d in card["dirs"]]
    if from_dir is not None:
        source_id = _dir_id(client, from_dir)
        if source_id not in dirs:
            raise OrganizeError(f"card #{card_id} is not in {from_dir}")
    elif len(dirs) > 1:
        names = ", ".join(sorted(paths.get(i, str(i)) for i in dirs))
        raise OrganizeError(
            f"card #{card_id} is in several directories ({names}); "
            "say which one it leaves with --from, or use `pauk link`/`pauk unlink`"
        )
    else:
        source_id = dirs[0] if dirs else None
    if source_id == dest_id:
        echo(f"card #{card_id} is already in {dest}")
        return
    client.link_card(dest_id, card_id)
    if source_id is not None:
        client.unlink_card(source_id, card_id)
        echo(f"moved card #{card_id} from {paths.get(source_id, source_id)} to {dest}")
    else:
        echo(f"moved card #{card_id} (unfiled) to {dest}")


def _move_dir(client: Client, path: str, dest: str, echo) -> None:
    """mv semantics: into `dest` if it is a directory, otherwise to
    `dest`'s parent under the new name `dest`'s last component; `/`
    (or an empty dest) is the top level."""
    if not path:
        raise OrganizeError("nothing to move")
    directory = client.resolve_dir(path)
    old_parent_path = path.rpartition("/")[0]
    old_parent = _dir_id(client, old_parent_path) if old_parent_path else None

    dest = dest.strip("/")
    new_name = directory["name"]
    new_parent_path: str | None = dest or None
    if dest:
        try:
            client.resolve_dir(dest)
        except ApiError as e:
            if e.code != "not_found":
                raise
            new_parent_path, _, new_name = dest.rpartition("/")
            new_parent_path = new_parent_path or None
            if not NAME_RE.match(new_name):
                raise OrganizeError(f"invalid directory name '{new_name}' (allowed: a-z, 0-9, -)")
    new_parent = _dir_id(client, new_parent_path) if new_parent_path else None

    parents = {p["id"] for p in directory["parents"]}
    if new_parent is None and old_parent is not None:
        others = parents - {old_parent}
        if others:
            raise OrganizeError(
                f"{path} has other parents as well, so it cannot become top-level; "
                f"use `pauk unlink {path}/ {old_parent_path}` to leave only {old_parent_path}"
            )
        _check_top_level_free(client, directory, new_name)
    if new_parent == old_parent and new_name == directory["name"]:
        echo(f"{path} is already there")
        return

    renamed = False
    if new_name != directory["name"]:
        client.rename_dir(directory["id"], new_name)
        renamed = True
    try:
        if new_parent is not None and new_parent != old_parent:
            client.link_dir(new_parent, directory["id"])
    except ApiError:
        if renamed:
            client.rename_dir(directory["id"], directory["name"])
        raise
    if old_parent is not None and new_parent != old_parent:
        client.unlink_dir(old_parent, directory["id"])
    target = f"{new_parent_path}/{new_name}" if new_parent_path else new_name
    echo(f"moved {path} to {target}")
    if renamed and len(parents - {old_parent}) > 0:
        echo(f"note: a directory has one name, so it is now {new_name} under its other parents too")


def _check_top_level_free(client: Client, directory: dict, name: str | None = None) -> None:
    """The API keeps top-level names unique on create and rename but
    not when an unlink leaves a directory without parents."""
    name = name or directory["name"]
    for top in client.list_dirs():
        if top["name"] == name and top["id"] != directory["id"]:
            raise OrganizeError(f"a top-level directory named {name} already exists")
