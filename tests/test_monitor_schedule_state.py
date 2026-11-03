"""Regression coverage for the ten-minute heartbeat / three-hour crawl policy.

These tests are network-free and never touch canonical listings, state or Preview.
"""

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import monitor_schedule_state as schedule


class CadenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        for name, file in [
            ("STATE", root / "state.json"),
            ("TMP_STATE", root / "attempt.json"),
            ("LISTINGS", root / "listings.json"),
        ]:
            p = patch.object(schedule, name, file)
            p.start()
            self.addCleanup(p.stop)

    def write(self, path, payload):
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def test_blocked_source_does_not_trigger_a_full_crawl_every_ten_minutes(self):
        now = datetime(2026, 11, 3, 2, 0, tzinfo=timezone.utc)
        self.write(schedule.STATE, {
            "lastFullCheckAttemptAt": (now - timedelta(minutes=25)).isoformat(),
            "lastSuccessfulFullCheckAt": (now - timedelta(days=4)).isoformat(),
        })
        self.write(schedule.LISTINGS, {"updatedAt": (now - timedelta(days=5)).isoformat()})
        result = Path(self.tmp.name) / "github_output"
        with patch.object(schedule, "utc_now", return_value=now), patch.dict(
            os.environ, {"GITHUB_OUTPUT": str(result)}
        ):
            schedule.gate()
        self.assertIn("run=false", result.read_text(encoding="utf-8"))

    def test_after_three_hours_a_new_attempt_is_due_even_if_old_failed(self):
        now = datetime(2026, 11, 3, 2, 0, tzinfo=timezone.utc)
        self.write(schedule.STATE, {
            "lastFullCheckAttemptAt": (now - timedelta(minutes=180)).isoformat(),
            "lastSuccessfulFullCheckAt": (now - timedelta(days=4)).isoformat(),
        })
        result = Path(self.tmp.name) / "github_output"
        with patch.object(schedule, "utc_now", return_value=now), patch.dict(
            os.environ, {"GITHUB_OUTPUT": str(result)}
        ):
            schedule.gate()
        self.assertIn("run=true", result.read_text(encoding="utf-8"))

    def test_failed_source_updates_attempt_only_and_keeps_verified_history(self):
        old_success = "2026-10-30T04:49:11+00:00"
        latest = {"lastSuccessfulFullCheckAt": old_success,
                  "sourceStatuses": {"591": "ok", "信義房屋": "ok"}}
        attempt = {"lastFullCheckAttemptAt": "2026-11-03T02:00:00+00:00",
                   "lastAttemptSourceStatuses": {"591": "error", "信義房屋": "ok"}}
        after = schedule.merge_attempt(latest, attempt, False)
        self.assertEqual(after["lastFullCheckAttemptAt"], attempt["lastFullCheckAttemptAt"])
        self.assertEqual(after["lastSuccessfulFullCheckAt"], old_success)
        self.assertEqual(after["sourceStatuses"], latest["sourceStatuses"])
        self.assertEqual(after["lastAttemptOutcome"], "incomplete")

    def test_success_only_after_both_verified_and_published(self):
        latest = {"lastSuccessfulFullCheckAt": "2026-10-30T04:49:11+00:00"}
        attempt = {"lastFullCheckAttemptAt": "2026-11-03T02:00:00+00:00",
                   "lastAttemptSourceStatuses": {"591": "ok", "信義房屋": "ok"}}
        with patch.dict(os.environ, {
            "SOURCE_OK": "true", "WORKFLOW_STATUS": "success",
            "LISTINGS_CHANGED": "true", "PUBLISH_OUTCOME": "success"
        }):
            self.assertTrue(schedule.verified_by_workflow())
        with patch.dict(os.environ, {
            "SOURCE_OK": "false", "WORKFLOW_STATUS": "success",
            "LISTINGS_CHANGED": "true", "PUBLISH_OUTCOME": "success"
        }):
            self.assertFalse(schedule.verified_by_workflow())
        with patch.dict(os.environ, {
            "SOURCE_OK": "true", "WORKFLOW_STATUS": "success",
            "LISTINGS_CHANGED": "true", "PUBLISH_OUTCOME": "failure"
        }):
            self.assertFalse(schedule.verified_by_workflow())
        with patch.dict(os.environ, {
            "SOURCE_OK": "true", "WORKFLOW_STATUS": "success",
            "LISTINGS_CHANGED": "false", "PUBLISH_OUTCOME": "skipped"
        }):
            self.assertTrue(schedule.verified_by_workflow())
        after = schedule.merge_attempt(latest, attempt, True)
        self.assertEqual(after["lastSuccessfulFullCheckAt"], attempt["lastFullCheckAttemptAt"])
        self.assertEqual(after["lastAttemptOutcome"], "verified")
        attempt["lastAttemptSourceStatuses"]["591"] = "error"
        with self.assertRaises(ValueError):
            schedule.merge_attempt(latest, attempt, True)

    def test_existing_newer_attempt_is_never_replaced(self):
        latest = {"lastFullCheckAttemptAt": "2026-11-03T03:00:00+00:00",
                  "lastSuccessfulFullCheckAt": "2026-11-03T02:30:00+00:00"}
        old = {"lastFullCheckAttemptAt": "2026-11-03T02:00:00+00:00"}
        self.assertEqual(schedule.merge_attempt(latest, old, False), latest)

    def test_prepare_tracks_errors_without_treating_them_as_success(self):
        now = datetime(2026, 11, 3, 2, 0, tzinfo=timezone.utc)
        self.write(schedule.LISTINGS, {
            "runs": {"591": {"status": "error"}, "信義房屋": {"status": "ok"}}
        })
        result = Path(self.tmp.name) / "github_output"
        with patch.object(schedule, "utc_now", return_value=now), patch.dict(
            os.environ, {"GITHUB_OUTPUT": str(result)}
        ):
            schedule.begin()
            schedule.prepare()
        self.assertIn("success=false", result.read_text(encoding="utf-8"))
        attempt = json.loads(schedule.TMP_STATE.read_text(encoding="utf-8"))
        self.assertEqual(attempt["lastAttemptSourceStatuses"]["591"], "error")


if __name__ == "__main__":
    unittest.main()
