#!/bin/sh
# Installs the pauk development toolchain into ~/.local (no admin rights):
#
#   PHP 8.4 CLI      static binary from static-php.dev   -> $PREFIX/bin/php
#   Composer         composer.phar                       -> $PREFIX/bin/composer
#   MariaDB 11.8     Linux: official binary tarball      -> $PREFIX/mariadb-11.8
#                    macOS: Homebrew bottle, symlinked   -> $PREFIX/mariadb-11.8
#   Python >= 3.10   checked only; install it with your OS tools
#
# Every piece is skipped when it is already in place, so the script is safe to
# re-run (`make setup` runs it every time). Override PREFIX, PHP_VERSION and
# MARIADB_VERSION in the environment if needed.
set -eu

PREFIX=${PREFIX:-$HOME/.local}
PHP_VERSION=${PHP_VERSION:-8.4.23}
MARIADB_VERSION=${MARIADB_VERSION:-11.8.9}
MARIADB_SERIES=${MARIADB_VERSION%.*}          # 11.8
MARIADB_DIR=$PREFIX/mariadb-$MARIADB_SERIES

os=$(uname -s)
arch=$(uname -m)
case "$os/$arch" in
    Darwin/arm64)  php_platform=macos-aarch64 ;;
    Darwin/x86_64) php_platform=macos-x86_64 ;;
    Linux/x86_64)  php_platform=linux-x86_64 ;;
    Linux/aarch64) php_platform=linux-aarch64 ;;
    *) echo "unsupported platform: $os/$arch" >&2; exit 1 ;;
esac

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$PREFIX/bin"

fetch() { curl -fsSL --retry 3 -o "$2" "$1"; }

# --- PHP ------------------------------------------------------------------
if "$PREFIX/bin/php" -v 2>/dev/null | grep -q '^PHP 8\.4' \
   && "$PREFIX/bin/php" -m | grep -qx pdo_mysql; then
    echo "php: ok ($("$PREFIX/bin/php" -v | head -1 | cut -d' ' -f1-2))"
else
    url=https://dl.static-php.dev/static-php-cli/common/php-$PHP_VERSION-cli-$php_platform.tar.gz
    echo "php: downloading $url"
    fetch "$url" "$tmp/php.tar.gz"
    tar -xzf "$tmp/php.tar.gz" -C "$tmp" php
    install -m 755 "$tmp/php" "$PREFIX/bin/php"
    "$PREFIX/bin/php" -m | grep -qx pdo_mysql || { echo "php: pdo_mysql missing" >&2; exit 1; }
    echo "php: installed $("$PREFIX/bin/php" -v | head -1 | cut -d' ' -f1-2)"
fi

# --- Composer -------------------------------------------------------------
if "$PREFIX/bin/composer" --version >/dev/null 2>&1; then
    echo "composer: ok ($("$PREFIX/bin/composer" --version 2>/dev/null | cut -d' ' -f1-3))"
else
    echo "composer: downloading composer.phar"
    fetch https://getcomposer.org/download/latest-stable/composer.phar "$tmp/composer.phar"
    install -m 755 "$tmp/composer.phar" "$PREFIX/bin/composer"
    echo "composer: installed $("$PREFIX/bin/composer" --version 2>/dev/null | cut -d' ' -f1-3)"
fi

# --- MariaDB --------------------------------------------------------------
if [ -x "$MARIADB_DIR/bin/mariadbd" ]; then
    echo "mariadb: ok ($("$MARIADB_DIR/bin/mariadbd" --version | sed 's/.*Ver //; s/ for .*//'))"
elif [ "$os" = Linux ]; then
    [ "$arch" = x86_64 ] || { echo "mariadb: no official tarball for linux/$arch; install MariaDB $MARIADB_SERIES yourself and symlink it to $MARIADB_DIR" >&2; exit 1; }
    name=mariadb-$MARIADB_VERSION-linux-systemd-x86_64
    url=https://archive.mariadb.org/mariadb-$MARIADB_VERSION/bintar-linux-systemd-x86_64/$name.tar.gz
    echo "mariadb: downloading $url"
    fetch "$url" "$tmp/mariadb.tar.gz"
    tar -xzf "$tmp/mariadb.tar.gz" -C "$PREFIX"
    ln -sfn "$PREFIX/$name" "$MARIADB_DIR"
    echo "mariadb: installed to $MARIADB_DIR"
else
    # No official macOS tarball exists; the Homebrew bottle is the mainstream route.
    command -v brew >/dev/null || { echo "mariadb: Homebrew is required on macOS (https://brew.sh), then re-run" >&2; exit 1; }
    brew list --versions "mariadb@$MARIADB_SERIES" >/dev/null 2>&1 || brew install "mariadb@$MARIADB_SERIES"
    ln -sfn "$(brew --prefix "mariadb@$MARIADB_SERIES")" "$MARIADB_DIR"
    echo "mariadb: linked $MARIADB_DIR -> $(readlink "$MARIADB_DIR")"
fi

# --- Python ---------------------------------------------------------------
PY=${PY:-python3}
if "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
    echo "python: ok ($("$PY" --version))"
else
    echo "python: python3 >= 3.10 not found; install it (e.g. apt install python3, brew install python)" >&2
    exit 1
fi

echo "toolchain complete in $PREFIX (make sure $PREFIX/bin is on your PATH)"
