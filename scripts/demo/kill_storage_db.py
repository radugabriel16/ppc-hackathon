"""Demo: storage-db down -> ingest 503 + Retry-After; restart -> retried readings land, counts match."""
import time
import fg


def run():
    c = fg.Client()
    ing = fg.Ingest(c)
    meter = c.get("/meters?size=100")["items"][0]
    code = meter["externalCode"]

    def total():
        return c.get(f"/meter-readings?meterId={meter['id']}&size=1")["totalElements"]

    base = total()
    batch = [ing.body(10_000 + i, code) for i in range(30)]
    ok_before = sum(ing.post(body=b).status_code == 201 for b in batch[:10])
    fg.check("ingest OK before outage", ok_before == 10, f"201 x{ok_before}/10")
    fg.on_exit(lambda: fg.start("storage-db") if not fg.cids("storage-db", all_=False) else None)
    fg.stop("storage-db")
    fg.info("storage-db stopped")
    resp = [ing.post(body=b) for b in batch[10:20]]
    codes = [r.status_code for r in resp]
    retry_after = {r.headers.get("Retry-After") for r in resp if r.status_code == 503}
    fg.check("ingest returns 503 + Retry-After", codes.count(503) == 10 and None not in retry_after,
             f"503 x{codes.count(503)}/10 Retry-After={sorted(map(str, retry_after))}")
    during = total()
    fg.check("no partial rows while down", during == base + ok_before, f"count {base}->{during}")
    fg.start("storage-db")
    fg.check("storage-db healthy again", fg.wait_healthy("storage-db"), "healthy")

    def deliver(bs):
        pending = list(bs)
        for _ in range(60):
            pending = [b for b in pending if ing.post(body=b).status_code not in (200, 201)]
            if not pending:
                return 0
            time.sleep(2)
        return len(pending)

    t0 = time.time()
    left = deliver(batch[10:20] + batch[20:30])
    fg.check("redelivered + new readings accepted after restart", left == 0,
             f"{20 - left}/20 accepted, {time.time() - t0:.0f}s to recover")
    expected = ok_before + 20
    final = total()
    fg.check("counts match", final - base == expected, f"stored {final - base} == accepted {expected}")
    fg.not_verified("simulator outbox", "no simulator service exists in this stack")


fg.main(run)
