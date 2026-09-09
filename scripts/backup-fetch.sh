#!/usr/bin/env bash
# Pull the newest database dump (and media, once it exists)
# from the server to ~/pauk-local-backups/.
set -euo pipefail

DEST="$HOME/pauk-local-backups"
mkdir -p "$DEST"

LATEST=$(ssh ionos 'ls -1 ~/pauk-backups/pauk-*.sql.gz 2>/dev/null | sort | tail -1')
if [ -z "$LATEST" ]; then
    echo "no dumps on the server yet" >&2
    exit 1
fi
rsync -az "ionos:$LATEST" "$DEST/"
ssh ionos 'test -d ~/web/pauk/media' \
    && rsync -az ionos:web/pauk/media "$DEST/" || true
echo "fetched $(basename "$LATEST") to $DEST"
