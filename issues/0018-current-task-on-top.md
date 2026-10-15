---
status: done
kind: feature
---

# The current task stays on top

Feedback from the user (2026-10-15): scrolling to follow the conversation is tiresome; the current task should always be at the top of the screen, as the only task, and older tasks should be reachable from the side panel.

2026-10-15: Done.
The browser has a task pane above the chat (`#task-pane`); exercises, drills and activities render there instead of inline, one at a time, the newest by default.
The chat below scrolls on its own and keeps a one-line link per task ("Task 3: ...").
The side panel lists all tasks of the session with open ones marked; clicking one shows it in the pane with "older task" and a button back to the current one, and a new task always replaces whatever is shown.
An older open exercise can still be answered from the pane.
On narrow screens the chat column is one screen high with the same split; the side panel follows below.
Checked in Edge against `pauk tutor --fake` (text, mc, map labelling, reload, phone width).
