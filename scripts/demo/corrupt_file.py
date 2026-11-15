"""Demo: flip one stored byte in S3 / FTP / BYTEA -> download refused, CORRUPT, IntegrityFailure alert."""
import ftplib, io, json, time
import fg


def flip_s3(fid):
    fg.aws("s3", "cp", f"s3://filegrid/{fid}", f"/tmp/{fid}")
    b = bytearray(open(f"/tmp/{fid}", "rb").read())
    b[-1] ^= 1
    open(f"/tmp/{fid}", "wb").write(b)
    fg.aws("s3", "cp", f"/tmp/{fid}", f"s3://filegrid/{fid}")


def flip_ftp(fid):
    with ftplib.FTP() as f:
        f.connect("ftp", 2121, timeout=15)
        f.login("filegrid", fg.secret("ftp_password"))
        buf = io.BytesIO()
        f.retrbinary(f"RETR {fid}", buf.write)
        data = bytearray(buf.getvalue())
        data[-1] ^= 1
        f.storbinary(f"STOR {fid}", io.BytesIO(bytes(data)))


def flip_db(fid):
    fg.psql("storage", "update file_contents set content = set_byte(content, length(content)-1, "
            f"get_byte(content, length(content)-1) # 1) where file_id='{fid}'")


def run():
    c = fg.Client()
    ing = fg.Ingest(c)
    fg.on_exit(lambda: fg.cleanup_files(fg.RUN))
    case = c.get("/connection-cases")["items"][0]
    dtype = c.get("/document-types")[0]
    a = c.asset()
    doc_meta = {"category": "CONNECTION_DOCUMENT", "caseId": case["id"], "documentTypeId": dtype["id"]}
    targets = []
    r = c.req("POST", "/files", 201, files={"file": (f"{fg.RUN}-doc.bin", b"private-document-bytes" * 500, "application/octet-stream"),
                                            "metadata": (None, json.dumps(doc_meta), "application/json")}).json()
    targets.append(("S3", "CONNECTION_DOCUMENT", "s3", r["id"], flip_s3))
    r = c.upload_outage(b"outage-bytes" * 500, f"{fg.RUN}-outage.bin").json()
    targets.append(("FTP", "OUTAGE_RECORD", r["storageBackend"], r["id"], flip_ftp if r["storageBackend"] == "ftp" else flip_s3))
    body = ing.body(20_000)
    assert ing.post(body=body).status_code == 201
    mid = fg.psql("catalog", f"select file_id from meter_readings where reading_key='{body['readingKey']}'")
    fg.on_exit(lambda: (fg.psql("catalog", f"delete from meter_readings where file_id='{mid}'"),
                        fg.psql("storage", f"delete from file_contents where file_id='{mid}'"),
                        fg.psql("catalog", f"delete from files where id='{mid}'")))
    targets.append(("BYTEA", "METER_READING", "db", mid, flip_db))
    before = fg.prom_vec("sum by (category,storage)(filegrid_integrity_failures_total)")
    for label, category, storage, fid, flip in targets:
        ok = c.req("GET", f"/files/{fid}/verify", 200).json()["valid"]
        flip(fid)
        d = c.req("GET", f"/files/{fid}/download")
        st = c.get(f"/files/{fid}")["status"]
        fg.check(f"{label}: byte flipped -> download refused, CORRUPT",
                 ok and d.status_code == 409 and st == "CORRUPT", f"verify-before={ok} download={d.status_code} status={st}")
    for label, category, storage, fid, _ in targets:
        def firing(category=category, storage=storage):
            return fg.prom(f'count(ALERTS{{alertname="IntegrityFailure",category="{category}",storage="{storage}",alertstate="firing"}})')
        existed = (("category", category), ("storage", storage)) in before
        q = f'sum(filegrid_integrity_failures_total{{category="{category}",storage="{storage}"}})'
        prev = before.get((("category", category), ("storage", storage)), 0)
        now = fg.wait_for(lambda: (fg.prom(q) or 0) > prev and fg.prom(q), 60, every=3) or fg.prom(q)
        hit = fg.wait_for(firing, 120, every=5) if existed else None
        if existed:
            fg.check(f"{label}: IntegrityFailure firing", bool(hit), f"{category}/{storage}, counter {prev:.0f}->{now:.0f}")
        else:
            fg.check(f"{label}: integrity counter incremented", bool(now and now >= 1), f"{category}/{storage} counter={now}")
            fg.info("IntegrityFailure cannot fire for a first-ever series (increase() of a new counter is 0); see MERGE NOTES")
    mail = [s for s in fg.mail_subjects() if "IntegrityFailure" in s and "FIRING" in s]
    fg.check("IntegrityFailure mails in mailpit", bool(mail), f"{len(mail)} FIRING mails, latest: {mail[0] if mail else 'none'}")
    rec = [x for x in fg.recent_alerts(c) if "ntegrity" in x["message"]]
    fg.check("alerts/recent has integrity alerts", bool(rec), f"{len(rec)}; {rec[0]['message'] if rec else ''}")


fg.main(run)
