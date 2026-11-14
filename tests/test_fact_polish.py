"""zh-fact-polish 单元测试。在 03_skill 目录下运行：D:\\Python311\\python.exe -m unittest discover -s tests"""
import os, sys, unittest
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, 'zh-fact-polish', 'scripts'))
from fplib import claims, evidence, discourse, grammar, refparse, guard, text  # noqa: E402


def ks(s):
    return claims.keys_of(s)


class TestKeys(unittest.TestCase):
    def test_numbers_after_cjk(self):
        self.assertEqual(ks('筛选了200多种中药、380多个提取物，不到40%')['numbers'], ['200多种', '380多个', '40%'])

    def test_wan_unit(self):
        self.assertIn('112万亩', ks('有林地112万亩')['numbers'])

    def test_year_separate(self):
        k = ks('1962年，369名建设者登上塞罕坝')
        self.assertEqual(k['years'], ['1962'])
        self.assertEqual(k['numbers'], ['369名'])

    def test_dates_not_numbers(self):
        self.assertEqual(ks('2012年1月19日向法院申请破产')['numbers'], [])

    def test_generic_cn_counts_ignored(self):
        self.assertEqual(ks('这是一个习惯，也是一种态度')['numbers'], [])

    def test_quote_needs_speech_verb(self):
        self.assertEqual(ks('他说："希望同学们把读书当成一种习惯。"')['quotes'], ['希望同学们把读书当成一种习惯。'])
        self.assertEqual(ks('所谓"慢下来"的道理')['quotes'], [])

    def test_titles(self):
        self.assertEqual(ks('葛洪《肘后备急方》记载')['titles'], ['肘后备急方'])


class TestExtract(unittest.TestCase):
    def test_flags_unsourced(self):
        cs = claims.extract([(1, '我国每年浪费粮食1700万吨，相当于3000万人一年的口粮。')])
        self.assertIn('F1_数据无来源', cs[0]['flags'])

    def test_sourced_no_flag(self):
        cs = claims.extract([(1, '据国家统计局2024年数据，全国人口为14.08亿人。')])
        self.assertNotIn('F1_数据无来源', cs[0]['flags'])

    def test_vague_flag(self):
        cs = claims.extract([(1, '大量研究表明，熬夜会损害记忆力和免疫力。')])
        self.assertIn('F2_模糊化来源', cs[0]['flags'])

    def test_material_extra_number(self):
        mat = '约 300 名师生参加，发放 200 份书签'
        cs = claims.extract([(1, '约300名师生参加了开幕式，现场发放书签500份。')], mat)
        self.assertIn('F6_超出素材', cs[0]['flags'])

    def test_material_ok(self):
        mat = '约 300 名师生参加，发放 200 份书签'
        cs = claims.extract([(1, '约300名师生参加了开幕式，现场发放了200份书签。')], mat)
        self.assertNotIn('F6_超出素材', cs[0]['flags'])

    def test_material_extra_quote(self):
        mat = '刘建平致辞原话："希望同学们把读书当成一种习惯。"'
        cs = claims.extract([(1, '刘建平说："读书是一辈子的事情，大家要坚持下去。"')], mat)
        self.assertIn('F6_超出素材', cs[0]['flags'])


C = claims.extract([(1, '截至2024年12月，我国网民规模达11.08亿，互联网普及率为78.6%。')])[0]


class TestEvidence(unittest.TestCase):
    def test_trusted(self):
        ev = {'url': 'https://www.cnnic.net.cn/x', 'agent_verdict': '支持',
              'excerpt': '截至2024年12月，我国网民规模达11.08亿人，较2023年12月增长1608万人，互联网普及率达78.6%。'}
        self.assertEqual(evidence.judge(C, ev, online=False)[0], '可信')

    def test_excerpt_mismatch(self):
        ev = {'url': 'https://www.cnnic.net.cn/x', 'agent_verdict': '支持', 'excerpt': '我国网民规模持续增长，数字中国建设成效显著。'}
        self.assertEqual(evidence.judge(C, ev, online=False)[0], '待验证')

    def test_no_url(self):
        ev = {'url': '', 'agent_verdict': '支持', 'excerpt': '截至2024年12月网民规模达11.08亿，普及率78.6%'}
        self.assertEqual(evidence.judge(C, ev, online=False)[0], '待验证')

    def test_contradict(self):
        self.assertEqual(evidence.judge(C, {'url': 'https://a.b', 'agent_verdict': '矛盾', 'excerpt': 'x' * 20}, online=False)[0], '存疑')

    def test_not_found(self):
        self.assertEqual(evidence.judge(C, None, online=False)[0], '待验证')

    def test_number_variants(self):
        c = claims.extract([(1, '我国60岁以上人口达3.1亿人。')])[0]
        ev = {'url': 'https://www.stats.gov.cn/x', 'agent_verdict': '支持', 'excerpt': '60岁及以上人口310310000人'}
        self.assertEqual(evidence.judge(c, ev, online=False)[0], '可信')


class TestEvidenceV21(unittest.TestCase):
    MAT = '规模：约 300 名师生参加；开幕式现场发放了 200 份书签'

    def test_material_source(self):
        c = claims.extract([(1, '约300名师生参加了开幕式，现场发放了200份书签。')], self.MAT)[0]
        ev = [{'url': 'material.md', 'excerpt': '规模：约 300 名师生参加', 'agent_verdict': '支持'}]
        self.assertEqual(evidence.judge(c, ev, self.MAT, online=False)[0], '可信')

    def test_multi_evidence_merge(self):
        c = claims.extract([(1, '1962年369名建设者登上塞罕坝；2017年塞罕坝获联合国地球卫士奖。')])[0]
        ev = [{'url': 'https://a.cn/1', 'excerpt': '1962年，369名平均年龄不到24岁的建设者来到塞罕坝', 'agent_verdict': '支持'},
              {'url': 'https://b.cn/2', 'excerpt': '2017年12月，塞罕坝林场建设者获得联合国环境规划署"地球卫士奖"', 'agent_verdict': '支持'}]
        self.assertEqual(evidence.judge(c, ev, online=False)[0], '可信')

    def test_single_evidence_partial(self):
        c = claims.extract([(1, '1962年369名建设者登上塞罕坝；2017年塞罕坝获联合国地球卫士奖。')])[0]
        ev = [{'url': 'https://a.cn/1', 'excerpt': '塞罕坝林场的建设者们长期坚持造林，成绩显著', 'agent_verdict': '支持'}]
        self.assertEqual(evidence.judge(c, ev, online=False)[0], '待验证')

    def test_qualitative_requires_review(self):
        c = claims.extract([(1, '研究表明，长期睡眠不足会降低接种疫苗后的抗体水平。')])[0]
        ev = [{'url': 'https://www.cdc.gov/x', 'excerpt': 'Studies show that people who do not get enough sleep produce fewer antibodies after vaccination.',
               'agent_verdict': '支持'}]
        lab, r, _ = evidence.judge(c, ev, online=False)
        # v2.2 policy change: Agent self-verdict alone is not semantic validation.
        self.assertEqual(lab, '待验证')
        self.assertTrue(r[0].startswith('（定性）'))

    def test_qualitative_weak(self):
        c = claims.extract([(1, '研究表明，长期睡眠不足会降低接种疫苗后的抗体水平。')])[0]
        ev = [{'url': 'https://www.cdc.gov/x', 'excerpt': '睡眠很重要', 'agent_verdict': '支持'}]
        self.assertEqual(evidence.judge(c, ev, online=False)[0], '待验证')

    def test_english_million(self):
        c = claims.extract([(1, '2019年的全球评估报告指出，约100万种动植物面临灭绝威胁。')])[0]
        ev = [{'url': 'https://www.ipbes.net/x', 'excerpt': '05 May 2019 around 1 million animal and plant species are now threatened',
               'agent_verdict': '支持'}]
        self.assertEqual(evidence.judge(c, ev, online=False)[0], '可信')

    def test_meta_flatten_year(self):
        js = {'message': {'title': ['Long Short-Term Memory'], 'author': [{'family': 'Hochreiter'}, {'family': 'Schmidhuber'}],
                          'issued': {'date-parts': [[1997, 11, 1]]}}}
        t = evidence._flatten_meta(js)
        self.assertIn('1997', t)
        self.assertIn('Hochreiter', t)

    def test_v20_dict_compat(self):
        self.assertEqual(len(evidence.as_list({'url': 'https://a.b', 'excerpt': 'x', 'agent_verdict': '支持'})), 1)


class TestDiscourse(unittest.TestCase):
    def test_repeated_fact_is_only_a_candidate(self):
        paras = [(1, '活动有28名志愿者分成4个小组为老人提供服务。'),
                 (4, '28名志愿者分成4个小组，按计划为老人提供服务。')]
        found = discourse.repeated_fact_candidates(paras)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]['rule'], 'E5_重复事实候选')
        self.assertIn('不得仅凭数字相同删除', found[0]['reasons'][0])

    def test_repeated_single_number_is_not_enough(self):
        paras = [(1, '活动有28名志愿者，每周参加社区服务。'),
                 (4, '另有28名老人参加了医疗讲座活动。')]
        self.assertEqual(discourse.repeated_fact_candidates(paras), [])

    def test_hollow_repeat(self):
        p1 = '本届读书节由图书馆和团委主办，共设打卡、诵读比赛、旧书交换和作家讲座四项活动，持续一个月，希望同学们在一个月里多读几本书，让阅读成为校园生活的一部分。'
        p2 = '读书节共设打卡、诵读比赛、旧书交换和作家讲座四项活动，由图书馆和团委主办，持续一个月，希望同学们在这一个月里多读几本书，让阅读成为校园生活的一部分。'
        self.assertTrue(discourse.hollow_candidates([(1, p1), (2, p2)]))

    def test_not_hollow_new_info(self):
        p1 = '1962年，369名建设者登上塞罕坝，头两年造林成活率不足5%，荒原上几乎看不到成片的树。'
        p2 = '1975年，柯达工程师萨森造出第一台数码相机，管理层担心冲击胶卷利润，把它锁进了实验室。'
        self.assertFalse(discourse.hollow_candidates([(1, p1), (2, p2)]))

    def test_overargue(self):
        p = ('当然，坚持很重要。但是坚持不等于固执。然而放弃也不是逃避。不过放弃并不意味着失败。'
             '可是很多人分不清两者。')
        self.assertTrue(discourse.overargue_candidates([(1, p)]))

    def test_contradiction_candidate(self):
        ps = [(1, '本次活动共有28名志愿者参加，分为4个小组。'), (2, '活动结束后，30名志愿者合影留念。')]
        self.assertTrue(discourse.contradiction_candidates(ps))


def gr(c):
    return [h[0] for h in grammar.check_clause(c)]


class TestGrammarRegression(unittest.TestCase):
    """v1 误报回归：这些是正确的中文，不能报语病。"""
    def test_le_de_ok(self):
        for c in ['一只翻了的塑料盆', '颜色像放久了的猪肝', '一根弯了的伞骨']:
            self.assertEqual(gr(c), [], c)

    def test_neg_le_ok(self):
        self.assertEqual(gr('他也没有因此乱了自己的脚步'), [])

    def test_still_catch(self):
        self.assertTrue(gr('他没有完成了任务'))
        self.assertTrue(gr('人工智能必将改变了世界'))
        self.assertTrue(gr('这是已经完成了的任务'))


class TestRefRegression(unittest.TestCase):
    def test_arxiv_not_year(self):
        es = refparse.parse_entries('[1] Beltagy I, Peters M E, Cohan A. Longformer: The long-document transformer[EB/OL]. '
                                    'arXiv preprint arXiv:2004.05150, 2020.', 0)
        self.assertEqual(es[0]['year'], 2020)

    def test_title_year_not_pub_year(self):
        es = refparse.parse_entries('[1] Twenge J M, Martin G N, Campbell W K. Decreases in psychological well-being among '
                                    'American adolescents after 2012[J]. Emotion, 2018, 18(6): 765-780.', 0)
        self.assertEqual(es[0]['year'], 2018)

    def test_doi_not_year(self):
        es = refparse.parse_entries('[1] He K. Deep residual learning[C]//CVPR. 2016. DOI: 10.1109/CVPR.2016.90.', 0)
        self.assertEqual(es[0]['year'], 2016)


class TestGuard(unittest.TestCase):
    BASE = '1962年，369名建设者登上塞罕坝，头两年造林成活率不足5%。\n\n他们没有换地方，而是换了方法，改春季造林为雨季造林。\n'

    def test_identity_pass(self):
        iss, st = guard.check(self.BASE, self.BASE)
        self.assertFalse([i for i in iss if i['severity'] == 'error'])
        self.assertEqual(st['len_change'], 0)

    def test_lost_number(self):
        new = self.BASE.replace('369名', '一批')
        iss, _ = guard.check(self.BASE, new, ledger={'claims': []})
        self.assertTrue(any(i['rule'] == '关键信息丢失' for i in iss))

    def test_lost_explained(self):
        new = self.BASE.replace('369名', '一批')
        led = {'claims': [{'text': '1962年，369名建设者登上塞罕坝，头两年造林成活率不足5%。', 'action': '弱化', 'new_text': ''}]}
        iss, _ = guard.check(self.BASE, new, ledger=led)
        self.assertFalse(any(i['rule'] == '关键信息丢失' for i in iss))

    def test_new_fact_unlogged(self):
        new = self.BASE + '\n据统计，87.5%的青年表示认同。\n'
        iss, _ = guard.check(self.BASE, new, ledger={'claims': []})
        self.assertTrue(any(i['rule'] == '新增事实未入账' for i in iss))

    def test_length_blowup(self):
        new = self.BASE * 2
        iss, _ = guard.check(self.BASE, new)
        self.assertTrue(any(i['rule'] == '篇幅变化过大' for i in iss))


class TestText(unittest.TestCase):
    def test_split(self):
        self.assertEqual(text.split_sentences('他说：“走吧。”我点头。'), ['他说：“走吧。”', '我点头。'])

    def test_refs_split(self):
        b, r, ln = text.split_body_refs('正文[1]。\n\n## 参考文献\n[1] A. B[J]. C, 2020.')
        self.assertIn('[1] A', r)


if __name__ == '__main__':
    unittest.main()
