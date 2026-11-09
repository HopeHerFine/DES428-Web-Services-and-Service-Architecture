#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
compose() { docker compose "$@"; }
fixture() { compose run --rm --no-deps -T resilience-fixture python -m app.resilience_fixture "$@"; }
reset_fault() {
    flag=$(mktemp runtime/faults/notifications.XXXXXX)
    printf '%s\n' '{"mode":"none"}' > "$flag"
    chmod 0644 "$flag"
    mv -f "$flag" runtime/faults/notifications.json
}
mkdir -p runtime/faults runtime/probes
reset_fault
compose build resilience-fixture
cleanup() {
    reset_fault
    fixture cleanup
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
fixture cleanup
fixture prepare
compose run --rm --no-deps -T resilience-probe
fixture verify