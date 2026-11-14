import unittest, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"zh-fact-polish/scripts"))
from fplib import guard
class Experience(unittest.TestCase):
 def test_new_past_action_requires_review(self):
  base="下周计划补充边界用例。"
  new=base+"这一周，我开始按边界条件的角度回看自己写过的用例。"
  issues,_=guard.check(base,new,material="下周计划补充边界用例。")
  self.assertTrue(any(x["rule"]=="新增个人经历待核" for x in issues))
 def test_original_action_not_flagged(self):
  base="这一周，我开始回看自己写过的用例。"
  issues,_=guard.check(base,base,material="下一周补充边界用例。")
  self.assertFalse(any(x["rule"]=="新增个人经历待核" for x in issues))
 def test_no_material_does_not_activate(self):
  issues,_=guard.check("这是原稿的一个简短说明。","这一周，我开始回看自己写过的用例。")
  self.assertFalse(any(x["rule"]=="新增个人经历待核" for x in issues))
