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


BOX_CHARS = "╭─╮│╰╯┌┐└┘├┤┬┴"


def test_help_has_no_box_chars(cli_env):
    for args in ([], ["quiz"], ["stats"]):
        result = run_cli(cli_env, *args, "--help")
        assert result.returncode == 0
        assert "Usage:" in result.stdout
        assert not any(ch in result.stdout for ch in BOX_CHARS)


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
    assert not any(ch in tree.stdout for ch in BOX_CHARS)

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
    assert "imported 0 cards, skipped 72 existing, added 0 links" in again.stdout

    # quiz two text questions: answer wrong, then quit
    quiz = run_cli(
        cli_env, "quiz", "--dir", "greek/lowercase", "-n", "2",
        input_text="definitely-wrong\nq\n",
    )
    assert quiz.returncode == 0, quiz.stderr
    assert "wrong" in quiz.stdout
    assert "accepted:" in quiz.stdout
    # header shows mode + shortcuts once
    assert "weighted pick" in quiz.stdout
    # a finished run yields a ranking
    assert "Top runs:" in quiz.stdout
    # no box-drawing characters in quiz output
    assert not any(ch in quiz.stdout for ch in BOX_CHARS)


def test_import_italian(cli_env):
    result = run_cli(cli_env, "import", str(REPO / "content" / "italian.json"))
    assert result.returncode == 0, result.stderr
    assert "imported 209 cards" in result.stdout

    tree = run_cli(cli_env, "ls", "--tree")
    assert "a1/" in tree.stdout
    assert "core-verbs/" in tree.stdout


def test_menu_tree_view(cli_env):
    # menu -> quiz picker -> Tab to tree view -> Right expands the
    # first deck (greek, alphabetically first with cards) -> Esc
    # back -> exit. "\x1bx" is Esc for the piped-input key reader.
    menu = run_cli(
        cli_env,
        input_text="1\n\t\x1b[C\x1bx4\n",
    )
    assert menu.returncode == 0, menu.stderr
    assert "directory tree" in menu.stdout
    assert "+ greek" in menu.stdout          # collapsed, expandable
    assert "- greek" in menu.stdout          # expanded after Right
    assert "lowercase" in menu.stdout        # its children became visible
    assert not any(ch in menu.stdout for ch in BOX_CHARS)


def test_quiz_repeat_wrong(cli_env):
    sample = {
        "dirs": ["repeat-demo"],
        "dir_links": [],
        "cards": [{
            "dirs": ["repeat-demo"],
            "type": "text",
            "question_md": "Repeat question",
            "accepted_answers": ["si"],
        }],
    }
    path = Path(cli_env["XDG_CONFIG_HOME"]) / "repeat.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sample))
    assert run_cli(cli_env, "import", str(path)).returncode == 0

    # wrong answer, repeat the wrong one, right answer, done
    quiz = run_cli(
        cli_env, "quiz", "--dir", "repeat-demo", "-n", "1",
        input_text="no\nw\nsi\n\n",
    )
    assert quiz.returncode == 0, quiz.stderr
    assert "repeat the 1 wrong" in quiz.stdout
    assert "Result: 0/1 correct." in quiz.stdout
    assert "Result: 1/1 correct." in quiz.stdout


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

    # menu: 1 = quiz, type to fuzzy-filter in the favorites view,
    # Enter picks the top match, 1 question, typo answer, Enter at
    # the repeat prompt, Esc leaves the picker, 4 exits the menu
    menu = run_cli(
        cli_env,
        input_text="1\nmenu-demo\r1\nhelo\n\n\x1bx4\n",
    )
    assert menu.returncode == 0, menu.stderr
    assert "Start a new quiz" in menu.stdout
    assert "favorites first" in menu.stdout
    assert "filter: menu-demo" in menu.stdout
    # a tolerated typo must show the correct spelling
    assert "correct spelling:" in menu.stdout
    assert "hello" in menu.stdout


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


def test_stats_command(cli_env):
    sample = {
        "dirs": ["stats-demo"],
        "dir_links": [],
        "cards": [{
            "dirs": ["stats-demo"],
            "type": "text",
            "question_md": "Stats question",
            "accepted_answers": ["yes"],
        }],
    }
    path = Path(cli_env["XDG_CONFIG_HOME"]) / "stats.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sample))
    assert run_cli(cli_env, "import", str(path)).returncode == 0
    # one wrong, one right answer via two 1-question quizzes
    run_cli(cli_env, "quiz", "--dir", "stats-demo", "-n", "1", input_text="nope\n")
    run_cli(cli_env, "quiz", "--dir", "stats-demo", "-n", "1", input_text="yes\n")

    stats = run_cli(cli_env, "stats", "stats-demo", "--cards", "5")
    assert stats.returncode == 0, stats.stderr
    assert "cards: 1" in stats.stdout
    assert "answers: 2" in stats.stdout
    assert "accuracy: 50%" in stats.stdout
    # top decks by started runs, with the deck's run count
    assert "Top decks" in stats.stdout
    assert "stats-demo" in stats.stdout
    assert "2 runs" in stats.stdout
    # hardest cards only on request (--cards)
    assert "Hardest cards" in stats.stdout
    assert "Stats question" in stats.stdout
    bare = run_cli(cli_env, "stats", "stats-demo")
    assert "Hardest cards" not in bare.stdout


def test_trophy_on_top_run(cli_env):
    sample = {
        "dirs": ["trophy-demo"],
        "dir_links": [],
        "cards": [{
            "dirs": ["trophy-demo"],
            "type": "text",
            "question_md": "Trophy question",
            "accepted_answers": ["win"],
        }],
    }
    path = Path(cli_env["XDG_CONFIG_HOME"]) / "trophy.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sample))
    assert run_cli(cli_env, "import", str(path)).returncode == 0
    quiz = run_cli(cli_env, "quiz", "--dir", "trophy-demo", "-n", "1", input_text="win\n")
    assert quiz.returncode == 0, quiz.stderr
    assert "Top runs:" in quiz.stdout
    assert "place #1" in quiz.stdout
    assert "==_==" in quiz.stdout  # the trophy art


def test_version_and_login(cli_env, server):
    version = run_cli(cli_env, "--version")
    assert version.returncode == 0
    assert version.stdout.startswith("pauk ")

    env = dict(cli_env)
    env.pop("PAUK_SERVER")
    env.pop("PAUK_TOKEN")
    login = run_cli(env, "login", server["url"], input_text=server["token"] + "\n")
    assert login.returncode == 0, login.stdout + login.stderr
    assert "Logged in" in login.stdout
    assert run_cli(env, "health").returncode == 0

    bad = run_cli(env, "login", server["url"], input_text="wrong-token\n")
    assert bad.returncode == 1


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
