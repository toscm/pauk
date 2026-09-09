# Development

All development happens locally on this machine, offline
from the production server. The live IONOS system is only
touched by `make deploy` and for reading logs.

## Toolchain (no admin rights required)

- PHP 8.4 CLI: a static binary (from static-php.dev,
  includes pdo_mysql) installed to `~/.local/bin/php`.

- Composer: `composer.phar` installed to
  `~/.local/bin/composer`.

- MariaDB 11.8: official binary tarball ("bintar") unpacked
  to `~/.local/mariadb-11.8/`. Runs entirely in user space;
  server and client binaries are addressed by full path from
  the Makefile, nothing global is touched.

- Python ≥ 3.10 with a project venv under `cli/.venv`.

`make setup` installs/verifies all of the above and the
PHP/Python dependencies. Candidate for toscpm registration
once stable.

## Databases

The same engine runs everywhere — MariaDB 11.8 locally, in
CI, and in production — so there are no SQL dialect
concerns (see docs/architecture.md, Decisions).

- Dev instance: `make db-start` boots a local mariadbd with
  datadir `api/var/devdb/`, port 33061, bound to
  127.0.0.1. `make db-stop` shuts it down. First start
  initializes the datadir.

- Tests boot their own scratch instances with throwaway
  datadirs under `api/var/test-*/`; see docs/testing.md.
  They never touch the dev instance.

- The API reads its connection from environment variables:

      PAUK_DB_HOST  PAUK_DB_PORT  PAUK_DB_NAME
      PAUK_DB_USER  PAUK_DB_PASS

- The production MariaDB is reachable for administration
  (backups, debugging) through an SSH tunnel:

      make tunnel   # ssh -L 33306:db5021384667...:3306 ionos

  Nothing in development or testing depends on it.

## Everyday commands (Makefile)

- `make setup` — install toolchain + dependencies
- `make db-start` / `make db-stop` — local dev database
- `make serve` — run the API on http://127.0.0.1:8080
  against the dev database (PHP built-in server,
  `api/public/`)
- `make test` — full suite (see docs/testing.md)
- `make deploy` — test, then deploy (see docs/deployment.md)
- `make tunnel` — SSH tunnel to the production DB

## CLI against arbitrary servers

The CLI resolves its server and token in this order:

1. `--server` / `--token` command-line flags
2. `PAUK_SERVER` / `PAUK_TOKEN` environment variables
3. `~/.config/pauk/config.toml`

Tests set the environment variables to point at the local
test server; humans normally use the config file.

## Workflow

1. Pick or create an issue in `issues/`.
2. Spec change first if the contract is affected
   (`docs/api.md`).
3. Implement + tests. `make test` must be green.
4. Update the issue file, commit, push.
5. `make deploy` when a deployable increment is ready.
