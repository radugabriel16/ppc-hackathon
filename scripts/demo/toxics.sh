#!/bin/sh
# Usage: toxics.sh {latency|loss|bandwidth|reset_peer|clear}  (proxy "degraded": :8443 -> nginx:443)
set -eu
project="${COMPOSE_PROJECT_NAME:-filegrid}"
id=$(docker ps -q --filter "label=com.docker.compose.project=$project" \
  --filter "label=com.docker.compose.service=toxiproxy")
[ -n "$id" ] || { echo "toxiproxy is not running" >&2; exit 1; }
cli() { docker exec "$id" /toxiproxy-cli "$@"; }
drop() { cli toxic delete -n "$1" degraded >/dev/null 2>&1 || true; }
case "${1:-}" in
  latency)    drop lat;  cli toxic add -t latency -n lat -u -a latency=150 -a jitter=50 degraded ;;
  bandwidth)  drop bw;   cli toxic add -t bandwidth -n bw -u -a rate=8192 degraded ;;
  loss)       drop loss; cli toxic add -t limit_data -n loss -u -a bytes=25165824 degraded ;;
  reset_peer) drop rst;  cli toxic add -t reset_peer -n rst -u -a timeout=4000 degraded ;;
  clear)      for n in lat bw loss rst; do drop "$n"; done; echo "toxics cleared" ;;
  *) echo "usage: $0 {latency|loss|bandwidth|reset_peer|clear}" >&2; exit 2 ;;
esac
