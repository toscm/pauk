# pauk

Flashcard app ("Karteikarten") with an HTTP API as the single
source of truth and thin clients on top of it.

Questions are written in Markdown (images/videos via the usual
`![name](url)` syntax) and organized into directories that form
a DAG: a question can live in several directories, and
directories can contain other directories (a "core verbs" quiz
can be both standalone and part of "all verbs"). Supported card
types: multiple choice and free text (with normalized,
typo-tolerant answer matching done server-side).

## Layout

This is a monorepo. Components are named by role, not by
implementation language:

- `spec/` — OpenAPI specification: the contract all clients
  are built against.

- `api/` — the HTTP API server. Currently PHP 8.4 + MariaDB,
  because it deploys onto plain IONOS shared webhosting. The
  language is an implementation detail behind the spec and may
  change; the contract in `spec/` is what stays.

- `cli/` — command-line client (Python).

- `web/` — web interface (later; a static SPA talking to the
  API).

Mobile clients start as a PWA built from `web/`. If a native
app with its own heavy toolchain ever materializes, it gets
its own repo (`pauk-android`, named by platform — again not by
language).

## Hosting

- API + media: https://pauk.aao756.de (IONOS webspace,
  directory `web/pauk`, deployed via rsync over SSH).
- Database: managed IONOS MariaDB, reachable from the webspace
  (and via SSH tunnel for development).
- Credentials live in `~/pauk.env` on the server and are never
  committed.
