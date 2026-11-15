#!/usr/bin/env python3
"""Verify seeded country model forecasts, a few exceedances, and atomic deduplication."""
import json
import re
import ssl
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from http.cookiejar import CookieJar

from smoke_auth import container_python


def main():
    config = container_python("""
import json
from app.core.settings import get_settings
s = get_settings()
print(json.dumps({"origin": str(s.app_origin).rstrip("/"),
                  "password": s.storage_secret("operator_password")}))
""")
    jar = CookieJar()
    client = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=ssl._create_unverified_context()),
        urllib.request.HTTPCookieProcessor(jar),
    )
    run_id = f"forecast-smoke-{uuid.uuid4().hex}"

    def request(path, body=None):
        headers = {"Content-Type": "application/json", "X-Request-Id": run_id}
        if body is not None:
            headers["Origin"] = config["origin"]
            headers["X-CSRF-Token"] = next(
                (cookie.value for cookie in jar if cookie.name == "filegrid_csrf"), "",
            )
        req = urllib.request.Request(
            config["origin"] + "/api/v1/" + path, headers=headers,
            data=json.dumps(body).encode() if body is not None else None,
        )
        with client.open(req, timeout=120) as response:
            assert response.headers["X-Request-Id"] == run_id
            return json.loads(response.read() or "null")

    request("auth/login", {"username": "operator", "password": config["password"]})
    try:
        original_thresholds = {
            item["segmentId"]: item for item in request("forecast/thresholds")
        }
        first = request("forecast/runs", {"scope": "country"})
        tomorrow = datetime.now(timezone.utc).date() + timedelta(days=1)
        assert first["status"] == "COMPLETED"
        assert len({segment["segmentId"] for segment in first["segments"]}) == 18
        exceedances = set()
        calibrated = 0
        for segment in first["segments"]:
            assert segment["method"] == "hgb_smooth" and not segment["fallbackUsed"], segment
            if segment["thresholdSource"] == "MANUAL":
                original = original_thresholds[segment["segmentId"]]
                assert original["source"] == "MANUAL"
                assert segment["thresholdKwh"] == original["dailyEnergyKwh"]
                assert segment["thresholdCalibration"] is None
            else:
                assert segment["thresholdSource"] == "HISTORY_P95"
                calibration = segment["thresholdCalibration"]
                assert calibration["sampleDays"] >= 14
                assert calibration["percentile"] == 95 and calibration["multiplier"] == 1.03
                assert abs(segment["thresholdKwh"]-calibration["p95Kwh"]*1.03) <= 0.000001
                calibrated += 1
            assert segment["bridge"]["persistedAsReadings"] is False
            assert segment["bridged"] and segment["bridge"]["intervals"] > 0
            assert segment["lastCompletedDay"] == (tomorrow - timedelta(days=2)).isoformat()
            assert len(segment["meters"]) == 8
            for index, point in enumerate(segment["forecasts"]):
                assert point["date"] == (tomorrow + timedelta(days=index)).isoformat()
                assert point["status"] == "READY" and not point["fallbackUsed"]
                assert point["bridged"] and point["eligibleMeters"] == point["expectedMeters"] == 8
                if point["excessKwh"] > 0:
                    exceedances.add((segment["segmentId"], point["date"]))
        assert calibrated > 0
        assert 1 <= len(exceedances) <= 5, exceedances
        issues = request("map-issues?type=ML_FORECAST&size=100")["items"]
        matching = [issue for issue in issues if (
            issue["segmentId"], issue["forecastDate"],
        ) in exceedances]
        assert len(matching) == len(exceedances)
        for issue in matching:
            assert re.search(
                rf"expected to exceed on {issue['forecastDate']} by \d+\.\d{{3}} kWh",
                issue["title"],
            ), issue
        second = request("forecast/runs", {"scope": "country"})
        assert second["createdIssues"] == []
        assert request("forecast/runs/" + first["id"]) == first
        persisted = container_python("""
import json
from sqlalchemy import text
from app.core.db import get_catalog_engine
with get_catalog_engine().connect() as db:
    rows = db.execute(text('''
        SELECT i.id::text, count(a.id) FROM map_issues i
        LEFT JOIN alerts a ON a.payload->>'issueId'=i.id::text
        WHERE i.type='ML_FORECAST' AND NOT i.is_historical
        GROUP BY i.id
    ''')).all()
    print(json.dumps(dict(rows)))
""")
        assert all(persisted[issue["id"]] == 1 for issue in matching)
        print(
            f"PASS: country uses model for 18/18 bridged segments; {len(exceedances)} exceedances; "
            f"{calibrated} calibrated thresholds; {18-calibrated} preserved manager overrides; "
            f"{len(first['createdIssues'])} new issues; rerun creates 0 duplicates; one alert per issue"
        )
        for issue in matching:
            print(issue["title"])
    finally:
        request("auth/logout", {})


if __name__ == "__main__":
    main()
