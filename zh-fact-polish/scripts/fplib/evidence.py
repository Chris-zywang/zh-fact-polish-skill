"""v2.3 开发版：数值、单位、范围及部分局部关系的保守一致性检查。

普通网页摘录仍由 Agent 提供，本模块不证明网页原文真实性。所有已抽取
要素和已实现关系均获得支持时才给“可信”；关键字段冲突为“存疑”，
要素缺失、关系无法绑定、纯定性判断为“待验证”。这不是完整语义核查。
"""
import json, re, urllib.parse, urllib.request
from . import factmatch

URL = re.compile(r'^https?://\S+$')
META_HOSTS = ('api.crossref.org', 'api.datacite.org', 'api.openalex.org', 'export.arxiv.org', 'arxiv.org/abs',
              'doi.org/api/handles', 'api.semanticscholar.org')
MATCH_TH = 1.0
QUAL_MIN_EXCERPT = 30
UA = 'zh-fact-polish/2.3-dev (course project; mailto:zh-fact-polish@example.com)'


def match_ratio(claim, text):
    result = factmatch.report(claim, [text])
    return result['ratio'], result['missing']


def is_meta_url(url):
    try:
        parsed = urllib.parse.urlsplit(url)
    except ValueError:
        return False
    return parsed.scheme in ('http', 'https') and any(
        parsed.hostname == h.split('/')[0] and (len(h.split('/', 1)) == 1 or parsed.path.startswith('/' + h.split('/', 1)[1]))
        for h in META_HOSTS)


def fetch_meta(url, cache):
    """请求学术元数据接口，返回可比对的文本（题名 作者 年份 刊名）。失败返回空串。"""
    if url in cache:
        return cache[url]
    txt = ''
    try:
        req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': 'application/json'})
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read().decode('utf-8', 'replace')
        try:
            js = json.loads(raw)
            txt = _flatten_meta(js)
        except ValueError:
            txt = re.sub(r'<[^>]+>', ' ', raw)[:4000]          # arXiv abs 页面等 HTML/Atom
    except Exception:
        txt = ''
    cache[url] = txt
    return txt


def _flatten_meta(js):
    m = js.get('message', js.get('data', js))
    if isinstance(m, dict) and 'attributes' in m:
        m = m['attributes']
    parts = []
    for k in ('title', 'titles', 'display_name', 'container-title', 'publisher', 'publicationYear', 'publication_year'):
        v = m.get(k) if isinstance(m, dict) else None
        if v:
            parts.append(json.dumps(v, ensure_ascii=False))
    for k in ('issued', 'published-print', 'published-online', 'created'):
        dp = (m.get(k) or {}).get('date-parts') if isinstance(m, dict) else None
        if dp and dp[0]:
            parts.append(str(dp[0][0]))
    for a in (m.get('author') or m.get('creators') or m.get('authorships') or [])[:10] if isinstance(m, dict) else []:
        if isinstance(a, dict):
            parts.append(a.get('family') or a.get('familyName') or (a.get('author') or {}).get('display_name') or a.get('name') or '')
    return ' '.join(parts)


def as_list(ev):
    """兼容 v2.0 的单条 dict 证据和 v2.1 的列表。"""
    if not ev:
        return []
    if isinstance(ev, dict):
        ev = [ev]
    return [e for e in ev if isinstance(e, dict) and any((e.get(k) or '').strip() for k in ('url', 'excerpt', 'agent_verdict'))]


def judge(claim, ev, material=None, online=True, cache=None):
    """返回 (label, reasons, source_kinds)。source_kinds 记录用到了哪类来源，便于统计。"""
    cache = {} if cache is None else cache
    evs = as_list(ev)
    if not evs:
        return '待验证', ['没有找到支撑证据；不能判定真伪，需补充来源'], []
    verdicts = {(e.get('agent_verdict') or '').strip() for e in evs}
    if '矛盾' in verdicts:
        notes = '；'.join((e.get('note') or '') for e in evs if (e.get('agent_verdict') or '') == '矛盾')
        return '存疑', ['Agent 判定证据与陈述矛盾：' + notes], []
    if verdicts <= {'未找到', ''}:
        return '待验证', ['没有找到支撑证据；不能判定真伪，需补充来源'], []
    texts, kinds = [], []
    for e in evs:
        url = (e.get('url') or '').strip()
        exc = (e.get('excerpt') or '').strip()
        if (e.get('agent_verdict') or '').strip() != '支持':
            continue
        if re.search(r'(^|[\\/])material\.md$|^素材', url) and material:
            texts.append(material)
            kinds.append('素材')
        elif URL.match(url):
            if exc:
                texts.append(exc)
            if is_meta_url(url) and online:
                meta = fetch_meta(url, cache)
                if meta:
                    texts.append(meta)
                    kinds.append('学术元数据')
                    continue
            kinds.append('网页' if len(exc) >= QUAL_MIN_EXCERPT else '网页(摘录过短)')
        elif exc:
            kinds.append('无链接摘录')
    if not texts:
        return '待验证', ['证据没有可用的链接、素材或摘录'], kinds
    if all(k == '无链接摘录' for k in kinds):
        return '待验证', ['证据缺少有效来源链接'], kinds
    comparison = factmatch.report(claim, texts)
    r, miss = comparison['ratio'], comparison['missing']
    if comparison['conflicts'] and not re.search(r'按.+计算|计算可得|相当于|每\s*\d', claim['text']):
        return '存疑', comparison['conflicts'], kinds
    if r is None:
        return '待验证', ['（定性）没有可机器核对的要素；Agent 自判支持和长摘录不构成语义核实，请逐项人工或独立核查'], kinds
    if not miss and r >= MATCH_TH:
        return '可信', ['全部可解析要素及已实现的局部关系检查一致；不等于整句语义、来源真实性或因果关系已核实'], kinds
    return '待验证', [f'要素或关系未获完整支持：{"、".join(miss)}'], kinds
