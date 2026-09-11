"""Recall card support across the CLI: importer round-trip and the
`pauk clone` / `pauk upload` markdown round-trip."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from conftest import run_cli
from pauk.client import Client
from pauk.importer import import_file


def _parse(file: Path) -> tuple[dict, str]:
    text = file.read_text(encoding="utf-8")
    assert text.startswith("---")
    _, front, body = text.split("---\n", 2)
    return yaml.safe_load(front), body.lstrip("\n")


def test_importer_roundtrips_recall(server, tmp_path):
    client = Client(server["url"], server["token"])
    content = {
        "dirs": ["recall-import"],
        "dir_links": [],
        "cards": [
            {
                "dirs": ["recall-import"],
                "type": "recall",
                "question_md": "Explain the bias-variance tradeoff.",
                "answer_md": "High-bias models underfit; high-variance models overfit ...",
            }
        ],
    }
    path = tmp_path / "recall.json"
    path.write_text(json.dumps(content))
    created, _ = import_file(client, path, echo=lambda *_: None)
    assert created == 1

    card = next(c for c in client.iter_cards() if c["type"] == "recall")
    assert card["question_md"] == "Explain the bias-variance tradeoff."
    assert card["answer_md"].startswith("High-bias models underfit")

    # content-dedup guard: re-importing the same card creates nothing
    created2, skipped2 = import_file(client, path, echo=lambda *_: None)
    assert created2 == 0
    assert skipped2 >= 1


def test_clone_upload_roundtrip_recall(cli_env, tmp_path):
    sample = {
        "dirs": ["recall-sync"],
        "dir_links": [],
        "cards": [
            {
                "dirs": ["recall-sync"],
                "type": "recall",
                "question_md": "State the central limit theorem.",
                "answer_md": "The sum of many iid variables is approximately normal.",
            }
        ],
    }
    content = tmp_path / "recall-sync.json"
    content.write_text(json.dumps(sample))
    assert run_cli(cli_env, "import", str(content)).returncode == 0

    dest = tmp_path / "dump"
    cloned = run_cli(cli_env, "clone", str(dest))
    assert cloned.returncode == 0, cloned.stderr

    # the shared session DB holds every card, so scope by our dir:
    # answer_md in frontmatter, question in body
    recall = None
    for f in sorted((dest / "cards").glob("*.md")):
        front, body = _parse(f)
        if front.get("type") == "recall" and "recall-sync" in front.get("dirs", []):
            recall = (front, body)
            break
    assert recall is not None
    front, body = recall
    assert front["answer_md"] == "The sum of many iid variables is approximately normal."
    assert body.strip() == "State the central limit theorem."
    assert front["dirs"] == ["recall-sync"]

    # author a brand-new recall card (no id) and upload it
    (dest / "cards" / "new-recall.md").write_text(
        "---\n"
        "type: recall\n"
        "dirs:\n"
        "  - recall-sync/fresh\n"
        "answer_md: Because the determinant is nonzero.\n"
        "---\n"
        "Why is this matrix invertible?\n",
        encoding="utf-8",
    )
    up = run_cli(cli_env, "upload", str(dest))
    assert up.returncode == 0, up.stderr
    assert "created 1 cards" in up.stdout

    ls = run_cli(cli_env, "ls", "recall-sync/fresh")
    assert "Why is this matrix invertible?" in ls.stdout
