"""The pauk full-screen application (Textual)."""

from __future__ import annotations

from textual.app import App

from pauk.client import Client
from pauk.tui.screens import HomeScreen, PickerScreen


class PaukApp(App):
    """Full-screen game-style UI. The typer subcommands remain the
    scripting interface; this app is what bare `pauk` launches."""

    TITLE = "pauk"
    CSS_PATH = "pauk.tcss"

    def __init__(self, client: Client):
        super().__init__()
        self.client = client
        # one picker for the whole session, so view mode, tree
        # expansion, and filter survive quiz runs by construction
        self.picker_screen = PickerScreen()

    def on_mount(self) -> None:
        self.push_screen(HomeScreen())


def run_tui(client: Client) -> None:
    PaukApp(client).run()
