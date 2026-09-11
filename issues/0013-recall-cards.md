---
status: done
kind: feature
---

# Recall card type (self-graded free recall)

The PhD-defense decks (content/phd-*.json) need questions whose answers are several sentences of prose.
No string matcher can grade those, so a sixth card type `recall` stores a reference `answer_md`; the client reveals it after the learner has thought or typed an attempt, and the learner judges themselves right or wrong.
The verdict goes to `POST /cards/{id}/self-grade` and is logged to `reviews`, so recall feeds the weighted selection and the deck performance metric like any other type.
No highscore.

2026-09-11 (API 0.9.0 / CLI 0.16.0): Done.
Migration 007 (`recall_cards` table, enum extension), Cards repo + self-grade endpoint, docs/api.md spec, importer/clone/upload support (`answer_md` in frontmatter), TUI RecallScreen (Enter reveals, y/n or buttons grade, Escape before grading exits the quiz), integration + e2e + Pilot tests.
Started as an agent WIP branch whose RecallScreen Pilot test hung: dismissing from inside the worker's call_from_thread pops the screen and cancels the very worker that is blocked waiting; deferring via call_after_refresh never fired headless.
Fixed by having the worker post a Message that the main thread handles by dismissing.
The six PhD decks used `PhD/...` directory names, which the API rejects (`^[a-z0-9-]+$`); renamed to `phd/...`.
A new e2e test imports every content/*.json on its own database so this cannot regress silently.
Not updated: docs/handbook.html still describes five card types and 14 tables.
