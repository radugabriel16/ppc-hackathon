"""Demo: scale api-ingest 1 -> 3 under load -> throughput up, no errors, Prometheus scrapes all 3."""
import json, os, time
import fg
from k6run import k6

VUS = os.environ.get("SCALE_VUS", "40")


def measure(name):
    rc, out, err = k6("throughput.js", NAME=name, VUS=VUS, DURATION="30s")
    s = json.load(open(f"{os.environ['DEMO_REPO']}/loadtest/results/{name}.json"))["metrics"]
    return rc, s["http_reqs"]["values"]["rate"], s["ingest_errors"]["values"]["rate"], s["http_req_duration{kind:ingest}"]["values"]["p(95)"]


def run():
    fg.Client()
    fg.on_exit(lambda: fg.scale("api-ingest", 1))
    n0 = len(fg.cids("api-ingest", all_=False))
    rc1, r1, e1, p1 = measure("scale_1")
    fg.info(f"{n0} replica: {r1:.0f} req/s, p95 {p1:.0f}ms")
    fg.scale("api-ingest", 3)
    fg.check("3 api-ingest replicas healthy", fg.wait_healthy("api-ingest") and len(fg.cids("api-ingest", all_=False)) == 3, "3 healthy")
    up = fg.wait_for(lambda: fg.prom('count(up{job="api-ingest"} == 1)') == 3 or None, 90, every=5)
    n_up = fg.prom('count(up{job="api-ingest"} == 1)')
    fg.check("Prometheus scrapes all 3", bool(up), f"up targets = {n_up}")
    time.sleep(12)  # nginx re-resolves api-ingest (valid=10s)
    rc3, r3, e3, p3 = measure("scale_3")
    fg.info(f"3 replicas: {r3:.0f} req/s, p95 {p3:.0f}ms")
    fg.check("throughput increased", r3 > r1 * 1.15, f"{r1:.0f} -> {r3:.0f} req/s ({r3 / r1:.2f}x)")
    fg.check("no errors", e1 < 0.01 and e3 < 0.01 and rc1 == 0 and rc3 == 0, f"errors {e1 * 100:.2f}% / {e3 * 100:.2f}%")


fg.main(run)
