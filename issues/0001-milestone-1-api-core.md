---
status: open
kind: task
---

# Milestone 1: API core

Implement the API per docs/api.md, minus media:

- project scaffolding (Slim 4, PSR-4, PHPUnit, Makefile)
- migrations + runner (SQLite/MariaDB variants where needed)
- bearer-token auth + token creation script
- endpoints: health, cards CRUD, answer/grading, paths, tags
- grading logic with exhaustive unit tests
- integration tests for every endpoint
- CI workflow (SQLite + MariaDB parity)
- deploy scripts (make deploy, rollback, smoke test) and the
  first production deploy

Acceptance: `make test` green locally, CI green,
`curl https://pauk.aao756.de/api/v1/health` returns ok, one
card creatable and answerable via curl with a real token.
