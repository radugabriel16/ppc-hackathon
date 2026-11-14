#!/usr/bin/env python3
"""Seed real demo observations, then exercise all four stats routes through nginx."""
import argparse
import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
import uuid
from http.cookiejar import CookieJar

from smoke_auth import container_python


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-seed", action="store_true")
    args = parser.parse_args()
    if not args.skip_seed:
        seeded = container_python(
            "import asyncio,json; from fixtures.seed_stats import seed_demo; "
            "print(json.dumps(asyncio.run(seed_demo())))"
        )
        assert seeded["meters"] == 3 and seeded["days"] == 3
    config = container_python("""
import json
from pathlib import Path
from app.core.settings import get_settings
s = get_settings()
print(json.dumps({"origin": str(s.app_origin).rstrip("/"),
 "passwords": {name: (Path(s.secrets_dir) / f"{name}_password").read_text().strip()
               for name in ("operator", "manager")}}))
""")
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE  # Local Compose uses its generated self-signed certificate.
    jar = CookieJar()
    client = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=context), urllib.request.HTTPCookieProcessor(jar),
    )
    run_id = f"stats-smoke-{uuid.uuid4().hex}"

    def request(path, status=200, body=None, headers=None):
        req = urllib.request.Request(
            config["origin"] + "/api/v1/" + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"X-Request-Id": run_id, "Content-Type": "application/json",
                     "Origin": config["origin"], **(headers or {})},
        )
        try:
            response = client.open(req, timeout=30)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            payload = json.loads(response.read() or "null")
            assert response.status == status, (path, response.status, payload)
            assert response.headers["X-Request-Id"] == run_id
            if status >= 400:
                assert {"code", "message", "fieldErrors", "requestId"} <= payload.keys()
            return payload

    paths = {
        "stats/storage-benchmark": "rows", "stats/recommendations": "items",
        "stats/meters": "meters", "stats/outages/hotspots": "features",
    }
    for path in paths:
        request(path, 401)
    for role in ("operator", "manager"):
        request("auth/login", body={"username": role, "password": config["passwords"][role]})
        try:
            for path, key in paths.items():
                result = request(path)
                assert result[key], (role, path, result)
                assert result["totalElements"] >= len(result[key])
                query = urllib.parse.urlencode({
                    "from": "1900-01-01T00:00:00Z", "to": "1900-01-02T00:00:00Z",
                })
                assert request(path + "?" + query)[key] == []
                query = urllib.parse.urlencode({
                    "from": "2026-02-01T00:00:00Z", "to": "2026-01-01T00:00:00Z",
                })
                request(path + "?" + query, 422)
            regions = request("regions")["items"]
            for region in regions:
                suffix = "?" + urllib.parse.urlencode({"regionId": region["id"]})
                meters = request("stats/meters" + suffix)["meters"]
                assert meters and all(m["regionCode"] == region["code"] for m in meters)
                assert any(sum(r["kWh"] for r in m["readings"]) > 0 for m in meters)
                features = request("stats/outages/hotspots" + suffix)["features"]
                assert features and all(
                    f["properties"]["regionCode"] == region["code"] for f in features
                )
            request("stats/forecast", 404)
            if role == "operator":
                request("admin/policies", 403)
            print(f"PASS {role}: four live stats endpoints, regions, empty/invalid ranges, auth")
        finally:
            csrf = next(cookie.value for cookie in jar if cookie.name == "filegrid_csrf")
            request("auth/logout", status=204, body={}, headers={"X-CSRF-Token": csrf})


if __name__ == "__main__":
    main()
