#!/bin/sh
# Runs inside the helper container. The repo is mounted at $DEMO_REPO (same path as on the host).
set -eu
demo="${1:-}"
shift || true
dir="$DEMO_REPO/scripts/demo"
export PYTHONPATH="$dir/lib"
case "$demo" in
  toxics) exec sh "$dir/toxics.sh" "$@" ;;
  restore) exec python3 -c 'import fg; fg.restore_stack(); print("stack restored")' ;;
  shell) exec sh ;;
  *) test -f "$dir/$demo.py" || { echo "unknown demo: $demo" >&2; exit 2; }
     exec python3 "$dir/$demo.py" "$@" ;;
esac
