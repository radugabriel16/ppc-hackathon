#!/usr/bin/env bash
# Run from the repository root against an already-running Compose stack.
set -euo pipefail

log=$(mktemp)
restore_ftp=0
compose=(docker compose -f docker-compose.yml -f backend/tests/compose.yml)

cleanup() {
    result=$?
    trap - EXIT
    if [ "$restore_ftp" -eq 1 ]; then
        if ! docker compose up -d --no-deps --no-recreate --wait --wait-timeout 60 ftp >>"$log" 2>&1; then
            tail -n 40 "$log"
            result=1
        fi
    fi
    rm -f "$log"
    exit "$result"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if ! docker compose build -q api-files >"$log" 2>&1; then
    tail -n 40 "$log"
    exit 1
fi
if ! "${compose[@]}" build -q storage-tests >"$log" 2>&1; then
    tail -n 40 "$log"
    exit 1
fi

"${compose[@]}" run --rm --no-deps -T storage-tests \
    python -m pytest -q -p no:cacheprovider -m 'not ftp_down'

restore_ftp=1
docker compose stop -t 5 ftp
"${compose[@]}" run --rm --no-deps -T storage-tests \
    python -m pytest -q -p no:cacheprovider -m ftp_down
