#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
docker compose run --rm --no-deps -T notifications-worker python -m app.smoke_gateway
docker compose run --rm --no-deps -T notifications-worker python -m app.smoke_payments