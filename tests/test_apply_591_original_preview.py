"""Offline integration regression: run the *existing* 591 dedupe with new wareList.

No network calls or writes to production or Preview are allowed.
"""
import json
import sys
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import dedupe_listings_v2 as dedupe
import apply_591_warelist_to_original_preview as overlay


class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline=json.loads(Path("docs/data/listings.json").read_text(encoding="utf-8"))
        cls.snapshot=json.loads(Path("docs/591-preview/snapshot.json").read_text(encoding="utf-8"))
        cls.reference_time=overlay.date_time(cls.snapshot["updatedAt"])+timedelta(minutes=1)

    def merge(self,state=None,snap=None):
        return overlay.merge_for_preview(
            state or self.baseline,snap or self.snapshot,now=self.reference_time)

    def test_original_preview_real_591_snapshot_and_history(self):
        preview=self.merge()
        old=[x for x in self.baseline["listings"] if x.get("source")=="591"]
        new=[x for x in preview["listings"] if x.get("source")=="591"]
        original_flat={x["id"]:x for x in dedupe.flatten_591(old)}
        updated_flat={x["id"]:x for x in dedupe.flatten_591(new)}
        observed={x["id"] for x in self.snapshot["listings"]}
        self.assertEqual(set(updated_flat),set(original_flat)|observed)
        for key,old_record in original_flat.items():
            record=updated_flat[key]
            self.assertEqual(record.get("firstSeenAt"),old_record.get("firstSeenAt"))
            if key not in observed:
                self.assertFalse(record.get("active"))
                if old_record.get("active") is False:
                    self.assertEqual(record.get("removedAt"),old_record.get("removedAt"))
                else:
                    self.assertIsNone(record.get("removedAt"))
        self.assertEqual(preview["updatedAt"],self.baseline["updatedAt"])
        self.assertTrue(preview["previewSources"]["591"]["missingIdIsNotDelisting"])
        self.assertEqual(
            [x for x in preview["listings"] if x.get("source")!="591"],
            [x for x in self.baseline["listings"] if x.get("source")!="591"])
        self.assertGreater(sum(x.get("active",True) for x in new),0)
        print(json.dumps({
            "input591": len(self.snapshot["listings"]),
            "grouped591":len(new),
            "activeGrouped591":sum(x.get("active",True) for x in new),
            "allHistoricalIdsRetained":len(original_flat),
            "newIds":len(observed-set(original_flat)),
            "canonicalUntouched":True,
            "oldMissingIdsAreNotConfirmedDelistings":True
        },ensure_ascii=False))

    def test_reject_incomplete_or_duplicate_snapshot(self):
        copy=json.loads(json.dumps(self.snapshot))
        copy["complete"]=False
        with self.assertRaises(ValueError):
            self.merge(snap=copy)
        copy=json.loads(json.dumps(self.snapshot))
        copy["listings"].append(copy["listings"][0].copy())
        copy["counts"]["totalListings"]+=1
        copy["roadCounts"][0]["count"]+=1
        with self.assertRaises(ValueError):
            self.merge(snap=copy)
        copy=json.loads(json.dumps(self.snapshot))
        copy["roadCounts"].pop()
        with self.assertRaises(ValueError):
            self.merge(snap=copy)

    def test_stale_snapshot_never_publish(self):
        with self.assertRaises(ValueError):
            overlay.merge_for_preview(
                self.baseline,self.snapshot,
                now=self.reference_time+timedelta(hours=12))

    def test_verified_different_floors_never_dedupe(self):
        base={"source":"591","road":"板橋區三民路二段",
              "title":"同社區採光三房","address":"板橋區三民路二段",
              "price":"1388萬","size":"30.12坪"}
        a={**base,"id":"591:90000001","houseId":"90000001",
           "structuredFloor":"3/5樓","floorSourceMode":"591_warelist_structured"}
        b={**base,"id":"591:90000002","houseId":"90000002",
           "structuredFloor":"4/5樓","floorSourceMode":"591_warelist_structured"}
        groups,_,_=overlay._preview_dedupe([a,b])
        self.assertEqual(len([g for g in groups if g.get("source")=="591"]),2)
        self.assertTrue(dedupe.same_property(a,b))  # Canonical algorithm unchanged.

    def test_unknown_floor_cannot_bridge_two_known_floors(self):
        base={"source":"591","road":"板橋區中山路二段",
              "title":"同一物件","address":"板橋區中山路二段",
              "price":"1800萬","size":"35坪"}
        a={**base,"id":"591:90000003","structuredFloor":"3/5樓",
           "floorSourceMode":"591_warelist_structured"}
        unknown={**base,"id":"591:90000004"}
        b={**base,"id":"591:90000005","structuredFloor":"4/5樓",
           "floorSourceMode":"591_warelist_structured"}
        groups,_,_=overlay._preview_dedupe([a,unknown,b])
        self.assertGreaterEqual(len([x for x in groups if x.get("source")=="591"]),2)
        for group in groups:
            overlay._assert_floor_integrity([group])

    def test_pure_merge_no_files_written(self):
        with patch.object(Path,"write_text",side_effect=AssertionError("unexpected write")):
            self.merge()


if __name__=="__main__":
    unittest.main()
