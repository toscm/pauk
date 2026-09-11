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
        # the real purpose of this test is to confirm the app starts
        # and renders its screens on a real terminal (catching bugs
        # like an attribute shadowing a framework internal); the
        # detailed navigation is covered by the headless Pilot tests
        child.expect("Start a quiz")
        child.send("\r")                    # open the picker (tree view by default)
        child.send("\t")                    # Tab: switch to the favorites view
        child.expect("all cards")           # picker rendered on a real tty
        child.send("\x1b")                  # Esc: back to home
        child.expect("Statistics")
        child.send("q")                     # quit binding
        child.expect(pexpect.EOF)
    finally:
        child.close(force=True)
    assert child.exitstatus in (0, None)
