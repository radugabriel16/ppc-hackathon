"""Shared helpers for the FileGrid NFR demos (runs inside the demo helper container)."""
import atexit, hashlib, json, os, signal, subprocess, sys, time, uuid
from datetime import datetime, timedelta, timezone

import requests
import urllib3

urllib3.disable_warnings()
BASE = os.environ.get("DEMO_BASE", "https://nginx")
ORIGIN = os.environ.get("DEMO_ORIGIN", "https://localhost")
PROJECT = os.environ.get("COMPOSE_PROJECT_NAME", "filegrid")
PROM = "http://prometheus:9090"
MAILPIT = "http://mailpit:8025"
SECRETS = "/run/secrets"
COOKIE = "filegrid_session"
MIB = 1024 * 1024
RUN = "demo-" + uuid.uuid4().hex[:8]
_results = []
_cleanups = []


# ---- reporting -------------------------------------------------------------
def check(name, ok, detail=""):
    _results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'} {name}: {detail}", flush=True)
    return ok


def info(msg):
    print(f"     {msg}", flush=True)


def not_verified(name, why):
    print(f"NOT VERIFIED {name}: {why}", flush=True)


def finish():
    ok = bool(_results) and all(_results)
    print(f"RESULT {'PASS' if ok else 'FAIL'} ({sum(_results)}/{len(_results)} checks)", flush=True)
    return 0 if ok else 1


# ---- cleanup / restore (runs even on failure or signal) ----------------------
def on_exit(fn):
    _cleanups.append(fn)


def _run_cleanups(*_):
    while _cleanups:
        try:
            _cleanups.pop()()
        except Exception as exc:  # noqa: BLE001
            print(f"cleanup error: {exc}", file=sys.stderr)


def main(fn):
    atexit.register(_run_cleanups)
    atexit.register(restore_stack)
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: sys.exit(130))
    try:
        fn()
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        check("unexpected error", False, repr(exc))
    sys.exit(finish())


# ---- docker ------------------------------------------------------------------
def sh(*cmd, check_rc=True, timeout=300, input=None):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, input=input)
    if check_rc and r.returncode:
        raise RuntimeError(f"{' '.join(cmd[:4])}: {r.stderr.strip()[-400:]}")
    return r.stdout.strip()


def cids(service, all_=True):
    out = sh("docker", "ps", *(["-a"] if all_ else []), "-q",
             "--filter", f"label=com.docker.compose.project={PROJECT}",
             "--filter", f"label=com.docker.compose.service={service}", check_rc=False)
    return out.split()


def cid(service):
    ids = cids(service)
    if not ids:
        raise RuntimeError(f"no container for service {service}")
    return ids[0]


def service_exists(service):
    return bool(cids(service))


def health(c):
    return sh("docker", "inspect", "-f", "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}", c,
              check_rc=False)


def stop(service):
    sh("docker", "stop", "-t", "5", *cids(service, all_=False))


def start(service):
    sh("docker", "start", *cids(service))


def wait_healthy(service, timeout=120):
    end = time.time() + timeout
    while time.time() < end:
        ids = cids(service, all_=False)
        if ids and all(health(c) == "healthy" for c in ids):
            return True
        time.sleep(2)
    return False


LONG_RUNNING = ["catalog-db", "storage-db", "seaweedfs", "ftp", "api-ingest", "api-files", "worker", "nginx",
                "toxiproxy", "prometheus", "alertmanager", "mailpit", "grafana", "loki", "alloy", "tempo"]


def restore_stack():
    """Best-effort: clear toxics, start every stopped service, scale api-ingest back to 1."""
    try:
        subprocess.run(["sh", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "toxics.sh"), "clear"],
                       capture_output=True, timeout=30)
        for svc in LONG_RUNNING:
            for c in cids(svc):
                if sh("docker", "inspect", "-f", "{{.State.Running}}", c, check_rc=False) != "true":
                    sh("docker", "start", c, check_rc=False)
        if len(cids("api-ingest", all_=False)) > 1:
            scale("api-ingest", 1)
    except Exception as exc:  # noqa: BLE001
        print(f"restore error: {exc}", file=sys.stderr)


def scale(service, n):
    sh("docker", "compose", "-p", PROJECT, "up", "-d", "--no-deps", "--no-build", "--no-recreate",
       "--scale", f"{service}={n}", service, timeout=300)


# ---- secrets -----------------------------------------------------------------
def secret(name):
    return open(f"{SECRETS}/{name}").read().strip()


def demo_user(name="operator"):
    for line in open(f"{SECRETS}/demo-users.txt"):
        user, _, pw = line.partition(":")
        if user.strip() == name:
            return pw.strip()
    raise KeyError(name)


# ---- API client (one session per script) -------------------------------------
class Client:
    def __init__(self, base=BASE, user="operator"):
        self.base, self.s = base, requests.Session()
        self.s.verify = False
        self.login(user)

    def login(self, user):
        r = self.s.post(f"{self.base}/api/v1/auth/login", json={"username": user, "password": demo_user(user)},
                        headers={"Origin": ORIGIN}, timeout=30)
        if r.status_code != 200:
            raise RuntimeError(f"login {r.status_code}: {r.text[:200]} (login is rate-limited; wait a minute)")

    def csrf(self):
        return self.s.cookies.get("filegrid_csrf", "")

    def req(self, method, path, expected=None, **kw):
        h = {"Origin": ORIGIN, **kw.pop("headers", {})}
        if method != "GET":
            h["X-CSRF-Token"] = self.csrf()
        kw.setdefault("timeout", 120)
        r = self.s.request(method, f"{self.base}/api/v1{path}", headers=h, **kw)
        if expected is not None and r.status_code != expected:
            raise RuntimeError(f"{method} {path}: expected {expected}, got {r.status_code} {r.text[:200]}")
        return r

    def get(self, path, **kw):
        return self.req("GET", path, 200, **kw).json()

    def asset(self):
        return self.get("/assets")["items"][0]

    def upload_outage(self, content, name=None):
        a = self.asset()
        meta = {"category": "OUTAGE_RECORD", "assetId": a["id"], "regionId": a["regionId"],
                "startedAt": "2026-01-01T10:00:00Z", "severity": "HIGH"}
        r = self.req("POST", "/files", files={"file": (name or f"{RUN}-outage.bin", content, "application/octet-stream"),
                                              "metadata": (None, json.dumps(meta), "application/json")})
        return r


# ---- meter ingest ----------------------------------------------------------------
class Ingest:
    """Bearer-token ingest through nginx, unique reading keys per run."""

    def __init__(self, client, base=BASE):
        self.token = secret("simulator_token")
        self.meters = [m["externalCode"] for m in client.get("/meters?size=100")["items"]]
        self.base, self.n = base, 0
        self.t0 = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(days=30)
        self.http = requests.Session()
        self.http.verify = False

    def body(self, i, code=None):
        n = 1 if code else len(self.meters)
        code = code or self.meters[i % len(self.meters)]
        start = self.t0 + timedelta(minutes=15 * (i // n) + int(RUN[-4:], 16) % 1000 * 1000)
        iso = start.isoformat().replace("+00:00", "Z")
        return {"meterExternalCode": code, "readingKey": f"{code}:{iso}", "seq": i, "intervalStart": iso,
                "intervalEnd": (start + timedelta(minutes=15)).isoformat().replace("+00:00", "Z"), "energyKwh": 1.25}

    def post(self, i=None, body=None):
        if body is None:
            i = self.n if i is None else i
            self.n += 1
            body = self.body(i)
        return self.http.post(f"{self.base}/api/v1/meter-readings/ingest", json=body, timeout=30,
                              headers={"Authorization": f"Bearer {self.token}"})


# ---- Prometheus / Mailpit / alerts -------------------------------------------------
def prom(query):
    r = requests.get(f"{PROM}/api/v1/query", params={"query": query}, timeout=15).json()
    res = r["data"]["result"]
    return float(res[0]["value"][1]) if res else None


def prom_vec(query):
    r = requests.get(f"{PROM}/api/v1/query", params={"query": query}, timeout=15).json()
    return {tuple(sorted(x["metric"].items())): float(x["value"][1]) for x in r["data"]["result"]}


def mail_subjects():
    r = requests.get(f"{MAILPIT}/api/v1/messages", params={"limit": 200}, timeout=15).json()
    return [m["Subject"] for m in r["messages"]]


def wait_for(fn, timeout, every=3):
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(every)
    return None


def alert_in_mail(alertname, status="FIRING", since_count=0):
    return wait_for(lambda: [s for s in mail_subjects() if alertname in s and status in s] or None, 1)


def recent_alerts(client):
    return client.get("/alerts/recent")


# ---- resumable upload ----------------------------------------------------------------
class Resumable:
    """Deterministic parts (no disk): part i = 1 MiB random block repeated, tagged with i."""

    def __init__(self, client, size, name=None, chunk=None):
        self.c, self.size = client, size
        self.block = os.urandom(MIB)
        self.name = name or f"{RUN}-video.bin"
        self.chunk = chunk
        self.retries = 0

    def part_bytes(self, i):
        start = (i - 1) * self.chunk
        n = min(self.chunk, self.size - start)
        full, rest = divmod(n, MIB)
        data = bytearray(self.block * full + self.block[:rest])
        data[:8] = i.to_bytes(8, "big")
        return bytes(data)

    def total_sha(self, parts):
        h = hashlib.sha256()
        for i in range(1, parts + 1):
            h.update(self.part_bytes(i))
        return h.hexdigest()

    def create(self):
        a = self.c.asset()
        # chunk size is policy-defined; ask server first with the real create call
        self.chunk = self.chunk or 16 * MIB
        parts = -(-self.size // self.chunk)
        self.digest = self.total_sha(parts)
        r = self.c.req("POST", "/uploads", 201, json={
            "category": "DRONE_VIDEO", "fileName": self.name, "sizeBytes": self.size, "sha256": self.digest,
            "metadata": {"category": "DRONE_VIDEO", "assetId": a["id"], "regionId": a["regionId"],
                         "recordedAt": "2026-01-01T10:00:00Z"}}).json()
        self.id, self.total = r["uploadId"], r["totalParts"]
        if r["chunkSize"] != self.chunk:  # server policy wins; recompute digest
            self.chunk = r["chunkSize"]
            self.digest = self.total_sha(self.total)
        return self

    def received(self):
        return set(self.c.get(f"/uploads/{self.id}")["receivedParts"])

    def put_part(self, i, attempts=40):
        data = self.part_bytes(i)
        sha = hashlib.sha256(data).hexdigest()
        for n in range(attempts):
            try:
                r = self.c.req("PUT", f"/uploads/{self.id}/parts/{i}", data=data, headers={
                    "X-Part-SHA256": sha, "Content-Type": "application/octet-stream"})
                if r.status_code == 200:
                    return
                if r.status_code not in (502, 503, 504):
                    raise RuntimeError(f"part {i}: {r.status_code} {r.text[:150]}")
            except requests.RequestException:
                pass
            self.retries += 1
            time.sleep(min(2, 0.3 * (n + 1)))
        raise RuntimeError(f"part {i}: gave up")

    def run(self, skip=()):
        """Upload missing parts (resumes using GET /uploads/{id}); returns after all parts are stored."""
        while True:
            try:
                have = self.received()
                break
            except requests.RequestException:
                self.retries += 1
                time.sleep(1)
        for i in range(1, self.total + 1):
            if i not in have and i not in skip:
                self.put_part(i)

    def complete(self, timeout=900):
        r = self.c.req("POST", f"/uploads/{self.id}/complete", 202, json={"sha256": self.digest}).json()
        self.file_id = r["fileId"]
        t0 = time.time()
        while time.time() - t0 < timeout:
            st = self.c.get(f"/files/{self.file_id}")["status"]
            if st in ("READY", "CORRUPT", "FAILED"):
                return st, time.time() - t0
            time.sleep(2)
        return "TIMEOUT", time.time() - t0

    def download_sha(self):
        h = hashlib.sha256()
        with self.c.req("GET", f"/files/{self.file_id}/download", 200, stream=True, timeout=300) as r:
            for chunk in r.iter_content(MIB):
                h.update(chunk)
        return h.hexdigest()


# ---- memory of api-files ---------------------------------------------------------------
def rss_reset(service="api-files"):
    sh("docker", "exec", cid(service), "sh", "-c", "echo 5 > /proc/1/clear_refs", check_rc=False)


def rss_mib(service="api-files", field="VmHWM"):
    out = sh("docker", "exec", cid(service), "sh", "-c", f"grep {field} /proc/1/status")
    return int(out.split()[1]) / 1024


# ---- DB / storage access for corruption + cleanup --------------------------------------
def psql(db, sql):
    host, user = ("catalog-db", "filegrid") if db == "catalog" else ("storage-db", "filegrid")
    name = "filegrid_catalog" if db == "catalog" else "filegrid_storage"
    env = {**os.environ, "PGPASSWORD": secret(f"{db}_db_password")}
    r = subprocess.run(["psql", "-h", host, "-U", user, "-d", name, "-At", "-c", sql], env=env,
                       capture_output=True, text=True, timeout=60)
    if r.returncode:
        raise RuntimeError(r.stderr.strip()[-300:])
    return r.stdout.strip()


def aws(*args, **kw):
    env = {**os.environ, "AWS_ACCESS_KEY_ID": secret("s3_access_key_id"),
           "AWS_SECRET_ACCESS_KEY": secret("s3_secret_access_key"), "AWS_DEFAULT_REGION": "us-east-1"}
    r = subprocess.run(["aws", "--endpoint-url", "http://seaweedfs:8333", *args], env=env,
                       capture_output=True, text=True, timeout=kw.get("timeout", 600))
    if r.returncode:
        raise RuntimeError(r.stderr.strip()[-300:])
    return r.stdout.strip()


def cleanup_files(prefix):
    """Delete demo files (catalog rows + stored bytes) whose original_name starts with prefix."""
    rows = psql("catalog", f"select id,storage_backend from files where original_name like '{prefix}%'")
    for line in filter(None, rows.splitlines()):
        fid, backend = line.split("|")
        try:
            if backend == "s3":
                aws("s3", "rm", f"s3://filegrid/{fid}")
            elif backend == "ftp":
                import ftplib
                with ftplib.FTP() as f:
                    f.connect("ftp", 2121, timeout=15); f.login("filegrid", secret("ftp_password")); f.delete(fid)
            else:
                psql("storage", f"delete from file_contents where file_id='{fid}'")
        except Exception:  # noqa: BLE001
            pass
    ids = ",".join(f"'{l.split('|')[0]}'" for l in rows.splitlines() if l)
    if ids:
        for t in ("client_documents", "outages", "video_inspections"):
            psql("catalog", f"delete from {t} where file_id in ({ids})")
        psql("catalog", f"delete from upload_parts where upload_id in (select id from upload_sessions where file_id in ({ids}))")
        psql("catalog", f"delete from upload_sessions where file_id in ({ids})")
        psql("catalog", f"delete from files where id in ({ids})")
    return len(rows.splitlines()) if rows else 0
