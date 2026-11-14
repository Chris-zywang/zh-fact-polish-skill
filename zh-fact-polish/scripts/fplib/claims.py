"""事实陈述抽取：把正文切成句子，识别可核查的事实陈述，并抽出关键要素（数字、年份、书名、引语、机构）。"""
import re
from .text import split_sentences, strip_md, cjk_len

NUM = re.compile(r'(?<![A-Za-z0-9_.])(\d+(?:[.,]\d+)*)\s*((?:%|％|‰)|(?:万亿|亿|万|千)?(?:多|余)?(?:人次|万人|人|名|位|个|项|次|篇|部|份|台|辆|吨|千克|公斤|克|元|美元|亩|公顷|'
                 r'平方公里|公里|千米|米|小时|分钟|秒|岁|家|所|座|种|条|株|只|头|例|册|期|届|支|毫秒|倍|GB|TB|kWh|度|号|周|天|年)?)')
CN_NUM = re.compile(r'(?<![一-鿿])(?:[二三四五六七八九十百千两]{1}[十百千]+[一二三四五六七八九]?|[一二三四五六七八九十百千两]+[万亿])(?:多|余)?(?:人|名|位|个|项|次|年|篇|种|倍|吨|元)')
YEAR = re.compile(r'(?<!\d)((?:1[5-9]|20)\d{2})\s*年')
TITLE = re.compile(r'《([^》]{1,40})》')
QUOTE = re.compile(r'[“"]([^”"]{4,80})[”"]')
SPEECH = re.compile(r'(?:说|写道|指出|提出|强调|认为|曾言|有言|所言|讲道)[:：，,]?\s*[“"]')
ORG = re.compile(r'[一-鿿A-Za-z]{2,14}?(?:研究院|研究所|研究会|研究中心|中心|大学|学院|协会|学会|委员会|'
                 r'统计局|管理局|总局|部|局|署|办公厅|公司|集团|组织|基金会|医院|报社|日报|新闻社|实验室)')
RESEARCH = re.compile(r'(?:研究|调查|报告|数据|统计|调研|白皮书|普查|监测)(?:结果)?(?:显示|表明|发现|指出|称)')
VAGUE = re.compile(r'据(?:不完全)?统计|有(?:关)?(?:数据|研究|调查|报告)(?:显示|表明)|(?:大量|许多|众多|多项)(?:研究|调查|数据)'
                   r'|数以(?:千|万|百万|千万|亿)计|成千上万|不计其数|专家(?:表示|指出|认为)|科学家(?:发现|认为)|研究人员(?:发现|认为)')
EVENT = re.compile(r'(?:发明|发现|提出|创立|创办|成立|发表|出版|获得|荣获|获颁|当选|登上|攻克|研制|建成|签署|颁布|印发|发布|'
                   r'战胜|击败|首次|第一次|首个|首位|诞生|去世|逝世|出生|率领|担任|被任命)')
SOURCE_HINT = re.compile(r'据|根据|来自|来源|发布的|公布的|显示|报告|统计|调查|\[\d+(?:[-–,，]\d+)*\]')
FICTION_OK = re.compile(r'^(?:我|我们|他|她)(?:想|觉得|认为|希望|记得)')


def keys_of(s):
    nums = []
    for m in NUM.finditer(s):
        unit = m.group(2) or ''
        if YEAR.match(s[m.start():m.end(1) + 2]) or re.match(r'\s*(?:月|日|时|点|:|：)', s[m.end(1):m.end(1) + 2]):
            continue          # 年份单列；月、日、钟点不算数据
        if not unit and len(m.group(1)) < 3:
            continue          # 裸的一两位数不算独立数据
        nums.append(m.group(1) + unit)
    return {'numbers': nums + CN_NUM.findall(s), 'years': YEAR.findall(s), 'titles': TITLE.findall(s),
            'quotes': [q for q in QUOTE.findall(s) if SPEECH.search(s)], 'orgs': sorted(set(ORG.findall(s)))}


def claim_types(s, k):
    """高召回：含数据、年份、书名、引语、研究结论或文献引用的句子都算候选，真假交给检索和 Agent 判断。"""
    t = []
    if k['numbers']:
        t.append('数据')
    if k['quotes']:
        t.append('引语')
    if k['years'] or (k['titles'] and EVENT.search(s)) or (EVENT.search(s) and k['orgs']):
        t.append('事件')
    if RESEARCH.search(s):
        t.append('研究结论')
    if re.search(r'\[\d', s):
        t.append('文献引用')
    return t


def extract(paras, material=None):
    """paras: [(行号, 段落)]；material: 用户素材文本（新闻稿类），用于判定 F6。
    返回 claims 列表，每条含 id/line/text/types/keys/flags。"""
    out, n = [], 0
    for line, p in paras:
        for s in split_sentences(p):
            clean = strip_md(s)
            if cjk_len(clean) < 6:
                continue
            k = keys_of(s)
            types = claim_types(s, k)
            vague = bool(VAGUE.search(s))
            if not types and not vague:
                continue
            n += 1
            flags = []
            if vague:
                flags.append('F2_模糊化来源')
            has_src = bool(SOURCE_HINT.search(s))
            if material is None and ('数据' in types or '研究结论' in types) and not has_src:
                flags.append('F1_数据无来源')   # 新闻稿类以素材为来源，不报 F1
            if material is not None:
                extra = [x for x in k['numbers'] + k['years'] if _norm_num(x) not in _mat_nums(material)]
                extra_q = [q for q in k['quotes'] if q not in material]
                if extra or extra_q:
                    flags.append('F6_超出素材')
            out.append({'id': f'C{n:02d}', 'line': line, 'text': s, 'types': types or ['模糊陈述'],
                        'keys': k, 'flags': flags, 'has_source_hint': has_src})
    return out


_MAT_CACHE = {}


def _mat_nums(material):
    if material not in _MAT_CACHE:
        _MAT_CACHE[material] = {_norm_num(m.group(1)) for m in re.finditer(r'(\d+(?:[.,]\d+)*)', material)}
    return _MAT_CACHE[material]


def _norm_num(x):
    m = re.match(r'(\d+(?:[.,]\d+)*)', x)
    return m.group(1).replace(',', '') if m else x
