#!/usr/bin/env bash
# Usage: scripts/demo/run.sh <demo|all|list|toxics ...|restore>   (host needs only Docker + compose)
set -uo pipefail
cd "$(dirname "$0")/../.." || exit 1
export DEMO_REPO="$PWD"
export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-filegrid}"
DEMOS="kill_storage kill_storage_db storm degrade_network corrupt_file scale_up upload_1gb"
run() { docker compose run --rm -T demo "$@"; }
restore() { run restore >/dev/null 2>&1 || true; }
case "${1:-list}" in
  list) echo "$DEMOS" ;;
  restore) run restore ;;
  toxics) shift; sh scripts/demo/toxics.sh "$@" ;;
  all)
    trap restore EXIT
    rc=0
    for d in $DEMOS; do
      echo "=== $d"; run "$d" || rc=1
    done
    exit $rc ;;
  *)
    trap restore EXIT
    run "$@" ;;
esac
