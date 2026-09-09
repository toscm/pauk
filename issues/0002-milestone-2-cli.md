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
