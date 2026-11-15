"""Demo: ingest load x10 (k6) -> meter p95 within SLO, rejections only in the overloaded category."""
import json, os, time
import fg
from k6run import k6

DURATION = os.environ.get("STORM_DURATION", "60")
SLO = 0.25


def run():
    fg.Client()  # fail fast on credentials
    rej0 = fg.prom_vec("sum by (category)(filegrid_requests_rejected_total)")
    t0 = time.time()
    rc, out, err = k6("ingest.js", PROFILE="storm", DURATION=f"{DURATION}s")
    took = int(time.time() - t0) + 25
    fg.info(out.splitlines()[-1] if out else err)
    time.sleep(25)  # let Prometheus scrape the tail
    win = f"{took + 20}s"
    p95 = fg.prom('histogram_quantile(0.95, sum by (le)(rate(filegrid_storage_operation_duration_seconds_bucket'
                  f'{{category="METER_READING"}}[{win}])))')
    fg.check("METER_READING p95 within SLO (Prometheus)", p95 is not None and p95 <= SLO,
             f"p95={p95 * 1000:.0f}ms <= {SLO * 1000:.0f}ms" if p95 is not None else "no data")
    rej1 = fg.prom_vec("sum by (category)(filegrid_requests_rejected_total)")
    delta = {dict(k).get("category"): rej1[k] - rej0.get(k, 0) for k in rej1}
    fg.info("bulkhead rejections (delta): " + (json.dumps({k: v for k, v in delta.items() if v}) or "none"))
    fg.check("no rejections outside overloaded category (METER_READING untouched)",
             delta.get("METER_READING", 0) == 0 and all(v == 0 for k, v in delta.items() if k != "OUTAGE_RECORD"),
             f"METER_READING={delta.get('METER_READING', 0):.0f} OUTAGE_RECORD={delta.get('OUTAGE_RECORD', 0):.0f}")
    summ = json.load(open(f"{os.environ['DEMO_REPO']}/loadtest/results/storm.json"))["metrics"]
    errs = summ["ingest_errors"]["values"]["rate"]
    fg.check("k6 ingest error rate < 1% and thresholds", errs < 0.01 and rc == 0,
             f"ingest errors {errs * 100:.2f}% k6 exit={rc} reqs/s={summ['http_reqs']['values']['rate']:.0f}")


fg.main(run)
