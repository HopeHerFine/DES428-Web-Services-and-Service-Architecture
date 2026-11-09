#!/bin/sh
# Run only on a disposable GitHub runner; never reset a developer's stack here.
set -eu
if [ "${GITHUB_ACTIONS:-}" != "true" ]; then
  echo 'CI-only script. Use check-clean-start.ps1 for a local rehearsal.' >&2
  exit 1
fi
export COMPOSE_PROJECT_NAME=noti-ci-raw
mkdir -p runtime/ci
cleanup() { code=$?; if [ "$code" -ne 0 ]; then docker compose -f compose.migration-base.yml logs --no-color --tail 60; fi; docker compose -f compose.migration-base.yml down --volumes --remove-orphans; }
trap cleanup EXIT
customers() {
  docker compose -f compose.migration-base.yml exec -T edemand node -e 'const Database=require("better-sqlite3");const db=new Database("/app/data/edemand.db",{readonly:true});console.log(db.prepare("SELECT COUNT(*) AS n FROM customers").get().n);db.close();'
}
test ! -e .env.notifications
docker compose -f compose.migration-base.yml config --quiet
docker compose -f compose.migration-base.yml up --build -d --wait --wait-timeout 360
test ! -e .env.notifications
test "$(docker compose -f compose.migration-base.yml run --rm --no-deps bootstrap id -u)" = "1000"
docker compose -f compose.migration-base.yml run --rm --no-deps notifications-worker python -m app.smoke
docker compose -f compose.migration-base.yml run --rm --no-deps notifications-worker python -m app.smoke_gateway
docker compose -f compose.migration-base.yml run --rm --no-deps notifications-worker python -m app.smoke_registration
customers > runtime/ci/customers-before-restart
docker compose -f compose.migration-base.yml down
docker compose -f compose.migration-base.yml up -d --wait --wait-timeout 360
customers > runtime/ci/customers-after-restart
cmp runtime/ci/customers-before-restart runtime/ci/customers-after-restart
docker compose -f compose.migration-base.yml run --rm --no-deps notifications-worker python -m app.smoke_registration
echo 'PASS: raw clone boot, non-root initialization and restart persistence.'

mkdir -p runtime/faults runtime/probes
chmod 777 runtime/probes
# Independent legacy-data fixture, confined to this runner and project namespace.
docker compose -f compose.migration-base.yml down --volumes --remove-orphans
python3 - <<'PY'
from pathlib import Path
import secrets
keys=('NOTIFICATIONS_DB_PASSWORD','RABBITMQ_PASSWORD','JWT_SECRET','KEYCLOAK_ADMIN_PASSWORD','PROVISIONER_CLIENT_SECRET','LEGACY_SOURCE_ID')
text=''.join(key+'='+secrets.token_hex(24)+'\n' for key in keys)
text+='JWT_ISSUER=http://localhost:8080/auth/realms/homeservice\n'
text+='JWT_JWKS_URL=http://keycloak:8080/auth/realms/homeservice/protocol/openid-connect/certs\n'
Path('.env.notifications').write_text(text)
PY
docker compose --env-file .env.notifications -f compose.notifications.yml up --build -d --wait --wait-timeout 360
docker compose --env-file .env.notifications -f compose.notifications.yml run --build --rm --no-deps keycloak-config
docker compose --env-file .env.notifications -f compose.notifications.yml run --rm --no-deps notifications-worker python -m app.smoke_registration
customers > runtime/ci/customers-before-adoption
docker compose --env-file .env.notifications -f compose.notifications.yml down
docker compose -f compose.migration-base.yml up --build -d --wait --wait-timeout 360
customers > runtime/ci/customers-after-adoption
cmp runtime/ci/customers-before-adoption runtime/ci/customers-after-adoption
docker compose -f compose.migration-base.yml run --rm --no-deps notifications-worker python -m app.smoke_registration
echo 'PASS: existing credentials adopted and domain data preserved.'
