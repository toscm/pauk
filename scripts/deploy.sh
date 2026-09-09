#!/usr/bin/env bash
# Deploy the API to the IONOS webspace. See docs/deployment.md.
# Gate: full local test suite green, clean and pushed work tree.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PHP="${PAUK_PHP:-$HOME/.local/bin/php}"
COMPOSER="${PAUK_COMPOSER:-$HOME/.local/bin/composer}"
SSH_HOST=ionos
URL=https://pauk.aao756.de

cd "$ROOT"

echo "==> running test suite"
make test

echo "==> checking work tree"
if [ -n "$(git status --porcelain)" ]; then
    echo "ERROR: work tree not clean; commit first." >&2
    exit 1
fi
if [ -n "$(git log --oneline @{upstream}..HEAD 2>/dev/null)" ]; then
    echo "ERROR: unpushed commits; push first." >&2
    exit 1
fi

VERSION=$(sed -n "s/.*VERSION = '\(.*\)'.*/\1/p" api/src/Version.php)
echo "==> building version $VERSION"
BUILD=$(mktemp -d)
trap 'rm -rf "$BUILD"' EXIT
cp -r api/src api/public api/bin api/migrations api/composer.json "$BUILD/"
(cd "$BUILD" && "$COMPOSER" install --no-dev --no-interaction --quiet)

REMOTE_HOME=$(ssh $SSH_HOST 'echo $HOME')

echo "==> pre-deploy database dump"
ssh $SSH_HOST 'bash -s' <<'EOS'
set -euo pipefail
mkdir -p ~/pauk-backups
set -a; . ~/pauk.env; set +a
mysqldump -h "$PAUK_DB_HOST" -P "$PAUK_DB_PORT" -u "$PAUK_DB_USER" \
    -p"$PAUK_DB_PASS" "$PAUK_DB_NAME" 2>/dev/null \
    | gzip > ~/pauk-backups/pauk-$(date +%F)-predeploy.sql.gz
EOS

echo "==> syncing app to $SSH_HOST"
ssh $SSH_HOST 'if [ -d ~/pauk-app ]; then rm -rf ~/pauk-app.prev && cp -r ~/pauk-app ~/pauk-app.prev; fi'
rsync -az --delete "$BUILD/" "$SSH_HOST:pauk-app/"

echo "==> writing docroot front controller"
ssh $SSH_HOST "REMOTE_HOME=$REMOTE_HOME bash -s" <<'EOS'
set -euo pipefail
mkdir -p ~/web/pauk
mkdir -p ~/web/pauk/media
cat > ~/web/pauk/index.php <<EOF
<?php
putenv('PAUK_APP_DIR=$REMOTE_HOME/pauk-app');
putenv('PAUK_ENV_FILE=$REMOTE_HOME/pauk.env');
require '$REMOTE_HOME/pauk-app/public/index.php';
EOF
cp ~/pauk-app/public/.htaccess ~/web/pauk/.htaccess
EOS

echo "==> running migrations"
ssh $SSH_HOST 'PAUK_ENV_FILE=$HOME/pauk.env /usr/bin/php8.4-cli ~/pauk-app/bin/migrate.php'

echo "==> installing backup cron + prune script"
scp -q "$ROOT/scripts/prune_backups.py" "$SSH_HOST:pauk-backups/prune_backups.py"
ssh $SSH_HOST 'bash -s' <<'EOS'
set -euo pipefail
cat > ~/pauk-backups/backup.sh <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
set -a; . ~/pauk.env; set +a
mysqldump -h "$PAUK_DB_HOST" -P "$PAUK_DB_PORT" -u "$PAUK_DB_USER" \
    -p"$PAUK_DB_PASS" "$PAUK_DB_NAME" 2>/dev/null \
    | gzip > ~/pauk-backups/pauk-$(date +%F).sql.gz
python3 ~/pauk-backups/prune_backups.py ~/pauk-backups
EOF
chmod +x ~/pauk-backups/backup.sh
crontab -l 2>/dev/null | grep -v 'pauk-backups/backup.sh' > /tmp/cron.$$ || true
echo '14 3 * * * bash $HOME/pauk-backups/backup.sh >> $HOME/pauk-backups/backup.log 2>&1' >> /tmp/cron.$$
crontab /tmp/cron.$$
rm /tmp/cron.$$
EOS

echo "==> smoke test"
sleep 2
HEALTH=$(curl -sS -m 20 "$URL/api/v1/health")
echo "    $HEALTH"
echo "$HEALTH" | grep -q '"status":"ok"' || { echo "SMOKE TEST FAILED" >&2; exit 1; }
echo "$HEALTH" | grep -q "\"version\":\"$VERSION\"" || { echo "VERSION MISMATCH" >&2; exit 1; }
echo "==> deployed $VERSION to $URL"
