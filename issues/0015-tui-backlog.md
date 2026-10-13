---
status: open
kind: task
---

# TUI frozen, moved to the backlog

The web frontend of the tutor (docs/tutor.md, issues/0014) becomes the primary client: it can render images, maps, math and interactive activities that a terminal cannot.
The Textual TUI keeps working and stays covered by its existing tests, but gets no new features.
With the tutor's phase 3 it moves from `pauk` (no arguments) to `pauk tui`.

Revisit once the web UI covers card quizzes: keep the TUI as an offline / LLM-free mode, or remove it.
