"""Demo: large resumable upload through toxiproxy (latency + bandwidth cap + connection cuts) completes intact."""
import os, subprocess, time
import fg

SIZE = int(os.environ.get("DEGRADE_MIB", "100")) * fg.MIB


def toxics(arg):
    subprocess.run(["sh", os.path.join(os.path.dirname(os.path.abspath(__file__)), "toxics.sh"), arg],
                   check=True, capture_output=True)


def run():
    fg.on_exit(lambda: fg.cleanup_files(fg.RUN))
    c = fg.Client(base="https://toxiproxy:8443")
    up = fg.Resumable(c, SIZE).create()
    fg.info(f"{SIZE // fg.MIB} MiB, {up.total} parts of {up.chunk // fg.MIB} MiB, via toxiproxy:8443")
    for t in ("latency", "bandwidth", "loss"):
        toxics(t)
    t0 = time.time()
    up.run(skip=set(range(up.total // 2 + 1, up.total + 1)))
    have = len(up.received())
    fg.info(f"client 'crash' after {have} parts; resuming from GET /uploads/{{id}}")
    up.run()
    elapsed = time.time() - t0
    toxics("clear")
    fg.check("all parts uploaded despite degradation", len(up.received()) == up.total,
             f"{up.total} parts in {elapsed:.0f}s ({SIZE / fg.MIB / elapsed:.1f} MiB/s), {up.retries} retries")
    st, took = up.complete()
    fg.check("file READY after server-side verify", st == "READY", f"{st} in {took:.0f}s")
    got = up.download_sha()
    fg.check("download SHA-256 matches", got == up.digest, f"{got[:16]}... == {up.digest[:16]}...")
    v = c.get(f"/files/{up.file_id}/verify")
    fg.check("/verify valid", v["valid"], f"actual={v['actualSha256'][:16]}...")


fg.main(run)
