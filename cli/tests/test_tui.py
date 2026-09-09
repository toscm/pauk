"""Headless TUI tests: Textual Pilot driving the real app against
the real test API. Network runs in worker threads, so tests wait
for workers to settle before asserting."""

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
    RouteScreen,
    QuizScreen,
    ResultScreen,
    SettingsScreen,
    StatsScreen,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture()
def client(server, tmp_path):
    client = Client(server["url"], server["token"])
    sample = {
        "dirs": ["tuidemo", "tuidemo/inner"],
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
    sample["dirs"].append("tuidemo/match")
    path = tmp_path / "tui.json"
    path.write_text(json.dumps(sample))
    import_file(client, path, echo=lambda *_: None)
    return client


async def _settle(pilot):
    """Wait for background workers (network) and the UI to catch up."""
    await pilot.app.workers.wait_for_complete()
    await pilot.pause()


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


async def test_tree_navigation_and_full_quiz(client):
    app = PaukApp(client)
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.press("enter")                  # Start a quiz
        assert isinstance(app.screen, PickerScreen)
        await _settle(pilot)
        await pilot.press("f2")                     # tree view
        await pilot.pause()
        tree = app.screen.query_one("#deck-tree")
        node = next(
            n for n in tree.root.children if n.data and n.data["path"] == "tuidemo"
        )
        tree.move_cursor(node)
        assert not node.is_expanded
        await pilot.press("right")                  # expand
        assert node.is_expanded
        assert "tuidemo" in app.picker_memory["expanded"]
        await pilot.press("down", "enter")          # child → start quiz
        await _settle(pilot)
        assert isinstance(app.screen, QuizScreen)
        assert app.screen.deck_title == "tuidemo/inner"
        assert len(app.screen.cards) == 2

        for _ in range(2):
            card = app.screen.cards[app.screen.index]
            if card["type"] == "text":
                await pilot.press(*"zzz", "enter")
            else:
                await pilot.press("space")
                await pilot.click("#submit")
            await _settle(pilot)
            assert app.screen.in_feedback
            await pilot.press("enter")              # Continue
            await _settle(pilot)

        assert isinstance(app.screen, ResultScreen)
        text = str(app.screen.query_one("#result-text").render())
        assert "Result:" in text

        await pilot.press("escape")                 # back to picker
        await pilot.pause()
        assert isinstance(app.screen, PickerScreen)
        assert "tuidemo" in app.picker_memory["expanded"]


async def test_question_count_in_statusbar(client):
    app = PaukApp(client)
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.press("enter")
        await _settle(pilot)
        assert app.picker_memory["n"] == 25         # default
        await pilot.press("]", "]")                 # +5, +5
        assert app.picker_memory["n"] == 35
        await pilot.press("[")                      # -5
        assert app.picker_memory["n"] == 30
        status = str(app.screen.query_one("#picker-status").render())
        assert "30 questions" in status


async def test_repeat_wrong_is_unranked(client):
    app = PaukApp(client)
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.press("enter")
        await _settle(pilot)
        await pilot.press(*"tuidemo/inner", "enter")  # filter + start
        await _settle(pilot)
        assert isinstance(app.screen, QuizScreen)
        assert app.screen.ranked is True

        # answer both wrong to populate wrong_cards
        for _ in range(len(app.screen.cards)):
            card = app.screen.cards[app.screen.index]
            if card["type"] == "text":
                await pilot.press(*"xxx", "enter")
            else:
                await pilot.click("#submit")        # nothing selected
            await _settle(pilot)
            await pilot.press("enter")
            await _settle(pilot)

        assert isinstance(app.screen, ResultScreen)
        assert app.screen.wrong_cards
        await pilot.press("w")                      # repeat wrong
        await _settle(pilot)
        assert isinstance(app.screen, QuizScreen)
        # the repeat run is explicitly unranked
        assert app.screen.ranked is False


async def test_settings_persist(client, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    from importlib import reload

    from pauk import config as config_mod
    reload(config_mod)

    app = PaukApp(client)
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.press("down", "down", "enter")  # Settings
        assert isinstance(app.screen, SettingsScreen)
        # choose 'top' for the status bar
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
        await pilot.press(*"imagedemo", "enter")
        await _settle(pilot)
        assert isinstance(app.screen, QuizScreen)
        from textual_image.widget import Image as ImageWidget

        assert len(app.screen.query(ImageWidget)) == 1
        # cached: the app holds the decoded image
        assert media["url"] in app._image_cache


async def test_match_card_flow(client):
    """A match card is answered by picking a right item for each left."""
    app = PaukApp(client)
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.press("enter")
        await _settle(pilot)
        await pilot.press(*"tuidemo/match", "enter")   # filter to the match deck
        await _settle(pilot)
        assert isinstance(app.screen, QuizScreen)
        assert app.screen.cards[0]["type"] == "match"
        # answer both lefts correctly: pick the choice whose id matches
        for _ in range(len(app.screen.cards[0]["lefts"])):
            card = app.screen.cards[app.screen.index]
            left_id = card["lefts"][app.screen._match_idx]["id"]
            choices = app.screen.query_one("#match-choices")
            # highlight the choice with the matching id, then select
            for i in range(choices.option_count):
                if choices.get_option_at_index(i).id == str(left_id):
                    choices.highlighted = i
                    break
            await pilot.press("enter")
            await _settle(pilot)
        assert app.screen.in_feedback
        assert "correct" in str(app.screen.query_one("#feedback").render())


async def test_all_cards_quiz(client):
    app = PaukApp(client)
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.press("enter")
        await _settle(pilot)
        # first favorites option is "all cards"
        fav = app.screen.query_one("#fav-list")
        assert fav.get_option_at_index(0).id == "__all__"
        fav.highlighted = 0
        await pilot.press("enter")
        await _settle(pilot)
        assert isinstance(app.screen, QuizScreen)
        assert app.screen.dir_id is None


async def test_quit_early_is_unranked(client, monkeypatch):
    app = PaukApp(client)
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.press("enter")
        await _settle(pilot)
        await pilot.press(*"tuidemo/inner", "enter")
        await _settle(pilot)
        assert isinstance(app.screen, QuizScreen)
        finished = {}
        real = app.client.finish_run

        def spy(run_id, correct, total, ranked=None):
            finished["ranked"] = ranked
            return real(run_id, correct, total, ranked)

        monkeypatch.setattr(app.client, "finish_run", spy)
        await pilot.press("escape")             # quit early
        await _settle(pilot)
        assert finished.get("ranked") is False


async def test_error_toast_on_load_failure(client, monkeypatch):
    def boom():
        raise RuntimeError("network down")

    app = PaukApp(client)
    async with app.run_test(size=(100, 40)) as pilot:
        monkeypatch.setattr(app.client, "quiz_dirs", boom)
        await pilot.press("enter")              # open picker → load fails
        await _settle(pilot)
        assert isinstance(app.screen, PickerScreen)  # did not crash
        notifications = list(app._notifications)
        assert any(n.severity == "error" for n in notifications)


async def test_repeat_full_deck_is_unranked(client):
    app = PaukApp(client)
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.press("enter")
        await _settle(pilot)
        await pilot.press(*"tuidemo/inner", "enter")
        await _settle(pilot)
        for _ in range(len(app.screen.cards)):
            card = app.screen.cards[app.screen.index]
            if card["type"] == "text":
                await pilot.press(*"x", "enter")
            else:
                await pilot.press("space")
                await pilot.click("#submit")
            await _settle(pilot)
            await pilot.press("enter")
            await _settle(pilot)
        assert isinstance(app.screen, ResultScreen)
        await pilot.press("r")                  # repeat whole deck
        await _settle(pilot)
        assert isinstance(app.screen, QuizScreen)
        assert app.screen.ranked is False


async def test_settings_default_questions(client, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg2"))
    from importlib import reload

    from pauk import config as config_mod
    reload(config_mod)
    app = PaukApp(client)
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.press("down", "down", "enter")   # Settings
        assert isinstance(app.screen, SettingsScreen)
        inp = app.screen.query_one("#default-n")
        inp.focus()
        await pilot.pause()
        await pilot.press("backspace", "backspace", "5", "0", "enter")
        assert config_mod.get("default_questions") == 50
    reload(config_mod)


class FakeProvider:
    """Deterministic provider for quest tests — no real LLM."""
    name = "fake"

    def chat(self, system, messages):
        return "Prego! (fake reply)"

    def judge(self, criteria, transcript):
        # succeed iff the user ever said the magic word
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
        await pilot.press("enter")                      # picker
        await _settle(pilot)
        await pilot.press(*"questdemo", "enter")        # start the deck
        await _settle(pilot)
        # a quest deck launches the QuestScreen
        assert isinstance(app.screen, QuestScreen)
        # send a winning message
        inp = app.screen.query_one("#quest-input")
        inp.focus()
        await pilot.press(*"vorrei due cornetti", "enter")
        await _settle(pilot)
        assert len(app.screen.messages) == 2            # user + assistant
        await pilot.press("f2")                         # finish → judge
        await _settle(pilot)
        assert app.screen.finished
        log = str(app.screen.query_one("#quest-log").render())
        assert "succeeded" in log


async def test_quest_give_up_counts_as_wrong(server, tmp_path):
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
        await pilot.press(*"questgiveup", "enter")
        await _settle(pilot)
        assert isinstance(app.screen, QuestScreen)
        await pilot.press("escape")                     # give up immediately
        await _settle(pilot)
        # back in the quiz, which finishes (only card) → ResultScreen
        assert isinstance(app.screen, ResultScreen)


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
        await pilot.press(*"routedemo", "enter")
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
