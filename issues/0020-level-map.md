---
status: done
kind: feature
---

# Level map: courses with stages, units and stars

Wish of the user (2026-10-15): the start screen should feel like a game in which you play through levels, e.g. Italian as A1, A2, B1, B2 … with many sublevels; the map shows which levels are passed (how well they are known), and a level is chosen together with the kind of exercise.

Decisions (asked 2026-10-15):

- All units stay playable; the next recommended one is highlighted (no locking).

- A1 and A2 have fixed item lists (A1 from the existing 227 items, A2 new); from B1 on, units have a topic and a goal and the teacher builds the items with the learner.

- Stars come from the memory model automatically, and an exam can pass a unit directly.

2026-10-15: Done (API 0.14.0, CLI 0.22.0), see docs/tutor.md 9.6.

- `content/curricula/italian.json`: 6 stages, 18 A1 units, 12 A2 units (179 new items in `items-italian-a2.json`), 34 B1–C2 units without items.

- One directory per unit (`italian/course/<stage>/<unit>`), created and filled by `pauk import` of the curriculum; `GET /profile/dirs` gives the progress of all units in one request.

- Start screen: a tab per course with the level map (stage sections, unit tiles with stars, progress bar, "next", "refresh", "game" badges) and a unit dialog with goal, counts and the modes learn, review, mixed, conversation, game and exam; the free subject picker is the second tab.

- Exam mode lifts the new-item budget; a first correct answer counts as "learning", so 80 % in an exam gives ★★ without a stored score.

- Units without items let the teacher create items directly into the unit.

Also in this change, on the user's request: memory aids (`attrs.mnemonic`, `attrs.anecdote`) on the Italian, Greek, PhD and Germany items, shown on item cards and used by the teacher, and `attrs.aliases` imported as searchable aliases (`aliases` in `PUT /items/bulk`).
