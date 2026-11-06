import sys
import unittest
from datetime import datetime,timezone,timedelta
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from check_preview_source_freshness import audit_source

NOW=datetime(2026,11,6,2,0,tzinfo=timezone.utc)
def stamp(minutes):return (NOW-timedelta(minutes=minutes)).isoformat()

class Freshness(unittest.TestCase):
    def test_current_verified(self):
        for name in ("591","樂屋網","5168"):
            self.assertEqual(audit_source(name,{"complete":True,"updatedAt":stamp(210)},NOW)["status"],"ok")
        self.assertEqual(audit_source("信義房屋",{"runs":{"信義房屋":{"status":"ok","checkedAt":stamp(210)}}},NOW)["status"],"ok")
    def test_four_hour_threshold(self):
        self.assertEqual(audit_source("591",{"complete":True,"updatedAt":stamp(240)},NOW)["status"],"stale")
    def test_failed_capture_not_healthy(self):
        self.assertEqual(audit_source("5168",{"complete":False,"updatedAt":stamp(0)},NOW)["status"],"error")
    def test_future_timestamp_untrusted(self):
        self.assertEqual(audit_source("樂屋網",{"complete":True,"updatedAt":stamp(-20)},NOW)["status"],"error")
if __name__=="__main__":unittest.main()
