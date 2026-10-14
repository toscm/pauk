"""E2E tests for `pauk edit`, `link`, `unlink` and `mv`: real CLI
process → real API → real MariaDB. The editor is a script that
applies scripted replacements, one step per invocation."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

from conftest import run_cli
from pauk.client import Client

FAKE_EDITOR = '''
import json, os, pathlib, sys
path = pathlib.Path(sys.argv[1])
state = pathlib.Path(os.environ["FAKE_EDITOR_STATE"])
steps = json.loads(state.read_text())
step = steps.pop(0)
state.write_text(json.dumps(steps))
text = path.read_text(encoding="utf-8")
with open(os.environ["FAKE_EDITOR_SEEN"], "a", encoding="utf-8") as seen:
    seen.write(json.dumps(text) + "\\n")
for old, new in step:
    assert old in text, (old, text)
    text = text.replace(old, new)
path.write_text(text, encoding="utf-8")
'''


@pytest.fixture()
def api(server):
    """A client whose created cards are deleted afterwards, so other
    tests on the shared database (e.g. "the first recall card") never
    see them."""
    client = Client(server["url"], server["token"], cache=False)
    created: list[int] = []
    create_card = client.create_card

    def tracked(body: dict) -> dict:
        card = create_card(body)
        created.append(card["id"])
        return card

    client.create_card = tracked
    yield client
    for card_id in created:
        client.delete_card(card_id)


@pytest.fixture()
def editor(cli_env, tmp_path):
    """Returns a function that scripts the editor: each argument is
    one invocation, a list of (old, new) replacements."""
    script = tmp_path / "fake_editor.py"
    script.write_text(FAKE_EDITOR, encoding="utf-8")
    state = tmp_path / "editor-steps.json"
    seen = tmp_path / "editor-seen.jsonl"
    cli_env["EDITOR"] = f"{sys.executable} {script}"
    cli_env["FAKE_EDITOR_STATE"] = str(state)
    cli_env["FAKE_EDITOR_SEEN"] = str(seen)

    def script_steps(*steps):
        state.write_text(json.dumps([list(map(list, step)) for step in steps]))
        seen.write_text("")
        return lambda: [json.loads(line) for line in seen.read_text().splitlines()]

    return script_steps


def _mkdirs(api: Client, *paths: str) -> dict[str, int]:
    ids = {}
    for path in paths:
        parent_path, _, name = path.rpartition("/")
        ids[path] = api.create_dir(name, ids.get(parent_path) or (api.resolve_dir(parent_path)["id"] if parent_path else None))["id"]
    return ids


def _dir_ids(card: dict) -> set[int]:
    return {d["id"] for d in card["dirs"]}


def test_edit_patches_changed_fields(cli_env, api, editor):
    ids = _mkdirs(api, "ed-mc", "ed-other")
    card = api.create_card({"type": "mc", "question_md": "Capital of Italy?", "dirs": [ids["ed-mc"]],
                            "options": [{"text_md": "Rome", "correct": True}, {"text_md": "Milan", "correct": False}]})
    seen = editor([("Capital of Italy?", "What is the capital of Italy?"),
                   ("text: Milan", "text: Turin"),
                   ("- ed-mc", "- ed-mc\n- ed-other")])
    result = run_cli(cli_env, "edit", str(card["id"]))
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"updated card #{card['id']}: dirs, options, question_md" in result.stdout

    # the editor saw the clone format: frontmatter + the question as body
    text = seen()[0]
    front = yaml.safe_load(text.split("---\n")[1])
    assert front["id"] == card["id"] and front["type"] == "mc" and front["dirs"] == ["ed-mc"]
    assert text.rstrip().endswith("Capital of Italy?")

    updated = api.get_card(card["id"])
    assert updated["question_md"] == "What is the capital of Italy?"
    assert [(o["text_md"], o["correct"]) for o in updated["options"]] == [("Rome", True), ("Turin", False)]
    assert _dir_ids(updated) == {ids["ed-mc"], ids["ed-other"]}


def test_edit_unchanged_and_quest_partial(cli_env, api, editor):
    card = api.create_card({"type": "quest", "scenario_md": "Order a coffee in Italian.",
                            "role_prompt": "You are a barista.", "success_criteria": "A coffee was ordered.",
                            "max_messages": 8, "lang": "it"})
    editor([])
    result = run_cli(cli_env, "edit", str(card["id"]))
    assert result.returncode == 0, result.stderr
    assert "file unchanged; card not modified" in result.stdout
    assert api.get_card(card["id"])["updated_at"] == card["updated_at"]

    editor([("max_messages: 8", "max_messages: 12")])
    result = run_cli(cli_env, "edit", str(card["id"]))
    assert result.returncode == 0, result.stderr
    assert f"updated card #{card['id']}: max_messages" in result.stdout
    updated = api.get_card(card["id"])
    assert updated["max_messages"] == 12
    assert updated["scenario_md"] == "Order a coffee in Italian."


def test_edit_invalid_reopens_with_edits_kept(cli_env, api, editor):
    card = api.create_card({"type": "text", "question_md": "Say hello in Italian", "accepted_answers": ["ciao"]})
    seen = editor([("type: text", "type: mc")],
                  [("type: mc", "type: text"), ("- ciao", "- ciao\n- salve")])
    result = run_cli(cli_env, "edit", str(card["id"]), input_text="y\n")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "invalid: type must stay text" in result.stdout
    assert f"updated card #{card['id']}: accepted_answers" in result.stdout
    # the second round opened the broken file, not the original
    assert "type: mc" in seen()[1]
    assert api.get_card(card["id"])["accepted_answers"] == ["ciao", "salve"]


def test_edit_invalid_declined_changes_nothing(cli_env, api, editor):
    card = api.create_card({"type": "recall", "question_md": "Why is the sky blue?", "answer_md": "Rayleigh scattering."})
    editor([("answer_md: Rayleigh scattering.", "answer_md: [unclosed")])
    result = run_cli(cli_env, "edit", str(card["id"]), input_text="n\n")
    assert result.returncode == 0, result.stderr
    assert "invalid: invalid YAML frontmatter" in result.stdout
    assert "aborted; card not modified" in result.stdout

    # a value the API rejects is reported the same way
    editor([("Why is the sky blue?", "Why is the sky blue? (explain)"), ("dirs: []", "dirs:\n- no-such-dir")])
    result = run_cli(cli_env, "edit", str(card["id"]), input_text="n\n")
    assert "no directory no-such-dir" in result.stdout
    assert api.get_card(card["id"])["question_md"] == "Why is the sky blue?"


def test_link_unlink_card(cli_env, api):
    ids = _mkdirs(api, "ln-a", "ln-b")
    card = api.create_card({"type": "text", "question_md": "Link me", "accepted_answers": ["x"], "dirs": [ids["ln-a"]]})
    result = run_cli(cli_env, "link", str(card["id"]), "ln-b")
    assert result.returncode == 0, result.stdout + result.stderr
    assert _dir_ids(api.get_card(card["id"])) == {ids["ln-a"], ids["ln-b"]}

    assert run_cli(cli_env, "unlink", f"#{card['id']}", "ln-a").returncode == 0
    assert _dir_ids(api.get_card(card["id"])) == {ids["ln-b"]}

    again = run_cli(cli_env, "unlink", str(card["id"]), "ln-a")
    assert again.returncode == 1
    assert f"card #{card['id']} is not in ln-a" in again.stdout

    last = run_cli(cli_env, "unlink", str(card["id"]), "ln-b")
    assert "now in no directory (unfiled)" in last.stdout
    assert api.get_card(card["id"])["dirs"] == []


def test_mv_card(cli_env, api):
    ids = _mkdirs(api, "mvc-a", "mvc-b", "mvc-c")
    card = api.create_card({"type": "text", "question_md": "Move me", "accepted_answers": ["x"], "dirs": [ids["mvc-a"]]})
    result = run_cli(cli_env, "mv", str(card["id"]), "mvc-b")
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"moved card #{card['id']} from mvc-a to mvc-b" in result.stdout
    assert _dir_ids(api.get_card(card["id"])) == {ids["mvc-b"]}

    # in two directories: which one it leaves must be said
    run_cli(cli_env, "link", str(card["id"]), "mvc-a")
    refused = run_cli(cli_env, "mv", str(card["id"]), "mvc-c")
    assert refused.returncode == 1
    assert "is in several directories (mvc-a, mvc-b)" in refused.stdout
    assert _dir_ids(api.get_card(card["id"])) == {ids["mvc-a"], ids["mvc-b"]}

    moved = run_cli(cli_env, "mv", str(card["id"]), "mvc-c", "--from", "mvc-a")
    assert moved.returncode == 0, moved.stdout
    assert _dir_ids(api.get_card(card["id"])) == {ids["mvc-b"], ids["mvc-c"]}


def test_mv_dir(cli_env, api):
    ids = _mkdirs(api, "mvd-src", "mvd-src/sub", "mvd-src/sub/leaf", "mvd-dst", "mvd-other")

    # into an existing directory: the edge from the source path moves
    result = run_cli(cli_env, "mv", "mvd-src/sub", "mvd-dst")
    assert result.returncode == 0, result.stdout + result.stderr
    assert [p["id"] for p in api.get_dir(ids["mvd-src/sub"])["parents"]] == [ids["mvd-dst"]]
    assert api.resolve_dir("mvd-dst/sub/leaf")["id"] == ids["mvd-src/sub/leaf"]

    # to a new name: mv semantics, rename + move
    result = run_cli(cli_env, "mv", "mvd-dst/sub", "mvd-src/renamed")
    assert result.returncode == 0, result.stdout + result.stderr
    assert api.resolve_dir("mvd-src/renamed")["id"] == ids["mvd-src/sub"]

    # a second parent: only the named edge moves, top level is refused
    assert run_cli(cli_env, "link", "mvd-src/renamed", "mvd-other").returncode == 0
    result = run_cli(cli_env, "mv", "mvd-other/renamed", "mvd-dst")
    assert result.returncode == 0, result.stdout
    parents = {p["id"] for p in api.get_dir(ids["mvd-src/sub"])["parents"]}
    assert parents == {ids["mvd-src"], ids["mvd-dst"]}
    refused = run_cli(cli_env, "mv", "mvd-dst/renamed", "/")
    assert refused.returncode == 1
    assert "has other parents as well" in refused.stdout

    # into its own subtree: the API refuses the cycle
    cycle = run_cli(cli_env, "mv", "mvd-src", "mvd-src/renamed/leaf")
    assert cycle.returncode == 1
    assert "cycle" in cycle.stdout

    # unlinking the last parent makes it top-level
    assert run_cli(cli_env, "unlink", "mvd-src/renamed", "mvd-src").returncode == 0
    result = run_cli(cli_env, "mv", "mvd-dst/renamed", "/")
    assert result.returncode == 0, result.stdout
    assert api.resolve_dir("renamed")["parents"] == []


def test_numeric_dir_name_is_ambiguous(cli_env, api):
    _mkdirs(api, "424242", "amb-target")
    result = run_cli(cli_env, "link", "424242", "amb-target")
    assert result.returncode == 1
    assert "both a card id and a directory" in result.stdout
    assert run_cli(cli_env, "link", "424242/", "amb-target").returncode == 0
    assert api.resolve_dir("amb-target/424242")
