import unittest
from scripts.preview_source_integrity import build,verified,add_freshness,SINYI_FEED
from pathlib import Path

ROADS=['中山路二段','三民路一段','三民路二段','翠華街','林森街','萬安街','光復街']
def snapshot(ids):
    return {'complete':True,'updatedAt':'2026-11-05T00:00:00+00:00',
            'roadCounts':[{'road':r,'count':len(ids) if i==0 else 0} for i,r in enumerate(ROADS)],
            'listings':[{'listingId':x,'firstSeenAt':'2026-10-01T00:00:00+00:00','sourcePublishedAt':1790000000} for x in ids]}
def sources():
    return {s:{'complete':False} for s in ('591','信義房屋','樂屋網','5168')}
class SafetyTests(unittest.TestCase):
    def test_duplicate_ids_rejected(self):
        self.assertFalse(verified('5168',snapshot(['1','1']))[0])
    def test_incomplete_retains_old_observation(self):
        prev={'entries':{'樂屋網':{'樂屋網:old':{'seenOnLastVerifiedCheck':True}}}}
        res=build(prev,sources())
        self.assertEqual(res['sources']['樂屋網']['status'],'stale')
        self.assertTrue(res['entries']['樂屋網']['樂屋網:old']['seenOnLastVerifiedCheck'])
    def test_missing_id_never_deleted(self):
        s=sources(); s['樂屋網']=snapshot(['1'])
        old={'entries':{'樂屋網':{'樂屋網:gone':{'seenOnLastVerifiedCheck':True}}}}
        res=build(old,s); entry=res['entries']['樂屋網']['樂屋網:gone']
        self.assertFalse(entry['seenOnLastVerifiedCheck'])
        self.assertNotIn('removedAt',entry)
    def test_reappeared_id_preserves_original_first_seen(self):
        s=sources();s['5168']=snapshot(['1'])
        old={'entries':{'5168':{'5168:1':{'firstObservedAt':'2026-01-01T00:00:00+00:00','seenOnLastVerifiedCheck':False}}}}
        res=build(old,s)
        self.assertEqual(res['entries']['5168']['5168:1']['firstObservedAt'],'2026-01-01T00:00:00+00:00')
        self.assertEqual(res['sources']['5168']['reappearedIdCount'],1)
        self.assertTrue(res['sources']['5168']['newIdIsNotNewProperty'])
    def test_sinyi_history_and_health_come_from_independent_feed(self):
        self.assertEqual(SINYI_FEED, Path('docs/preview/sinyi-source.json'))
        roads=['板橋區'+r for r in ROADS]
        stamp='2026-11-05T02:00:00+00:00'
        payload={
            'source':'信義房屋', 'previewOnly':True, 'complete':True,
            'updatedAt':stamp, 'noOffmarketDecision':True,
            'noAutomaticNewPropertyDecision':True,
            'roadCounts':[{'road':r,'count':1 if i==0 else 0}
                          for i,r in enumerate(roads)],
            'uniqueListingCount':1,
            'runs':{'信義房屋':{'status':'ok','checkedAt':stamp,'totalCount':1}},
            'listings':[{'id':'信義房屋:ABCD', 'houseId':'ABCD',
                         'source':'信義房屋','road':roads[0],
                         'sinyiApiVerifiedAt':stamp}],
        }
        self.assertTrue(verified('信義房屋',payload)[0])
        s=sources()
        s['信義房屋']=payload
        result=build({},s)
        self.assertEqual(result['sources']['信義房屋']['lastVerifiedAt'],stamp)
        self.assertEqual(result['sources']['信義房屋']['observedIdCount'],1)
        self.assertIn('信義房屋:ABCD',result['entries']['信義房屋'])
        payload['complete']=False
        self.assertFalse(verified('信義房屋',payload)[0])

    def test_four_sources_independently_report_freshness(self):
        s=sources(); s['5168']=snapshot(['1'])
        report=build({},s)
        add_freshness(report,now='2026-11-05T03:30:00+00:00',limit_minutes=240)
        self.assertEqual(report['sources']['5168']['health'],'healthy')
        self.assertEqual(report['sources']['5168']['minutesSinceVerified'],210)
        self.assertEqual(report['sources']['591']['health'],'unverified')
        self.assertTrue(report['sources']['591']['alertRequired'])
    def test_overdue_does_not_mark_property_offmarket(self):
        s=sources(); s['5168']=snapshot(['1'])
        report=build({},s)
        add_freshness(report,now='2026-11-06T00:00:00+00:00',limit_minutes=240)
        self.assertEqual(report['sources']['5168']['health'],'overdue')
        self.assertEqual(report['sources']['5168']['status'],'ok')
        self.assertTrue(report['entries']['5168']['5168:1']['seenOnLastVerifiedCheck'])
if __name__=='__main__': unittest.main()
