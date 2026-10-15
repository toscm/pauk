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

## This repository is PUBLIC — no sensitive data

`github.com/toscm/pauk` is a public repository.
Everything committed here, including the full git history of every branch, is readable by anyone and stays so: deleting a file later does not unpublish it, and removing it properly means rewriting history and rotating whatever leaked.
So before every commit, check the diff (and every new file) against this list.

Never commit:

- Unpublished research: unpublished data, results, figures, gene lists, screen details, manuscripts or manuscript methods, and the design or results of projects that are not yet published.
  A deck or items file written from such sources (a private repo's README, a manuscript draft, lab notes, meeting notes) is private, even if most of its facts are textbook knowledge.

- Information about people: colleagues, collaborators, supervisors, patients, study participants; who works on what, who is responsible for what, personal assessments.

- Internal project or employer information: funding applications and their review outcomes, grant plans, budgets, organisational details of research programmes.

- Credentials and private infrastructure: tokens, passwords, keys, `.env` / `pauk.env` contents, and database dumps, backups or `pauk export` files (they hold the whole collection, private cards included).

- The user's own learning data: tutor session transcripts, problem reports with their context, knowledge-profile exports.

Private knowledge cards belong in a private file outside this repo, next to the project they are about (convention: `~/projects/<project>/pauk-cards/`), and are imported from there with `pauk import`; afterwards they live only in the database.
`content/` is for published, public knowledge only (textbooks, published papers, public datasets, languages, geography).
Commit messages, `issues/` files and docs are public too: do not describe private content there beyond "a private file outside the repo".

If it is unclear whether something is publishable, do not commit it: keep it in the private file and ask the user.

## Rules

- Design principle: as simple as possible, follow mainstream
  conventions wherever one exists (naming, layout, tooling).

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
