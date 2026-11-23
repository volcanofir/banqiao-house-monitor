import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, Mock

from scripts.reuse_verified_preview_snapshot import (
    SOURCES, recent_snapshot, should_reuse,
)

NOW = datetime(2026, 11, 23, 5, 0, tzinfo=timezone.utc)


def snapshot(source, age=60):
    return {
        "complete": True,
        "source": SOURCES[source]["label"],
        "updatedAt": (NOW - timedelta(minutes=age)).isoformat(),
        "listings": [{"id": "test-listing"}],
    }


class SnapshotReuseTests(unittest.TestCase):
    def test_reuses_only_recent_completed_snapshot(self):
        for source in SOURCES:
            self.assertTrue(recent_snapshot(source, snapshot(source, 149), NOW)[0])
            self.assertFalse(recent_snapshot(source, snapshot(source, 151), NOW)[0])
            self.assertFalse(recent_snapshot(source, snapshot(source, -10), NOW)[0])

    def test_refuses_wrong_source_missing_time_and_incomplete(self):
        for source in SOURCES:
            wrong = snapshot(source)
            wrong["source"] = "unexpected"
            self.assertFalse(recent_snapshot(source, wrong, NOW)[0])
            bad = snapshot(source)
            bad["updatedAt"] = "2026-11-23T05:00:00"  # timezone missing
            self.assertFalse(recent_snapshot(source, bad, NOW)[0])
            bad = snapshot(source)
            bad["complete"] = False
            self.assertFalse(recent_snapshot(source, bad, NOW)[0])
            bad = snapshot(source)
            bad["listings"] = []
            self.assertFalse(recent_snapshot(source, bad, NOW)[0])

    def test_validator_failure_always_forces_refetch(self):
        import json
        for source in SOURCES:
            with patch("pathlib.Path.read_text", return_value=json.dumps(snapshot(source))), \
                 patch("scripts.reuse_verified_preview_snapshot.subprocess.run",
                       return_value=Mock(returncode=1, stderr="Invalid count")):
                result = should_reuse(source, NOW)
                self.assertFalse(result[0])
                self.assertIn("validator failed", result[1])

    def test_validator_pass_can_reuse(self):
        import json
        with patch("pathlib.Path.read_text", return_value=json.dumps(snapshot("rakuya"))), \
             patch("scripts.reuse_verified_preview_snapshot.subprocess.run",
                   return_value=Mock(returncode=0, stdout="verified")):
            self.assertTrue(should_reuse("rakuya", NOW)[0])


if __name__ == "__main__":
    unittest.main()
