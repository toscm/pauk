"""Real-terminal regression test: drives the actual pauk binary
on a pseudo-terminal via pexpect, so key handling is exercised
the way a terminal delivers it (whole escape sequences in one
chunk) — the piped-input path cannot catch that class of bug."""

from __future__ import annotations

import sys

import pexpect

from conftest import REPO, run_cli


def test_arrow_keys_on_real_pty(cli_env):
    # idempotent: guarantees at least one deck with cards exists
    assert run_cli(cli_env, "import", str(REPO / "content" / "greek.json")).returncode == 0

    child = pexpect.spawn(
        sys.executable, ["-m", "pauk"],
        env=cli_env, cwd=str(REPO), encoding="utf-8",
        dimensions=(40, 160), timeout=30,
    )
    try:
        child.expect("what do you want")
        child.sendline("1")
        child.expect("favorites first")
        child.send("\t")                    # tree view
        child.expect("directory tree")
        child.send("\x1b[C")                # Right: expand first deck
        child.expect(r"- \w+")              # expanded marker appears
        child.send("\x1b[B")                # Down: move into children
        child.send("\x1b[D")                # Left: collapse again
        child.expect(r"\+ \w+")
        child.send("\x1b")                  # lone Esc: back to menu
        child.expect("Exit")
        child.sendline("4")
        child.expect(pexpect.EOF)
    finally:
        child.close(force=True)
    assert child.exitstatus == 0
