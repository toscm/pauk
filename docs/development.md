# Development

All development happens locally on this machine, offline
from the production server. The live IONOS system is only
touched by `make deploy` and for reading logs.

## Toolchain (no admin rights required)

`make setup` installs the toolchain into `~/.local` (via `scripts/install-toolchain.sh`, which skips whatever is already there), then the PHP dependencies with Composer and the Python ones into a venv.
`make toolchain` runs only the first step.

- PHP 8.4 CLI: a static binary from static-php.dev (the "common" build, which includes pdo_mysql and mbstring) installed to `~/.local/bin/php`.

- Composer: `composer.phar` installed to `~/.local/bin/composer`.

- MariaDB 11.8 under `~/.local/mariadb-11.8/`.
  On Linux (x86_64) this is the official binary tarball ("bintar"), unpacked next to it and symlinked.
  On macOS there is no official tarball, so the script installs the Homebrew bottle `mariadb@11.8` and symlinks the Homebrew prefix to `~/.local/mariadb-11.8` (Homebrew must be installed first).
  Either way the server runs entirely in user space; server and client binaries are addressed by full path from the Makefile, nothing global is touched.

- Python ≥ 3.10: checked, not installed; `make setup` creates the project venv under `cli/.venv` with it and installs the CLI with its dev extras.

The paths can be overridden for `make` (`PHP`, `COMPOSER`, `MARIADB`, `PY`) and for the script (`PREFIX`, `PHP_VERSION`, `MARIADB_VERSION`).
`~/.local/bin` should be on the `PATH` so that `php` and `composer` work outside `make` as well.
CI (`.github/workflows/ci.yml`) installs the same versions with GitHub actions and a MariaDB service container; it is the reference when something about the toolchain is unclear.

- On Windows the toolchain runs inside WSL (Ubuntu), installed the same way into the WSL home (`make setup` works there as on Linux).
  Run the suite from a WSL-side copy of the checkout (the MariaDB datadirs do not work well on the `/mnt/c` mount), and start pytest under `setsid` when WSL is launched from a Windows terminal: otherwise the hidden token prompt in `test_version_and_login` reads from the terminal instead of stdin and the test hangs.

## Databases

The same engine runs everywhere — MariaDB 11.8 locally, in
CI, and in production — so there are no SQL dialect
concerns (see docs/architecture.md, Decisions).

- Dev instance: `make db-start` boots a local mariadbd with
  datadir `api/var/devdb/`, port 33061, bound to
  127.0.0.1. `make db-stop` shuts it down. First start
  initializes the datadir.

- Tests boot their own scratch instances with throwaway
  datadirs under `api/var/test-*/`; see docs/testing.md.
  They never touch the dev instance.

- The API reads its connection from environment variables:

      PAUK_DB_HOST  PAUK_DB_PORT  PAUK_DB_NAME
      PAUK_DB_USER  PAUK_DB_PASS

- The production MariaDB is reachable for administration
  (backups, debugging) through an SSH tunnel:

      make tunnel   # ssh -L 33306:db5021384667...:3306 ionos

  Nothing in development or testing depends on it.

## Everyday commands (Makefile)

- `make setup` — install toolchain + dependencies (`make toolchain` for the toolchain alone)
- `make db-start` / `make db-stop` — local dev database
- `make serve` — run the API on http://127.0.0.1:8080
  against the dev database (PHP built-in server,
  `api/public/`)
- `make test` — full suite (see docs/testing.md)
- `make deploy` — test, then deploy (see docs/deployment.md)
- `make tunnel` — SSH tunnel to the production DB
- `make backup-fetch` / `make restore-local` — newest production dump into a throwaway local instance (see docs/deployment.md, "Restore")

## Calibrating the memory model

`api/bin/calibrate.php` checks how well the memory model (docs/tutor.md 4.6) predicts a recorded log.
It replays the events in time order, and before every test of an item that already has a state it predicts the recall probability `R` and compares it with the outcome (any outcome but `fail` counts as recalled).
First contacts, `introduce` and `self_report` are not scored; simulation evidence (`source: simulation`) is left out.

    cd api
    php bin/calibrate.php                      # interaction log of the PAUK_DB_* database
    php bin/calibrate.php --source=reviews     # legacy card reviews table (good/fail, mode from the card type)
    php bin/calibrate.php --export=pauk.jsonl  # a pauk export instead of a database
    php bin/calibrate.php --min-gap-hours=24   # score only predictions made at least a day after the item's previous event

It prints the number of events and scored predictions (also by gap), log loss and Brier score of the current constants next to a constant predictor at the observed success rate, a reliability table (predicted `R` in bins against the observed rate), and the best of a small grid of alternatives (v1 with the first stabilities, the growth constants and the forgetting curve each scaled by 0.5, 1 or 2) with the paired log-loss difference to v1 and its standard error.
The metric code is `Pauk\Knowledge\Calibration` (unit-tested); the model takes its constants from `MemoryModel::PARAMS`.
Run it on a restored copy of production (`make restore-local`), never against the live database.

How to read it: a useful model beats the constant predictor on log loss, and its reliability rows have observed rates close to their predictions.
Same-session repeats (gap under an hour) are predicted at `R ≈ 1` by construction, so judge the constants mainly with `--min-gap-hours=24`.
Change constants only when an alternative wins by several standard errors on a sample of at least several hundred spaced reviews over weeks; a change is a new model version (docs/tutor.md 6).
The first run (2026-10-14) is summarized in issues/0014.

## CLI against arbitrary servers

The CLI resolves its server and token in this order:

1. `--server` / `--token` command-line flags
2. `PAUK_SERVER` / `PAUK_TOKEN` environment variables
3. `~/.config/pauk/config.toml`

Tests set the environment variables to point at the local
test server; humans normally use the config file.

## Workflow

1. Pick or create an issue in `issues/`.
2. Spec change first if the contract is affected
   (`docs/api.md`).
3. Implement + tests. `make test` must be green.
4. Update the issue file, commit, push.
5. `make deploy` when a deployable increment is ready.
