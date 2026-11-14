"""第 3 步：守门复查。比较 output.md 与原稿 base.md，并检查账本是否逐条交代、修改稿是否还残留问题。
用法：python fp_guard.py output.md --workdir zfp
退出码 0 = 规则检查通过，1 = 结构或事实冲突未通过，2 = 结构通过但事实仍需复核。
规则通过不代表全部语义事实已证实。"""
import argparse, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fplib import text as tu, guard, grammar, evidence, delivery  # noqa: E402

VALID_ACTIONS = {'保留', '改正', '弱化', '删除'}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('output')
    ap.add_argument('--workdir', default='zfp')
    ap.add_argument('--target-chars', type=int, default=None, help='题目约定字数；超出宽容范围只提示人工复核')
    a = ap.parse_args()
    wd = a.workdir
    ledger = json.load(open(os.path.join(wd, 'ledger.json'), encoding='utf-8'))
    diag = json.load(open(os.path.join(wd, 'diagnosis.json'), encoding='utf-8'))
    base = tu.read_text(os.path.join(wd, 'base.md'))
    new = tu.read_text(a.output)
    issues = []
    final_sentences = {delivery.normalized(x) for x in guard._sents(new)}
    # ① 账本是否逐条交代
    for c in ledger['claims']:
        act = (c.get('action') or '').strip()
        if act not in VALID_ACTIONS:
            issues.append(guard._issue('账本未交代', 'error', f'{c["id"]} {c["text"][:40]}',
                                       '每条陈述的 action 必须填 保留/改正/弱化/删除 之一'))
        elif c.get('label') in ('存疑',) and act == '保留':
            issues.append(guard._issue('存疑陈述被原样保留', 'error', f'{c["id"]} {c["text"][:40]}',
                                       '存疑陈述只能改正、弱化或删除'))
        elif c.get('label') == '待验证' and act == '保留' and not any((e.get('url') or '').strip() for e in evidence.as_list(c.get('evidence'))):
            issues.append(guard._issue('待验证陈述无来源却保留', 'warn', f'{c["id"]} {c["text"][:40]}',
                                       '保留时必须标记待复核，不能作为已核实内容交付'))
        if act in ('改正', '弱化') and not (c.get('new_text') or '').strip():
            issues.append(guard._issue('改后句子未登记', 'warn', c['id'], '把修改后的句子写进 new_text'))
        if act in ('改正', '弱化') and (c.get('new_text') or '').strip():
            registered = delivery.normalized(c['new_text'])
            if registered not in final_sentences:
                issues.append(guard._issue('登记改后句不在终稿', 'review', c['id'], '核对账本和终稿；不得以不存在的句子继承证据'))
            if delivery.normalized(c['text']) in final_sentences and delivery.normalized(c['text']) != registered:
                issues.append(guard._issue('原句仍在终稿', 'review', c['id'], '核对是否同时保留了要改正的原句；若是在引用或解释，人工判断语义'))
        if act == '保留' and delivery.normalized(c['text']) not in final_sentences:
            registered = delivery.normalized(c.get('new_text') or '')
            if not registered or registered not in final_sentences:
                issues.append(guard._issue('保留记录难以对应终稿', 'review', c['id'], '检查是否发生改写、删去或句子拆分；按实际情况登记'))
        if act == '删除' and c['text'][:15] in new:
            issues.append(guard._issue('声称删除但仍在文中', 'error', c['id'], '账本写了删除，但原句仍在修改稿中'))
    # ② 修改稿与原稿的守门比对
    flagged = [c['text'] for c in ledger['claims'] if c.get('action') in ('改正', '弱化', '删除')]
    flagged += [i['text'] for i in diag['items']]
    material_path = ledger.get('material_path')
    material = tu.read_text(material_path) if material_path and os.path.isfile(material_path) else None
    g, stats = guard.check(base, new, flagged, ledger, a.target_chars, material)
    issues += g
    # ③ 修改稿是否新出现硬语病
    body, _, _ = tu.split_body_refs(new)
    for line, p in tu.paragraphs(body):
        for s in tu.split_sentences(p):
            for cl in tu.split_clauses(s):
                for name, sug, frag, _ in grammar.check_clause(cl):
                    issues.append(dict(guard._issue(name, 'error', cl, sug), line=line))
    structural_passed = not [i for i in issues if i['severity'] == 'error']
    final_checks = delivery.assess(new, ledger, material)
    pending = [c for c in final_checks if c['label'] == '待验证']
    questionable = [c for c in final_checks if c['label'] == '存疑']
    manual_reviews = [i for i in issues if i['severity'] == 'review']
    passed = structural_passed and not pending and not questionable and not manual_reviews
    rep = {'passed': passed, 'structural_passed': structural_passed, 'ready_for_delivery': passed,
           'stats': stats, 'issues': issues, 'final_fact_checks': final_checks,
           'pending_fact_count': len(pending), 'questionable_fact_count': len(questionable),
           'manual_review_count': len(manual_reviews),
           'scope_note': '仅核对抽取出的事实候选及已实现关系，未覆盖全部语义、来源真实性和漏抽取事实'}
    with open(os.path.join(wd, 'guard.json'), 'w', encoding='utf-8') as f:
        json.dump(rep, f, ensure_ascii=False, indent=1)
    status = '规则检查通过（不代表全部事实已证实）' if passed else ('待复核，未就绪' if structural_passed and not questionable else '未通过')
    md = [f'# 守门复查：{status}', '',
          f'结构检查：{"通过" if structural_passed else "未通过"}；最终事实待验证 {len(pending)} 条、存疑 {len(questionable)} 条，其他待复核 {len(manual_reviews)} 项。', '',
          f'篇幅变化 {stats.get("len_change", 0):+.0%}；未被标出问题的句子改写比例 {stats.get("unflagged_rewrite", 0):.0%}；'
          f'丢失关键信息 {stats.get("lost_unexplained", 0)} 处（未说明理由）', '']
    for i in issues:
        md.append(f'- [{ {"error": "必须修改", "warn": "建议修改", "review": "需复核"}.get(i["severity"], i["severity"]) }] '
                  f'{i["rule"]}：{i["text"]} → {i["suggestion"]}')
    for c in pending + questionable:
        md.append(f'- 【{c["label"]}】第{c["line"]}行：{c["text"]} → {"；".join(c["reasons"])}')
    md += ['', '有链接、填了 new_text 或把语气改成“约/据报道”均不等于核验完成。',
           '检查仅覆盖抽取出的事实候选及已实现规则，未检出问题不等于整篇事实完全可靠。']
    with open(os.path.join(wd, 'guard_report.md'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(md))
    sys.stdout.reconfigure(encoding='utf-8')
    print('\n'.join(md))
    return 0 if passed else (2 if structural_passed and not questionable else 1)


if __name__ == '__main__':
    sys.exit(main())
