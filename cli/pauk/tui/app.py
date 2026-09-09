"""The pauk full-screen application (Textual)."""

from __future__ import annotations

import io

from textual.app import App

from pauk.client import Client
from pauk.tui.screens import HomeScreen


class PaukApp(App):
    """Full-screen game-style UI. The typer subcommands remain the
    scripting interface; this app is what bare `pauk` launches."""

    TITLE = "pauk"
    CSS_PATH = "pauk.tcss"

    def __init__(self, client: Client, provider=None):
        super().__init__()
        self.client = client
        self._image_cache: dict[str, object] = {}
        # the quest LLM provider; lazily built from the machine unless
        # injected (tests pass a fake)
        self._provider = provider

    @property
    def provider(self):
        if self._provider is None:
            from pauk.llm.provider import default_provider

            self._provider = default_provider()
        return self._provider

    def on_mount(self) -> None:
        self.push_screen(HomeScreen())

    def image_for(self, url: str):
        """A decoded PIL image for a media URL, cached so repeating a
        quiz (or re-showing a card) never re-downloads or re-decodes."""
        if url not in self._image_cache:
            from PIL import Image as PILImage

            data = self.client.get_bytes(url)
            image = PILImage.open(io.BytesIO(data))
            image.load()
            self._image_cache[url] = image
        return self._image_cache[url]


def run_tui(client: Client) -> None:
    try:
        PaukApp(client).run()
    finally:
        client.close()
