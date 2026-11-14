import json, os, subprocess, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "zh-fact-polish/scripts"))
from fplib import guard

class GuardUpdates(unittest.TestCase):
    def test_target_separate_from_change(self):
        text = "这是一个用于检查篇幅的较短的段落。"
        issues, stats = guard.check(text, text, target_chars=100)
        self.assertTrue(any(x["rule"] == "题目字数需复核" and x["severity"] == "review" for x in issues))
        self.assertEqual(stats["len_change"], 0)

    def test_large_change_requires_review(self):
        text = "这是第一段需要经过保留的文章内容。"
        issues, _ = guard.check(text, text * 2)
        self.assertTrue(any(x["rule"] == "篇幅变化过大" and x["severity"] == "review" for x in issues))

    def test_registered_replacement_missing(self):
        script = Path(__file__).resolve().parents[1] / "zh-fact-polish/scripts/fp_guard.py"
        with tempfile.TemporaryDirectory() as td:
            d=Path(td);old="这次活动一共有300人参加。";new="这次活动一共有300人参加。"
            (d/"base.md").write_text(old,encoding="utf8");(d/"output.md").write_text(new,encoding="utf8")
            led={"claims":[{"id":"C01","text":old,"label":"可信","action":"改正","new_text":"这次活动一共有200人参加。","evidence":[]}]}
            (d/"ledger.json").write_text(json.dumps(led,ensure_ascii=False),encoding="utf8");(d/"diagnosis.json").write_text("{\"items\":[]}",encoding="utf8")
            env=dict(os.environ,PYTHONIOENCODING="utf-8");subprocess.run([sys.executable,str(script),str(d/"output.md"),"--workdir",str(d)],capture_output=True,env=env,timeout=30)
            result=json.loads((d/"guard.json").read_text(encoding="utf8"));rules={x["rule"] for x in result["issues"]}
            self.assertIn("登记改后句不在终稿",rules);self.assertIn("原句仍在终稿",rules);self.assertFalse(result["ready_for_delivery"])
