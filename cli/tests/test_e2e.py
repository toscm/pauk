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


def test_quiz_typo_shows_spelling(cli_env):
    sample = {
        "dirs": ["typo-demo"],
        "dir_links": [],
        "cards": [{
            "dirs": ["typo-demo"],
            "type": "text",
            "question_md": "Say hello",
            "accepted_answers": ["hello"],
        }],
    }
    path = Path(cli_env["XDG_CONFIG_HOME"]) / "typo.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sample))
    assert run_cli(cli_env, "import", str(path)).returncode == 0

    quiz = run_cli(
        cli_env, "quiz", "--dir", "typo-demo", "-n", "1",
        input_text="helo\n\n",
    )
    assert quiz.returncode == 0, quiz.stderr
    # a tolerated typo must show the correct spelling
    assert "correct spelling:" in quiz.stdout
    assert "hello" in quiz.stdout


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


def test_media_upload_and_import_substitution(cli_env, tmp_path):
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
        b"\x00\x00\x05\x00\x01\x0d\x0a\x2d\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    img = tmp_path / "pixel.png"
    img.write_bytes(png)

    added = run_cli(cli_env, "media", "add", str(img))
    assert added.returncode == 0, added.stderr
    assert "url: http" in added.stdout
    url = re.search(r"url: (\S+)", added.stdout).group(1)

    # the file is actually served
    import httpx

    assert httpx.get(url, timeout=10).content == png

    # import with media: substitution, idempotent on re-run
    sample = {
        "dirs": ["media-demo"],
        "dir_links": [],
        "cards": [{
            "dirs": ["media-demo"],
            "type": "text",
            "question_md": "What is this? ![p](media:pixel.png)",
            "accepted_answers": ["a pixel"],
        }],
    }
    content = tmp_path / "media-demo.json"
    content.write_text(json.dumps(sample))
    result = run_cli(cli_env, "import", str(content))
    assert result.returncode == 0, result.stderr
    assert "uploaded 1 media files" in result.stdout
    assert "imported 1 cards" in result.stdout
    again = run_cli(cli_env, "import", str(content))
    assert "imported 0 cards" in again.stdout

    ls = run_cli(cli_env, "ls", "media-demo")
    assert "media:" not in ls.stdout
    assert "/media/" in ls.stdout

    # media: also substituted inside an mc option's text_md
    mc_sample = {
        "dirs": ["media-mc"],
        "dir_links": [],
        "cards": [{
            "dirs": ["media-mc"],
            "type": "mc",
            "question_md": "Pick the image option",
            "options": [
                {"text_md": "this ![p](media:pixel.png)", "correct": True},
                {"text_md": "plain", "correct": False},
            ],
        }],
    }
    mc_content = tmp_path / "media-mc.json"
    mc_content.write_text(json.dumps(mc_sample))
    mc_result = run_cli(cli_env, "import", str(mc_content))
    assert mc_result.returncode == 0, mc_result.stderr
    assert "imported 1 cards" in mc_result.stdout

    listed = run_cli(cli_env, "media", "ls")
    assert "pixel.png" in listed.stdout

    # deletion refused while referenced
    media_id = re.search(r"#(\d+) pixel", listed.stdout).group(1)
    refused = run_cli(cli_env, "media", "rm", media_id)
    assert refused.returncode == 1
    assert "referenced" in refused.stdout

    # unlink the card, then media rm succeeds
    ls_cards = run_cli(cli_env, "ls", "media-demo")
    import re as _re
    card_id = _re.search(r"#(\d+)", ls_cards.stdout).group(1)
    run_cli(cli_env, "rm", card_id)
    # (the mc card also references it) remove media-mc card too
    for line in run_cli(cli_env, "ls", "media-mc").stdout.splitlines():
        m = _re.search(r"#(\d+)", line)
        if m:
            run_cli(cli_env, "rm", m.group(1))
    removed = run_cli(cli_env, "media", "rm", media_id)
    assert removed.returncode == 0, removed.stdout
    assert "deleted" in removed.stdout


def test_route_run_and_graph(cli_env):
    """The deterministic route core: bundled graph + km + recording."""
    from pauk.route import load_graph
    from pauk.client import Client

    g = load_graph("germany-autobahn")
    assert g.shortest_km("muenchen", "berlin") == 595

    client = Client(cli_env["PAUK_SERVER"], cli_env["PAUK_TOKEN"])
    dir_id = client.create_dir("routee2e")["id"]
    card = client.create_card({
        "type": "route",
        "question_md": "Ingolstadt to Nürnberg",
        "graph_name": "germany-autobahn",
        "start_node": "ingolstadt",
        "goal_node": "nuernberg",
        "dirs": [dir_id],
    })
    # a real one-hop route, km summed from the graph
    km = g.edge_km("ingolstadt", "nuernberg")
    assert km and km > 0
    result = client.route_run(card["id"], True, km)
    assert result["best_km"] == km
    assert result["rank"] == 1
    # a longer run does not beat it
    worse = client.route_run(card["id"], True, km + 200)
    assert worse["best_km"] == km


def test_quest_import_is_idempotent(cli_env):
    r1 = run_cli(cli_env, "import", str(REPO / "content" / "italian-quests.json"))
    assert r1.returncode == 0, r1.stderr
    r2 = run_cli(cli_env, "import", str(REPO / "content" / "italian-quests.json"))
    assert "imported 0 cards" in r2.stdout   # deduped by scenario_md
