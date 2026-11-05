import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from warelist_structured_fields import normalize_floor,source_fields,source_floor_tokens

class WarelistStructuredTests(unittest.TestCase):
    def test_normal_single_floor(self):
        self.assertEqual(normalize_floor('20F/24F'),'20/24樓')
        self.assertEqual(normalize_floor('3F/4F'),'3/4樓')
    def test_multilevel_and_whole_building(self):
        self.assertEqual(normalize_floor('1F~2F/3F'),'1~2/3樓')
        self.assertIsNone(normalize_floor('整棟/3F'))
        self.assertIsNone(normalize_floor('高樓層'))
        self.assertIsNone(normalize_floor('B1F/6F'))
        self.assertIsNone(normalize_floor('7F/4F'))
    def test_source_metadata_no_inferences(self):
        d=source_fields({'floor':'4F/5F','room':'3房2廳2衛','houseage':37,
           'community_name':'測試社區','kind_name':'住宅','has_carport':0,
           'address':'某路段'})
        self.assertEqual(d['structuredFloor'],'4/5樓')
        self.assertEqual(d['structuredLayout'],'3房2廳2衛')
        self.assertEqual(d['sourceHouseAge'],37)
        self.assertFalse(d['sourceParkingFlag'])
        self.assertNotIn('address',d)
    def test_unknown_floor_not_guessed(self):
        d=source_fields({'floor':'整棟/3F','title':'陽光三樓'})
        self.assertNotIn('structuredFloor',d)
        self.assertEqual(source_floor_tokens(d),set())
    def test_floor_conflict(self):
        a=source_fields({'floor':'3F/5F'})
        b=source_fields({'floor':'4F/5F'})
        self.assertTrue(source_floor_tokens(a).isdisjoint(source_floor_tokens(b)))
    def test_missing_critical_fields_do_not_raise(self):
        self.assertEqual(source_fields({}),{})
if __name__=='__main__':unittest.main()
