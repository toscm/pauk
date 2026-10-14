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

## IONOS quirks (do not "clean up")

- Per-directory mod_rewrite returns 500 on this Apache;
  `api/public/.htaccess` therefore uses
  `FallbackResource /index.php`. Real files (media/) are
  still served directly.

- CGI PHP drops the `Authorization` header. Two measures
  re-expose it: `SetEnvIf Authorization ...` in the
  .htaccess, and the front controller promotes
  `REDIRECT_`-prefixed variants that the FallbackResource
  internal redirect produces. Removing either breaks every
  authenticated endpoint in production only — the local dev
  server has neither quirk.

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

- Nightly cron on the server (03:14, installed by
  deploy.sh): `~/pauk-backups/backup.sh` runs
  `mysqldump | gzip > ~/pauk-backups/pauk-YYYY-MM-DD.sql.gz`,
  then `prune_backups.py` (deployed from `scripts/`).

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

## Restore

The dumps are plain `mysqldump` output: for every table a `DROP TABLE IF EXISTS`, the `CREATE TABLE` and the rows, no `CREATE DATABASE`, so they load into a database of any name.
They are written by the MariaDB 11.8 client and start with a `/*M!999999\- enable the sandbox mode */` line, so load them with a MariaDB client (a MySQL client rejects that line).

### Locally, for inspection (tested)

    make backup-fetch                         # newest dump to ~/pauk-local-backups/
    make restore-local                        # or: make restore-local DUMP=path/to/pauk-YYYY-MM-DD.sql.gz
    scripts/restore-local.sh stop             # stop the instance, delete the copy

`scripts/restore-local.sh` never talks to the server.
It boots a fresh MariaDB 11.8 instance with its datadir in `~/pauk-restore/` (outside the repo, because it holds production data; override with `PAUK_RESTORE_DIR`, port 33071 with `PAUK_RESTORE_PORT`), loads the dump into the database `pauk_restore`, compares the row count of every table with the rows in the dump's INSERT statements (`scripts/dump_row_counts.py`) and aborts on any difference.
It then runs the migrations of the current checkout: a no-op if the dump is as new as the code, otherwise a rehearsal of the next deploy's migrations on real data.
The instance keeps running so the API or `bin/calibrate.php` can be pointed at it with the `PAUK_DB_*` line the script prints, for example:

    export PAUK_DB_HOST=127.0.0.1 PAUK_DB_PORT=33071 PAUK_DB_USER=root PAUK_DB_PASS= PAUK_DB_NAME=pauk_restore
    cd api && php bin/create-token.php <user> restore-check   # scratch token, only in the copy
    php -S 127.0.0.1:8089 public/index.php                    # then GET /api/v1/health etc.

Delete the copy (`scripts/restore-local.sh stop`) when done.

### To production, in an emergency (written down, never rehearsed against the live database)

This is the one procedure besides `make deploy` that writes to the server, and it is run by hand.
Steps 4 and 5 were rehearsed against a local restore (drop, reload, migrate), never against the live database.
Everything recorded after the chosen dump is replaced, so the first steps keep the current state.

1. Pick the dump (`ssh ionos 'ls -l ~/pauk-backups'`) and verify it locally first: copy it with `rsync ionos:pauk-backups/pauk-YYYY-MM-DD.sql.gz ~/pauk-local-backups/` (or `make backup-fetch` for the newest), then `make restore-local DUMP=...` must report matching counts.

2. Take the API offline so nothing writes during the restore: `ssh ionos 'mv ~/web/pauk/index.php ~/web/pauk/index.php.off'` (requests then fail; that is intended).

3. Dump the current state, however broken, so nothing is lost for good.
   The file gets a timestamp and is never overwritten (a second attempt on the same day must not replace the pre-incident state with a damaged one), it lives outside `~/pauk-backups` so the nightly prune never deletes it, and it is copied off the server right away:

       ssh ionos 'bash -s' <<'EOS'
       set -euo pipefail
       set -o noclobber
       set -a; . ~/pauk.env; set +a
       mkdir -p ~/pauk-prerestore
       mysqldump -h "$PAUK_DB_HOST" -P "$PAUK_DB_PORT" -u "$PAUK_DB_USER" -p"$PAUK_DB_PASS" "$PAUK_DB_NAME" \
           | gzip > ~/pauk-prerestore/pauk-prerestore-$(date +%F-%H%M%S).sql.gz
       gzip -t ~/pauk-prerestore/pauk-prerestore-*.sql.gz
       EOS
       rsync -a ionos:pauk-prerestore/ ~/pauk-local-backups/prerestore/

4. Drop all tables, then load the dump.
   Dropping first matters: the dump only drops the tables it contains, so a table created by a later migration would survive, and re-running that migration would then fail on it.
   Set `DUMP` to the file chosen in step 1; the script checks that it exists and is a complete gzip file before it drops anything.
   If the load fails half way, run this step again with `DUMP` set to the newest `~/pauk-prerestore/` file to get back to where you started.

       ssh ionos 'bash -s' <<'EOS'
       set -euo pipefail
       DUMP=~/pauk-backups/pauk-YYYY-MM-DD.sql.gz
       test -s "$DUMP" && gzip -t "$DUMP"
       set -a; . ~/pauk.env; set +a
       DB=(mysql -h "$PAUK_DB_HOST" -P "$PAUK_DB_PORT" -u "$PAUK_DB_USER" -p"$PAUK_DB_PASS" "$PAUK_DB_NAME")
       { echo 'SET FOREIGN_KEY_CHECKS = 0;'
         "${DB[@]}" -N -e "SELECT CONCAT('DROP TABLE \`', table_name, '\`;') FROM information_schema.tables WHERE table_schema = DATABASE()"
       } | "${DB[@]}"
       gunzip -c "$DUMP" | "${DB[@]}"
       EOS

5. Bring the schema up to the deployed code: `ssh ionos 'PAUK_ENV_FILE=$HOME/pauk.env /usr/bin/php8.4-cli ~/pauk-app/bin/migrate.php'`.
   Item states come back with the dump; a state written by an older model version is replayed on the next event.

6. Put the API back (`ssh ionos 'mv ~/web/pauk/index.php.off ~/web/pauk/index.php'`), check `curl https://pauk.aao756.de/api/v1/health`, and spot-check row counts via `make tunnel`.

7. Media: files are content-hashed and immutable, so restoring is only adding missing ones: `rsync -a ~/pauk-local-backups/media/ ionos:web/pauk/media/` (never with `--delete`).

8. Salvage what was recorded after the dump, if wanted: the `pauk-prerestore-*` dump (on the server in `~/pauk-prerestore/` and locally in `~/pauk-local-backups/prerestore/`) holds it, and interactions from a `pauk export` taken before the restore can be re-imported with `pauk import`, which upserts by uuid.

## Post-deploy

- Logs: `ssh ionos 'tail -f ~/logs/...'` (Apache/PHP error
  logs; exact path visible in `~/logs/` on the server).
- After schema changes, spot-check via `make tunnel` +
  `mysql` against the tunnel.
