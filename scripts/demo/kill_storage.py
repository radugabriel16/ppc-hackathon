"""Demo: FTP down -> OUTAGE_RECORD falls back to S3, meter ingest unaffected, alert fires, recovery closes circuit."""
import time
import fg

CIRCUIT = 'max(filegrid_circuit_state{storage="ftp"})'


def run():
    c = fg.Client()
    ing = fg.Ingest(c)
    fg.on_exit(lambda: fg.cleanup_files(fg.RUN))
    r = c.upload_outage(b"baseline-" * 100, f"{fg.RUN}-base.bin").json()
    fg.check("baseline OUTAGE_RECORD on FTP", r["storageBackend"] == "ftp" and not r["fallbackUsed"],
             f"backend={r['storageBackend']} fallbackUsed={r['fallbackUsed']}")
    fg.on_exit(lambda: fg.start("ftp") if not fg.cids("ftp", all_=False) else None)
    fg.stop("ftp")
    fg.info("ftp stopped")
    lat, fb, bad = [], 0, 0
    for i in range(12):
        t = time.time()
        resp = c.upload_outage(f"outage-{i}".encode() * 200, f"{fg.RUN}-o{i}.bin")
        lat.append(time.time() - t)
        if resp.status_code == 201 and resp.json()["storageBackend"] == "s3" and resp.json()["fallbackUsed"]:
            fb += 1
        else:
            bad += 1
    fg.check("outage uploads fall back to S3 (fallbackUsed=true)", fb == 12,
             f"{fb}/12 ok, {bad} bad, max {max(lat):.2f}s, median {sorted(lat)[6]:.2f}s")
    codes = [ing.post().status_code for _ in range(20)]
    fg.check("meter ingest unaffected", codes.count(201) == 20, f"201 x{codes.count(201)}/20")
    state = fg.prom(CIRCUIT)
    fg.info(f"circuit_state{{ftp}} max now = {state}")

    def firing():  # keep light traffic so the breaker keeps probing/open
        c.upload_outage(b"probe" * 50, f"{fg.RUN}-p{time.time_ns()}.bin")
        return fg.prom('count(ALERTS{alertname="StorageCircuitOpen",storage="ftp",alertstate="firing"})')

    t0 = time.time()
    fired = fg.wait_for(firing, 300, every=5)
    fg.check("StorageCircuitOpen firing in Prometheus", bool(fired), f"after {time.time() - t0:.0f}s")
    mail = fg.wait_for(lambda: [s for s in fg.mail_subjects() if "StorageCircuitOpen" in s and "FIRING" in s] or None, 90)
    fg.check("StorageCircuitOpen mail in mailpit", bool(mail), mail[0] if mail else "none")
    rec = fg.wait_for(lambda: [a for a in fg.recent_alerts(c) if "circuit" in a["message"].lower()] or None, 60)
    fg.check("alert in /api/v1/alerts/recent", bool(rec), rec[0]["message"] if rec else "none")
    fg.start("ftp")
    fg.check("ftp healthy again", fg.wait_healthy("ftp"), "healthy")

    def closed():
        r = c.upload_outage(b"after" * 50, f"{fg.RUN}-after{time.time_ns()}.bin").json()
        return r if r["storageBackend"] == "ftp" and not r["fallbackUsed"] else None

    t0 = time.time()
    back = fg.wait_for(closed, 90, every=3)
    fg.check("uploads return to FTP", bool(back), f"after {time.time() - t0:.0f}s")
    gauge = fg.wait_for(lambda: fg.prom(CIRCUIT) == 0 or None, 60)
    fg.check("circuit closed (gauge 0)", bool(gauge), f"circuit_state={fg.prom(CIRCUIT)}")


fg.main(run)
