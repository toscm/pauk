"""E2E round-trip for `pauk clone` and `pauk upload`."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from conftest import run_cli


def _parse(file: Path) -> tuple[dict, str]:
    text = file.read_text(encoding="utf-8")
    assert text.startswith("---")
    _, front, body = text.split("---\n", 2)
    return yaml.safe_load(front), body.lstrip("\n")


# a 1x1 PNG, uploaded via `media add` and referenced from a card
PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\x0d\x0a\x2d\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def test_clone_upload_roundtrip(cli_env, tmp_path):
    # --- seed a small set (text + mc + match) via import ---------
    img = tmp_path / "pixel.png"
    img.write_bytes(PNG)
    added = run_cli(cli_env, "media", "add", str(img))
    assert added.returncode == 0, added.stderr

    sample = {
        "dirs": ["sync-demo", "sync-demo/sub"],
        "dir_links": [],
        "cards": [
            {
                "dirs": ["sync-demo"],
                "type": "text",
                "question_md": "Picture? ![p](media:pixel.png)",
                "accepted_answers": ["a pixel", "pixel"],
            },
            {
                "dirs": ["sync-demo/sub"],
                "type": "mc",
                "question_md": "Pick one",
                "options": [
                    {"text_md": "right", "correct": True},
                    {"text_md": "wrong", "correct": False},
                ],
            },
            {
                "dirs": ["sync-demo"],
                "type": "match",
                "question_md": "Match them",
                "pairs": [
                    {"left_md": "io", "right_md": "parlo"},
                    {"left_md": "tu", "right_md": "parli"},
                ],
            },
        ],
    }
    content = tmp_path / "sync-demo.json"
    content.write_text(json.dumps(sample))
    assert run_cli(cli_env, "import", str(content)).returncode == 0

    # --- clone ----------------------------------------------------
    dest = tmp_path / "dump"
    cloned = run_cli(cli_env, "clone", str(dest))
    assert cloned.returncode == 0, cloned.stderr

    cards_dir = dest / "cards"
    files = sorted(cards_dir.glob("*.md"))
    assert (dest / "README.md").is_file()

    # The DB is a shared session fixture, so the dump holds every
    # card. One file per card: no duplicate ids, and each filename
    # is its card id.
    fronts = {}
    for f in files:
        front, body = _parse(f)
        assert isinstance(front["id"], int)
        assert f.stem == str(front["id"])
        fronts[f.stem] = (front, body)
    assert len(fronts) == len(files)  # one file per card, no dupes

    # locate the three cards we just seeded by their dirs/content
    mine = {
        front["type"]: (front, body)
        for front, body in fronts.values()
        if any(d.startswith("sync-demo") for d in front.get("dirs", []))
    }
    assert set(mine) == {"text", "mc", "match"}

    # text card: accepted_answers in frontmatter, question in body,
    # media link rewritten to local relative path, file downloaded
    tfront, tbody = mine["text"]
    assert tfront["accepted_answers"] == ["a pixel", "pixel"]
    assert tfront["dirs"] == ["sync-demo"]
    assert "media/" in tbody and "http" not in tbody
    local = tbody.split("media/", 1)[1].split(")", 1)[0]
    assert (dest / "media" / local).read_bytes() == PNG

    # mc card: options rendered readably, body is the question
    mfront, mbody = mine["mc"]
    assert mbody.strip() == "Pick one"
    assert mfront["options"] == [
        {"text": "right", "correct": True},
        {"text": "wrong", "correct": False},
    ]
    assert mfront["dirs"] == ["sync-demo/sub"]

    # match card: pairs rendered readably
    mafront, _ = mine["match"]
    assert mafront["pairs"] == [
        {"left": "io", "right": "parlo"},
        {"left": "tu", "right": "parli"},
    ]

    # --- add a brand-new card (no id) and upload ------------------
    (cards_dir / "new.md").write_text(
        "---\n"
        "type: text\n"
        "dirs:\n"
        "  - sync-demo/fresh\n"
        "accepted_answers:\n"
        "  - quarantaquattro\n"
        "---\n"
        "A freshly authored question\n",
        encoding="utf-8",
    )

    up = run_cli(cli_env, "upload", str(dest))
    assert up.returncode == 0, up.stderr
    assert "created 1 cards" in up.stdout

    # the new card is now on the server, in its resolved dir
    ls = run_cli(cli_env, "ls", "sync-demo/fresh")
    assert "A freshly authored question" in ls.stdout

    # the new card's file got its id stamped back
    new_front, _ = _parse(cards_dir / "new.md")
    assert isinstance(new_front["id"], int)

    # --- re-upload creates nothing --------------------------------
    again = run_cli(cli_env, "upload", str(dest))
    assert again.returncode == 0, again.stderr
    assert "created 0 cards" in again.stdout


def test_upload_media_from_clone_path(cli_env, tmp_path):
    """A new card referencing a local media/ file gets it uploaded."""
    dest = tmp_path / "coll"
    (dest / "cards").mkdir(parents=True)
    (dest / "media").mkdir()
    (dest / "media" / "pixel.png").write_bytes(PNG)

    (dest / "cards" / "img.md").write_text(
        "---\n"
        "type: text\n"
        "dirs:\n"
        "  - media-author\n"
        "accepted_answers:\n"
        "  - affirmative\n"
        "---\n"
        "Local image: ![p](media/pixel.png)\n",
        encoding="utf-8",
    )

    up = run_cli(cli_env, "upload", str(dest))
    assert up.returncode == 0, up.stderr
    assert "created 1 cards" in up.stdout

    ls = run_cli(cli_env, "ls", "media-author")
    # the media/ reference became a served URL
    assert "/media/" in ls.stdout
    assert "media/pixel.png" not in ls.stdout
