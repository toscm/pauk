---
status: done
kind: feature
---

# Sync learning progress between devices through git

Problem (2026-11-12): progress made on one machine (the learning log in `~/pauk/users/<name>/`) was invisible on another.
pauk 2 had no sync (issues/0001), so each machine kept its own log and the two would drift apart.

Goal: practise on several machines (macOS, Windows, Linux servers) with one shared progress, transparent and inspectable, without adding a dependency.

## Options considered

- A sync folder such as OneDrive: works on macOS and Windows but not on Linux servers, and adds a dependency.

- The progress in the knowledge repository: every session would add commits that bury the history of the decks, admin edits in the browser write to the same repository, and progress belongs to a person, not to a set of decks (which may be several, or shared).

- The public pauk repository: impossible, learning data must never be published.

- Chosen: a separate private repository for the progress, synced by pauk with git.
  git is already needed for the knowledge repositories and for pauk itself.

## Decisions

- `progress` in `config.yaml` says where the users' folders live (default: `users/` in the pauk home, as before).

- There is no extra switch: pauk syncs the folder when it is a git repository (has its own `.git`); it commits, and with an upstream it also pulls (rebase) and pushes.
  A fresh clone of an empty repository gets its upstream on the first push.

- When: at `pauk start`, before and after each session, every 5 minutes while running, and on SIGINT/SIGTERM; `pauk sync` by hand.
  Relying on "the end of a session" alone would miss sessions that end by closing the browser or putting the laptop to sleep.

- Conflicts are designed out: each device appends to its own `log/<device>/` folder (`device` in `config.yaml`, default the host name), and the replay sorts the lines of all devices by time.
  pauk writes a `.gitattributes`: union merge for the append-only files (`*.jsonl`, `items.yaml`), LF line endings everywhere (Windows' `core.autocrlf` would otherwise rewrite the files of other devices); for `settings.yaml` the device that syncs last wins.

- The API logs (`api/`) are not part of the progress: they move to `~/pauk/api/<name>/` (pauk moves existing ones).
  They are large with `teacher.debug` and belong to the machine that made the calls; the monthly budget therefore counts per machine.

- Machine files stay local: `config.yaml` (paths, listen address, password hashes), `.env`, `logins.json`.

- A failed sync (offline, no access) is printed and retried at the next occasion; git runs with `GIT_TERMINAL_PROMPT=0` so it never waits for a password.

- After other devices' changes arrive, learners without a running session are read again from the files.

Details: `docs/files.md` (Progress and sync), `app/src/sync.ts`, tests in `app/test/sync.test.ts` (two clones of a local bare repository).

## Setting it up

1. Create an empty private repository, e.g. `pauk-progress`, and clone it on every machine.

2. Set `progress: <the clone>` in `~/pauk/config.yaml` on every machine.

3. On the machine with the existing progress, move the folders from `~/pauk/users/` into the clone and run `pauk sync`.
