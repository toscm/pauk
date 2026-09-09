---
status: open
kind: task
---

# Milestone 2: CLI client

Python CLI (`pauk`) per docs/development.md:

- config resolution: flags > env > ~/.config/pauk/config.toml
- commands: config, add, edit ($EDITOR round-trip), ls
  (--tree), mv, rm, tag
- quiz mode: interactive session with filters (--path, --tag,
  -n), markdown rendering via rich, graded results
- import/export as markdown files with frontmatter
- pytest e2e suite against a locally spawned API (see
  docs/testing.md level 3)

Acceptance: full create → quiz → export → reimport cycle
works against the local test server and against production.
