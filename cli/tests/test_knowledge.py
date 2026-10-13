"""Knowledge profile through the CLI: item import (idempotent, with
card links), profile, export and restore."""

from __future__ import annotations

import json
import uuid

from conftest import run_cli
from pauk.client import ApiError, Client

ITEMS = {
    "space": "it",
    "dirs": ["kn-italian", "kn-italian/a1"],
    "items": [
        {"key": "present-are", "kind": "rule", "label_md": "present tense of -are verbs",
         "gloss_md": "-o, -i, -a, -iamo, -ate, -ano", "priority": 90, "dirs": ["kn-italian/a1"]},
        {"key": "parlare", "kind": "word", "label_md": "parlare", "gloss_md": "to speak", "priority": 95,
         "dirs": ["kn-italian/a1"], "links": [{"rel": "requires", "to": "present-are"}]},
        {"key": "farfalla", "kind": "word", "label_md": "farfalla", "gloss_md": "butterfly", "priority": 40,
         "dirs": ["kn-italian"]},
    ],
    "card_links": [{"card": "KN: Italian for **to speak**?", "item": "parlare"}],
}


def test_import_profile_export_restore(cli_env, server, tmp_path):
    client = Client(server["url"], server["token"], cache=False)
    card = client.create_card({"type": "text", "question_md": "KN: Italian for **to speak**?",
                               "accepted_answers": ["parlare"]})
    client.answer(card["id"], {"answer": "parlare"})

    file = tmp_path / "kn-italian.json"
    file.write_text(json.dumps(ITEMS), encoding="utf-8")
    first = run_cli(cli_env, "import", str(file))
    assert first.returncode == 0, first.stdout + first.stderr
    assert "items: 3 created, 0 updated, 0 unchanged; 1 card links" in first.stdout

    again = run_cli(cli_env, "import", str(file))
    assert "items: 0 created, 0 updated, 3 unchanged" in again.stdout

    # the card's earlier review was backfilled onto the linked item
    parlare = client.get_item("it/parlare")
    assert parlare["cards"] == [card["id"]]
    assert parlare["state"]["reps"] == 1

    profile = run_cli(cli_env, "profile", "kn-italian")
    assert profile.returncode == 0, profile.stdout + profile.stderr
    assert "items: 3" in profile.stdout
    # parlare was just answered (learning, not due); the rule comes first among new items
    assert "learning 1" in profile.stdout
    assert "it/parlare" not in profile.stdout
    assert profile.stdout.index("it/present-are") < profile.stdout.index("it/farfalla")

    client.record_interaction({"uuid": str(uuid.uuid4()), "mode": "recall",
                               "items": [{"ref": "it/farfalla", "outcome": "good"}]})
    out = tmp_path / "export.jsonl"
    exported = run_cli(cli_env, "export", "-o", str(out))
    assert exported.returncode == 0, exported.stdout + exported.stderr
    lines = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert lines[0]["format"] == "pauk-export"
    assert {"item", "interaction", "settings"} <= {line.get("type") for line in lines}

    # restoring into the same database is a no-op (refs and uuids are identities)
    restored = run_cli(cli_env, "import", str(out))
    assert restored.returncode == 0, restored.stdout + restored.stderr
    assert "restored 0 new items, 0 new interactions" in restored.stdout


def test_duplicate_candidates_reach_the_client(server):
    client = Client(server["url"], server["token"], cache=False)
    client.create_item({"space": "it", "kind": "word", "label_md": "kn-ape", "gloss_md": "bee"})
    try:
        client.create_item({"space": "it", "kind": "word", "label_md": "la kn-ape"})
    except ApiError as e:
        assert e.status == 409
        assert e.code == "possible_duplicates"
        assert e.data["candidates"][0]["ref"] == "it/kn-ape"
    else:
        raise AssertionError("expected possible_duplicates")


def test_item_import_creates_missing_parent_dirs(cli_env, server, tmp_path):
    file = tmp_path / "deep.json"
    file.write_text(json.dumps({
        "space": "it", "dirs": ["kn-deep/a/b/c"],
        "items": [{"key": "kn-profondo", "kind": "word", "label_md": "kn-profondo", "dirs": ["kn-deep/a/b/c"]}],
    }), encoding="utf-8")
    result = run_cli(cli_env, "import", str(file))
    assert result.returncode == 0, result.stdout + result.stderr
    client = Client(server["url"], server["token"], cache=False)
    assert client.resolve_dir("kn-deep/a/b")["name"] == "b"


def test_items_and_reports_commands(cli_env, server):
    client = Client(server["url"], server["token"], cache=False)
    for label in ("kn-t-cell", "kn-t-lymphocyte"):
        client.create_item({"space": "concepts", "kind": "term", "label_md": label, "distinct_from": [], "reason": "x"})
    listed = run_cli(cli_env, "items", "list", "--space", "concepts", "--json")
    assert listed.returncode == 0, listed.stdout + listed.stderr
    assert {"concepts/kn-t-cell", "concepts/kn-t-lymphocyte"} <= {i["ref"] for i in json.loads(listed.stdout)}
    suggested = run_cli(cli_env, "items", "suggest-merge", "concepts/kn-t-cell", "concepts/kn-t-lymphocyte", "--reason", "synonyms")
    assert suggested.returncode == 0, suggested.stdout + suggested.stderr
    merges = run_cli(cli_env, "items", "merges")
    assert "concepts/kn-t-lymphocyte → concepts/kn-t-cell" in merges.stdout
    assert "pauk duplicate sweep instructions" in run_cli(cli_env, "items", "dedup-instructions").stdout

    client.create_report({"reporter": "learner", "category": "ux", "text_md": "KN: the timer is hard to see"})
    listed = run_cli(cli_env, "reports")
    assert "KN: the timer is hard to see" in listed.stdout
    report_id = listed.stdout.split("#", 1)[1].split(" ", 1)[0]
    marked = run_cli(cli_env, "reports", "mark", report_id, "--status", "triaged", "--issue", "issues/9999-x.md")
    assert json.loads(marked.stdout)["status"] == "triaged"
    assert "pauk triage instructions" in run_cli(cli_env, "reports", "triage-instructions").stdout
