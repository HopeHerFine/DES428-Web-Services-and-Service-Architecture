#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
docker compose run --build --rm --no-deps -T security-probe python -m app.security_probe