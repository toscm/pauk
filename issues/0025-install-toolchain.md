---
status: done
kind: task
---

# Installation: `make setup` should install the toolchain, and the README should say how to install

## Problem

docs/development.md claimed that `make setup` "installs/verifies" PHP, Composer and MariaDB, but the target only ran `composer install` and `pip install`; the three tools had to be put under `~/.local` by hand, with no download commands anywhere.
The README started "Using the CLI" with `make setup`, which fails on a fresh machine on the missing Composer even though a CLI-only user needs neither PHP nor Composer.
It also gave no Python version, no checkout-free install recipe, no dependency list (the `claude` CLI) and no link to docs/development.md.

## Done (2026-10-19)

- `scripts/install-toolchain.sh` installs PHP 8.4 (static-php.dev), Composer (composer.phar) and MariaDB 11.8 (Linux: official bintar; macOS: Homebrew bottle, symlinked) into `~/.local`, checks Python >= 3.10, and skips every piece that is already there.
  `make toolchain` runs it, `make setup` depends on it.

- README: new "Installation" section with the two paths (CLI only via pipx/pip, full toolchain via `make setup`), the `claude` CLI dependency and links to the docs.

- docs/development.md: toolchain section rewritten to match what the script does; the WSL note now just says `make setup` works there.

Verified on macOS arm64: a run with a scratch `PREFIX` downloaded PHP and Composer and linked MariaDB; a second `make setup` on the real prefix skipped everything.
The Linux branch (MariaDB bintar) was checked only for the download URL, not run.
