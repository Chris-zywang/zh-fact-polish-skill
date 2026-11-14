"""篇章层诊断（候选 + 分数，最终由 Agent 判定）：
  E3 前后矛盾候选：同一对象在不同句中出现不同数字；同一句式的肯定与否定
  E4 钻牛角尖：让步/否定式界定链过密；段落偏离题目关键词
  E5 空转：段落具体性低（缺数字、专名、实例）；段间内容高度重复；结尾复述开头"""
import re
from collections import defaultdict
from .text import split_sentences, cjk_len, strip_md
from .claims import NUM, YEAR, TITLE

CONCESSION = re.compile(r'当然|诚然|固然|不可否认|诚然|话虽如此|但是|但|然而|不过|可是|却|反而')
NEG_DEF = re.compile(r'不是[^。！？；]{1,25}?[，,]?\s*(?:而是|更不是|也不是)|并不(?:等于|意味着|是)|不等于|不意味着|并非')
CONCRETE = [
    re.compile(r'\d'),                                       # 数字
    re.compile(r'《[^》]+》'),                                # 书名作品
    re.compile(r'[“"][^”"]{2,}[”"]'),                         # 引语
    re.compile(r'(?:19|20)\d{2}'),                            # 年份
    re.compile(r'[一-鿿]{1,3}(?:省|市|县|镇|村|区|山|河|湖|岛|街|路|楼|馆|厅|室)'),  # 地点
    re.compile(r'[一-鿿]{2,4}(?:先生|女士|教授|老师|院士|主任|同学|馆长|校长|经理)|[一-鿿]·[一-鿿]'),  # 人物
    re.compile(r'比如|例如|譬如|以[一-鿿]{2,6}为例'),                # 举例
]
ABSTRACT = re.compile(r'意义|价值|精神|力量|温度|底色|内涵|本质|方式|过程|习惯|态度|情怀|担当|坚持|成长|未来|生活|日常|阅读|读书|世界')


def specificity(p):
    """每百字具体信息单位数。"""
    s = strip_md(p)
    n = sum(len(r.findall(s)) for r in CONCRETE)
    return n / max(cjk_len(s), 1) * 100


def _bigrams(s):
    s = re.sub(r'[^一-鿿]', '', s)
    return {s[i:i + 2] for i in range(len(s) - 1)}


def overlap(a, b):
    A, B = _bigrams(a), _bigrams(b)
    return len(A & B) / max(1, min(len(A), len(B)))


def info_units(p):
    s = strip_md(p)
    u = set()
    for r in CONCRETE[:6]:
        u |= set(r.findall(s))
    return u


def hollow_candidates(paras, th_novel=0.62, th_novel_hard=0.5):
    """E5 空转：段落相对“前文 + 素材”的新增内容太少。
    只和本文前面的段落比较（新闻稿首段复述素材属于正常写法，不算空转）。
    novelty = 本段中前文未出现过的汉字二元组比例；new_units = 本段新出现的数字/专名/引语等。
    阈值来自开发集（v1 原生 40 篇）：段落 novelty 的 P5≈0.66、P10≈0.71。
    判定：novelty < 0.5，或 novelty < 0.62 且没有任何新信息单位。"""
    out = []
    seen_b, seen_u = set(), set()
    for i, (l, p) in enumerate(paras):
        b, u = _bigrams(p), info_units(p)
        nov = len(b - seen_b) / max(len(b), 1)
        nu = len(u - seen_u)
        is_note = re.match(r'^[（(]?(?:数据来源|资料来源|注[:：])', p)
        if cjk_len(p) >= 60 and i > 0 and not is_note:
            if nov < th_novel_hard or (nov < th_novel and nu == 0):
                out.append({'rule': 'E5_空转候选', 'line': l, 'text': p[:60], 'score': round(nov, 2),
                            'reasons': [f'本段只有 {nov:.0%} 的内容是前文（含素材）没出现过的，'
                                        f'新增具体信息 {nu} 处；可能在重复已说过的话']})
        seen_b |= b
        seen_u |= u
    return out


def repeated_fact_candidates(paras):
    """Suggest review for later sentences repeating multiple numeric facts.

    Numeric overlap is never itself proof of redundancy: keep this as a
    candidate and let the editor consider context and information loss.
    """
    prior = []
    out = []
    for line, paragraph in paras:
        for sentence in split_sentences(paragraph):
            clean = strip_md(sentence)
            if cjk_len(clean) < 14:
                continue
            numbers = {n.group(1) for n in NUM.finditer(clean)}
            if len(numbers) >= 2:
                for previous_line, previous, old_numbers in prior:
                    common = numbers & old_numbers
                    similarity = overlap(clean, previous)
                    if len(common) >= 2 and similarity >= 0.55:
                        out.append({'rule': 'E5_重复事实候选', 'line': line,
                                    'text': sentence[:80], 'score': round(similarity, 2),
                                    'reasons': [f'与第{previous_line}行至少重复{len(common)}个数字，字词重合度{similarity:.0%}；'
                                                '请检查是否有新增信息；不得仅凭数字相同删除']})
                        break
            prior.append((line, clean, numbers))
    return out


def overargue_candidates(paras, th=0.5):
    """E4：一段里让步/转折 + 否定式界定的句子占比过高，像在和假想对手反复拉扯。"""
    out = []
    for l, p in paras:
        ss = split_sentences(p)
        if len(ss) < 3:
            continue
        hits = [s for s in ss if CONCESSION.search(s) or NEG_DEF.search(s)]
        r = len(hits) / len(ss)
        if r >= th and len(hits) >= 3:
            out.append({'rule': 'E4_反复让步与界定', 'line': l, 'text': p[:60], 'score': round(r, 2),
                        'reasons': [f'{len(hits)}/{len(ss)} 句是让步、转折或"不是…而是"式界定']})
    return out


def _subjects(s):
    """取“数字+量词+后面最近的名词”作为对象键，如“28名志愿者”→(名|志愿者, 28)。"""
    res = []
    for m in NUM.finditer(s):
        unit = (m.group(2) or '').strip()
        if not unit or unit in ('%', '％', '‰') or YEAR.match(s[m.start():m.end(1) + 2]):
            continue
        noun = re.match(r'[一-鿿]{2,4}', s[m.end():m.end() + 4])
        if noun:
            res.append((unit + '|' + noun.group(0)[:3], m.group(1) + unit))
    return res


def contradiction_candidates(paras):
    """E3：同一“对象|单位”在全文出现不同数值。只给候选，由 Agent 判断是否真矛盾。"""
    seen = defaultdict(list)
    for l, p in paras:
        for s in split_sentences(p):
            for key, val in _subjects(s):
                seen[key].append((l, val, s))
    out = []
    for key, vs in seen.items():
        vals = {v for _, v, _ in vs}
        sents = {s for _, _, s in vs}
        # 同一句里并列出现多个数（枚举、对比）不算矛盾；必须是不同句子给出不同数值
        by_sent = defaultdict(set)
        for _, v, s in vs:
            by_sent[s].add(v)
        if any(len(x) > 1 for x in by_sent.values()):
            continue
        if len(vals) > 1 and len(sents) > 1:
            out.append({'rule': 'E3_数字前后不一致候选', 'line': vs[0][0],
                        'text': '；'.join(f'第{l}行「{s[:30]}」' for l, _, s in vs[:3]),
                        'score': len(vals), 'reasons': [f'“{key.split("|")[1]}”的数量有 {"、".join(sorted(vals))}，请确认是否指同一对象']})
    return out
