#!/bin/sh
set -eu
test "${GITHUB_ACTIONS:-}" = true || { echo 'Disposable CI runner only.' >&2; exit 1; }
export COMPOSE_PROJECT_NAME=payments-cutover-ci
mkdir -p runtime/payments-cutover
base() { docker compose -f compose.migration-base.yml "$@"; }
tools() { docker compose -f compose.migration-base.yml -f compose.payments.yml -f compose.payments-cutover.yml "$@"; }
cleanup() {
  code=$?
  if [ "$code" -ne 0 ]; then tools logs --no-color --tail 80; fi
  # Operator copies and backups are retained; the disposable runner is discarded.
  tools down --remove-orphans
}
trap cleanup EXIT
base up --build -d --wait --wait-timeout 360
base run --rm --no-deps -e CUTOVER_FIXTURE=synthetic notifications-worker python -m app.seed_payments_cutover
pwsh -NoProfile -File switch-payments.ps1 -PauseBeforeOpen
if curl -fsS --max-time 3 http://localhost:8080/gateway-health; then
  echo 'Public ingress was unexpectedly open before release' >&2; exit 1
fi
pwsh -NoProfile -File switch-payments.ps1 -RollbackBeforeOpen
tools run --rm --no-deps -e GATEWAY_CONNECT_HOST=gateway cutover-read-check python -m app.check_payments_cutover --legacy
pwsh -NoProfile -File switch-payments.ps1
run_id=$(python3 -c 'import json;print(json.load(open("runtime/payments-cutover/active.json"))["run_id"])')
docker compose -f compose.migration-base.yml -f compose.payments.yml -f "runtime/payments-cutover/$run_id/volume.json" run --rm --no-deps notifications-worker python -m app.smoke_payments
if pwsh -NoProfile -File switch-payments.ps1 -RollbackBeforeOpen; then
  echo 'Rollback after public release was unexpectedly permitted' >&2; exit 1
fi
pwsh -NoProfile -File start-payments.ps1
echo 'PASS: legacy history cutover, private verification, pre-release rollback, retained copies and forward restart.'
