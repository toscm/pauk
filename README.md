# pauk

> [!WARNING]
> This is a private hobby project, published for convenience (so I
> can `pip install` it on my own machines) and not intended for use
> by anyone else. There is no support, no stability guarantee, and
> no promise it works anywhere but on my own setups. The hosted API
> at pauk.aao756.de is my personal instance — please do not rely on
> it. Use at your own risk.

Flashcard app ("Karteikarten") with an HTTP API as the single
source of truth and thin clients on top of it.

Questions are written in Markdown (images/videos via the usual
`![name](url)` syntax) and organized into directories that form
a DAG: a question can live in several directories, and
directories can contain other directories (a "core verbs" quiz
can be both standalone and part of "all verbs"). Five card
types: multiple choice, free text (normalized, typo-tolerant
matching), matching (connect each left to its right, e.g. a
pronoun to a verb form), LLM dialog quests, and graph-route
tasks with deterministic scoring. Grading and question
selection are server-side.

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

## Using the CLI

    make setup                 # or: pip install -e ./cli
    pauk login https://pauk.aao756.de   # prompts for the token
    pauk                       # interactive menu
    pauk quiz --dir greek      # quiz a folder (recursive)
    pauk ls --tree             # browse all folders
    pauk import content/greek.json

Tokens are created on the server:

    ssh ionos 'PAUK_ENV_FILE=$HOME/pauk.env \
        /usr/bin/php8.4-cli ~/pauk-app/bin/create-token.php <user>'

## Hosting

- API + media: https://pauk.aao756.de (IONOS webspace,
  directory `web/pauk`, deployed via rsync over SSH).
- Database: managed IONOS MariaDB, reachable from the webspace
  (and via SSH tunnel for development).
- Credentials live in `~/pauk.env` on the server and are never
  committed.
