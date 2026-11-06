"""Floor identity regression tests for the existing, Preview-only deduplication."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import compare_yungching_preview_v3 as v3
import compare_yungching_preview_v4 as v4
import audit_scheme_a_ambiguity_v2 as audit


class PreviewIdentityRetentionTests(unittest.TestCase):
    def test_591_official_floor_survives_compaction_and_audit(self):
        row={"source":"591","id":"591:99913","road":"板橋區光復街",
             "title":"房仲廣告打高樓層","price":"1088萬","size":"24坪",
             "structuredFloor":"3/5樓","structuredFloorRaw":"3F/5F",
             "floorSourceMode":"591_warelist_structured",
             "structuredCommunity":"測試社區","structuredLayout":"3房2廳"}
        compact=v3.compact_listing(row)
        self.assertEqual(compact["structuredFloor"],"3/5樓")
        self.assertEqual(compact["structuredCommunity"],"測試社區")
        self.assertEqual(v4.listing_floor_tokens(compact),{3})
        self.assertEqual(audit.structured_listing_floors(compact),{3})

    def test_nested_591_members_keep_distinct_floors(self):
        row={"source":"591","id":"591:3","mergedListings":[
            {"source":"591","id":"591:3","structuredFloor":"3/5樓",
             "floorSourceMode":"591_warelist_structured"},
            {"source":"591","id":"591:4","structuredFloor":"4/5樓",
             "floorSourceMode":"591_warelist_structured"}]}
        compact=v3.compact_listing(row)
        self.assertEqual([m["structuredFloor"] for m in compact["mergedListings"]],
                         ["3/5樓","4/5樓"])
        self.assertEqual(v4.listing_floor_tokens(compact),{3,4})

    def test_sinyi_official_floor_dominates_marketing_title(self):
        row={"source":"信義房屋","title":"頂樓景觀四樓",
             "floor":"2/5樓","structuredFloor":"2樓",
             "floorSourceMode":"sinyi_official_filterObject_api"}
        compact=v3.compact_listing(row)
        self.assertEqual(v4.listing_floor_tokens(compact),{2})
        self.assertEqual(audit.structured_listing_floors(compact),{2})

    def test_5168_official_floor_dominates_title(self):
        row={"source":"5168","title":"超大四樓三房",
             "structuredFloor":"3/5樓","floorSourceMode":"5168-app-detail",
             "housepriceGroupSid":"12345"}
        compact=v3.compact_listing(row)
        self.assertEqual(compact["housepriceGroupSid"],"12345")
        self.assertEqual(v4.listing_floor_tokens(compact),{3})
        self.assertEqual(audit.structured_listing_floors(compact),{3})

    def test_verified_different_floor_not_same_identity(self):
        a=v3.compact_listing({"source":"591","road":"板橋區光復街",
                 "title":"低總價三房","price":"1088萬","size":"24坪",
                 "structuredFloor":"3/5樓",
                 "floorSourceMode":"591_warelist_structured"})
        b=v3.compact_listing({"source":"591","road":"板橋區光復街",
                 "title":"低總價三房","price":"1088萬","size":"24坪",
                 "structuredFloor":"4/5樓",
                 "floorSourceMode":"591_warelist_structured"})
        ok,info=v4.pair_591_info(a,b)
        self.assertFalse(ok)
        self.assertTrue(info["floorConflict"])

    def test_missing_verified_floor_remains_unknown(self):
        row=v3.compact_listing({"source":"591","title":"低總價兩房",
                     "structuredFloor":"整棟/5F",
                     "floorSourceMode":"591_warelist_structured"})
        self.assertEqual(v4.listing_floor_tokens(row),set())
        self.assertEqual(audit.structured_listing_floors(row),set())

if __name__=="__main__":
    unittest.main()
