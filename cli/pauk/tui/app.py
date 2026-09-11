"""The pauk full-screen application (Textual)."""

from __future__ import annotations

import io
import os

from textual.app import App

from pauk import config
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
        self._image_cls = None
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

    def image_widget_class(self):
        """The Textual widget class used to draw card images.

        Sixel and kitty give crisp images but need terminal support,
        and inside tmux they also need passthrough enabled. "auto"
        therefore drops to the half-block renderer under tmux (which
        works in any 256-color terminal) unless passthrough is turned
        on. A fixed renderer can be forced via config or
        PAUK_IMAGE_MODE."""
        if self._image_cls is not None:
            return self._image_cls
        from textual_image.widget import (
            AutoImage, HalfcellImage, SixelImage, TGPImage, UnicodeImage,
        )

        mode = os.environ.get("PAUK_IMAGE_MODE") or config.get("image_mode") or "auto"
        forced = {
            "halfcell": HalfcellImage, "sixel": SixelImage,
            "tgp": TGPImage, "unicode": UnicodeImage,
        }.get(mode)
        if forced is not None:
            self._image_cls = forced
        elif os.environ.get("TMUX") and not config.get("tmux_image_passthrough"):
            self._image_cls = HalfcellImage
        else:
            self._image_cls = AutoImage
        return self._image_cls

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
    # fire health + the picker's data in the background before the UI
    # starts, so the first screen isn't waiting on a cold connection
    client.prewarm()
    try:
        PaukApp(client).run()
    finally:
        client.close()
