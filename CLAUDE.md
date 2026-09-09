# CLAUDE.md

pauk is a flashcard app: an HTTP API (PHP 8.4 + MariaDB on
IONOS shared hosting) with thin clients (CLI first, web and
mobile later). Read `README.md` for the repo layout.

## Documentation map

- `docs/architecture.md` — components, data model, decisions
- `docs/api.md` — the HTTP API specification (the contract)
- `docs/development.md` — local toolchain and dev workflow
- `docs/testing.md` — test levels and how to run them
- `docs/deployment.md` — deploy process and backup strategy
- `issues/` — issue tracking as markdown files (see
  `issues/README.md` for the convention)

## Rules

- The API spec in `docs/api.md` is the contract. Change the
  spec first, then the implementation, then the clients.

- All development and testing happens locally against
  scratch MariaDB instances (user-space install, same engine
  and version as production); the live IONOS database is
  never used for tests. See `docs/testing.md`.

- Deploy only via `make deploy`, which runs the full test
  suite first and aborts if anything is red. Never rsync to
  the server manually.

- Track work in `issues/`: one markdown file per issue,
  updated in the same commit as the code that addresses it.

- Architecture decisions of lasting relevance go into
  `docs/architecture.md` under "Decisions", not into commit
  messages alone.

## Server facts

- SSH: `ssh ionos` (alias in `~/.ssh/config`)
- Docroot: `~/web/pauk` on the server → https://pauk.aao756.de
- DB credentials: `~/pauk.env` on the server (never committed)
- Database: MariaDB 11.8, `dbs16106557` at
  `db5021384667.hosting-data.io` (reachable only from the
  webspace or through an SSH tunnel)
- Web PHP is 8.4; CLI PHP on the server is `php8.4-cli`
