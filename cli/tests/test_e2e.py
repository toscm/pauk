"""End-to-end tests: real CLI process → real API → real MariaDB."""

from __future__ import annotations

import json
import re
from pathlib import Path

from conftest import REPO, run_cli


def test_health(cli_env):
    result = run_cli(cli_env, "health")
    assert result.returncode == 0
    assert "'status': 'ok'" in result.stdout


def test_mkdir_add_ls_roundtrip(cli_env):
    assert run_cli(cli_env, "mkdir", "bio/cells").returncode == 0
    add = run_cli(
        cli_env, "add", "--dir", "bio/cells",
        input_text="text\nWhat does DNA stand for?\ndeoxyribonucleic acid\n\n",
    )
    assert add.returncode == 0, add.stderr
    assert "created card" in add.stdout

    ls = run_cli(cli_env, "ls")
    assert "bio/" in ls.stdout
    ls = run_cli(cli_env, "ls", "bio/cells")
    assert "DNA" in ls.stdout

    tree = run_cli(cli_env, "ls", "--tree")
    assert "cells/" in tree.stdout

    # rm deletes the card again
    ls = run_cli(cli_env, "ls", "bio/cells")
    card_id = re.search(r"#(\d+)", ls.stdout).group(1)
    removed = run_cli(cli_env, "rm", card_id)
    assert removed.returncode == 0
    assert f"deleted card #{card_id}" in removed.stdout
    assert "DNA" not in run_cli(cli_env, "ls", "bio/cells").stdout


def test_import_greek_and_quiz(cli_env):
    result = run_cli(cli_env, "import", str(REPO / "content" / "greek.json"))
    assert result.returncode == 0, result.stderr
    assert "imported 72 cards" in result.stdout

    # importing again must be a no-op
    again = run_cli(cli_env, "import", str(REPO / "content" / "greek.json"))
    assert "imported 0 cards, skipped 72" in again.stdout

    # quiz three text questions, quit style: answer wrong, then quit
    quiz = run_cli(
        cli_env, "quiz", "--dir", "greek/lowercase", "-n", "2",
        input_text="definitely-wrong\nq\n",
    )
    assert quiz.returncode == 0, quiz.stderr
    assert "wrong" in quiz.stdout
    assert "accepted:" in quiz.stdout


def test_import_italian(cli_env):
    result = run_cli(cli_env, "import", str(REPO / "content" / "italian.json"))
    assert result.returncode == 0, result.stderr
    assert "imported 209 cards" in result.stdout

    tree = run_cli(cli_env, "ls", "--tree")
    assert "a1/" in tree.stdout
    assert "core-verbs/" in tree.stdout


def test_quiz_via_menu(cli_env):
    sample = {
        "dirs": ["menu-demo"],
        "dir_links": [],
        "cards": [{
            "dirs": ["menu-demo"],
            "type": "text",
            "question_md": "Say hello",
            "accepted_answers": ["hello"],
        }],
    }
    path = Path(cli_env["XDG_CONFIG_HOME"]) / "sample.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sample))
    assert run_cli(cli_env, "import", str(path)).returncode == 0

    # the quiz menu lists top-level dirs alphabetically; find
    # menu-demo's number instead of hardcoding it
    names = sorted(
        line.split("/")[0]
        for line in run_cli(cli_env, "ls").stdout.splitlines()
        if "/" in line
    )
    demo_index = names.index("menu-demo") + 1

    # menu: 1 = quiz, then pick the folder, 1 question, answer, exit
    menu = run_cli(
        cli_env,
        input_text=f"1\n{demo_index}\n1\nhello\n4\n",
    )
    assert menu.returncode == 0, menu.stderr
    assert "Start a new quiz" in menu.stdout
    assert "correct" in menu.stdout


def test_mc_quiz_answer(cli_env):
    sample = {
        "dirs": ["mc-demo"],
        "dir_links": [],
        "cards": [{
            "dirs": ["mc-demo"],
            "type": "mc",
            "question_md": "Pick the right one",
            "options": [
                {"text_md": "right", "correct": True},
                {"text_md": "nope", "correct": False},
            ],
        }],
    }
    path = Path(cli_env["XDG_CONFIG_HOME"]) / "mc.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sample))
    assert run_cli(cli_env, "import", str(path)).returncode == 0

    quiz = run_cli(
        cli_env, "quiz", "--dir", "mc-demo", "-n", "1",
        input_text="1\n",
    )
    assert quiz.returncode == 0, quiz.stderr
    assert "Result:" in quiz.stdout


def test_config_file(cli_env, tmp_path):
    env = dict(cli_env)
    env.pop("PAUK_SERVER")
    env.pop("PAUK_TOKEN")
    result = run_cli(env, "health")
    assert result.returncode == 1
    assert "No server/token configured" in result.stdout

    saved = run_cli(env, "config", cli_env["PAUK_SERVER"], cli_env["PAUK_TOKEN"])
    assert saved.returncode == 0
    result = run_cli(env, "health")
    assert result.returncode == 0
