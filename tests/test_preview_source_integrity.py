import unittest
from scripts.preview_source_integrity import build,verified

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
if __name__=='__main__': unittest.main()
