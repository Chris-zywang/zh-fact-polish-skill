"""参考文献条目解析（GB/T 7714 与 APA 两种常见格式）与正文引用抽取。"""
import re

ENTRY = re.compile(r'^\s*(?:\[(\d+)\]|(\d+)[.、．])\s*(.+)$')
DOI = re.compile(r'10\.\d{4,9}/[^\s，。；,;]+', re.I)
ARXIV = re.compile(r'arXiv[:：]?\s*(\d{4}\.\d{4,5})', re.I)
YEAR = re.compile(r'(?<!\d)(19[5-9]\d|20[0-3]\d)(?!\d)')
TYPE_MARK = re.compile(r'\[(J|C|M|D|R|S|P|N|EB/OL|J/OL|C/OL|M/OL|Z|A|G)\]', re.I)
CITE = re.compile(r'\[(\d+(?:\s*[-–~,，、]\s*\d+)*)\]')


def parse_entries(ref_text, start_line):
    entries = []
    for off, ln in enumerate(ref_text.splitlines()):
        m = ENTRY.match(ln)
        if not m:
            continue
        raw = m.group(3).strip()
        doi = DOI.search(raw)
        e = {'no': int(m.group(1) or m.group(2)), 'line': start_line + off + 1, 'raw': raw,
             'doi': doi.group(0).rstrip('.').rstrip(')') if doi else None}
        ax = ARXIV.search(raw)
        e['arxiv'] = ax.group(1) if ax else None
        tm = TYPE_MARK.search(raw)
        e['type'] = tm.group(1).upper() if tm else None
        # 年份抽取前去掉 DOI、arXiv 编号、URL，避免把 arXiv:2004.05150 的 2004 当年份
        clean = re.sub(r'DOI[:：]?\s*\S+|10\.\d{4,9}/\S+|arXiv[:：]?\s*\d{4}\.\d{4,5}(v\d+)?|https?://\S+', ' ', raw, flags=re.I)
        e['authors'], e['title'] = _authors_title(raw, tm)
        # 题名里常含年份（如 "after 2012"），优先取题名之后、出版信息里的年份
        tail = clean
        if e['title'] and e['title'] in clean:
            tail = clean[clean.index(e['title']) + len(e['title']):]
        years = YEAR.findall(tail) or YEAR.findall(clean)
        e['year'] = int(years[0]) if years else None
        e['lang'] = 'zh' if re.search(r'[一-鿿]', e['title'] or raw) else 'en'
        entries.append(e)
    return entries


def _authors_title(raw, tm):
    if tm:  # GB/T 7714：作者. 题名[J]. ...
        head = raw[:tm.start()]
        parts = re.split(r'(?<=[.．])\s+', head, maxsplit=1)
        if len(parts) == 2:
            return parts[0].rstrip('.． '), parts[1].strip()
        return '', head.strip()
    m = re.match(r'^(.+?)\s*[（(](\d{4})[a-z]?[）)][.．]?\s*(.+?)[.．。](?:\s|$)', raw)
    if m:  # APA：作者 (年份). 题名. 来源
        return m.group(1), m.group(3)
    parts = re.split(r'[.．]\s+', raw)
    return (parts[0], parts[1]) if len(parts) > 1 else ('', raw)


def first_author_surname(authors):
    a = re.split(r'[,，、;；]|\bet al\b|等', authors or '')[0].strip()
    if not a:
        return ''
    if re.search(r'[一-鿿]', a):
        return a[0]
    a = a.replace('&', ' ').strip()
    tok = a.split()
    # "Vaswani A" / "Vaswani, A." / "Ashish Vaswani"：取长度>1 的首个全字母词
    cands = [t.strip('.') for t in tok if len(t.strip('.')) > 1 and t.strip('.').isalpha()]
    return cands[0] if cands else ''


def citations(body):
    """正文引用编号 -> 出现次数（先去掉 LaTeX 公式，避免把 [0,1] 当成引用）"""
    body = re.sub(r'\$\$.*?\$\$', ' ', body, flags=re.S)
    body = re.sub(r'\$[^$\n]*\$', ' ', body)
    cnt = {}
    for m in CITE.finditer(body):
        for n in expand(m.group(1)):
            cnt[n] = cnt.get(n, 0) + 1
    return cnt


def expand(s):
    out = []
    for part in re.split(r'[,，、]', s):
        part = part.strip()
        r = re.split(r'\s*[-–~]\s*', part)
        if len(r) == 2 and r[0].isdigit() and r[1].isdigit() and int(r[1]) - int(r[0]) < 50:
            out.extend(range(int(r[0]), int(r[1]) + 1))
        elif part.isdigit():
            out.append(int(part))
    return out
