"""第 1 步：解析草稿，生成主张账本 ledger.json 和表达诊断 diagnosis.json。
用法：python fp_extract.py draft.md --workdir zfp [--material material.md] [--offline]
输出（都在 --workdir 下）：
  ledger.json    每条事实陈述一项，evidence 字段留空，等 Agent 检索后填写
  diagnosis.json 表达问题与篇章候选（E1–E5）
  extract.md     给 Agent 看的检索任务清单"""
import argparse, json, os, shutil, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fplib import text as tu, claims, refparse, refcheck, discourse, style, grammar  # noqa: E402


def detect_genre(t, refs, material):
    if material:
        return 'news'
    if refs.strip():
        return 'paper'
    if sum(k in t for k in ('调研', '报告', '调查', '数据来源', '科普')) >= 2:
        return 'report'
    return 'essay'


def expression(paras, genre):
    style.set_genre('paper' if genre in ('paper', 'report') else 'essay')
    out = []
    for line, p in paras:
        for s in tu.split_sentences(p):
            for c in tu.split_clauses(s):
                for name, sug, frag, _ in grammar.check_clause(c):
                    out.append({'cat': 'E1_表达不顺', 'rule': name, 'severity': 'error', 'line': line,
                                'text': c.strip()[:80], 'suggestion': f'{sug}（命中：{frag}）'})
    if not paras:
        return out
    for fn in (style.check_contrast, style.check_intensifiers, style.check_cliches,
               style.check_para_endings, style.check_rhythm):
        r = fn(paras)
        r = r[0] if isinstance(r, tuple) else r
        out += [dict(i, cat='E2_AI腔') for i in r]
    out += [dict(i, cat='E1_表达不顺' if i['rule'] in ('“对…进行…”冗余', '“进行+动词”冗余', '“的”字堆叠', '句子过长')
                 else 'E2_AI腔') for i in style.check_translationese(paras) + style.check_para_heads(paras)]
    for c in (discourse.contradiction_candidates(paras) + discourse.overargue_candidates(paras)
              + discourse.hollow_candidates(paras) + discourse.repeated_fact_candidates(paras)):
        cat = {'E3': 'E3_前后矛盾', 'E4': 'E4_钻牛角尖', 'E5': 'E5_空转'}[c['rule'][:2]]
        out.append({'cat': cat, 'rule': c['rule'], 'severity': 'candidate', 'line': c['line'],
                    'text': c['text'], 'suggestion': '；'.join(c['reasons']) + '。请判断是否成立，成立则按改写指南修改',
                    'agent_verdict': ''})
    return out


def references(body, refs_text, ref_line, online):
    entries = refparse.parse_entries(refs_text, ref_line or 0) if refs_text else []
    cites = refparse.citations(body)
    if not entries and not cites:
        return None
    res = refcheck.verify_all(entries, online) if entries else []
    nos = {e['no'] for e in entries}
    return {'entries': [{'no': r['no'], 'line': r['line'], 'raw': r['raw'], 'status': r['status'],
                         'notes': r.get('notes', []),
                         'registered': {k: (r.get('matched') or {}).get(k) for k in ('title', 'authors', 'year', 'venue', 'doi')}
                         if r.get('matched') else None} for r in res],
            'dangling': sorted(set(cites) - nos), 'uncited': sorted(nos - set(cites))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('draft')
    ap.add_argument('--workdir', default='zfp')
    ap.add_argument('--material')
    ap.add_argument('--offline', action='store_true')
    a = ap.parse_args()
    os.makedirs(a.workdir, exist_ok=True)
    raw = tu.read_text(a.draft)
    material = tu.read_text(a.material) if a.material else None
    body, refs_text, ref_line = tu.split_body_refs(raw)
    paras = tu.paragraphs(body)
    genre = detect_genre(raw, refs_text, material)
    cs = claims.extract(paras, material)
    for c in cs:
        c.update(evidence=[{'url': '', 'excerpt': '', 'agent_verdict': '', 'note': ''}],
                 action='', new_text='', label='')
    ledger = {'draft': os.path.abspath(a.draft), 'genre': genre, 'claims': cs,
              'material_path': os.path.abspath(a.material) if a.material else None,
              'references': references(body, refs_text, ref_line, not a.offline)}
    diag = {'genre': genre, 'items': expression(paras, genre)}
    shutil.copy(a.draft, os.path.join(a.workdir, 'base.md'))
    with open(os.path.join(a.workdir, 'ledger.json'), 'w', encoding='utf-8') as f:
        json.dump(ledger, f, ensure_ascii=False, indent=1)
    with open(os.path.join(a.workdir, 'diagnosis.json'), 'w', encoding='utf-8') as f:
        json.dump(diag, f, ensure_ascii=False, indent=1)
    md = render(ledger, diag)
    with open(os.path.join(a.workdir, 'extract.md'), 'w', encoding='utf-8') as f:
        f.write(md)
    sys.stdout.reconfigure(encoding='utf-8')
    print(md)


def render(ledger, diag):
    cs = ledger['claims']
    out = [f'# 第 1 步结果：事实陈述 {len(cs)} 条，表达诊断 {len(diag["items"])} 项（体裁：{ledger["genre"]}）', '',
           '## A. 需要你逐条检索核实的事实陈述', '',
           '对下面每一条：用网页搜索找到可靠来源，打开来源页面，把**原文中支撑这句话的那一段**复制到账本该条',
           '`evidence` 列表的 `excerpt`，链接填 `url`，`agent_verdict` 填 `支持` / `矛盾` / `未找到`。',
           '一句话包含多件事时，可以在 `evidence` 列表里加多条证据，每条对应其中一件事。',
           '学术论文优先给元数据接口链接（如 `https://api.crossref.org/works/<DOI>`），脚本会自己读取登记的年份和作者。',
           '新闻稿、总结类的事实来自用户素材时，`url` 填 `material.md`，`excerpt` 复制素材中对应的那一行。', '']
    for c in cs:
        flags = f'  ⚠ {"，".join(c["flags"])}' if c['flags'] else ''
        k = c['keys']
        keys = '、'.join(k['numbers'] + k['years'] + k['titles'] + k['quotes'][:1]) or '无'
        out.append(f'- **{c["id"]}**（第{c["line"]}行，{"/".join(c["types"])}）{c["text"]}')
        out.append(f'  关键要素：{keys}{flags}')
    r = ledger.get('references')
    if r:
        out += ['', '## B. 参考文献接口结果（离线或请求失败时可能尚未核实）', '']
        for e in r['entries']:
            out.append(f'- [{e["no"]}] {e["status"]}：{"；".join(e["notes"]) or "与登记信息一致"}')
        if r['dangling']:
            out.append(f'- 悬空引用（正文引用了但文献表没有）：{r["dangling"]}')
        if r['uncited']:
            out.append(f'- 未被正文引用的文献：{r["uncited"]}')
    cand = [i for i in diag['items'] if i['severity'] == 'candidate']
    if cand:
        out += ['', '## C. 需要你判断是否成立的篇章问题候选', '',
                '在 diagnosis.json 对应条目的 `agent_verdict` 填 `成立` 或 `不成立`。', '']
        for i in cand:
            out.append(f'- [{i["cat"]}] 第{i["line"]}行「{i["text"]}」→ {i["suggestion"]}')
    return '\n'.join(out)


if __name__ == '__main__':
    main()
