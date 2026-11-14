"""Check actual Docker health, datasource/dashboards, replica discovery and logs."""
import json
import subprocess
import time
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ["docker", "compose"]


def command(args):
    return subprocess.check_output(args, cwd=ROOT, stderr=subprocess.PIPE, text=True)


def ids(service):
    return command(COMPOSE + ["ps", "--status", "running", "-q", service]).split()


def retry(check, seconds=180):
    deadline = time.monotonic() + seconds
    while True:
        try:
            return check()
        except (AssertionError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
            if time.monotonic() >= deadline:
                raise RuntimeError(str(exc) if isinstance(exc, AssertionError) else "Container/API check failed; inspect service logs.") from None
            time.sleep(3)


def healthy():
    config = json.loads(command(COMPOSE + ["config", "--format", "json"]))
    for service, definition in config["services"].items():
        if service == "simulator":
            continue
        if service in ("init", "migrate", "s3-init"):
            completed = command(COMPOSE + ["ps", "-a", "-q", service]).split()
            assert completed, f"{service}: no one-shot container"
            for container in completed:
                state = json.loads(command(["docker", "inspect", "--format", "{{json .State}}", container]))
                assert state["Status"] == "exited" and state["ExitCode"] == 0, f"{service}: did not exit successfully"
            continue
        if definition.get("profiles"):
            continue
        containers = ids(service)
        assert containers, f"{service}: no running container"
        for container in containers:
            state = json.loads(command(["docker", "inspect", "--format", "{{json .State.Health}}", container]))
            assert state and state.get("Status") == "healthy", f"{service}: not healthy"


def prometheus_targets():
    data = json.loads(command(COMPOSE + ["exec", "-T", "prometheus", "/bin/wget", "-q", "-O", "-", "http://127.0.0.1:9090/api/v1/targets"]))
    targets = data["data"]["activeTargets"]
    required = ["api-ingest", "api-files", "worker"]
    for service in required:
        running = ids(service)
        assert running, f"{service}: no running replicas"
        found = [target for target in targets if target["labels"].get("job") == service]
        assert len(found) == len(running), f"{service}: discovered {len(found)} / {len(running)} running replicas"
        assert len({target["labels"]["instance"] for target in found}) == len(found), f"{service}: duplicate instance identities"
        assert all(target["health"] == "up" for target in found), f"{service}: a metrics target is DOWN"


# Keep credentials inside the container shell. They are never printed, passed in
# host command arguments, or included in subprocess error messages.
GRAFANA_GET = r'''
credential=$(printf '%s:%s' "$GF_SECURITY_ADMIN_USER" "$(cat "$GF_SECURITY_ADMIN_PASSWORD__FILE")" | base64 | tr -d '\n')
exec /usr/bin/wget -q -O - --header="Authorization: Basic $credential" "http://127.0.0.1:3000/grafana$1"
'''


def grafana_raw(path):
    return command(COMPOSE + ["exec", "-T", "grafana", "/bin/sh", "-ec", GRAFANA_GET, "-", path])


def grafana_get(path):
    return json.loads(grafana_raw(path))


def provisioned():
    for uid in ("prometheus", "loki"):
        health = grafana_get(f"/api/datasources/uid/{uid}/health")
        assert health.get("status") == "OK", f"Grafana datasource {uid}: not OK"
    # Grafana 11's Tempo backend does not implement CheckHealth; the datasource
    # uses Tempo's /api/echo through Grafana's proxy for its connection test.
    grafana_raw("/api/datasources/proxy/uid/tempo/api/echo")
    dashboards = sorted((ROOT / "infra/observability/grafana/dashboards").glob("*.json"))
    assert len(dashboards) == 5, "Expected the five FileGrid dashboards"
    for path in dashboards:
        uid = json.loads(path.read_text())["uid"]
        response = grafana_get(f"/api/dashboards/uid/{uid}")
        assert response["dashboard"]["uid"] == uid, f"Dashboard {uid}: not loaded"
        assert response["meta"].get("provisioned"), f"Dashboard {uid}: not provisioned"
    project = json.loads(command(COMPOSE + ["config", "--format", "json"]))["name"]
    query = urlencode({"query": '{compose_project=' + json.dumps(project) + '}', "limit": "1"})
    response = grafana_get("/api/datasources/proxy/uid/loki/loki/api/v1/query_range?" + query)
    assert response["data"]["result"], "No project container logs reached Loki through Alloy"


if __name__ == "__main__":
    retry(healthy)
    print("Stack services healthy; init/migrate/s3-init exited 0.")
    retry(prometheus_targets)
    print("Every running API/worker replica discovered and UP; simulator target is optional.")
    retry(provisioned)
    print("Three Grafana datasources healthy; five dashboards provisioned; Docker logs present in Loki.")
