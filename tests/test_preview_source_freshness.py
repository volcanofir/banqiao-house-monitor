"""Unit tests for the independent Preview health check and Sinyi validation."""
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from check_preview_source_freshness import SOURCES, audit_source

NOW = datetime(2026, 11, 6, 2, 0, tzinfo=timezone.utc)
ROADS = (
    "板橋區中山路二段", "板橋區三民路一段", "板橋區三民路二段",
    "板橋區翠華街", "板橋區林森街", "板橋區萬安街", "板橋區光復街",
)


def stamp(minutes):
    return (NOW - timedelta(minutes=minutes)).isoformat()


def verified_sinyi(minutes=210):
    at = stamp(minutes)
    return {
        "source": "信義房屋",
        "previewOnly": True,
        "complete": True,
        "updatedAt": at,
        "noOffmarketDecision": True,
        "noAutomaticNewPropertyDecision": True,
        "roadCounts": [{"road": road, "count": 1 if i == 0 else 0}
                       for i, road in enumerate(ROADS)],
        "uniqueListingCount": 1,
        "runs": {"信義房屋": {"status": "ok", "checkedAt": at, "totalCount": 1}},
        "listings": [{"id": "信義房屋:TEST1", "source": "信義房屋",
                      "road": ROADS[0], "sinyiApiVerifiedAt": at}],
    }


class Freshness(unittest.TestCase):
    def test_sinyi_alert_reads_independent_feed(self):
        self.assertEqual(dict(SOURCES)["信義房屋"], Path("docs/preview/sinyi-source.json"))

    def test_current_verified(self):
        for name in ("591", "樂屋網", "5168"):
            self.assertEqual(audit_source(name, {"complete": True, "updatedAt": stamp(210)}, NOW)["status"], "ok")
        self.assertEqual(audit_source("信義房屋", verified_sinyi(), NOW)["status"], "ok")

    def test_four_hour_threshold(self):
        self.assertEqual(audit_source("信義房屋", verified_sinyi(240), NOW)["status"], "stale")
        self.assertEqual(audit_source("591", {"complete": True, "updatedAt": stamp(240)}, NOW)["status"], "stale")

    def test_failed_capture_not_healthy(self):
        self.assertEqual(audit_source("5168", {"complete": False, "updatedAt": stamp(0)}, NOW)["status"], "error")
        failed = verified_sinyi()
        failed["complete"] = False
        self.assertEqual(audit_source("信義房屋", failed, NOW)["status"], "error")

    def test_stale_legacy_canonical_cannot_mask_missing_feed(self):
        self.assertEqual(audit_source("信義房屋", {"runs": {"信義房屋": {
            "status": "ok", "checkedAt": stamp(1)}}}, NOW)["status"], "error")

    def test_mismatching_publish_stamp_rejected(self):
        bad = verified_sinyi()
        bad["runs"]["信義房屋"]["checkedAt"] = stamp(30)
        self.assertEqual(audit_source("信義房屋", bad, NOW)["status"], "error")

    def test_duplicate_id_rejected(self):
        bad = verified_sinyi()
        bad["listings"].append(dict(bad["listings"][0]))
        bad["uniqueListingCount"] = 2
        bad["runs"]["信義房屋"]["totalCount"] = 2
        bad["roadCounts"][0]["count"] = 2
        self.assertEqual(audit_source("信義房屋", bad, NOW)["status"], "error")

    def test_incomplete_road_counts_rejected(self):
        bad = verified_sinyi()
        bad["roadCounts"].pop()
        self.assertEqual(audit_source("信義房屋", bad, NOW)["status"], "error")

    def test_future_timestamp_untrusted(self):
        self.assertEqual(audit_source("信義房屋", verified_sinyi(-20), NOW)["status"], "error")
        self.assertEqual(audit_source("樂屋網", {"complete": True, "updatedAt": stamp(-20)}, NOW)["status"], "error")


if __name__ == "__main__":
    unittest.main()
