import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'zh-fact-polish/scripts'))
from fplib import sourcepack, evidence, claims

class SourcePackTests(unittest.TestCase):
    def setUp(self):
        self.material = ('[来源1] https://example.org/a\n2024年该公司利润为37亿元。\n'
                         '[来源2] https://example.org/b\n相关论文于2024年发表。')
    def test_multiple_excerpts_keep_individual_sources(self):
        x = {'excerpts': [{'excerpt':'2024年该公司利润为37亿元。','verdict':'支持'},
                          {'excerpt':'相关论文于2024年发表。','verdict':'支持'}]}
        got = sourcepack.evidence_entries(x,self.material)
        self.assertEqual([e['url'] for e in got],['https://example.org/a','https://example.org/b'])
    def test_separate_metadata_and_findings_can_resolve_missing_year(self):
        value='某研究于2019年发表，受试者100人。'
        claim={'text':value,'keys':claims.keys_of(value)}
        material='[来源1] https://example.org/paper\n某研究于2019年发表。\n研究招募100人。'
        only=sourcepack.evidence_entries({'excerpt':'研究招募100人。','verdict':'支持'},material)
        self.assertEqual(evidence.judge(claim,only,online=False)[0],'待验证')
        multi=sourcepack.evidence_entries({'excerpts':[{'excerpt':'某研究于2019年发表。','verdict':'支持'},
                                                       {'excerpt':'研究招募100人。','verdict':'支持'}]},material)
        self.assertEqual(evidence.judge(claim,multi,online=False)[0],'可信')

    def test_unfound_and_fabricated_cannot_support(self):
        x={'excerpts':[{'excerpt':'2024年该公司利润为99亿元。','verdict':'支持'},
                       {'excerpt':'相关论文于2024年发表。','verdict':'未找到'}]}
        got=sourcepack.evidence_entries(x,self.material)
        self.assertTrue(all(e['agent_verdict']=='未找到' for e in got))
        value='2024年该公司利润为99亿元。'
        self.assertNotEqual(evidence.judge({'text':value,'keys':claims.keys_of(value)},got,online=False)[0],'可信')
    def test_ambiguous_source_is_not_silently_resolved(self):
        material='[来源1] https://example.org/a\n同一段文字。\n[来源2] https://example.org/b\n同一段文字。'
        got=sourcepack.evidence_entries({'excerpt':'同一段文字。','verdict':'支持'},material)
        self.assertEqual(got[0]['agent_verdict'],'未找到')
    def test_news_only_uses_exact_material(self):
        good=sourcepack.evidence_entries({'excerpt':'参加300人','verdict':'支持'},'规模：参加300人',True)
        self.assertEqual(good[0]['url'],'material.md')
        bad=sourcepack.evidence_entries({'excerpt':'参加500人','verdict':'支持'},'规模：参加300人',True)
        self.assertEqual(bad[0]['agent_verdict'],'未找到')

if __name__ == '__main__': unittest.main()
