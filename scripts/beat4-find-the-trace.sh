#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
docker compose run --rm --no-deps -T notifications-worker python -m app.observability_probe
printf '%s\n' 'Open http://localhost:16686 and paste trace_id into Lookup by Trace ID.'