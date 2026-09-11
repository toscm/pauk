"""E2E fixtures: boot the real API (PHP built-in server) against
the scratch MariaDB the environment points at (started by
scripts/with-testdb.sh or provided by CI), seed a token, and hand
tests a ready environment for driving the actual CLI."""

from __future__ import annotations

import os
import re
import socket
import subprocess
import time
from pathlib import Path

import httpx
import pytest

# Safety net: never let a test download a multi-GB model, even if one
# accidentally builds a real local provider. Tests mock the provider.
os.environ.setdefault("PAUK_NO_MODEL_DOWNLOAD", "1")

REPO = Path(__file__).resolve().parents[2]
PHP = os.environ.get("PAUK_PHP", str(Path.home() / ".local" / "bin" / "php"))


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="session")
def server() -> dict:
    """Start the API on a random port with a fresh database."""
    env = os.environ.copy()
    db_name = "pauk_cli_test"
    env.setdefault("PAUK_DB_HOST", "127.0.0.1")
    env.setdefault("PAUK_DB_PORT", "33068")
    env.setdefault("PAUK_DB_USER", "root")
    env.setdefault("PAUK_DB_PASS", "")
    env["PAUK_DB_NAME"] = db_name

    def php(code: str) -> str:
        return subprocess.run(
            [PHP, "-r", code], cwd=REPO / "api", env=env,
            capture_output=True, text=True, check=True,
        ).stdout

    php(
        "$p = new PDO('mysql:host=' . getenv('PAUK_DB_HOST') . ';port='"
        " . getenv('PAUK_DB_PORT'), getenv('PAUK_DB_USER'), getenv('PAUK_DB_PASS'));"
        f"$p->exec('DROP DATABASE IF EXISTS {db_name}');"
        f"$p->exec('CREATE DATABASE {db_name} CHARACTER SET utf8mb4');"
    )
    subprocess.run(
        [PHP, "bin/migrate.php"], cwd=REPO / "api", env=env,
        capture_output=True, text=True, check=True,
    )
    out = subprocess.run(
        [PHP, "bin/create-token.php", "e2e"], cwd=REPO / "api", env=env,
        capture_output=True, text=True, check=True,
    ).stdout
    token = re.search(r"token: ([0-9a-f]+)", out).group(1)

    port = _free_port()
    # media files must land inside public/ so the dev server can
    # serve them statically, exactly as Apache does in production
    env["PAUK_MEDIA_DIR"] = str(REPO / "api" / "public" / "media")
    env["PAUK_BASE_URL"] = f"http://127.0.0.1:{port}"
    proc = subprocess.Popen(
        [PHP, "-S", f"127.0.0.1:{port}", "public/index.php"],
        cwd=REPO / "api", env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            if httpx.get(f"{base}/api/v1/health", timeout=2).status_code == 200:
                break
        except httpx.TransportError:
            time.sleep(0.1)
    else:
        proc.terminate()
        raise RuntimeError("API server did not come up")
    yield {"url": base, "token": token}
    proc.terminate()
    proc.wait(timeout=10)


@pytest.fixture()
def cli_env(server, tmp_path) -> dict:
    """Environment for running the CLI as a subprocess."""
    env = os.environ.copy()
    env["PAUK_SERVER"] = server["url"]
    env["PAUK_TOKEN"] = server["token"]
    env["XDG_CONFIG_HOME"] = str(tmp_path / "config")
    # rich: deterministic, uncolored output
    env["TERM"] = "dumb"
    env["NO_COLOR"] = "1"
    env["COLUMNS"] = "200"
    return env


def run_cli(env: dict, *args: str, input_text: str | None = None):
    import sys

    return subprocess.run(
        [sys.executable, "-m", "pauk", *args],
        env=env, input=input_text, capture_output=True, text=True,
        cwd=REPO, timeout=120,
    )
