#!/bin/sh
set -eu
project_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$project_root"
compose() { docker compose "$@"; }
compose config --quiet
compose run --rm --no-deps --entrypoint /bin/promtool prometheus check config /etc/prometheus/prometheus.yml
compose run --rm --no-deps --entrypoint /bin/promtool prometheus check rules /etc/prometheus/rules/filegrid.yml
compose run --rm --no-deps --entrypoint /bin/promtool prometheus test rules /etc/prometheus/rules/tests/filegrid.test.yml
compose run --rm --no-deps --entrypoint /bin/amtool alertmanager check-config /etc/alertmanager/alertmanager.yml
python3 infra/observability/verify_runtime.py
