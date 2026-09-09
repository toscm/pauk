"""Real-terminal smoke test: the Textual app on a pseudo-terminal
via pexpect. Headless Pilot tests cover the logic; this guards
the one thing they cannot — that the app actually starts, renders,
and navigates on a real tty."""

from __future__ import annotations

import sys

import pexpect

from conftest import REPO, run_cli


def test_tui_starts_and_navigates_on_real_pty(cli_env):
    assert run_cli(cli_env, "import", str(REPO / "content" / "greek.json")).returncode == 0

    env = dict(cli_env)
    env["TERM"] = "xterm-256color"
    child = pexpect.spawn(
        sys.executable, ["-m", "pauk"],
        env=env, cwd=str(REPO), encoding="utf-8",
        dimensions=(40, 120), timeout=30,
    )
    try:
        child.expect("Start a quiz")
        child.send("\r")                    # open the picker
        child.expect("Favorites")
        child.expect("all cards")
        child.send("\x1bOQ")                # F2: tree view (SS3 code)
        child.send("\x1b[12~")              # F2 fallback (CSI code)
        child.expect("greek")
        child.send("\x1b")                  # Esc: back to home
        child.expect("Statistics")
        child.send("q")                     # quit binding
        child.expect(pexpect.EOF)
    finally:
        child.close(force=True)
    assert child.exitstatus in (0, None)
