"""第 2 步：读取 Agent 填好证据的 ledger.json，给每条陈述打可信度标签，生成修改单 report.md。
用法：python fp_verify.py --workdir zfp
规则见 fplib/evidence.py；输入依赖提供的证据，不替代来源真实性与完整语义核查。"""
import argparse, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fplib import evidence  # noqa: E402

ACTION_BY_LABEL = {
    '可信': '保留；议论文、报告类在句中自然注明来源（如“据××2024年报告”），新闻稿类不必注明',
    '待验证': '改成有出处的说法；找不到可靠出处就明确标记未核实并转交复核，或删除；不能仅加“约/据报道”当作已核实',
    '存疑': '按证据改正；没有证据就删除，不要换一个同样没有来源的说法',
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--workdir', default='zfp')
    ap.add_argument('--offline', action='store_true', help='不请求学术元数据接口')
    a = ap.parse_args()
    lp = os.path.join(a.workdir, 'ledger.json')
    ledger = json.load(open(lp, encoding='utf-8'))
    diag = json.load(open(os.path.join(a.workdir, 'diagnosis.json'), encoding='utf-8'))
    counts = {'可信': 0, '待验证': 0, '存疑': 0}
    empty = []
    mp = ledger.get('material_path')
    material = open(mp, encoding='utf-8-sig').read() if mp and os.path.exists(mp) else None
    cache = {}
    for c in ledger['claims']:
        evs = evidence.as_list(c.get('evidence'))
        if not evs:
            empty.append(c['id'])
        label, reasons, kinds = evidence.judge(c, evs, material, online=not a.offline, cache=cache)
        if 'F6_超出素材' in c['flags'] and '素材' in kinds and label != '可信':
            label, reasons = '存疑', ['超出用户提供的素材，属于无依据添加'] + reasons
        c['label'], c['label_reasons'], c['source_kinds'] = label, reasons, kinds
        counts[label] += 1
    with open(lp, 'w', encoding='utf-8') as f:
        json.dump(ledger, f, ensure_ascii=False, indent=1)
    md = render(ledger, diag, counts, empty)
    with open(os.path.join(a.workdir, 'report.md'), 'w', encoding='utf-8') as f:
        f.write(md)
    sys.stdout.reconfigure(encoding='utf-8')
    print(md)
    return 1 if empty else 0


def render(ledger, diag, counts, empty):
    out = [f'# 修改单（事实：可信 {counts["可信"]} / 待验证 {counts["待验证"]} / 存疑 {counts["存疑"]}）', '']
    if empty:
        out += [f'⚠ 还有 {len(empty)} 条陈述没有填写证据：{"、".join(empty)}。请先完成检索再运行本步骤。', '']
    out += ['## 一、事实陈述的处理（每一条都要在 ledger.json 的 `action` 填：保留 / 改正 / 弱化 / 删除，'
            '并把修改后的句子写进 `new_text`）', '']
    for c in ledger['claims']:
        out.append(f'- **{c["id"]}【{c["label"]}】** 第{c["line"]}行：{c["text"]}')
        out.append(f'  原因：{"；".join(c["label_reasons"])}')
        out.append(f'  处理：{ACTION_BY_LABEL[c["label"]]}')
    r = ledger.get('references')
    if r:
        bad = [e for e in r['entries'] if e['status'] in ('not_found', 'mismatch')]
        if bad or r['dangling'] or r['uncited']:
            out += ['', '## 二、参考文献（必须修改）', '']
            for e in bad:
                reg = e.get('registered') or {}
                fix = f'；登记信息：题名《{reg.get("title")}》，作者 {", ".join((reg.get("authors") or [])[:3])}，' \
                      f'年份 {reg.get("year")}，来源 {reg.get("venue")}，DOI {reg.get("doi")}' if reg.get('title') else ''
                out.append(f'- [{e["no"]}] {"查无此文" if e["status"] == "not_found" else "信息不符"}：'
                           f'{"；".join(e["notes"])}{fix}')
            if r['dangling']:
                out.append(f'- 悬空引用 {r["dangling"]}：补上文献或删去正文引用')
            if r['uncited']:
                out.append(f'- 未被引用的文献 {r["uncited"]}：在正文对应位置引用，或删去')
        unv = [e for e in r['entries'] if e['status'] == 'unverifiable']
        if unv:
            out.append(f'- 接口无法核验（中文文献等）{[e["no"] for e in unv]}：保留，但要在交付说明里列出，请用户核对')
    items = diag['items']
    hard = [i for i in items if i['severity'] == 'error']
    soft = [i for i in items if i['severity'] == 'warn']
    cand = [i for i in items if i['severity'] == 'candidate' and i.get('agent_verdict') == '成立']
    if hard or soft or cand:
        out += ['', '## 三、表达问题（只改被标出的句子，其他句子保持原样）', '']
        for tag, group in (('必须修改', hard), ('篇章问题（你已确认成立）', cand), ('建议修改', soft)):
            for i in group:
                out.append(f'- [{tag}][{i["cat"]}] {i["rule"]}（第{i["line"]}行）「{i["text"]}」→ {i["suggestion"]}')
    out += ['', '## 四、修改要求',
            '1. 只改上面列出的句子；没有被列出的句子保持原样。',
            '2. 不得新增原稿和证据里都没有的数字、人名、引语；新增的事实必须写进账本并附证据。',
            '3. 不改变原文观点和结构，篇幅变化尽量在 ±15% 以内；超过 15% 警告，超过 30% 阻断。',
            '4. 改完保存为 output.md，然后运行守门复查；退出码 2 表示仍需复核，不能宣称已就绪。']
    return '\n'.join(out)


if __name__ == '__main__':
    sys.exit(main())
