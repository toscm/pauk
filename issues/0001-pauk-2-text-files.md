---
status: in-progress
kind: feature
---

# pauk 2: text files, a local web app, no database

Goal (2026-10-29): move pauk off the hosted PHP API onto the learner's own machine.
Knowledge and learning data become plain text files that can be edited, reviewed and versioned locally; a small web app on a machine in the LAN serves the learners' devices; the teacher calls the Claude API with a per-user budget.
Sync between devices is explicitly the lowest priority.

Decisions (details in docs/architecture.md and docs/files.md):

- Knowledge: YAML decks and Markdown items in source folders (the user's own, usually private repositories); identity is `space/key`; the file path is the subject.

- Learning data: an append-only JSON-lines log per user and month; states are recomputed from it.
  Edit rules instead of versions: keys keep their meaning, renames and merges go through `aliases`.

- TypeScript on Node.js, no build step, no framework; the target was under 5,000 lines (pauk 1's client alone has about 18,000).

- The teacher is a tool-use loop over the Messages API; every call is logged (`pauk debug`).

2026-10-29: First version on branch `v2`, in `app/` (about 1,700 lines plus tests).

- Done: knowledge loader and `pauk check`, learning log and replay, memory model pauk-mm@1 and grading ported unchanged (the PHP unit cases pass), practice without a teacher, the Claude teacher with debug log and budgets, login for several users, the browser app, and a pauk deck about pauk itself (`app/knowledge/pauk/`).

- Done later: the start page is a search field (a command palette over subject paths, matched letters marked; favorites and recently used subjects first, suggested before anything is typed) and a Browse tab that shows the subject folders in learning order, as folders that fill with green as their items become known; number prefixes in file and folder names give that order; settings moved to their own tab.

- Done later: Browse is the only page; the search field moved into the top bar; the items of a subject show as its files (a short name, coloured by how well each is known, details on click).

- Done later: `pauk service install` runs pauk as a launchd login service with a menu bar item (status, addresses, restart, Ctrl+Option+Cmd+P).

- Not yet: courses and the level map, activities (town, maps, routes), quests, item merges proposed by the teacher, the profile page, i18n of the UI (English only), sync, log compaction.

- Done later: practice text fields accept typing again (an inline key handler returned false and so cancelled every key); admins can edit items, add items and start folders in the browser (`app/src/edit.ts`).

2026-11-05: pauk 2 replaces pauk 1.
The PHP API, the Python CLI and the IONOS deployment were removed (the hosted site and its database are gone), the knowledge decks moved to a private repository, and the repository history restarted with pauk 2 as its initial version; earlier issues described pauk 1 and were dropped with it.
