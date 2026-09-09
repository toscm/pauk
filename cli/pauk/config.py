"""Server/token resolution: flags > environment > config file."""

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


@dataclass
class Settings:
    server: str | None
    token: str | None


def load(server_flag: str | None = None, token_flag: str | None = None) -> Settings:
    file_server = file_token = None
    if CONFIG_PATH.is_file():
        with open(CONFIG_PATH, "rb") as fh:
            data = tomllib.load(fh)
        file_server = data.get("server")
        file_token = data.get("token")
    return Settings(
        server=server_flag or os.environ.get("PAUK_SERVER") or file_server,
        token=token_flag or os.environ.get("PAUK_TOKEN") or file_token,
    )


def save(server: str, token: str) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    escaped_server = server.replace("\\", "\\\\").replace('"', '\\"')
    escaped_token = token.replace("\\", "\\\\").replace('"', '\\"')
    CONFIG_PATH.write_text(
        f'server = "{escaped_server}"\ntoken = "{escaped_token}"\n',
        encoding="utf-8",
    )
    CONFIG_PATH.chmod(0o600)
