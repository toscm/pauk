# Architecture

## Components

pauk is one Node.js program (`app/`) and a few kinds of text files.

- Knowledge sources: folders of YAML decks and Markdown items (`docs/files.md`), usually git repositories.
  The pauk repository ships two: `app/knowledge/` (pauk explains itself, always loaded) and `examples/` (a new `config.yaml` lists it).

- The pauk home `~/pauk`: `config.yaml`, `.env` with the API key, and one folder per user with the learning log, settings, session transcripts and the API log.

- The server (`app/src/server.ts`): the browser app (`app/public/`), a small JSON API for it and a server-sent event stream per session, on one port in the LAN.

- The teacher (`app/src/teacher.ts`): a tool-use loop over the Claude Messages API whose tools are methods of one learner's session.

- On macOS a launchd login service and a menu bar item (`app/src/service.ts`, `app/macos/PaukMenu.swift`).

## Data flow

1. At startup pauk reads all sources into an in-memory index (`app/src/knowledge.ts`) and replays each user's log through the memory model (`app/src/memory.ts`) into item states.

2. A session picks what is due or new (`app/src/profile.ts`), shows exercises from the items' cards, grades answers (`app/src/grader.ts`, `app/src/text.ts`) and appends every observation to the log.

3. Knowledge files edited while pauk runs are re-read on the next request; edits made in the browser go through `app/src/edit.ts`.

## Decisions

- As simple as possible; follow mainstream conventions wherever one exists (naming, layout, tooling).

- Text files instead of a database (issues/0001).
  Knowledge lives in YAML decks and Markdown items that people edit; learning data is an append-only JSON-lines log per user from which item states are recomputed at startup.
  At a few thousand items and a few hundred thousand log lines an in-memory index loads in well under a second, and files can be read, diffed, versioned and fixed by hand.
  Chosen over SQLite (a binary file that cannot be reviewed or merged) and over the hosted PHP/MariaDB API of pauk 1 (latency, and private knowledge on a shared host).

- TypeScript on Node.js, without a build step (Node runs `.ts` directly; the server strips types from the browser modules it serves) and without a web framework.
  One language for server and browser, a first-class Anthropic SDK, and a runtime the phone's browser shares.
  Rust was considered and rejected for now: the browser part would still be TypeScript, and the server would be roughly twice as long.

- The teacher calls the Claude Messages API directly instead of running an agent CLI.
  Its tools are methods of one learner's session, so it can serve several users (e.g. over the LAN) without any access to files or to other users' data; every call is logged with its usage and cost, and a monthly budget per user stops it.

- Computations are deterministic, judgements of meaning belong to the LLM.
  Memory scores, scheduling and the grading of closed cards are code; whether a free answer means the right thing is the teacher's call.

- Identity spaces are separate from subjects.
  An item is `space/key` (one space per language, `concepts` for everything else), which only prevents false collisions; its subject is the path of the file it sits in, so moving files reorganises without touching identity.
  Renames and merges go through `aliases`, so the log never has to be rewritten.

- The log is the truth and is never rewritten: corrections are `amend` lines, and states are a pure function of the log.

- Typo tolerance treats a vowel swapped for another vowel as two edits: in Italian, Spanish, Greek and German that usually changes the word (gender, number, person).

- All user files live in one visible folder, `~/pauk` (`$PAUK_HOME` moves it), not in XDG or macOS Library folders.
  The learning log and the teacher's items are the user's own data, meant to be read and edited, like a Zotero or Obsidian folder; one folder is also one thing to back up, version or sync.

- Progress syncs through git, not a sync service: the progress folder may be a private repository that pauk commits, pulls and pushes (`src/sync.ts`).
  git is already needed for the knowledge repositories, works the same on macOS, Windows and Linux servers, and every change stays inspectable.
  Conflicts are designed out instead of resolved: each device appends to its own log folder, and the replay sorts all lines by time.
  The progress lives in its own repository, apart from the knowledge: it changes with every session (that would bury the history of the decks), belongs to a person rather than to a set of decks, and one progress folder serves any number of sources.
  Secrets go into `~/pauk/.env`, separate from `config.yaml`, so the config can be shown and shared without leaking the API key.

- The pauk repository is public and holds no knowledge decks beyond `examples/` and pauk's own deck.
  Everything else lives in the user's own (usually private) source repositories, so publishing the code never publishes what someone learns.

- The browser can edit knowledge, but only narrowly: an admin edits an item's fields, adds an item to a folder or starts a folder with its first item.
  `app/src/edit.ts` changes just that node in the YAML file and keeps the rest of the file as written; a change that would add a problem `pauk check` reports is undone.
  Cards, links, Markdown items and the decks that ship with pauk are edited in an editor.
