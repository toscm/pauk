# Deployment

Target: IONOS shared webhosting, `ssh ionos`.

## Server layout

- `~/web/pauk/` — docroot (https://pauk.aao756.de). Contains
  only `api/public/` content (front controller, .htaccess)
  and the `media/` directory.

- `~/pauk-app/` — application code + vendor/ (outside the
  docroot, not web-accessible).

- `~/pauk-config/` — `config.php` reading `~/pauk.env`
  (DB credentials; file mode 600, never in git).

- `~/pauk-backups/` — database dumps (see Backups).

## Process (`make deploy`)

1. `make test` — levels 1–3 locally; abort on any failure.
2. Check the working tree is clean and pushed; abort if not.
3. `composer install --no-dev` into a build directory.
4. rsync build → `~/pauk-app/`, public part → `~/web/pauk/`.
   `media/` and config are excluded from --delete.
5. Run pending migrations over the SSH connection
   (`php8.4-cli ~/pauk-app/bin/migrate.php`). Migrations are
   forward-only; every migration must keep existing data
   valid.
6. Smoke test: `GET https://pauk.aao756.de/api/v1/health`
   must return ok + the new version, otherwise the deploy is
   declared failed (see Rollback).

## Rollback

rsync is atomic enough per file but not per deploy, so:
step 4 first copies the current `~/pauk-app` to
`~/pauk-app.prev`. `make rollback` restores it and re-runs
the smoke test. Schema rollbacks are not automated —
migrations are written to be backward compatible with the
previous app version (add, don't repurpose).

## Backups

- Nightly cron on the server:
  `mysqldump | gzip > ~/pauk-backups/pauk-YYYY-MM-DD.sql.gz`,
  followed by a prune step.

- Retention (grandfather-father-son, date-anchored so it is
  computable from filenames alone). A dump is kept iff:

  - it is at most 7 days old, or
  - its day of month is 1, 8, 15, or 22 and it is at most
    35 days old, or
  - its day of month is 1 and it is at most 366 days old.

  That yields ~7 dailies, ~4 weekly anchors, ~12 monthly
  anchors — roughly 20 small gzipped dumps at any time. The
  prune logic lives in a script with unit tests (pure
  filename → keep/drop decision).

- `make deploy` additionally takes a dump right before
  running migrations (kept alongside, pruned like a daily).

- Media files are content-hashed and immutable, so a weekly
  rsync of `media/` to the local machine suffices.

- `make backup-fetch` pulls the latest dump + media to
  `~/pauk-local-backups/` on this machine.

## Post-deploy

- Logs: `ssh ionos 'tail -f ~/logs/...'` (Apache/PHP error
  logs; exact path visible in `~/logs/` on the server).
- After schema changes, spot-check via `make tunnel` +
  `mysql` against the tunnel.
