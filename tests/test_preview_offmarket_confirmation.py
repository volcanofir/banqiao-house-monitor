"""Regression tests for 591/Sinyi/Rakuya/5168 group-level delisting safety."""
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import add_recent_offmarket as offmarket

NOW=datetime(2026,11,3,4,43,tzinfo=timezone.utc)
CUTOFF=NOW-timedelta(days=10)
REMOVED="2026-11-01T03:00:00+00:00"


class OffmarketSafety(unittest.TestCase):
    def test_all_sources_must_have_confirmed_removed_at(self):
        good=[{"active":False,"removedAt":REMOVED},
              {"active":False,"removedAt":REMOVED}]
        status,t=offmarket.removal_certainty(good,CUTOFF)
        self.assertEqual(status,"confirmed")
        self.assertEqual(t.isoformat(),REMOVED)

        bad=[{"active":False,"removedAt":REMOVED},
             {"active":False,"removedAt":None}]
        self.assertEqual(
            offmarket.removal_certainty(bad,CUTOFF)[0], "unconfirmed")

    def test_active_5168_listing_vetoes_offmarket(self):
        rows=[{"active":False,"removedAt":REMOVED},
              {"active":True,"removedAt":None}]
        self.assertEqual(
            offmarket.removal_certainty(rows,CUTOFF)[0], "active_or_unknown")

    def test_no_explicit_removal_is_unknown(self):
        self.assertEqual(
            offmarket.removal_certainty([{"active":False,"removedAt":None}],CUTOFF)[0],
            "unknown")

    def test_old_verified_removal_is_outside_10_day_window(self):
        stale=(NOW-timedelta(days=12)).isoformat()
        self.assertEqual(
            offmarket.removal_certainty([{"active":False,"removedAt":stale}],CUTOFF)[0],
            "outside_window")

    def test_real_original_preview_grouping_preserves_unknowns(self):
        root=Path("docs/preview")
        state=json.loads((root/"scheme-a-external-enriched.json").read_text(encoding="utf-8")) if (root/"scheme-a-external-enriched.json").exists() else None
        if state is None:
            self.skipTest("Intermediate local enriched input is not committed")
        gap=json.loads((root/"company-gap.json").read_text(encoding="utf-8"))
        with patch.object(Path,"write_text",side_effect=AssertionError("unexpected write")):
            result=offmarket.build_offmarket_report(state,gap,NOW)
        self.assertEqual(result["recentOffMarketCount"],len(result["recentOffMarketGroups"]))
        for g in result["recentOffMarketGroups"]:
            self.assertTrue(g["offMarket"])
        self.assertTrue(result["offMarketPolicy"].find("unknown 591")>=0)
        print(json.dumps({
            "confirmed":result["recentOffMarketCount"],
            "unconfirmed":result["pendingOffMarketConfirmationCount"],
            "5168VetoEnabled":True
        },ensure_ascii=False))


if __name__=="__main__":
    unittest.main()
