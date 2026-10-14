---
status: done
kind: task
---

# Automated backups

Per docs/deployment.md: nightly mysqldump cron on the IONOS
server (GFS retention), `make backup-fetch` to pull dump
+ media locally. Set up together with the first production
deploy (issues/0001). Verify that a dump actually restores
(e.g. into a scratch database on the IONOS server, or a
MariaDB reached via CI); document the tested restore
procedure here.

2026-09-09: Nightly cron (03:14) installed on the server,
prune_backups.py deployed with unit-tested GFS retention,
manual run verified (~10 KB gzipped, complete dump of the
seeded database). make backup-fetch verified: pulls the
latest dump to ~/pauk-local-backups/. Still open: verify a
dump restores cleanly, then document the restore procedure
here.

2026-10-14: Restore verified and documented; closed.
The nightly dump of 2026-10-14 (165 KB gzipped, 29 tables) was fetched with `make backup-fetch` and restored into a throwaway local MariaDB 11.8 with the new `make restore-local` (`scripts/restore-local.sh`).
Every table's row count matched the rows in the dump (checked by `scripts/dump_row_counts.py`, unit-tested), e.g. 766 cards, 290 reviews, 367 items, 230 interactions.
Migrations on the copy were not a no-op: production is at migration 008, and 009_tutor (not yet deployed) applied cleanly on the real data, a useful rehearsal for the next deploy.
The API (0.11.0 from this branch) ran against the copy on the PHP built-in server: `/health` ok with db ok, 401 without a token, and with a scratch token created on the copy `/stats`, `/dirs`, `/cards`, `/items`, `/profile`, `/profile/next`, `/interactions`, `/settings` and `/export` all returned 200 (the export held all 367 items and 230 interactions).
The procedure, including the emergency restore to production (written down, its drop-reload-migrate steps rehearsed only on the local copy), is in docs/deployment.md, "Restore".
The local copy of the production data was deleted afterwards.
