"""Sinyi Preview-only source feed cannot silently mark listing removals."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from refresh_sinyi_preview_source import build
import monitor_pages as core


class SinyiPreviewSourceTests(unittest.TestCase):
    def make_row(self, num=1, road=None):
        return {"id": f"信義房屋:{num}", "source": "信義房屋",
                "houseId": str(num), "road": road or next(iter(core.WATCH_ROADS)),
                "sinyiApiVerifiedAt": "2026-11-07T15:00:00+00:00"}

    def test_complete_snapshot_is_preview_only_and_never_delists(self):
        result = build("2026-11-07T15:00:00+00:00", [self.make_row()])
        self.assertTrue(result["complete"])
        self.assertTrue(result["previewOnly"])
        self.assertTrue(result["noOffmarketDecision"])
        self.assertTrue(result["noAutomaticNewPropertyDecision"])
        self.assertEqual(len(result["roadCounts"]), 7)
        self.assertEqual(result["uniqueListingCount"], 1)

    def test_duplicate_advertisement_rejected(self):
        with self.assertRaises(ValueError):
            build("2026-11-07T15:00:00+00:00", [self.make_row(), self.make_row()])

    def test_empty_response_rejected_to_preserve_previous_data(self):
        with self.assertRaises(ValueError):
            build("2026-11-07T15:00:00+00:00", [])


if __name__ == "__main__":
    unittest.main()
