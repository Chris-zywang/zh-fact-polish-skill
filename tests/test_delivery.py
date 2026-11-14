import sys
from pathlib import Path
import unittest
import tempfile
import subprocess
import json
import os

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'zh-fact-polish/scripts'))
from fplib import delivery


def entry(value, source, action='保留', new_text=''):
    return {'id': 'C01', 'text': value, 'action': action, 'new_text': new_text,
            'evidence': [{'url': 'https://example.invalid/source', 'excerpt': source, 'agent_verdict': '支持'}]}


class FinalFactChecks(unittest.TestCase):
    def test_rechecks_registered_changed_number(self):
        old = '该公司净利润为37亿元。'
        new = '该公司净利润为999亿元。'
        checks = delivery.assess(new, {'claims': [entry(old, old, '改正', new)]})
        self.assertEqual(checks[0]['label'], '存疑')

    def test_supported_registered_change(self):
        old = '该公司净利润为37亿元。'
        new = '该公司净利润为999亿元。'
        checks = delivery.assess(new, {'claims': [entry(old, new, '改正', new)]})
        self.assertEqual(checks[0]['label'], '可信')

    def test_final_evidence_is_assessed_against_corrected_sentence(self):
        old = '该公司净利润为37亿元。'
        new = '该公司净利润为999亿元。'
        record = entry(old, new, '改正', new)
        record['evidence'][0]['agent_verdict'] = '矛盾'
        record['final_evidence'] = [{'url': 'https://example.invalid/source', 'excerpt': new,
                                     'agent_verdict': '支持', 'note': '此判定针对修改句；原句的矛盾判断保留。'}]
        self.assertEqual(delivery.assess(new, {'claims': [record]})[0]['label'], '可信')

    def test_split_sentence_reuses_only_exact_fragment_evidence(self):
        old = '会上通报，活动预计有300人参加。'
        final = '活动预计有300人参加。'
        record = entry(old, final)
        checks = delivery.assess(final, {'claims': [record]})
        self.assertEqual(len(checks), 1)
        self.assertEqual(checks[0]['ledger_ids'], ['C01'])

    def test_ambiguous_fragment_cannot_inherit_evidence(self):
        final = '该项目共有300名参与者。'
        a = entry('消息称，该项目共有300名参与者。', final)
        b = {**entry('统计显示，该项目共有300名参与者。', final), 'id': 'C02'}
        checks = delivery.assess(final, {'claims': [a, b]})
        self.assertEqual(checks[0]['label'], '待验证')
        self.assertEqual(checks[0]['ledger_ids'], [])

    def test_no_evidence_is_pending_and_not_deliverable(self):
        from fplib import evidence
        self.assertEqual(evidence.judge({'text': '参加人数为300人。'}, None, online=False)[0], '待验证')

    def test_link_does_not_clear_qualitative_review(self):
        value = '研究表明，三套数据均来自英国青少年。'
        checks = delivery.assess(value, {'claims': [entry(value, 'Three datasets include adolescents in several countries.')]})
        self.assertEqual(checks[0]['label'], '待验证')


class GuardExitCodes(unittest.TestCase):
    def test_final_verdict_controls_delivery(self):
        fixtures = [
            ('该公司净利润为37亿元。', '该公司净利润为37亿元。', 0, True),
            ('研究表明，三套数据均来自英国青少年。', 'Three datasets are discussed in the research paper.', 2, False),
            ('该公司净利润为37亿元。', '该公司净利润为999亿元。', 1, False),
        ]
        script = Path(__file__).resolve().parents[1] / 'zh-fact-polish/scripts/fp_guard.py'
        for output, source, expected_code, expected_ready in fixtures:
            with self.subTest(expected_code=expected_code), tempfile.TemporaryDirectory() as folder:
                d = Path(folder)
                (d / 'base.md').write_text(output, encoding='utf-8')
                (d / 'output.md').write_text(output, encoding='utf-8')
                ledger = {'claims': [{**entry(output, source), 'label': '可信'}]}
                (d / 'ledger.json').write_text(json.dumps(ledger, ensure_ascii=False), encoding='utf-8')
                (d / 'diagnosis.json').write_text('{"items": []}', encoding='utf-8')
                proc = subprocess.run([sys.executable, '-B', str(script), str(d / 'output.md'), '--workdir', str(d)],
                                      capture_output=True, encoding='utf-8',
                                      env=dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1'), timeout=30)
                self.assertEqual(proc.returncode, expected_code, proc.stdout + proc.stderr)
                result = json.loads((d / 'guard.json').read_text(encoding='utf-8'))
                self.assertEqual(result['ready_for_delivery'], expected_ready)

    def test_missing_source_reports_review_without_approving_delivery(self):
        script = Path(__file__).resolve().parents[1] / 'zh-fact-polish/scripts/fp_guard.py'
        value = '该活动预计有300人参加。'
        with tempfile.TemporaryDirectory() as folder:
            d = Path(folder)
            (d / 'base.md').write_text(value, encoding='utf-8')
            (d / 'output.md').write_text(value, encoding='utf-8')
            ledger = {'claims': [{**entry(value, value), 'label': '待验证', 'evidence': []}]}
            (d / 'ledger.json').write_text(json.dumps(ledger, ensure_ascii=False), encoding='utf-8')
            (d / 'diagnosis.json').write_text('{"items": []}', encoding='utf-8')
            proc = subprocess.run([sys.executable, '-B', str(script), str(d / 'output.md'), '--workdir', str(d)],
                                  capture_output=True, encoding='utf-8',
                                  env=dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1'), timeout=30)
            self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
            result = json.loads((d / 'guard.json').read_text(encoding='utf-8'))
            self.assertFalse(result['ready_for_delivery'])
            self.assertGreater(result['pending_fact_count'], 0)

    def test_preserved_number_without_year_requires_review(self):
        from fplib import guard
        old = '2023年调查显示，该公司利润为37亿元。'
        new = '调查显示，该公司利润为37亿元。'
        rec = entry(old, old, '改正', new)
        issues, stats = guard.check(old, new, ledger={'claims': [rec]})
        self.assertEqual(stats['temporal_scope_review'], 1)
        self.assertTrue(any(x['severity'] == 'review' for x in issues))

    def test_unchanged_year_does_not_trigger_scope_review(self):
        from fplib import guard
        old = '2023年调查显示，该公司利润为37亿元。'
        new = '据调查，2023年该公司利润为37亿元。'
        rec = entry(old, old, '改正', new)
        _, stats = guard.check(old, new, ledger={'claims': [rec]})
        self.assertEqual(stats['temporal_scope_review'], 0)

    def test_new_chinese_duration_requires_review(self):
        from fplib import guard
        old = '摄影协会开展了年度工作。'
        new = '摄影协会这十个月开展了年度工作。'
        issues, stats = guard.check(old, new, ledger={'claims': []})
        self.assertEqual(stats['new_chinese_duration_review'], 1)
        self.assertTrue(any(x['rule'] == '新增中文时长待核' and x['severity'] == 'review' for x in issues))

    def test_existing_chinese_duration_does_not_trigger(self):
        from fplib import guard
        old = '摄影协会这十个月开展了年度工作。'
        _, stats = guard.check(old, old, ledger={'claims': []})
        self.assertEqual(stats['new_chinese_duration_review'], 0)

    def test_unregistered_new_sentence_needs_review(self):
        old = '该公司净利润为37亿元。'
        new = '该公司净利润为999亿元。'
        checks = delivery.assess(new, {'claims': [entry(old, old)]})
        self.assertEqual(checks[0]['label'], '待验证')


if __name__ == '__main__':
    unittest.main()
