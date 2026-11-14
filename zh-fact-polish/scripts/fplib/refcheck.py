"""参考文献核验：DOI 解析 + Crossref/DataCite 元数据比对 + 无 DOI 时按题名检索。

状态：
  verified     元数据与条目一致（题名相似度高，作者/年份不冲突）
  mismatch     找到了文献，但 DOI 指向别的文章，或作者/年份/题名有明显出入
  not_found    DOI 不存在，或检索不到相近题名（高度疑似编造）
  unverifiable 中文文献/政策文件/网络错误等，自动接口覆盖不到，需人工核查
"""
import json, os, re, time, urllib.parse, urllib.request
from difflib import SequenceMatcher
from .refparse import first_author_surname

UA = 'zh-fact-polish/2.0 (course project; mailto:zh-fact-polish@example.com)'
CACHE_PATH = os.environ.get('ZFP_CACHE') or os.path.join(os.getcwd(), '.zfp_refcache.json')
_cache = None


def _load_cache():
    global _cache
    if _cache is None:
        try:
            with open(CACHE_PATH, encoding='utf-8') as f:
                _cache = json.load(f)
            if not isinstance(_cache, dict):
                _cache = {}
        except Exception:
            _cache = {}
    return _cache


def _save_cache():
    if not _cache:
        return
    try:
        with open(CACHE_PATH, 'w', encoding='utf-8') as f:
            json.dump(_cache, f, ensure_ascii=False)
    except Exception:
        pass


def _get(url, timeout=20):
    """返回 (status, json或None)。404 -> (404, None)；网络错误 -> (None, None)。"""
    c = _load_cache()
    if url in c:
        return c[url]
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                res = (r.status, json.loads(r.read().decode('utf-8')))
            break
        except urllib.error.HTTPError as e:
            res = (e.code, None)
            if e.code in (404, 400):
                break
        except Exception:
            res = (None, None)
        time.sleep(1.5 * (attempt + 1))
    if res[0] in (200, 404):
        c[url] = res
    return res


def norm(s):
    return re.sub(r'[^0-9a-z一-鿿]', '', (s or '').lower())


def title_sim(a, b):
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0.0
    if len(a) > 15 and len(b) > 15 and (a in b or b in a):
        return 0.95
    return SequenceMatcher(None, a, b).ratio()


def _crossref_meta(item):
    title = (item.get('title') or [''])[0]
    sub = (item.get('subtitle') or [''])
    if sub and sub[0]:
        title_full = title + ' ' + sub[0]
    else:
        title_full = title
    year = None
    for k in ('published-print', 'published-online', 'issued', 'created'):
        dp = (item.get(k) or {}).get('date-parts')
        if dp and dp[0] and dp[0][0]:
            year = dp[0][0]
            break
    fams = [a.get('family') or a.get('name') or '' for a in item.get('author', [])]
    return {'title': title_full, 'year': year, 'authors': fams,
            'doi': item.get('DOI'), 'venue': (item.get('container-title') or [''])[0]}


def _datacite_meta(d):
    at = d.get('attributes', {})
    title = (at.get('titles') or [{}])[0].get('title', '')
    fams = [c.get('familyName') or c.get('name', '') for c in at.get('creators', [])]
    return {'title': title, 'year': at.get('publicationYear'), 'authors': fams,
            'doi': at.get('doi'), 'venue': at.get('publisher', '')}


def lookup_doi(doi):
    """返回 (meta 或 None, 'ok'|'missing'|'neterr'|'no_meta')"""
    q = urllib.parse.quote(doi, safe='/')
    st, js = _get(f'https://api.crossref.org/works/{q}')
    if st == 200 and js:
        return _crossref_meta(js['message']), 'ok'
    st2, js2 = _get(f'https://api.datacite.org/dois/{q}')
    if st2 == 200 and js2:
        return _datacite_meta(js2['data']), 'ok'
    st3, _ = _get(f'https://doi.org/api/handles/{q}')
    if st3 == 200:
        return None, 'no_meta'      # DOI 存在但登记机构不是 Crossref/DataCite（如部分中文期刊）
    if st == 404 and st3 == 404:
        return None, 'missing'
    return None, 'neterr'


def search_title(entry):
    """Crossref + DataCite（覆盖 arXiv）题名检索。
    返回最相近的 (meta, 相似度)；两个接口都网络错误时返回 (None, None)。
    候选按 题名相似度 + 作者一致加分 排序，避免同名不同文（如书中同名章节）。"""
    title, author = entry['title'], first_author_surname(entry['authors'])
    cands, any_ok = [], False
    q = urllib.parse.quote(f'{title} {author}'.strip())
    st, js = _get('https://api.crossref.org/works?rows=8&select=DOI,title,subtitle,author,'
                  f'issued,published-print,published-online,container-title&query.bibliographic={q}')
    if st == 200 and js:
        any_ok = True
        cands += [_crossref_meta(it) for it in js['message'].get('items', [])]
    if entry['lang'] == 'en':
        q2 = urllib.parse.quote(f'titles.title:"{title}"')
        st2, js2 = _get(f'https://api.datacite.org/dois?page[size]=5&query={q2}')
        if st2 == 200 and js2:
            any_ok = True
            cands += [_datacite_meta(d) for d in js2.get('data', [])]
    if not any_ok:
        return None, None
    best, bs, bkey = None, 0.0, -1
    for m in cands:
        s = title_sim(title, m['title'])
        a = _author_ok(entry, m)
        key = s + (0.1 if a else 0) - (0.3 if a is False else 0)
        if key > bkey:
            best, bs, bkey = m, s, key
    return best, bs


def _author_ok(entry, meta):
    sur = first_author_surname(entry['authors'])
    if not sur or not meta['authors']:
        return None
    if re.search(r'[一-鿿]', sur) and not any(re.search(r'[一-鿿]', a) for a in meta['authors']):
        return None   # 中文作者 vs 拼音登记，无法直接比对
    fams = [norm(a) for a in meta['authors'][:3]]
    return norm(sur) in fams or any(norm(sur) in f or f in norm(sur) for f in fams if f)


def _compare(entry, meta):
    """返回 (status, 说明列表)"""
    notes = []
    sim = title_sim(entry['title'], meta['title'])
    same_work = _author_ok(entry, meta) and entry['year'] and meta['year'] \
        and abs(entry['year'] - meta['year']) <= 1
    if sim < 0.6 and same_work:
        return 'verified', [f'作者与年份一致，但登记题名为《{meta["title"]}》（可能是不同版本），请确认']
    if sim < 0.6 and entry['lang'] == 'zh' and not re.search(r'[一-鿿]', meta['title'] or ''):
        # 中文论文的 DOI 常登记英文题名：DOI 能解析即视为存在，题名无法直接比对
        notes = [f'DOI 登记的是英文题名《{meta["title"]}》，无法与中文题名直接比对，请人工确认']
        if entry['year'] and meta['year'] and abs(entry['year'] - meta['year']) > 1:
            notes.append(f'年份 {entry["year"]} 与登记年份 {meta["year"]} 不一致')
            return 'mismatch', notes
        return 'unverifiable', notes
    if sim < 0.6:
        return 'mismatch', [f'DOI/检索结果对应的题名是《{meta["title"]}》，与条目题名不符']
    if sim < 0.85:
        notes.append(f'题名与登记题名《{meta["title"]}》有出入')
    a = _author_ok(entry, meta)
    if a is False:
        notes.append(f'第一作者与登记作者（{", ".join(meta["authors"][:3])}）不一致')
    if entry['year'] and meta['year'] and abs(entry['year'] - meta['year']) > 1:
        if sim >= 0.95 and a is not False and meta['year'] > entry['year']:
            # 题名几乎相同、作者不冲突、登记年份更晚：多为重印/再版/收录年份，不算错误
            return 'verified', [f'登记年份 {meta["year"]} 晚于条目年份 {entry["year"]}，可能是重印或再版，可核对']
        notes.append(f'年份 {entry["year"]} 与登记年份 {meta["year"]} 不一致')
    return ('mismatch' if notes else 'verified'), notes


def _by_title(entry):
    meta, sim = search_title(entry)
    if sim is None:
        return 'unverifiable', ['检索接口网络错误，未能核验'], None
    if meta and sim >= 0.85:
        st, notes = _compare(entry, meta)
        diff_year = entry['year'] and meta['year'] and abs(entry['year'] - meta['year']) > 1
        if st == 'mismatch' and _author_ok(entry, meta) is False and diff_year:
            # 题名相同但作者、年份都不同：检索到的是同名的另一篇（如书中同名章节），原文献无 DOI 登记
            return 'unverifiable', ['只检索到作者、年份都不同的同名记录，原文献可能未登记 DOI，请人工确认'], None
        return st, notes, meta
    if entry['lang'] == 'zh':
        return 'unverifiable', ['中文文献在 Crossref 覆盖有限，未检索到，请到知网/万方人工核查'], None
    if meta and sim >= 0.6:
        return 'unverifiable', [f'只检索到近似题名《{meta["title"]}》，请人工确认'], meta
    return 'not_found', ['Crossref 中检索不到该题名，疑似编造或题名有误'], None


def verify_entry(entry, online=True):
    r = {'no': entry['no'], 'line': entry['line'], 'raw': entry['raw'], 'doi': entry['doi']}
    if not online:
        r.update(status='unverifiable', notes=['离线模式，未联网核验'])
        return r
    doi = entry['doi'] or (f'10.48550/arXiv.{entry["arxiv"]}' if entry['arxiv'] else None)
    is_web = entry['type'] in ('EB/OL', 'N') or re.search(r'https?://|gov\.cn', entry['raw'])
    if not doi and is_web:
        r.update(status='unverifiable', notes=['网络资源/政策文件，请打开链接人工确认'])
        return r
    if not entry['title']:
        r.update(status='unverifiable', notes=['未能解析出题名'])
        return r
    if doi:
        meta, st = lookup_doi(doi)
        if st == 'ok':
            status, notes = _compare(entry, meta)
            if status == 'mismatch' and title_sim(entry['title'], meta['title']) < 0.6:
                s2, n2, m2 = _by_title(entry)
                if s2 == 'verified' and m2 and m2.get('doi'):
                    notes.append(f'按题名检索到该文献，正确 DOI 应为 {m2["doi"]}')
            r.update(status=status, notes=notes, matched=meta)
            return r
        if st == 'missing':
            s2, n2, m2 = _by_title(entry)
            notes = [f'DOI {doi} 不存在']
            if s2 == 'verified' and m2:
                notes.append(f'文献本身存在，正确 DOI 应为 {m2.get("doi")}')
                r.update(status='mismatch', notes=notes, matched=m2)
            else:
                r.update(status='not_found', notes=notes + n2)
            return r
        if st == 'no_meta' and entry['lang'] == 'zh':
            r.update(status='unverifiable', notes=['DOI 可解析但无公开元数据，请人工核对题名'])
            return r
    s2, n2, m2 = _by_title(entry)
    r.update(status=s2, notes=n2, matched=m2)
    return r


def verify_all(entries, online=True):
    out = []
    for e in entries:
        out.append(verify_entry(e, online))
    _save_cache()
    return out
