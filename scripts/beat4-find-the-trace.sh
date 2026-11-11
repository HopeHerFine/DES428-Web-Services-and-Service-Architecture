#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
docker compose build notifications-worker
printf '%s\n' 'Notifications trace:'
docker compose run --rm --no-deps -T notifications-worker python -m app.observability_probe
printf '%s\n' 'Payments trace:'
docker compose run --rm --no-deps -T notifications-worker python -m app.payments_observability_probe
printf '%s\n' 'Open http://localhost:16686 and paste trace_id into Lookup by Trace ID.'
