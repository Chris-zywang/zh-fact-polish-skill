"""Behavioral regression cases: supported facts must stay usable; bad bindings must not pass."""
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'zh-fact-polish/scripts'))
from fplib import claims, evidence


class EvidenceRelations(unittest.TestCase):
    def test_reference_cases(self):
        cases = json.loads((ROOT / 'validation/development_cases.json').read_text(encoding='utf-8'))
        for case in cases:
            with self.subTest(case=case['id']):
                claim = {'text': case['claim'], 'keys': claims.keys_of(case['claim'])}
                evs = [{'url': 'https://example.invalid/development-fixture', 'excerpt': text,
                        'agent_verdict': '支持'} for text in case['sources']]
                label, reasons, _ = evidence.judge(claim, evs, online=False)
                self.assertEqual(label == '可信', case['expected_trusted'], reasons)

    def test_unfound_excerpt_cannot_supply_missing_fact(self):
        claim = {'text': '2024年该公司利润为37亿元。', 'keys': claims.keys_of('2024年该公司利润为37亿元。')}
        evs = [{'url': 'https://example.invalid/a', 'excerpt': '2024年该公司销售额100亿元。', 'agent_verdict': '支持'},
               {'url': 'https://example.invalid/b', 'excerpt': '2024年该公司利润为37亿元。', 'agent_verdict': '未找到'}]
        self.assertNotEqual(evidence.judge(claim, evs, online=False)[0], '可信')

    def test_metadata_url_uses_hostname(self):
        self.assertTrue(evidence.is_meta_url('https://api.crossref.org/works/10.1/test'))
        self.assertFalse(evidence.is_meta_url('https://example.invalid/?next=api.crossref.org'))
        self.assertFalse(evidence.is_meta_url('https://api.crossref.org.example.invalid/works/x'))
        self.assertFalse(evidence.is_meta_url('https://[invalid-host'))

    def test_unbound_year_from_another_source_requires_review(self):
        value = '1962年，当年造林成活率不足5%。'
        claim = {'text': value, 'keys': claims.keys_of(value)}
        evs = [{'url': 'https://example.invalid/a', 'excerpt': '1962年建设者进驻林场。', 'agent_verdict': '支持'},
               {'url': 'https://example.invalid/b', 'excerpt': '当年春夏之交栽下松树。然而，林木成活率不足5%。', 'agent_verdict': '支持'}]
        self.assertEqual(evidence.judge(claim, evs, online=False)[0], '待验证')

    def test_year_cannot_be_borrowed_from_unrelated_excerpt(self):
        value = '2023年该公司利润为37亿元。'
        claim = {'text':value, 'keys':claims.keys_of(value)}
        evs = [{'url':'https://example.invalid/a','excerpt':'该公司成立于2023年。','agent_verdict':'支持'},
               {'url':'https://example.invalid/b','excerpt':'该公司利润为37亿元。','agent_verdict':'支持'}]
        self.assertNotEqual(evidence.judge(claim, evs, online=False)[0], '可信')
        evs[1]['excerpt'] = '2023年该公司利润为37亿元。'
        self.assertEqual(evidence.judge(claim, evs, online=False)[0], '可信')

    def test_english_pronoun_is_not_country_evidence(self):
        value = '美国的一项调查共有100名参与者。'
        claim = {'text': value, 'keys': claims.keys_of(value)}
        source = {'url': 'https://example.invalid/a', 'excerpt': 'The survey gives us 100 people to study.', 'agent_verdict': '支持'}
        self.assertNotEqual(evidence.judge(claim, source, online=False)[0], '可信')
        source['excerpt'] = 'A survey in the US included 100 people.'
        self.assertEqual(evidence.judge(claim, source, online=False)[0], '可信')


if __name__ == '__main__':
    unittest.main()
