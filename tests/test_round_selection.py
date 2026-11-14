import unittest,tempfile,json,sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from select_best_round import select_best
class SelectRound(unittest.TestCase):
 def test_prefers_structural_pass_over_fewer_pending(self):
  with tempfile.TemporaryDirectory() as td:
   d=Path(td)
   for n,ok,pending in [(0,True,3),(1,False,0)]:
    (d/f'SK_round{n}.md').write_text('稿',encoding='utf8')
    (d/f'round{n}_ledger.json').write_text('{}',encoding='utf8')
    (d/f'round{n}_guard.json').write_text(json.dumps({'structural_passed':ok,'questionable_fact_count':0,'pending_fact_count':pending,'manual_review_count':0}),encoding='utf8')
   self.assertEqual(select_best(d,[{'round':0},{'round':1}])['round'],0)
 def test_missing_snapshot_not_chosen(self):
  with tempfile.TemporaryDirectory() as td:self.assertIsNone(select_best(td,[{'round':0}]))
