---
status: done
kind: feature
---

# Spaced repetition

The reviews log exists from milestone 1. Build scheduling on
top: Leitner boxes first (simple, explainable), SM-2 later if
wanted. New endpoint for "due cards"; quiz mode gains a
--due filter. Design to be specced in docs/api.md before
implementation.

2026-10-14: Superseded by the knowledge profile (issues/0014).
Scheduling lives on items, not cards: the memory model `pauk-mm@1` (docs/tutor.md 4.6) derives each item's recall probability from the interaction log, and `GET /profile/next` returns what is due.
Linked cards feed it (every answer of a linked card is an interaction), and the tutor uses it to choose what to practise.
The TUI keeps its weighted card selection (issues/0015).
