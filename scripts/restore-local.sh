#!/usr/bin/env bash
# Restore a production dump into a throwaway local MariaDB for
# inspection (docs/deployment.md, "Restore"). Never touches the
# server or the live database.
#
#   scripts/restore-local.sh [DUMP]   restore (default: newest dump in
#                                     ~/pauk-local-backups), check row
#                                     counts, apply migrations, leave
#                                     the instance running
#   scripts/restore-local.sh stop     stop it and delete the datadir
#
# The datadir holds production data, so it lives outside the repo:
# $PAUK_RESTORE_DIR (default ~/pauk-restore). Port: $PAUK_RESTORE_PORT
# (default 33071).
set -euo pipefail

MARIADB="${PAUK_MARIADB_DIR:-$HOME/.local/mariadb-11.8}"
PHP="${PAUK_PHP:-$HOME/.local/bin/php}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIR="${PAUK_RESTORE_DIR:-$HOME/pauk-restore}"
PORT="${PAUK_RESTORE_PORT:-33071}"
DB=pauk_restore
DATADIR="$DIR/data"
CLIENT=("$MARIADB/bin/mariadb" --no-defaults --skip-ssl -h 127.0.0.1 -P "$PORT" -u root)

stop() {
    if [ -f "$DATADIR.pid" ]; then
        kill "$(cat "$DATADIR.pid")" 2>/dev/null || true
        for _ in $(seq 1 50); do
            [ -f "$DATADIR.pid" ] || break
            sleep 0.2
        done
    fi
    rm -rf "$DIR"
}

if [ "${1:-}" = stop ]; then
    stop
    echo "stopped; deleted $DIR"
    exit 0
fi

DUMP="${1:-$(ls -1 "$HOME"/pauk-local-backups/pauk-*.sql.gz 2>/dev/null | sort | tail -1)}"
if [ -z "$DUMP" ] || [ ! -f "$DUMP" ]; then
    echo "no dump given and none in ~/pauk-local-backups (run make backup-fetch)" >&2
    exit 1
fi
case "$DIR" in
    "$ROOT"|"$ROOT"/*) echo "PAUK_RESTORE_DIR must be outside the repo" >&2; exit 1 ;;
esac

echo "==> fresh instance in $DIR (port $PORT)"
stop
mkdir -p "$DIR"
chmod 700 "$DIR"
"$MARIADB/scripts/mariadb-install-db" --no-defaults \
    --basedir="$MARIADB" --datadir="$DATADIR" \
    --auth-root-authentication-method=normal --skip-test-db >/dev/null
"$MARIADB/bin/mariadbd" --no-defaults \
    --basedir="$MARIADB" --datadir="$DATADIR" \
    --port="$PORT" --bind-address=127.0.0.1 \
    --socket="$DATADIR.sock" --skip-name-resolve \
    --pid-file="$DATADIR.pid" 2>"$DATADIR.log" &
for _ in $(seq 1 100); do
    "${CLIENT[@]}" -e 'SELECT 1' >/dev/null 2>&1 && break
    sleep 0.2
done
"${CLIENT[@]}" -e "CREATE DATABASE $DB"

echo "==> loading $(basename "$DUMP")"
if [[ "$DUMP" == *.gz ]]; then gzip -dc "$DUMP"; else cat "$DUMP"; fi \
    | "${CLIENT[@]}" "$DB"

echo "==> comparing row counts with the dump"
python3 "$ROOT/scripts/dump_row_counts.py" "$DUMP" > "$DIR/expected.txt"
mismatch=0
tables=$("${CLIENT[@]}" -N -e "SELECT table_name FROM information_schema.tables WHERE table_schema = '$DB' ORDER BY table_name")
for t in $tables; do
    actual=$("${CLIENT[@]}" -N "$DB" -e "SELECT COUNT(*) FROM \`$t\`")
    expected=$(awk -v t="$t" '$1 == t { print $2 }' "$DIR/expected.txt")
    expected=${expected:-0}
    flag=ok
    if [ "$actual" != "$expected" ]; then flag=MISMATCH; mismatch=1; fi
    printf '    %-24s dump %6s  restored %6s  %s\n' "$t" "$expected" "$actual" "$flag"
done
for t in $(awk '{ print $1 }' "$DIR/expected.txt"); do
    if ! grep -qx "$t" <<<"$tables"; then
        echo "    $t: in the dump but not restored  MISMATCH"
        mismatch=1
    fi
done
if [ "$mismatch" -ne 0 ]; then
    echo "ERROR: restored row counts differ from the dump" >&2
    exit 1
fi

echo "==> applying migrations (no-op if the dump is up to date)"
(cd "$ROOT/api" && PAUK_DB_HOST=127.0.0.1 PAUK_DB_PORT="$PORT" PAUK_DB_USER=root \
    PAUK_DB_PASS= PAUK_DB_NAME=$DB "$PHP" bin/migrate.php)

cat <<EOF
==> restored; the instance keeps running. Point the API or tools at it with

    export PAUK_DB_HOST=127.0.0.1 PAUK_DB_PORT=$PORT PAUK_DB_USER=root PAUK_DB_PASS= PAUK_DB_NAME=$DB

and clean up with: scripts/restore-local.sh stop
EOF
