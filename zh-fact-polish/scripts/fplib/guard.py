"""守门复查：修改稿 vs 修改前的原稿。
检查：①关键信息是否被无故删掉（需要在账本里说明理由）；②篇幅变化；③未标问题的句子改动是否过多（变相重写）；
     ④是否引入原稿没有的新数字/引语（新事实必须进账本并有证据）。"""
import re
from difflib import SequenceMatcher
from .text import split_body_refs, paragraphs, split_sentences, cjk_len, strip_md
from .claims import keys_of
from . import factmatch

LEN_WARN, LEN_ERR = 0.15, 0.30
REWRITE_WARN = 0.45      # 未被标出问题的句子中，被改写（相似度<0.6）的比例


def _sents(text):
    body, _, _ = split_body_refs(text)
    return [s for _, p in paragraphs(body) for s in split_sentences(p)]


def _keyset(sents):
    ks = set()
    for s in sents:
        k = keys_of(s)
        ks |= {('num', x) for x in k['numbers']} | {('year', x) for x in k['years']}
        ks |= {('title', x) for x in k['titles']} | {('quote', x) for x in k['quotes']}
    return ks


def _issue(rule, sev, text, sug):
    return {'cat': '守门', 'rule': rule, 'severity': sev, 'line': None, 'text': text[:80], 'suggestion': sug}


def check(base_text, new_text, flagged_sents=(), ledger=None, target_chars=None, material=None):
    """flagged_sents：本轮报告里被标出问题的原句（允许大改）；ledger：账本 dict，用于核对删除和新增是否有交代。"""
    issues, stats = [], {}
    bs, ns = _sents(base_text), _sents(new_text)
    bl = sum(cjk_len(strip_md(s)) for s in bs)
    nl = sum(cjk_len(strip_md(s)) for s in ns)
    ratio = (nl - bl) / bl if bl else 0
    stats['len_change'] = round(ratio, 3)
    if abs(ratio) > LEN_ERR:
        issues.append(_issue('篇幅变化过大', 'review', f'{bl}→{nl} 字',
                             '变化超过 30%，请检查是否误删信息，并结合题目字数与重复内容判断；不要机械补充空话'))
    elif abs(ratio) > LEN_WARN:
        issues.append(_issue('篇幅变化偏大', 'warn', f'{bl}→{nl} 字', '篇幅变化超过 15%，请确认没有扩写或删减正常内容'))
    # Approximate target length separately from change against the original.
    if target_chars:
        body, _, _ = split_body_refs(new_text)
        approximate_chars = len(re.sub(r'\s+', '', strip_md(body)))
        stats['approx_chars'] = approximate_chars
        stats['target_chars'] = target_chars
        if not 0.75 * target_chars <= approximate_chars <= 1.25 * target_chars:
            issues.append(_issue('题目字数需复核', 'review', f'约 {approximate_chars} 字；题目约 {target_chars} 字',
                                 '按题目要求和实际文字处理规范复核篇幅，勿为凑字数添加未经提供的事实或重复空话'))
    handled = {}
    if ledger:
        for c in ledger.get('claims', []):
            handled[c.get('text', '')] = c.get('action', '')
    lost = _keyset(bs) - _keyset(ns)
    explained = set()
    for s, act in handled.items():
        if act in ('删除', '改正', '弱化'):
            explained |= _keyset([s])
    unexplained = sorted(v for k, v in lost - explained)
    stats['lost_keys'] = len(lost)
    stats['lost_unexplained'] = len(unexplained)
    if unexplained:
        issues.append(_issue('关键信息丢失', 'error', '、'.join(unexplained[:8]),
                             '原稿中的这些数字/年份/书名/引语在修改稿里不见了，账本里也没有说明删除或改正的理由。'
                             '要么恢复，要么在账本对应条目写明处理方式'))
    # If a numerical fact remains but its original year disappears in the
    # corresponding rewritten sentence, do not silently mark it resolved.
    # This is a review signal, not a claim that the fact is false.
    scope_warnings = []
    for c in (ledger or {}).get('claims', []):
        if c.get('action') not in ('改正', '弱化'):
            continue
        before = c.get('text', '')
        after = c.get('new_text', '')
        if not before or not after or after not in new_text:
            continue
        old_tokens = [x for x in factmatch.amounts(before) if x.kind == 'number']
        new_tokens = [x for x in factmatch.amounts(after) if x.kind == 'number']
        missing_years = set()
        for old in old_tokens:
            old_year = factmatch.year_of(before, old)
            if not old_year:
                continue
            for new in new_tokens:
                if (factmatch.value_supported(old, new) and
                        not factmatch.year_of(after, new)):
                    missing_years.add(old_year)
        if missing_years:
            scope_warnings.append(c.get('id', ''))
            issues.append(_issue('保留数字但可能丢失年份', 'review',
                                 c.get('id', '') + '：原文年份 ' + '、'.join(sorted(missing_years)),
                                 '检查保留的数字是否仍有明确年份；若年份被更正，登记依据，不得仅凭数字相同放行'))
    stats['temporal_scope_review'] = len(scope_warnings)
    # Chinese-written durations are not reliably parsed by numeric rules.
    # A newly introduced duration must be reviewed even when it happens to be
    # registered; we cannot infer its validity from literal presence alone.
    zh_duration = re.compile(r'[零〇一二两三四五六七八九十百]{1,4}个?月')
    base_durations = set(zh_duration.findall(base_text))
    new_durations = sorted(set(zh_duration.findall(new_text)) - base_durations)
    stats['new_chinese_duration_review'] = len(new_durations)
    if new_durations:
        issues.append(_issue('新增中文时长待核', 'review', '、'.join(new_durations[:8]),
                             '检查新增时长是否有明确来源及题目许可；规则未自动核实中文数字'))
    # New first-person accounts in material-only writing can introduce events
    # without numbers; report candidates, never infer factuality automatically.
    if material is not None:
        base_norm = {re.sub(r"\s+", "", strip_md(s)) for s in bs}
        action = re.compile(r"(?:我|本人)(?:本周|这一周|已经|还|也|便|就|开始|先|随后|又|逐步|主动|反复|曾|已|在|按|从|将|对|把|去|来|仔细|认真|尝试|着手|重新|进一步|\w|[\u4e00-\u9fff]){0,14}(?:开始|回看|复盘|编写|参加|学习|完成|提交|发现|检查|处理|测试|分析|修复|安排|联系|组织|访问|记录|梳理)")
        for sentence in ns:
            key = re.sub(r"\s+", "", strip_md(sentence))
            if key not in base_norm and key not in re.sub(r"\s+", "", strip_md(material)) and action.search(sentence):
                issues.append(_issue('新增个人经历待核', 'review', sentence,
                                     '检查动作是否由题目素材明确支持；主观感想、对未来的计划和一般性表述可能误报'))
    added = sorted(v for k, v in _keyset(ns) - _keyset(bs))
    stats['added_keys'] = len(added)
    if added and ledger is not None:
        in_ledger = _keyset([c.get('new_text', '') for c in ledger.get('claims', [])])
        new_unlogged = sorted(v for k, v in (_keyset(ns) - _keyset(bs)) - in_ledger)
        stats['added_unlogged'] = len(new_unlogged)
        if new_unlogged:
            issues.append(_issue('新增事实未入账', 'error', '、'.join(new_unlogged[:8]),
                                 '修改稿新增了原稿没有的数字/引语，必须在账本中登记并附证据，否则删除'))
    flagged = set(flagged_sents)
    keep = [s for s in bs if s not in flagged]
    changed = 0
    for s in keep:
        best = max((SequenceMatcher(None, s, t).ratio() for t in ns), default=0)
        if best < 0.6:
            changed += 1
    rr = changed / len(keep) if keep else 0
    stats['unflagged_rewrite'] = round(rr, 3)
    if rr > REWRITE_WARN:
        issues.append(_issue('改动面过大', 'warn', f'{changed}/{len(keep)} 句未被标出问题的句子被改写',
                             '只改报告里标出的句子；没有问题的句子保持原样'))
    return issues, stats
