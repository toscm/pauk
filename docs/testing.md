# Testing

Principle: everything runs locally, fast, against throwaway
SQLite databases. The production system is never part of a
test run; the only test that touches it is the read-only
post-deploy smoke check.

## Levels

1. PHP unit tests (PHPUnit, `api/tests/unit/`)

   Pure logic, no I/O: answer normalization, Levenshtein
   grading, path/tag validation, cursor encoding. This is
   where the grading rules from docs/api.md are pinned down
   case by case (umlauts, punctuation, typo threshold ...).

2. API integration tests (PHPUnit, `api/tests/integration/`)

   Full HTTP request → response cycle against the real app
   with a fresh SQLite DB per test class (migrations run in
   setUp). Requests go through Slim's request handler
   in-process, so no server process is needed. Covers every
   endpoint, auth, validation errors, pagination.

3. End-to-end CLI tests (pytest, `cli/tests/`)

   A pytest fixture starts the real API once per session:
   PHP built-in server on a random port, SQLite DB in a temp
   directory, a token seeded into it. Tests then invoke the
   CLI with `PAUK_SERVER`/`PAUK_TOKEN` pointing at that
   server and assert on output and server state. This
   exercises exactly what a user runs, including quiz flows
   (with piped stdin answers).

4. MariaDB parity (CI only)

   GitHub Actions runs levels 1–2 twice: once on SQLite,
   once against a `mariadb:11.8` service container. This
   catches dialect drift that SQLite alone would hide. Not
   runnable locally (no Docker here) — that is acceptable;
   CI is mandatory before deploys anyway.

5. Post-deploy smoke test

   `make deploy` ends with `GET /health` on the live URL and
   fails loudly if the response is not `{"status":"ok",
   "db":"ok", ...}` with the just-deployed version.

## Invocation

- `make test` — levels 1–3 (the deploy gate locally)
- `make test-php` / `make test-cli` — subsets
- CI runs levels 1–4 on every push

## Rules

- New endpoint or CLI command → integration/e2e test in the
  same commit.
- Bug fix → regression test first.
- Tests must not depend on network access or on each other.
