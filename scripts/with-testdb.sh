#!/usr/bin/env bash
# Run a command against a throwaway local MariaDB instance.
# Exports PAUK_DB_* and executes "$@". If PAUK_DB_HOST is
# already set (e.g. in CI with a service container), the
# command runs directly against that.
set -euo pipefail

if [ -n "${PAUK_DB_HOST:-}" ]; then
    exec "$@"
fi

MARIADB="${PAUK_MARIADB_DIR:-$HOME/.local/mariadb-11.8}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VAR="$ROOT/api/var"
PORT="${PAUK_TEST_DB_PORT:-33068}"
DATADIR="$VAR/testdb-$PORT"
TEMPLATE="$VAR/db-template"
mkdir -p "$VAR"

# Initializing a datadir takes seconds; do it once and copy.
if [ ! -d "$TEMPLATE" ]; then
    "$MARIADB/scripts/mariadb-install-db" --no-defaults \
        --basedir="$MARIADB" --datadir="$TEMPLATE" \
        --auth-root-authentication-method=normal \
        --skip-test-db >/dev/null
fi
rm -rf "$DATADIR"
cp -r "$TEMPLATE" "$DATADIR"

"$MARIADB/bin/mariadbd" --no-defaults \
    --basedir="$MARIADB" --datadir="$DATADIR" \
    --port="$PORT" --bind-address=127.0.0.1 \
    --socket="$DATADIR.sock" --skip-name-resolve \
    --pid-file="$DATADIR.pid" 2>"$DATADIR.log" &
DBPID=$!
cleanup() {
    kill "$DBPID" 2>/dev/null || true
    wait "$DBPID" 2>/dev/null || true
    rm -rf "$DATADIR" "$DATADIR.sock" "$DATADIR.pid"
}
trap cleanup EXIT

for _ in $(seq 1 100); do
    if "$MARIADB/bin/mariadb" --no-defaults -h 127.0.0.1 -P "$PORT" \
        -u root -e 'SELECT 1' >/dev/null 2>&1; then
        break
    fi
    sleep 0.2
done

export PAUK_DB_HOST=127.0.0.1
export PAUK_DB_PORT="$PORT"
export PAUK_DB_USER=root
export PAUK_DB_PASS=
export PAUK_DB_NAME=pauk_test
"$@"
