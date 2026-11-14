"""History seeder gap handling; no Docker or database needed."""
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import unittest


spec = importlib.util.spec_from_file_location(
    "seed_history", Path(__file__).resolve().parents[2] / "scripts/seed_history.py",
)
seed_history = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seed_history)


class SeedHistoryTests(unittest.TestCase):
    def setUp(self):
        self.start = datetime(2026, 11, 13, tzinfo=timezone.utc)
        self.end = self.start + timedelta(hours=6)

    def test_partial_and_overlapping_existing_intervals_leave_only_gaps(self):
        hour = timedelta(hours=1)
        existing = [
            (self.start - hour, self.start + hour),
            (self.start + 2 * hour, self.start + 3 * hour),
            (self.start + 2 * hour, self.start + 4 * hour),
            (self.end + hour, self.end + 2 * hour),
        ]
        self.assertEqual(list(seed_history.uncovered(self.start, self.end, existing)), [
            (self.start + hour, self.start + 2 * hour),
            (self.start + 4 * hour, self.end),
        ])

    def test_latest_interval_accounts_for_delivery_delay_and_midnight(self):
        self.assertEqual(seed_history.last_complete_interval(
            self.end + timedelta(minutes=1),
        ), self.start)
        self.assertEqual(seed_history.last_complete_interval(
            self.end + timedelta(minutes=2),
        ), self.end)
        self.assertEqual(seed_history.last_complete_interval(self.start),
                         self.start - timedelta(hours=6))

    def test_repeat_after_filling_gaps_inserts_nothing(self):
        hour = timedelta(hours=1)
        existing = [(self.start + hour, self.start + 2 * hour)]
        gaps = list(seed_history.uncovered(self.start, self.end, existing))
        self.assertEqual(
            list(seed_history.uncovered(self.start, self.end, sorted(existing + gaps))), [],
        )
        self.assertEqual(
            list(seed_history.uncovered(self.start, self.end, [])), [(self.start, self.end)],
        )

    def test_payload_and_identity_use_real_meter_and_gap_start(self):
        meter = {"id": "catalog-meter", "external_code": "MTR-0006", "region_id": "region"}
        received = self.end + timedelta(seconds=120)
        row = seed_history.reading(meter, self.start, self.end, 12.3456789, received)
        self.assertEqual(row, seed_history.reading(
            meter, self.start, self.end, 12.3456789, received,
        ))
        payload = json.loads(row[10])
        self.assertEqual(payload["meterExternalCode"], "MTR-0006")
        self.assertEqual(payload["readingKey"], "MTR-0006:2026-11-13T00:00:00+00:00")
        self.assertEqual(payload["energyKwh"], 12.345679)
        self.assertEqual(row[7], received)
        self.assertLess(payload["seq"], 2**31)
        later = seed_history.reading(
            meter, self.start + timedelta(minutes=15), self.end, 12, received,
        )
        self.assertNotEqual(row[0], later[0])
        self.assertLess(row[3], later[3])

    def test_profile_matching_reserves_real_types_and_preserves_missing_metadata(self):
        untyped = {
            "id": "untyped", "external_code": "MTR-1", "region": "BANAT",
            "client_type": None,
        }
        typed = {
            "id": "typed", "external_code": "MTR-2", "region": "BANAT",
            "client_type": "INDUSTRIAL",
        }
        profiles = [
            {"id": "wrong-region", "region": "MUNTENIA", "client_type": "INDUSTRIAL"},
            {"id": "industrial", "region": "BANAT", "client_type": "INDUSTRIAL"},
            {"id": "residential", "region": "BANAT", "client_type": "RESIDENTIAL"},
        ]
        matches = seed_history.match_profiles([untyped, typed], profiles)
        self.assertEqual([(m["id"], p["id"]) for m, p in matches], [
            ("typed", "industrial"), ("untyped", "residential"),
        ])
        self.assertIsNone(untyped["client_type"])
        with self.assertRaisesRegex(ValueError, "No unused history-v2 profile"):
            seed_history.match_profiles([typed], profiles[:1])

    def test_profiles_can_be_reused_deterministically_for_144_catalog_meters(self):
        meters = [
            {"id": str(index), "external_code": f"RO-BANAT-1-{index:03d}",
             "region": "BANAT", "client_type": "RESIDENTIAL"}
            for index in range(48)
        ]
        profiles = [{"id": "profile", "region": "BANAT", "client_type": "RESIDENTIAL"}]
        matches = seed_history.match_profiles(meters, profiles)
        self.assertEqual(len(matches), 48)
        self.assertEqual(matches, seed_history.match_profiles(meters, profiles))
