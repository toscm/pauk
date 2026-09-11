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
