"""表达层检查：句式模板重复、套话密度、句长单调、段首/段尾雷同、翻译腔。
每个检查返回 issue 列表：{cat, rule, severity, line, text, suggestion}
severity: error（硬错误，必须改） / warn（应当改） / info（参考）"""
import re, statistics
from collections import Counter, defaultdict
from . import lexicon as lx
from .text import split_sentences, split_clauses, cjk_len, strip_md

# 阈值（在 dev 集 T01–T10 上调定，test 集不参与调参）
TH = {
    'contrast_per_doc': 2,        # 全文“不是…而是”类对举句超过该数 → 逐条报出
    'intens_per_doc': 3,          # “真正的/从来/恰恰”超过该数 → 报出
    'cliche_per_doc': 1,          # 同一类套话出现 >1 次 → 报
    'para_head_repeat': 3,        # 同一段首词 >= 该数 → 报
    'connector_chain': 3,         # 首先/其次/最后、其一/其二/其三 成套使用 → 报
    'aphorism_end_ratio': 0.4,    # 以警句收尾的段落占比 >= 该值 → 报
    'sent_len_cv_min': 0.35,      # 句长变异系数低于该值 → 句长单调
    'long_sent': 90,              # 单句汉字数 > 该值 → 过长
    'semicolon_run': 3,           # 一句里分号 >= 该数 → 排比堆砌
    'quote_per_1k': 8.0,          # 引号短语密度（每千字）超过 → 引号滥用
}
# 学术文本：主题词做段首、较长的复句都属正常，放宽两项
PAPER_TH = dict(TH, para_head_repeat=4, long_sent=120)


def set_genre(genre):
    global TH
    TH = PAPER_TH if genre == 'paper' else BASE_TH


BASE_TH = dict(TH)

APHORISM = re.compile(r'不是[^。]*而是|从来|真正的|才是|恰恰|唯有|并非|而非|不在于|与其')
CONNECTOR_SETS = [('首先', '其次', '最后'), ('其一', '其二', '其三'), ('第一', '第二', '第三'),
                  ('一是', '二是', '三是')]


def _issue(cat, rule, sev, line, text, sug):
    return {'cat': cat, 'rule': rule, 'severity': sev, 'line': line,
            'text': text[:80], 'suggestion': sug}


def check_contrast(paras):
    """对举纠偏句（不是…而是）：AI 文本最典型的模板，单篇超过阈值才报。"""
    hits = []
    for line, p in paras:
        for s in split_sentences(p):
            if any(re.search(pat, s) for pat in lx.CONTRAST):
                hits.append((line, s))
    if len(hits) <= TH['contrast_per_doc']:
        return [], len(hits)
    out = [_issue('句式重复', '“不是…而是…”类对举句过多', 'warn', l, s,
                  f'全文“不是…而是…”式对举句偏多（{len(hits)} 处），读起来像模板。'
                  '保留最有力的一处，其余改为正面直述，如“X 不是 A，而是 B”→“X 是 B”或补充具体理由')
           for l, s in hits]
    return out, len(hits)


def check_intensifiers(paras):
    hits = [(l, m.group(0), s) for l, p in paras for s in split_sentences(p)
            for m in re.finditer(lx.INTENSIFIERS, s)]
    if len(hits) <= TH['intens_per_doc']:
        return [], len(hits)
    return [_issue('套话', f'绝对化强调词“{w}”过多', 'warn', l, s,
                   f'“真正的/从来/恰恰”等强调词偏多（{len(hits)} 处），'
                   '多数可直接删去而不改变意思')
            for l, w, s in hits], len(hits)


def check_cliches(paras):
    out, by_rule = [], defaultdict(list)
    for l, p in paras:
        for s in split_sentences(p):
            for pat, name, sug in lx.CLICHES:
                if re.search(pat, s):
                    by_rule[(name, sug)].append((l, s))
    n = sum(len(v) for v in by_rule.values())
    for (name, sug), hs in by_rule.items():
        if len(hs) > TH['cliche_per_doc'] or name in ('提示性套话', '互联网黑话', '宣传腔'):
            out += [_issue('套话', name, 'warn', l, s, sug) for l, s in hs]
    return out, n


def check_translationese(paras):
    out = []
    for l, p in paras:
        for s in split_sentences(p):
            for pat, name, sug in lx.TRANSLATIONESE:
                m = re.search(pat, s)
                if m:
                    out.append(_issue('表达不通顺', name, 'warn', l, m.group(0), sug))
            for c in split_clauses(s):
                if c.count('的') >= 4 and cjk_len(c) < 40:
                    out.append(_issue('表达不通顺', '“的”字堆叠', 'warn', l, c,
                                      '一个小句里“的”过多，拆句或删去可省的“的”'))
    return out


def check_para_heads(paras):
    """段首雷同（同一个词开头）与连接词成套。"""
    out = []
    heads = Counter()
    first = {}
    for l, p in paras:
        m = re.match(r'[一-鿿]{1,4}?[，,]|[一-鿿]{2}', p)
        if m:
            k = m.group(0).rstrip('，,')
            heads[k] += 1
            first.setdefault(k, []).append((l, p))
    for k, n in heads.items():
        if n >= TH['para_head_repeat']:
            out += [_issue('句式重复', f'段首重复“{k}”', 'warn', l, p[:30],
                           f'{n} 个段落都以“{k}”开头，换一种起笔（用事例、问题或具体场景开头）')
                    for l, p in first[k]]
    full = '\n'.join(p for _, p in paras)
    for st in CONNECTOR_SETS:
        if all(w in full for w in st):
            ls = [l for l, p in paras if any(w in p for w in st)]
            out.append(_issue('句式重复', f'成套连接词“{"/".join(st)}”', 'info', ls[0], st[0],
                              '议论文和报告里机械的“首先/其次/最后”显得模板化，可改用内容本身的递进来衔接'))
    return out


def check_para_endings(paras):
    """段尾警句化：每段都用“不是…而是/真正的/从来”式金句收尾。"""
    ends = []
    for l, p in paras:
        ss = split_sentences(p)
        if len(ss) >= 2 and APHORISM.search(ss[-1]):
            ends.append((l, ss[-1]))
    long_paras = sum(1 for _, p in paras if len(split_sentences(p)) >= 2)
    ratio = len(ends) / long_paras if long_paras else 0
    if long_paras >= 4 and ratio >= TH['aphorism_end_ratio']:
        return [_issue('句式重复', '段尾警句化', 'warn', l, s,
                       f'{len(ends)}/{long_paras} 个段落以警句收尾，读起来像格言集。'
                       '保留结尾段的总结，其余段落以事实、例子或推论自然收束')
                for l, s in ends], ratio
    return [], ratio


def check_rhythm(paras):
    """句长单调、超长句、分号排比堆砌、引号滥用。"""
    out = []
    lens = []
    for l, p in paras:
        for s in split_sentences(strip_md(p)):
            n = cjk_len(s)
            if n == 0:
                continue
            lens.append(n)
            if n > TH['long_sent']:
                out.append(_issue('表达不通顺', '句子过长', 'warn', l, s,
                                  f'该句约 {n} 字，拆成 2–3 句，每句只讲一层意思'))
            if s.count('；') >= TH['semicolon_run']:
                out.append(_issue('句式重复', '分号排比堆砌', 'warn', l, s,
                                  f'一句内 {s.count("；")} 个分号，排比过密；保留最关键的两项，其余展开或删去'))
    cv = statistics.pstdev(lens) / statistics.mean(lens) if len(lens) >= 8 else None
    if cv is not None and cv < TH['sent_len_cv_min']:
        out.append(_issue('句式重复', '句长单调', 'info', paras[0][0], '',
                          '句子长短过于均匀，长短句交替会更自然'))
    text = ''.join(p for _, p in paras)
    nq = len(re.findall(r'“[^”]{1,10}”', text))
    k = cjk_len(text) / 1000 or 1
    if nq / k > TH['quote_per_1k']:
        out.append(_issue('套话', '引号短语过多', 'info', paras[0][0], '',
                          '短引号偏多，'
                          '引号用于引用和特指，不必给普通词语加引号来强调'))
    return out, {'sent_mean': round(statistics.mean(lens), 1) if lens else 0,
                 'sent_cv': round(cv, 3) if cv is not None else None, 'n_sent': len(lens)}
