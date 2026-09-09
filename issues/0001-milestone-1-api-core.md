---
status: done
kind: task
---

# Milestone 1: API core

Implement the API per docs/api.md, minus media:

- project scaffolding (Slim 4, PSR-4, PHPUnit, Makefile)
- local MariaDB tooling (make setup/db-start/db-stop)
- migrations + runner
- bearer-token auth + token creation script
- endpoints: health, cards CRUD, answer/grading, dirs
  (DAG: CRUD, resolve, link/unlink, cycle rejection)
- grading logic with exhaustive unit tests
- integration tests for every endpoint
- CI workflow (mariadb:11.8 service container)
- deploy scripts (make deploy, rollback, smoke test) and the
  first production deploy

Acceptance: `make test` green locally, CI green,
`curl https://pauk.aao756.de/api/v1/health` returns ok, one
card creatable and answerable via curl with a real token.

2026-09-09: Done. Deployed as 0.1.0 to
https://pauk.aao756.de. IONOS quirks worth remembering:
per-directory mod_rewrite 500s (FallbackResource used
instead), CGI PHP drops the Authorization header (SetEnvIf +
REDIRECT_ promotion in the front controller), and recursive
CTE anchors need CAST or the CTE column is typed as a short
string.
