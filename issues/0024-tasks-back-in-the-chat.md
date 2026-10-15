---
status: done
kind: feature
---

# Tasks back in the chat, wider chat

Feedback from the user (2026-10-15) on issues/0018: the task pane on top is worse, especially with a long explanation before the task.
Tasks should stay at the bottom of the screen, and the chat should be wider, configurable, by default from the left edge to the side panel.

2026-10-15: Done.
Exercises, drills and activities render inline in the chat again; the newest one is at the bottom and gets the focus.
The side panel keeps the task list from issues/0018; a click scrolls to the task and marks it briefly.
The chat width is a per-device setting (full by default, wide, narrow) in the settings dialog, stored in `localStorage` (`pauk.width`) and shown in the side panel's configuration.
Checked in Edge against `pauk tutor --fake` (text, mc, map labelling, width change and reload, phone width).
