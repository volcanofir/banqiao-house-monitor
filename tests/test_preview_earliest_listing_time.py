"""Regression tests for earliest-known publication across source and old ad IDs."""
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import compare_yungching_preview_v11 as v11
import compare_yungching_preview_v3 as v3

def stamp(text):
    return int(datetime.fromisoformat(text.replace("Z","+00:00")).timestamp())

class EarliestKnownListingTests(unittest.TestCase):
    def test_historical_exact_id_older_than_current_crawl_and_posttime(self):
        ad_id="591:20537650"
        row={"source":"591","id":ad_id,"sourcePublishedAt":stamp("2026-10-01T00:00:00Z"),
             "postTime":stamp("2026-07-12T00:00:00Z"),
             "firstSeenAt":"2026-11-05T00:00:00Z"}
        group={"primarySource":"591","sourceListings":[row]}
        history={"591":{ad_id:{"sourcePublishedAt":stamp("2024-06-12T10:30:00Z")}}}
        got=v11.annotate_property_first_publish(group,history)
        self.assertEqual(got["propertyFirstPublishedAt"],"2024-06-12T10:30:00+00:00")
        self.assertEqual(got["propertyFirstPublishedEvidence"],"permanent_id_history")
        self.assertEqual(got["propertyFirstPublishedListingId"],ad_id)

    def test_different_old_ad_in_same_verified_property_is_earliest(self):
        group={"primarySource":"591","sourceListings":[{
           "source":"591","id":"591:old","sourcePublishedAt":stamp("2025-01-01T00:00:00Z"),
           "mergedListings":[{"id":"591:older","source":"591",
                               "postTime":stamp("2024-01-01T00:00:00Z")}]},
          {"source":"信義房屋","id":"SY:now",
           "sourcePublishedAt":stamp("2026-09-01T00:00:00Z")}]}
        got=v11.annotate_property_first_publish(group)
        self.assertEqual(got["propertyFirstPublishedAt"],"2024-01-01T00:00:00+00:00")
        self.assertEqual(got["propertyFirstPublishedListingId"],"591:older")

    def test_unrelated_historical_id_never_contributes(self):
        group={"primarySource":"591","sourceListings":[{
            "source":"591","id":"591:current",
            "postTime":stamp("2026-10-01T00:00:00Z")}]}
        history={"591":{"591:another_house":{"sourcePublishedAt":stamp("2020-01-01T00:00:00Z")}}}
        got=v11.annotate_property_first_publish(group,history)
        self.assertEqual(got["propertyFirstPublishedAt"],"2026-10-01T00:00:00+00:00")

    def test_new_id_cannot_override_older_source_posttime(self):
        item={"source":"591","id":"591:new",
              "sourcePublishedAt":stamp("2026-11-05T00:00:00Z"),
              "postTime":stamp("2025-03-01T00:00:00Z")}
        got=v11.annotate_property_first_publish({"primarySource":"591","sourceListings":[item]})
        self.assertEqual(got["propertyFirstPublishedAt"],"2025-03-01T00:00:00+00:00")

    def test_monitor_first_seen_never_substituted(self):
        item={"source":"591","id":"591:unknown",
              "firstSeenAt":"2026-11-05T00:00:00Z","newAt":"2026-11-05T00:00:00Z",
              "monitorFirstSeenAt":"2026-11-05T00:00:00Z"}
        got=v11.annotate_property_first_publish({"primarySource":"591","sourceListings":[item]})
        self.assertIsNone(got["propertyFirstPublishedAt"])
        self.assertEqual(got["propertyFirstPublishedBasis"],"unavailable_no_source_publish_date")

    def test_raw_posttime_survives_preview_compaction(self):
        item={"source":"591","id":"591:old",
              "postTime":stamp("2024-01-01T00:00:00Z"),
              "sourcePublishedAt":stamp("2025-01-01T00:00:00Z"),
              "mergedListings":[{"id":"591:older","postTime":stamp("2023-01-01T00:00:00Z"),
                                 "sourcePublishedAt":stamp("2024-01-01T00:00:00Z")}]}
        compact=v3.compact_listing(item)
        self.assertEqual(compact["postTime"],item["postTime"])
        self.assertEqual(compact["mergedListings"][0]["postTime"],item["mergedListings"][0]["postTime"])
        got=v11.annotate_property_first_publish({"primarySource":"591","sourceListings":[compact]})
        self.assertEqual(got["propertyFirstPublishedAt"],"2023-01-01T00:00:00+00:00")

if __name__ == "__main__":
    unittest.main()
