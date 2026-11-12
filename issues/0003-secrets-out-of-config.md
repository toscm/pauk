---
status: done
kind: feature
---

# config.yaml without secrets, shareable between machines

Goal (2026-11-12): the same `config.yaml` on every machine, kept in a (private) dotfiles repository and linked into `~/pauk`.
That failed on two things: `config.yaml` held the users' password hashes, and the listen address differed per machine.

## Options considered

- A machine-local override file (`config.local.yaml` merged over `config.yaml`): flexible, but a second config layer for one or two keys.

- Keeping secrets in the private dotfiles repository, with a warning never to make it public: the API key would sit in the git history of every clone and on the git host for good, and one slip (the repository made public, a collaborator added, the file copied elsewhere) leaks it until the key is rotated.

- Chosen: a fixed split by kind instead of by machine.
  `config.yaml` holds nothing secret; `secrets.yaml` holds the API key and the logins and stays on the machine.

## Decisions

- `secrets.yaml` in the pauk home: `anthropic_api_key` (the shell's `ANTHROPIC_API_KEY` wins) and `users` (written by `pauk user add`).
  pauk creates it with a placeholder key (`sk-ant-REPLACE-ME`, treated as no key) and mode 600.
  It replaces `.env`: one file for everything secret instead of two.

- Migration: on the first start after the update, pauk moves `users` out of `config.yaml` (keeping its comments) and the key out of `.env` into `secrets.yaml`, and deletes `.env`.
  A placeholder in `.env` never overwrites a real key.

- One default port on every machine, 8642 (`listen: 127.0.0.1:8642`).
  With progress synced through git (issues/0002) every machine runs its own pauk on its own copy of the progress, so the same local address works everywhere and no ssh tunnel to another machine's pauk is needed.
  A machine that serves phones in the LAN still sets `0.0.0.0:8642`.

- `device` defaults to the host name, so a shared `config.yaml` leaves it out.

- Logins are per machine: a new machine needs one `pauk user add` (and the key pasted into `secrets.yaml`).

Details: `docs/files.md` (config.yaml, secrets.yaml), `app/src/config.ts`, tests in `app/test/config.test.ts`.
