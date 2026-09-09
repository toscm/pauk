---
status: in-progress
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
manual run verified (dump ~10 KB). Still open: verify a dump
restores cleanly, then document the restore procedure here.
