"""Configuration: server/token resolution (flags > env > file)
plus persisted UI preferences."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

CONFIG_PATH = Path(
    os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")
) / "pauk" / "config.toml"

DEFAULTS = {
    "statusbar_position": "bottom",   # "bottom" | "top"
    # how card images are drawn: "auto" picks the best protocol the
    # terminal supports, but inside tmux it falls back to the reliable
    # half-block renderer unless tmux_image_passthrough is turned on
    # (see docs/images.md). Force a specific renderer with "halfcell",
    # "sixel", "tgp" or "unicode". Override per-run with PAUK_IMAGE_MODE.
    "image_mode": "auto",
    "tmux_image_passthrough": False,
}


@dataclass
class Settings:
    server: str | None
    token: str | None


def _read() -> dict:
    if CONFIG_PATH.is_file():
        with open(CONFIG_PATH, "rb") as fh:
            return tomllib.load(fh)
    return {}


def load(server_flag: str | None = None, token_flag: str | None = None) -> Settings:
    data = _read()
    return Settings(
        server=server_flag or os.environ.get("PAUK_SERVER") or data.get("server"),
        token=token_flag or os.environ.get("PAUK_TOKEN") or data.get("token"),
    )


def get(key: str):
    """A UI preference, falling back to its default."""
    return _read().get(key, DEFAULTS.get(key))


def set_value(key: str, value) -> None:
    data = _read()
    data[key] = value
    _write(data)


def save(server: str, token: str) -> None:
    data = _read()
    data["server"] = server
    data["token"] = token
    _write(data)


def _write(data: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for key, value in data.items():
        if isinstance(value, bool):
            lines.append(f"{key} = {'true' if value else 'false'}")
        elif isinstance(value, int):
            lines.append(f"{key} = {value}")
        else:
            escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'{key} = "{escaped}"')
    CONFIG_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    CONFIG_PATH.chmod(0o600)
