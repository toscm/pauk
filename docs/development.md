# Development

All development happens locally on this machine, offline
from the production server. The live IONOS system is only
touched by `make deploy` and for reading logs.

## Toolchain (no admin rights required)

- PHP 8.4 CLI: a static binary (from static-php.dev, includes
  pdo_sqlite and pdo_mysql) installed to `~/.local/bin/php`.

- Composer: `composer.phar` installed to
  `~/.local/bin/composer`.

- Python ≥ 3.10 with a project venv under `cli/.venv`.

`make setup` installs/verifies all of the above and the
PHP/Python dependencies. Candidate for toscpm registration
once stable.

## Databases

- Local development and tests use SQLite files; PHP's
  pdo_sqlite needs no server process. The API selects its
  database via environment variables:

      PAUK_DB_DRIVER=sqlite  PAUK_DB_PATH=var/dev.sqlite
      PAUK_DB_DRIVER=mysql   PAUK_DB_HOST=... PAUK_DB_NAME=...

- The production MariaDB is reachable for administration
  (migrations, backups, debugging) through an SSH tunnel:

      make tunnel   # ssh -L 33306:db5021384667...:3306 ionos

  Nothing in development or testing depends on it.

## Everyday commands (Makefile)

- `make setup` — install toolchain + dependencies
- `make serve` — run the API on http://127.0.0.1:8080 with a
  fresh dev SQLite DB (PHP built-in server, `api/public/`)
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
