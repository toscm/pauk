# Testing

Principle: everything runs locally, fast, against throwaway
local MariaDB instances. The production system is never part
of a test run; the only test that touches it is the
read-only post-deploy smoke check.

## Levels

1. PHP unit tests (PHPUnit, `api/tests/unit/`)

   Pure logic, no I/O: answer normalization, Levenshtein
   grading, name/path validation, cursor encoding, cycle
   detection. This is where the grading rules from
   docs/api.md are pinned down case by case (umlauts,
   punctuation, typo threshold ...).

2. API integration tests (PHPUnit, `api/tests/integration/`)

   Full HTTP request → response cycle against the real app.
   A scratch MariaDB instance is booted once per test run
   (throwaway datadir under `api/var/`, random port); each
   test class gets a freshly created database with
   migrations applied. Requests go through Slim's request
   handler in-process, so no web server process is needed.
   Covers every endpoint, auth, validation errors, DAG edge
   cases, pagination.

   To keep startup cheap, the harness initializes one datadir
   template on first use and copies it per run instead of
   re-running mariadb-install-db every time.

3. End-to-end CLI tests (pytest, `cli/tests/`)

   A pytest fixture starts the real stack once per session:
   scratch MariaDB plus the API on the PHP built-in server
   (random port), with a token seeded into the database.
   Tests then invoke the CLI with `PAUK_SERVER`/`PAUK_TOKEN`
   pointing at that server and assert on output and server
   state. This exercises exactly what a user runs, including
   the interactive menu and quiz flows (with piped stdin).

4. CI (GitHub Actions)

   Runs levels 1–3 on every push, using a `mariadb:11.8`
   service container instead of the tarball install. Same
   engine, same version as production.

5. Post-deploy smoke test

   `make deploy` ends with `GET /health` on the live URL and
   fails loudly if the response is not `{"status":"ok",
   "db":"ok", ...}` with the just-deployed version.

## Invocation

- `make test` — levels 1–3 (the deploy gate locally)
- `make test-php` / `make test-cli` — subsets

## Rules

- New endpoint or CLI command → integration/e2e test in the
  same commit.
- Bug fix → regression test first.
- Tests must not depend on network access or on each other.
