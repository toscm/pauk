---
status: in-progress
kind: task
---

# Milestone 2: CLI client

Python CLI (`pauk`) per docs/development.md:

- config resolution: flags > env > ~/.config/pauk/config.toml
- interactive start menu when run without arguments:
  1. Start a new quiz (pick a directory, then quiz its
     cards, transitively including subdirectories)
  2. Organize questions (browse dirs, add/edit/move/link)
  3. Configure settings
  4. Exit
- every menu action also exists as a direct subcommand:
  config, add, edit ($EDITOR round-trip), ls (--tree), link,
  unlink, rm, quiz
- quiz mode: filters (--dir, --recursive, -n), markdown
  rendering via rich, graded results
- import/export as markdown files with frontmatter
- pytest e2e suite against a locally spawned API (see
  docs/testing.md level 3)

Acceptance: full create → quiz → export → reimport cycle
works against the local test server and against production.

2026-09-09: Implemented and e2e-tested: menu (quiz path),
quiz, ls/--tree, add, rm, import, config, health; plus
mkdir (added beyond the original spec, replacing the
spec's implicit dir creation). Greek + italian content
imported to production through the CLI. Still missing
from the body spec: edit ($EDITOR round-trip), export,
link/unlink, moving cards/dirs, and a real 'Organize
questions' menu (currently a stub that lists the
subcommands).

2026-09-09 (v0.2.0): Added fuzzy quiz picker sorted by
favorites (started runs), stats subcommand, login (hidden
token prompt), update (git pull + reinstall), --version,
readline line editing, plain no-box quiz output with one-time
header and end-of-run top-3 ranking (trophy on a podium
place). pauk is now a toscpm-tracked tool (toscpm v1.24.0).
Unchanged from the missing list: edit, export, link/unlink,
moving cards/dirs, real organize menu.

2026-09-09 (v0.3.0): Interactive picker with two views —
favorites (most-started decks first, type-to-filter) and a
collapsible directory tree (arrow keys: right enters, left
leaves; view/expansion state survives a quiz). Repeat options
after each run (r = all, w = only wrong answers). Plain Click
help and plain ls --tree: no box-drawing characters anywhere
(e2e-enforced). pauk stats now shows the top 5 decks by runs;
hardest cards behind --cards N.

2026-09-09 (v0.4.0/v0.5.0): bare `pauk` is now a full-screen
Textual app (home, deck picker with favorites+tree, quiz with
inline images, results with repeat/repeat-wrong). The old
line-based menu and picker were removed. media subcommands
added. Still open from the body spec: edit ($EDITOR), export,
link/unlink, moving cards/dirs.

2026-09-09 (v0.7.0): match card type added (pronoun→verb-form
mappings, rendered as one pick per left); quit-early runs now
unranked; answer/finish moved to worker threads; UI minimalism
pass (status bars carry only non-obvious keys). Italian
conjugations (24 verbs) and German match/facts content
imported. Still open: edit ($EDITOR), export, link/unlink.
