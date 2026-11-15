#!/usr/bin/env python3
"""Real history-db outage: forecasts fail explicitly; ordinary catalog routes stay up."""
import json
import ssl
import subprocess
import urllib.error
import urllib.request
from http.cookiejar import CookieJar

from smoke_auth import container_python


def main():
    config = container_python("""
import json
from app.core.settings import get_settings
s=get_settings()
print(json.dumps({"origin":str(s.app_origin).rstrip("/"),"password":s.storage_secret("operator_password")}))
""")
    jar = CookieJar()
    client = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=ssl._create_unverified_context()),
        urllib.request.HTTPCookieProcessor(jar),
    )
    def request(path, body=None, expected=200):
        headers = {"Content-Type": "application/json"}
        if body is not None:
            headers["Origin"] = config["origin"]
            headers["X-CSRF-Token"] = next((c.value for c in jar if c.name == "filegrid_csrf"), "")
        req = urllib.request.Request(
            config["origin"]+"/api/v1/"+path, headers=headers,
            data=json.dumps(body).encode() if body is not None else None,
        )
        try:
            response = client.open(req, timeout=20)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            data = json.loads(response.read() or "null")
            assert response.status == expected, (path, response.status, data)
            return data
    request("auth/login", {"username": "operator", "password": config["password"]})
    meter = request("meters?size=1")["items"][0]["id"]
    path = f"meters/{meter}/forecast"
    up = request(path)
    assert up["method"] == "hgb_smooth" and not up["fallbackUsed"]
    try:
        subprocess.run(["docker", "compose", "stop", "-t", "5", "history-db"], check=True)
        down = request(path, expected=503)
        assert down["code"] == "HISTORY_UNAVAILABLE"
        assert "history-db" in down["message"]
        for ordinary in ("files", "connection-cases", "meters", "meter-readings",
                         "map-issues", "map/features?layer=ISSUES"):
            request(ordinary)
    finally:
        subprocess.run([
            "docker", "compose", "up", "-d", "--no-deps", "--no-recreate",
            "--wait", "--wait-timeout", "90", "history-db",
        ], check=True)
    restored = request(path)
    assert restored["method"] == "hgb_smooth" and not restored["fallbackUsed"]
    request("auth/logout", {}, expected=204)
    print("PASS: real model up/restored; history-db down -> clear 503; six catalog/map routes remain available")


if __name__ == "__main__":
    main()
