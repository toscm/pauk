---
status: done
kind: task
---

# TUI frozen, moved to the backlog

The web frontend of the tutor (docs/tutor.md, issues/0014) becomes the primary client: it can render images, maps, math and interactive activities that a terminal cannot.
The Textual TUI keeps working and stays covered by its existing tests, but gets no new features.
With the tutor's phase 3 it moves from `pauk` (no arguments) to `pauk tui`.

Revisit once the web UI covers card quizzes: keep the TUI as an offline / LLM-free mode, or remove it.

2026-10-14: Decision: keep the TUI, frozen, as the offline, LLM-free mode for card quizzes (`pauk tui`).
It costs nothing to keep (it runs on the same API and stays covered by its tests), and it is the only client that works without a local LLM.
It gets bug fixes, no features; remove it only if it starts to hold back API changes.
