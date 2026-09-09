"""Headless TUI tests: Textual Pilot driving the real app
against the real test API (same server fixture as the e2e
suite)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pauk.client import Client
from pauk.importer import import_file
from pauk.tui.app import PaukApp
from pauk.tui.screens import (
    HomeScreen,
    PickerScreen,
    QuizScreen,
    ResultScreen,
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
        ],
    }
    path = tmp_path / "tui.json"
    path.write_text(json.dumps(sample))
    import_file(client, path, echo=lambda *_: None)
    return client


async def test_home_menu_and_stats(client):
    app = PaukApp(client)
    async with app.run_test(size=(100, 40)) as pilot:
        assert isinstance(app.screen, HomeScreen)
        # second entry: Statistics
        await pilot.press("down", "enter")
        assert isinstance(app.screen, StatsScreen)
        assert "Statistics" in str(app.screen.query_one("#stats-text").render())
        await pilot.press("escape")
        assert isinstance(app.screen, HomeScreen)


async def test_tree_navigation_and_full_quiz(client):
    app = PaukApp(client)
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.press("enter")                  # Start a quiz
        assert isinstance(app.screen, PickerScreen)
        await pilot.press("f2")                     # tree view
        tree = app.screen.query_one("#deck-tree")
        await pilot.pause()
        # cursor onto the tuidemo deck (position varies with other
        # seeded decks), enter it with Right
        node = next(
            n for n in tree.root.children
            if n.data and n.data["path"] == "tuidemo"
        )
        tree.move_cursor(node)
        assert not node.is_expanded
        await pilot.press("right")
        assert node.is_expanded
        assert "tuidemo" in app.picker_memory["expanded"]
        # move onto the child and start it
        await pilot.press("down", "enter")
        # count dialog: replace default with 2
        await pilot.press("backspace", "backspace", "2", "enter")
        assert isinstance(app.screen, QuizScreen)
        assert app.screen.deck_title == "tuidemo/inner"
        assert len(app.screen.cards) == 2

        # answer both cards (text: wrong on purpose; mc: pick first)
        for _ in range(2):
            card = app.screen.cards[app.screen.index]
            if card["type"] == "text":
                await pilot.press(*"zzz", "enter")
            else:
                await pilot.press("space")           # toggle first option
                await pilot.click("#submit")
            await pilot.pause()
            assert app.screen.in_feedback
            await pilot.press("enter")               # Continue button
            await pilot.pause()

        assert isinstance(app.screen, ResultScreen)
        text = str(app.screen.query_one("#result-text").render())
        assert "Result:" in text
        assert "Top runs:" in text

        # back to the picker: expansion state survived
        await pilot.press("escape")
        assert isinstance(app.screen, PickerScreen)
        assert "tuidemo" in app.picker_memory["expanded"]
        tree = app.screen.query_one("#deck-tree")
        assert any(
            node.data and node.data["path"] == "tuidemo" and node.is_expanded
            for node in tree.root.children
        )


async def test_favorites_filter_and_repeat_wrong(client):
    app = PaukApp(client)
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.press("enter")                  # picker, favorites tab
        assert isinstance(app.screen, PickerScreen)
        await pilot.press(*"tuidemo/inner", "enter")  # filter + top match
        await pilot.press("backspace", "backspace", "1", "enter")
        assert isinstance(app.screen, QuizScreen)

        # answer wrong to unlock "repeat wrong"
        card = app.screen.cards[0]
        if card["type"] == "text":
            await pilot.press(*"wrong", "enter")
        else:
            await pilot.click("#submit")            # nothing selected = wrong
        await pilot.pause()
        await pilot.press("enter")                  # Continue -> finish
        await pilot.pause()
        assert isinstance(app.screen, ResultScreen)
        assert app.screen.wrong_cards

        # repeat only the wrong card
        await pilot.click("#repeat-wrong")
        await pilot.pause()
        assert isinstance(app.screen, QuizScreen)
        assert len(app.screen.cards) == 1
        await pilot.press("escape")                 # end early -> picker
        await pilot.pause()
        assert isinstance(app.screen, PickerScreen)
        # filter text survived the quiz
        assert app.picker_memory["filter"] == "tuidemo/inner"
