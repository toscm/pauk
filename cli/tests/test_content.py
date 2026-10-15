"""Every shipped content file under content/ imports cleanly.

Runs on its own database so the ~800 cards never disturb the counts
and rankings the other e2e tests rely on. This is the guard that
would have caught a card type the API does not know or a directory
name outside ^[a-z0-9-]+$ (docs/api.md), both of which only surface
when someone actually runs `pauk import`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import REPO, start_api
from pauk.client import Client
from pauk.importer import import_file

CONTENT = REPO / "content"
# only files in the import format count; the autobahn graph and
# similar data files have no "cards" key
FILES = sorted(
    f for f in CONTENT.glob("*.json")
    if "cards" in json.loads(f.read_text(encoding="utf-8"))
)
# knowledge item files (docs/tutor.md 13); imported after the decks
# because their card_links point at deck cards
def _dependency_order(files: list[Path]) -> list[Path]:
    """Item files in import order: a file whose links or forms point to
    items of another file comes after it (e.g. items-italian-a2.json
    builds on the verbs of items-italian.json)."""
    defined, needed = {}, {}
    for f in files:
        data = json.loads(f.read_text(encoding="utf-8"))
        space = data.get("space")
        refs = {f"{i.get('space', space)}/{i['key']}" for i in data["items"]}
        defined[f] = refs
        targets = {(link["to"] if "/" in link["to"] else f"{i.get('space', space)}/{link['to']}")
                   for i in data["items"] for link in i.get("links", [])}
        targets |= {f"{i.get('space', space)}/{i['key'].split('.')[0]}" for i in data["items"] if i["kind"] == "form"}
        needed[f] = targets - refs
    ordered: list[Path] = []
    pending = sorted(files)
    while pending:
        ready = [f for f in pending
                 if not any(needed[f] & defined[g] for g in pending if g is not f)]
        assert ready, f"cyclic links between {[f.name for f in pending]}"
        ordered.append(ready[0])
        pending.remove(ready[0])
    return ordered


ITEM_FILES = _dependency_order([
    f for f in CONTENT.glob("*.json")
    if "items" in json.loads(f.read_text(encoding="utf-8"))
])


@pytest.fixture(scope="module")
def content_server() -> dict:
    proc, info = start_api("pauk_content_test")
    yield info
    proc.terminate()
    proc.wait(timeout=10)


@pytest.mark.parametrize("file", FILES, ids=[f.name for f in FILES])
def test_content_file_imports(content_server, file: Path):
    client = Client(content_server["url"], content_server["token"], cache=False)
    expected = len(json.loads(file.read_text(encoding="utf-8"))["cards"])
    created, skipped = import_file(client, file, echo=lambda *_: None)
    # a file may share cards with another (dedup by question), but
    # nothing may fail or be silently dropped
    assert created + skipped == expected


@pytest.mark.parametrize("file", ITEM_FILES, ids=[f.name for f in ITEM_FILES])
def test_item_file_imports(content_server, file: Path):
    client = Client(content_server["url"], content_server["token"], cache=False)
    data = json.loads(file.read_text(encoding="utf-8"))
    messages: list[str] = []
    import_file(client, file, echo=lambda m, *_: messages.append(str(m)))
    # every item exists, every link and card link resolved
    assert not [m for m in messages if "unresolved link" in m or "card not found" in m], messages
    space = data.get("space")
    for item in data["items"]:
        assert client.get_item(f"{item.get('space', space)}/{item['key']}")
