#!/bin/sh
set -eu
test "${GITHUB_ACTIONS:-}" = true || { echo 'Disposable CI runner only.' >&2; exit 1; }
export COMPOSE_PROJECT_NAME=payments-ci
compose() { docker compose "$@"; }
cleanup() {
  code=$?
  if [ "$code" -ne 0 ]; then compose logs --no-color --tail 70; fi
  compose down --volumes --remove-orphans
}
trap cleanup EXIT
mkdir -p runtime/faults runtime/probes
# The disposable fixture containers use a different UID from the runner.
chmod 0777 runtime/faults runtime/probes
compose config --quiet
compose up --build -d --wait --wait-timeout 360
for beat in scripts/beat[1-4]-*.sh; do sh "$beat"; done
compose exec -T edemand node -e 'const D=require("better-sqlite3");const db=new D("/app/data/edemand.db",{readonly:true});for(const t of ["payment_intents","transactions"]){if(db.prepare("SELECT COUNT(*) AS n FROM "+t).get().n!==0)throw Error("Legacy payment table was written: "+t);} console.log("PASS: no payment writes in Booking SQLite");'
compose restart payments payments-worker
compose up -d --wait --wait-timeout 360
compose run --rm --no-deps notifications-worker python -m app.smoke_payments
