"""Headless TUI tests: Textual Pilot driving the real app against
the real test API. Network runs in worker threads, so tests wait
for workers to settle before asserting.

Quizzes are open-ended: a deck runs until Escape, with no fixed
length, no ResultScreen, and wrong cards resurfacing. The current
card is `app.screen.current`."""

from __future__ import annotations

import json

import pytest

from pauk.client import Client
from pauk.importer import import_file
from pauk.tui.app import PaukApp
from pauk.tui.screens import (
    HomeScreen,
    PickerScreen,
    QuestScreen,
    QuizScreen,
    RouteScreen,
    SettingsScreen,
    StatsScreen,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture()
def client(server, tmp_path):
    client = Client(server["url"], server["token"])
    sample = {
        "dirs": ["tuidemo", "tuidemo/inner", "tuidemo/match"],
        "dir_links": [],
        "cards": [
            {
                "dirs": ["tuidemo/inner"],
                "type": "text",
                "question_md": "TUI question one",
                "accepted_answers": ["uno"],
            },
            {
                "dirs": ["tuidemo/inner"],
                "type": "mc",
                "question_md": "TUI question two",
                "options": [
                    {"text_md": "right", "correct": True},
                    {"text_md": "nope", "correct": False},
                ],
            },
            {
                "dirs": ["tuidemo/match"],
                "type": "match",
                "question_md": "Match them",
                "pairs": [
                    {"left_md": "io", "right_md": "sono"},
                    {"left_md": "tu", "right_md": "sei"},
                ],
            },
        ],
    }
    path = tmp_path / "tui.json"
    path.write_text(json.dumps(sample))
    import_file(client, path, echo=lambda *_: None)
    return client


async def _settle(pilot):
    await pilot.app.workers.wait_for_complete()
    await pilot.pause()


async def _pick(pilot, query):
    """Filtering lives in the favorites view; switch there (tree is the
    default landing view), type the query, and start the top match."""
    if pilot.app.picker_memory.get("view") == "tree":
        await pilot.press("tab")
    await pilot.press(*query, "enter")


async def _answer_current(pilot, correct: bool):
    """Answer whatever card is showing, then advance past the feedback."""
    screen = pilot.app.screen
    card = screen.current
    if card["type"] == "mc":
        if correct:
            # select the first correct option
            sel = screen.query_one("#choices")
            for i, opt in enumerate(card["options"]):
                if opt.get("correct"):
                    sel.select(sel.get_option_at_index(i))
                    break
        await pilot.click("#submit")
    elif card["type"] == "match":
        for _ in range(len(card["lefts"])):
            left_id = card["lefts"][screen._match_idx]["id"]
            choices = screen.query_one("#match-choices")
            for i in range(choices.option_count):
                wanted = str(left_id) if correct else "x"
                if choices.get_option_at_index(i).id == wanted:
                    choices.highlighted = i
                    break
            await pilot.press("enter")
        await _settle(pilot)
        return
    else:  # text
        await pilot.press(*("uno" if correct else "zzz"), "enter")
    await _settle(pilot)


async def test_home_menu_and_stats(client):
    app = PaukApp(client)
    async with app.run_test(size=(100, 40)) as pilot:
        assert isinstance(app.screen, HomeScreen)
        await pilot.press("down", "enter")          # Statistics
        assert isinstance(app.screen, StatsScreen)
        await _settle(pilot)
        assert "Statistics" in str(app.screen.query_one("#stats-text").render())
        await pilot.press("escape")
        assert isinstance(app.screen, HomeScreen)


async def test_tab_tree_navigation_and_open_ended_quiz(client):
    app = PaukApp(client)
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.press("enter")                  # Start a quiz
        assert isinstance(app.screen, PickerScreen)
        await _settle(pilot)
        assert app.picker_memory["view"] == "tree"  # tree is the default
        await pilot.press("tab")                    # Tab toggles to favorites
        assert app.picker_memory["view"] == "fav"
        await pilot.press("tab")                    # and back to the tree
        assert app.picker_memory["view"] == "tree"
        await pilot.pause()
        tree = app.screen.query_one("#deck-tree")
        node = next(
            n for n in tree.root.children if n.data and n.data["path"] == "tuidemo"
        )
        tree.move_cursor(node)
        await pilot.press("right")                  # expand
        assert node.is_expanded
        await pilot.press("down", "enter")          # child → start quiz
        await _settle(pilot)
        assert isinstance(app.screen, QuizScreen)
        assert app.screen.deck_title == "tuidemo/inner"

        # open-ended: answer a couple of cards, then leave with Escape
        await _answer_current(pilot, correct=True)
        assert app.screen.answered >= 1
        await pilot.press("enter")                  # continue to next
        await _settle(pilot)
        await _answer_current(pilot, correct=True)
        await pilot.press("escape")                 # end the session
        await _settle(pilot)
        assert isinstance(app.screen, PickerScreen)


async def test_filter_and_status(client):
    app = PaukApp(client)
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.press("enter")
        await _settle(pilot)
        await pilot.press("tab")                    # tree → favorites (filterable)
        await pilot.press(*"match")                 # fuzzy filter
        await pilot.pause()
        status = str(app.screen.query_one("#picker-status").render())
        assert "/match" in status                   # filter shown, no question count


async def test_settings_persist(client, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    from importlib import reload

    from pauk import config as config_mod
    reload(config_mod)
    app = PaukApp(client)
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.press("down", "down", "enter")  # Settings
        assert isinstance(app.screen, SettingsScreen)
        pos = app.screen.query_one("#pos-list")
        pos.focus()
        await pilot.pause()
        await pilot.press("down", "enter")          # 'top'
        await pilot.pause()
        assert config_mod.get("statusbar_position") == "top"
    reload(config_mod)


async def test_quiz_shows_image(client, tmp_path):
    from PIL import Image as PILImage

    img_path = tmp_path / "map.png"
    PILImage.new("RGB", (40, 30), (200, 30, 30)).save(img_path)
    media = client.upload_media(img_path)
    client.create_card({
        "type": "text",
        "question_md": f"Where is this? ![map]({media['url']})",
        "accepted_answers": ["nowhere"],
        "dirs": [client.create_dir("imagedemo")["id"]],
    })

    app = PaukApp(client)
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.press("enter")
        await _settle(pilot)
        await _pick(pilot, "imagedemo")
        await _settle(pilot)
        assert isinstance(app.screen, QuizScreen)
        # any renderer (auto / half-block under tmux / sixel) is fine
        from textual_image.widget import BaseImage

        assert len(app.screen.query(BaseImage)) == 1
        assert media["url"] in app._image_cache


async def test_match_card_flow(client):
    app = PaukApp(client)
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.press("enter")
        await _settle(pilot)
        await _pick(pilot, "tuidemo/match")
        await _settle(pilot)
        assert isinstance(app.screen, QuizScreen)
        assert app.screen.current["type"] == "match"
        await _answer_current(pilot, correct=True)
        assert app.screen.in_feedback
        assert "correct" in str(app.screen.query_one("#feedback").render())


async def test_all_cards_quiz(client):
    app = PaukApp(client)
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.press("enter")
        await _settle(pilot)
        await pilot.press("tab")                    # tree → favorites ("all cards")
        fav = app.screen.query_one("#fav-list")
        assert fav.get_option_at_index(0).id == "__all__"
        fav.highlighted = 0
        await pilot.press("enter")
        await _settle(pilot)
        # an all-cards session starts; the first card may be a task,
        # so the screen is the quiz or a task sub-screen it launched
        assert isinstance(app.screen, (QuizScreen, QuestScreen, RouteScreen))
        if isinstance(app.screen, QuizScreen):
            assert app.screen.dir_id is None


async def test_wrong_card_resurfaces(client):
    app = PaukApp(client)
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.press("enter")
        await _settle(pilot)
        await _pick(pilot, "tuidemo/inner")
        await _settle(pilot)
        assert isinstance(app.screen, QuizScreen)
        # answer the first card wrong → it should be scheduled to return
        await _answer_current(pilot, correct=False)
        assert len(app.screen.retry) == 1           # queued to resurface


async def test_escape_returns_to_picker(client):
    app = PaukApp(client)
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.press("enter")
        await _settle(pilot)
        await _pick(pilot, "tuidemo/inner")
        await _settle(pilot)
        assert isinstance(app.screen, QuizScreen)
        await pilot.press("escape")
        await _settle(pilot)
        assert isinstance(app.screen, PickerScreen)


async def test_error_toast_on_load_failure(client, monkeypatch):
    def boom():
        raise RuntimeError("network down")

    app = PaukApp(client)
    async with app.run_test(size=(100, 40)) as pilot:
        monkeypatch.setattr(app.client, "quiz_dirs", boom)
        await pilot.press("enter")
        await _settle(pilot)
        assert isinstance(app.screen, PickerScreen)
        assert any(n.severity == "error" for n in app._notifications)


class FakeProvider:
    """Deterministic provider for quest tests — no real LLM."""
    name = "fake"

    def chat(self, system, messages):
        return "Prego! (fake reply)"

    def judge(self, criteria, transcript):
        return any("cornetti" in m["content"] for m in transcript if m["role"] == "user")


async def test_quest_flow_success(server, tmp_path):
    client = Client(server["url"], server["token"])
    quest = {
        "dirs": ["questdemo"],
        "dir_links": [],
        "cards": [{
            "dirs": ["questdemo"],
            "type": "quest",
            "scenario_md": "Order cornetti",
            "role_prompt": "You are a baker.",
            "success_criteria": "Ordered cornetti.",
            "max_messages": 3,
            "lang": "it",
        }],
    }
    path = tmp_path / "quest.json"
    path.write_text(json.dumps(quest))
    import_file(client, path, echo=lambda *_: None)

    app = PaukApp(client, provider=FakeProvider())
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.press("enter")
        await _settle(pilot)
        await _pick(pilot, "questdemo")
        await _settle(pilot)
        assert isinstance(app.screen, QuestScreen)
        app.screen.query_one("#quest-input").focus()
        await pilot.press(*"vorrei due cornetti", "enter")
        await _settle(pilot)
        assert len(app.screen.messages) == 2
        await pilot.press("f2")                         # finish → judge
        await _settle(pilot)
        assert app.screen.finished
        assert "succeeded" in str(app.screen.query_one("#quest-log").render())


async def test_quest_give_up_returns_to_quiz(server, tmp_path):
    client = Client(server["url"], server["token"])
    quest = {
        "dirs": ["questgiveup"],
        "dir_links": [],
        "cards": [{
            "dirs": ["questgiveup"],
            "type": "quest",
            "scenario_md": "Do a thing",
            "role_prompt": "You are someone.",
            "success_criteria": "Did the thing.",
            "max_messages": 3,
            "lang": "",
        }],
    }
    path = tmp_path / "q2.json"
    path.write_text(json.dumps(quest))
    import_file(client, path, echo=lambda *_: None)

    app = PaukApp(client, provider=FakeProvider())
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.press("enter")
        await _settle(pilot)
        await _pick(pilot, "questgiveup")
        await _settle(pilot)
        assert isinstance(app.screen, QuestScreen)
        await pilot.press("escape")                     # give up
        await _settle(pilot)
        # open-ended: the only card resurfaces → back on a QuestScreen,
        # not a crash and not a (removed) result screen
        assert isinstance(app.screen, (QuestScreen, QuizScreen))


async def test_route_flow_reaches_goal(server):
    client = Client(server["url"], server["token"])
    dir_id = client.create_dir("routedemo")["id"]
    client.create_card({
        "type": "route",
        "question_md": "Drive Ingolstadt to Nürnberg.",
        "graph_name": "germany-autobahn",
        "start_node": "ingolstadt",
        "goal_node": "nuernberg",
        "dirs": [dir_id],
    })
    app = PaukApp(client)
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.press("enter")
        await _settle(pilot)
        await _pick(pilot, "routedemo")
        await _settle(pilot)
        await pilot.pause()
        assert isinstance(app.screen, RouteScreen)
        moves = app.screen.query_one("#route-moves")
        target = next(
            i for i in range(moves.option_count)
            if "Nürnberg" in moves.get_option_at_index(i).prompt
        )
        moves.highlighted = target
        await pilot.press("enter")
        await _settle(pilot)
        assert app.screen.arrived
        assert app.screen.km > 0
        assert "Arrived" in str(app.screen.query_one("#route-outcome").render())


async def test_route_give_up_records_nothing(server):
    client = Client(server["url"], server["token"])
    dir_id = client.create_dir("routegiveup")["id"]
    card = client.create_card({
        "type": "route",
        "question_md": "Ingolstadt to Nürnberg.",
        "graph_name": "germany-autobahn",
        "start_node": "ingolstadt",
        "goal_node": "nuernberg",
        "dirs": [dir_id],
    })
    app = PaukApp(client)
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.press("enter")
        await _settle(pilot)
        await _pick(pilot, "routegiveup")
        await _settle(pilot)
        await pilot.pause()
        assert isinstance(app.screen, RouteScreen)
        await pilot.press("escape")
        await _settle(pilot)
    result = client.route_run(card["id"], True, 1)
    assert result["rank"] == 1
