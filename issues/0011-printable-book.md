---
status: done
kind: task
---

# Printable architecture book

A single printable document (HTML artifact or PDF-ready) that
explains the whole system so someone could learn pauk from it:

- the data model: every table, column, type, and relationship,
  with the DAG and leaderboard design explained
- the IONOS deployment: shared hosting, the docroot stub,
  Apache quirks, the managed MariaDB, backups
- the three (soon four) card types with example questions and
  a worked task/quest
- CLI walkthrough with example "screenshots" of the menu, the
  deck picker, a quiz, a conversation
- API reference with runnable curl examples per endpoint

Build after the LLM/quest work so the book can cover tasks too.

2026-09-09 (iteration 5): Done. Built as a printable HTML
handbook (Artifact) with six chapters: overview, the data
model (all 14 tables with columns/types + the DAG/leaderboard
design), the five card types with real examples, IONOS
deployment (docroot stub, Apache quirks, backups), a CLI
walkthrough with terminal "screenshots" (menu, picker, quiz,
quest, route), and a curl API reference. Source saved at
docs/handbook.html; print CSS with page breaks and a TOC.
