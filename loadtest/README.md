k6 (grafana/k6:0.55.0) ingest + upload load tests. Run through the demo helper:

    scripts/demo/run.sh storm            # or: normal | peak via PROFILE env in the helper
    docker compose run --rm -T -e PROFILE=peak demo shell   # then: k6 run /repo/loadtest/ingest.js

Profiles (`PROFILE`): normal = `BASE_RATE` (default 2 req/s), peak x5, storm x10, each with concurrent
small OUTAGE_RECORD uploads (1 / 3 / 8 per second). One api-ingest replica saturates near 35 req/s on a dev laptop. Thresholds: ingest p95 < 250 ms, error rate < 1 %. JSON summary:
`loadtest/results/<profile>.json`. Needs env `OPERATOR_PASSWORD`, `SIMULATOR_TOKEN` (the demo
scripts read both from /run/secrets).
