# CLAUDE.md

pauk is a personal teacher that runs on the user's own machine: knowledge in YAML decks and Markdown items, an append-only learning log per user, a Claude teacher, and a small web app for the devices in the LAN.
The code is in `app/` (TypeScript on Node.js, no build step); `README.md` explains how to run it.

## Documentation map

- `docs/files.md`: every file pauk reads or writes (the contract)
- `docs/architecture.md`: components and decisions
- `issues/`: issue tracking as markdown files (see `issues/README.md` for the convention)

## This repository is PUBLIC — no sensitive data

`github.com/toscm/pauk` is a public repository.
Everything committed here, including the full git history of every branch, is readable by anyone and stays so: deleting a file later does not unpublish it, and removing it properly means rewriting history and rotating whatever leaked.
So before every commit, check the diff (and every new file) against this list.

Never commit:

- Unpublished research: unpublished data, results, figures, gene lists, screen details, manuscripts or manuscript methods, and the design or results of projects that are not yet published.
  A deck or items file written from such sources (a private repo's README, a manuscript draft, lab notes, meeting notes) is private, even if most of its facts are textbook knowledge.

- Information about people: colleagues, collaborators, supervisors, patients, study participants; who works on what, who is responsible for what, personal assessments.

- Internal project or employer information: funding applications and their review outcomes, grant plans, budgets, organisational details of research programmes.

- Credentials and private infrastructure: tokens, passwords, keys, `secrets.yaml` contents, and backups or copies of a pauk home (`~/pauk`).

- The user's own learning data: learning logs, session transcripts, API logs, teacher reports.

Knowledge decks do not belong in this repo at all: they live in the private repository `toscm/pauk-content` (locally `~/Repos/pauk-content`), which pauk reads as a source.
This repo ships only the small example decks in `examples/` (Greek letters, a little Italian) and pauk's own deck in `app/knowledge/`.
Commit messages, `issues/` files and docs are public too: do not describe private content there beyond "a private file outside the repo".

If it is unclear whether something is publishable, do not commit it: keep it in the private repository and ask the user.

## Rules

- Design principle: as simple as possible, follow mainstream conventions wherever one exists (naming, layout, tooling).

- `docs/files.md` is the contract: change it first, then the code.

- Before a commit: `npm test` and `npm run check` in `app/` pass, and `pauk check` reports no errors for the example decks.
  Tests use scratch folders and a scripted fake teacher; they never touch `~/pauk` or call the API.

- Track work in `issues/`: one markdown file per issue, updated in the same commit as the code that addresses it.

- Architecture decisions of lasting relevance go into `docs/architecture.md` under "Decisions", not into commit messages alone.
