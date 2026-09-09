#!/usr/bin/env bash
# Restore the previous app version kept by deploy.sh.
# Schema rollbacks are not automated (docs/deployment.md).
set -euo pipefail

URL=https://pauk.aao756.de

ssh ionos 'bash -s' <<'EOS'
set -euo pipefail
if [ ! -d ~/pauk-app.prev ]; then
    echo "ERROR: no previous version on the server" >&2
    exit 1
fi
rm -rf ~/pauk-app.rollback-tmp
mv ~/pauk-app ~/pauk-app.rollback-tmp
mv ~/pauk-app.prev ~/pauk-app
rm -rf ~/pauk-app.rollback-tmp
EOS

echo "==> smoke test"
curl -sS -m 20 "$URL/api/v1/health"
echo
curl -sS -m 20 "$URL/api/v1/health" | grep -q '"status":"ok"' \
    || { echo "SMOKE TEST FAILED after rollback" >&2; exit 1; }
echo "==> rollback complete"
