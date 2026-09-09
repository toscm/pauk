---
status: open
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
