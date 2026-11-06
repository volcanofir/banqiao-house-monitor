import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from track_591_presence_preview import build

ROADS=["中山路二段","三民路一段","三民路二段","翠華街","林森街","萬安街","光復街"]
def src(at,ids):
    return {"updatedAt":at,"complete":True,"noOffmarketDecision":True,
      "roadCounts":[{"road":r,"count":len(ids) if i==0 else 0} for i,r in enumerate(ROADS)],
      "listings":[{"id":rid} for rid in ids],"counts":{"totalListings":len(ids)}}

class Tests(unittest.TestCase):
    def test_confirmed_never_from_absence(self):
        a=build({},src("2026-11-06T00:00:00Z",["591:1","591:2"]))
        b=build(a,src("2026-11-06T03:00:00Z",["591:2"]))
        self.assertEqual(b["unobservedOnceIdCount"],1)
        self.assertEqual(b["pendingConfirmationIdCount"],0)
        c=build(b,src("2026-11-06T06:00:00Z",["591:2"]))
        self.assertEqual(c["pendingConfirmationIdCount"],1)
        self.assertEqual(c["confirmedOffmarketIdCount"],0)
        d=build(c,src("2026-11-06T09:00:00Z",["591:1","591:2"]))
        self.assertEqual(d["pendingConfirmationIdCount"],0)
        self.assertEqual(d["reappearedThisCheckCount"],1)
        self.assertEqual(d["records"]["591:1"]["firstObservedAt"],"2026-11-06T00:00:00Z")
    def test_incomplete_fails_closed(self):
        s=src("2026-11-06T00:00:00Z",["591:1"]);s["complete"]=False
        with self.assertRaises(ValueError):build({},s)
    def test_duplicate_fails_closed(self):
        with self.assertRaises(ValueError):
            build({},src("2026-11-06T00:00:00Z",["591:1","591:1"]))
    def test_same_snapshot_no_false_increment(self):
        a=build({},src("2026-11-06T00:00:00Z",["591:1","591:2"]))
        b=build(a,src("2026-11-06T03:00:00Z",["591:2"]))
        self.assertEqual(build(b,src("2026-11-06T03:00:00Z",["591:2"])),b)
    def test_no_older_snapshot(self):
        a=build({},src("2026-11-06T06:00:00Z",["591:1"]))
        with self.assertRaises(ValueError):
            build(a,src("2026-11-06T03:00:00Z",["591:2"]))
if __name__=="__main__":unittest.main()
