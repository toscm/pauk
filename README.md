# pauk

> [!WARNING]
> This is a private hobby project, published for convenience (so I
> can `pip install` it on my own machines) and not intended for use
> by anyone else. There is no support, no stability guarantee, and
> no promise it works anywhere but on my own setups. The hosted API
> at pauk.aao756.de is my personal instance — please do not rely on
> it. Use at your own risk.

pauk connects your personal knowledge base with the LLM you already run on your own machine, and turns the two into a personal teacher.
The knowledge base holds everything you know or want to learn, from Italian verbs to the papers of your field, together with how well you remember each piece right now.
The LLM reads it, picks what is due or worth learning next, teaches and quizzes you in a browser chat with exercises, images, maps and small games, and every answer flows back into the knowledge base.
pauk itself is the glue: it stores the knowledge, computes the memory scores, and gives the LLM a clear, narrow set of actions, so learning stays fun, personal and effective.

Status: the knowledge profile is live; the tutor chat (`pauk`) is new and evolving (docs/tutor.md, issues/0014).
What exists today is the flashcard ("Karteikarten") foundation described below: an HTTP API as the single source of truth and thin clients on top of it.

Questions are written in Markdown (images/videos via the usual
`![name](url)` syntax) and organized into directories that form
a DAG: a question can live in several directories, and
directories can contain other directories (a "core verbs" quiz
can be both standalone and part of "all verbs"). Six card
types: multiple choice, free text (normalized, typo-tolerant
matching), matching (connect each left to its right, e.g. a
pronoun to a verb form), self-graded recall (reveal the
reference answer, judge yourself), LLM dialog quests, and
graph-route tasks with deterministic scoring. Grading and
question selection are server-side.

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
    pauk                       # tutor: local web chat + LLM teacher (prints the link)
    pauk tutor --no-agent      # same, but attach the teacher yourself
    pauk tui                   # the older terminal quiz app
    pauk quiz --dir greek      # quiz a folder (recursive)
    pauk ls --tree             # browse all folders
    pauk edit 17               # edit card 17 in $EDITOR; only changed fields are saved
    pauk link 17 italian/a2    # card 17 is now in italian/a2 as well (a directory works too)
    pauk unlink 17 italian/a1  # take it out of one directory; nothing is deleted
    pauk mv 17 italian/a2      # move a card (--from DIR when it is in several)
    pauk mv italian/old greek  # move a directory into greek; `mv a/x a/y` renames, `/` is the top level
    pauk import content/greek.json
    pauk import content/items-greek.json   # knowledge items, linked to the cards
    pauk profile greek         # knowledge profile + what to practise next
    pauk export -o me.jsonl    # items + evidence; `pauk import me.jsonl` restores
    pauk reports               # problem reports filed from tutor sessions
    pauk items dedup           # an agent suggests merges of duplicate items
    pauk triage                # an agent turns new reports into issues/ files (triage branch)
    pauk --server http://127.0.0.1:8080 --token ... simulate --persona cli/pauk/tutor/personas/italian-beginner.md
                               # LLM teacher + LLM learner against a scratch API, then a review

The tutor's teacher is the `claude` CLI by default (it must be installed and logged in); it uses only `pauk teach` commands.
Another agent can be plugged in with `--agent-cmd` or `PAUK_TUTOR_AGENT` (a command line with `{prompt}`).

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
