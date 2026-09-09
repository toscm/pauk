---
status: open
kind: task
---

# Automated backups

Per docs/deployment.md: nightly mysqldump cron on the IONOS
server (14 dumps retained), `make backup-fetch` to pull dump
+ media locally. Set up together with the first production
deploy (issues/0001). Verify that a dump actually restores
(e.g. into a scratch database on the IONOS server, or a
MariaDB reached via CI); document the tested restore
procedure here.
