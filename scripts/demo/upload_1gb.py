"""Demo: 1 GB resumable upload; reports peak RSS of api-files (bounded memory)."""
import os, time
import fg

SIZE = int(os.environ.get("UPLOAD_MIB", "1024")) * fg.MIB
LIMIT = int(os.environ.get("RSS_LIMIT_MIB", "512"))


def run():
    fg.on_exit(lambda: fg.cleanup_files(fg.RUN))
    c = fg.Client()
    fg.rss_reset()
    base = fg.rss_mib(field="VmRSS")
    up = fg.Resumable(c, SIZE).create()
    fg.info(f"{SIZE // fg.MIB} MiB in {up.total} parts of {up.chunk // fg.MIB} MiB; api-files RSS before: {base:.0f} MiB")
    t0 = time.time()
    up.run()
    el = time.time() - t0
    fg.check("all parts uploaded", len(up.received()) == up.total, f"{up.total} parts, {SIZE / fg.MIB / el:.1f} MiB/s, {up.retries} retries")
    st, took = up.complete()
    fg.check("file READY after server-side SHA-256 verify", st == "READY", f"{st} in {took:.0f}s")
    v = c.get(f"/files/{up.file_id}/verify")
    fg.check("/verify valid (full re-read)", v["valid"] and v["actualSha256"] == up.digest, v["actualSha256"][:16] + "...")
    peak = fg.rss_mib(field="VmHWM")
    fg.check(f"api-files peak RSS < {LIMIT} MiB", peak < LIMIT, f"peak RSS {peak:.0f} MiB (before {base:.0f} MiB), file {SIZE // fg.MIB} MiB")


fg.main(run)
