"""Offline safety tests for independent 591 preview builder."""
import sys
import unittest
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1] / "scripts"))
import build_591_warelist_preview as preview


class PreviewTests(unittest.TestCase):
    def setUp(self):
        self.roads=list(preview.ROADS)
        self.current={}
        for i,road in enumerate(self.roads):
            n=str(10000000+i)
            self.current[road]=[{
                "id":"591:"+n,"houseId":n,
                "source":"591","road":road,
                "title":"板橋採光測試"+n,
                "address":"新北市"+road+"100號",
                "price":1000+i*100,"size":25+i,"postTime":1770000000+i,
                "url":"https://m.591.com.tw/v2/sale/"+n
            }]
        first=self.current[self.roads[0]][0]
        self.history={"runs":{"591":{"status":"error"}},
           "listings":[{**first,"active":True,"mergedListings":[{**first,"active":True}]}]}
        self.stats=Counter({"roads_ok":7,"raw":8})

    def build(self):
        return preview.build_snapshot(self.current,self.stats,self.history,
          now=datetime(2026,11,3,tzinfo=timezone.utc))

    def test_seven_roads_and_history_id_protection(self):
        result=self.build()
        self.assertEqual(result["counts"]["totalListings"],7)
        self.assertEqual(result["counts"]["historicalIdSeen"],1)
        self.assertEqual(result["counts"]["idNotInHistory"],6)
        self.assertTrue(result["noOffmarketDecision"])
        self.assertTrue(result["noAutomaticNewPropertyDecision"])
        self.assertEqual(result["mode"],"preview_only")
        self.assertEqual(result["listings"][0]["identityStatus"],"id_not_in_history")

    def test_history_reappearing_is_not_a_new_id(self):
        self.history["listings"][0]["mergedListings"][0]["active"]=False
        self.history["listings"][0]["active"]=False
        d=self.build()
        self.assertEqual(d["counts"]["historicallyInactiveReappeared"],1)
        self.assertEqual(d["counts"]["idNotInHistory"],6)

    def test_structured_floor_and_layout_survive_snapshot(self):
        target=self.current[self.roads[0]][0]
        target.update({"structuredFloor":"3/5樓",
                       "structuredFloorRaw":"3F/5F",
                       "floorSourceMode":"591_warelist_structured",
                       "structuredLayout":"3房2廳2衛",
                       "sourceHouseAge":37,
                       "sourceParkingFlag":False})
        row=next(x for x in self.build()["listings"] if x["id"]==target["id"])
        self.assertEqual(row["structuredFloor"],"3/5樓")
        self.assertEqual(row["structuredLayout"],"3房2廳2衛")
        self.assertFalse(row["sourceParkingFlag"])

    def test_missing_road_fails_closed(self):
        self.current.pop(self.roads[2])
        with self.assertRaises(ValueError):
            self.build()

    def test_duplicate_cross_road_id_fails_closed(self):
        self.current[self.roads[1]][0]["id"]=self.current[self.roads[0]][0]["id"]
        with self.assertRaises(ValueError):
            self.build()

    def test_incomplete_field_fails_closed(self):
        self.current[self.roads[1]][0]["price"]=None
        with self.assertRaises(ValueError):
            self.build()

    def test_incomplete_road_count_fails_closed(self):
        self.stats["roads_ok"]=6
        with self.assertRaises(ValueError):
            self.build()

    def test_no_canonical_writes(self):
        # Pure snapshot calculation must not invoke any file writes.
        with patch.object(Path,"write_text",side_effect=AssertionError("unexpected write")):
            self.build()


if __name__=="__main__":
    unittest.main()
