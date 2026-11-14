"""文本读取与切分：段落、句子、小句，正文与参考文献分离。"""
import re

TERMINALS = set('。！？!?')
CLOSERS = set('”’」』）)》"' + "'")
CJK = re.compile(r'[一-鿿]')
REF_HEAD = re.compile(
    r'^\s*(?:#{1,6}\s*)?(?:\*\*)?\s*(?:参考文献|参考资料|引用文献|References|Bibliography)'
    r'\s*(?:\*\*)?\s*[:：]?\s*$', re.I)
HEADING = re.compile(
    r'^(?:#{1,6}\s|\*\*[^*]+\*\*$|第[一二三四五六七八九十百]+[章节部分]|'
    r'[一二三四五六七八九十]+[、.．]|（[一二三四五六七八九十]+）|\d+(?:\.\d+)*[、.．\s])')
CLAUSE_SPLIT = re.compile(r'[，,；;：:]')


def read_text(path):
    with open(path, 'r', encoding='utf-8-sig') as f:
        return f.read()


def cjk_len(s):
    return len(CJK.findall(s))


def split_sentences(para):
    """按句末标点切句，句末标点后的引号/括号归入前一句。"""
    sents, buf, i = [], '', 0
    while i < len(para):
        ch = para[i]
        buf += ch
        is_end = ch in TERMINALS or (ch == '…' and para[i + 1:i + 2] != '…')
        if is_end:
            while i + 1 < len(para) and (para[i + 1] in TERMINALS or para[i + 1] in CLOSERS):
                i += 1
                buf += para[i]
            if buf.strip():
                sents.append(buf.strip())
            buf = ''
        i += 1
    if buf.strip():
        sents.append(buf.strip())
    return sents


def split_clauses(sent):
    return [c for c in CLAUSE_SPLIT.split(sent) if c.strip()]


def is_heading(line):
    s = line.strip()
    if s.startswith('#') or (s.startswith('**') and s.endswith('**')):
        return True
    if len(s) <= 30 and s[-1:] not in TERMINALS and HEADING.match(s):
        return True
    return len(s) <= 20 and s[-1:] not in TERMINALS and '，' not in s


def split_body_refs(text):
    """返回 (正文, 参考文献原文, 参考文献起始行号)。没有参考文献节时后两项为 ('', None)。"""
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        if REF_HEAD.match(ln):
            return '\n'.join(lines[:i]), '\n'.join(lines[i + 1:]), i + 1
    return text, '', None


def paragraphs(body):
    """正文段落列表：[(行号, 段落文本)]，跳过标题、公式块、空行、关键词/摘要标签行。"""
    out, in_math = [], False
    for no, ln in enumerate(body.splitlines(), 1):
        s = ln.strip()
        if s.startswith('$$'):
            single_line = len(s) > 4 and s.endswith('$$')
            if not single_line:
                in_math = not in_math
            continue
        if in_math or not s or s.startswith('|') or s.startswith('```'):
            continue
        if is_heading(s) or cjk_len(s) < 8:
            continue
        if re.match(r'^\*{0,2}(关键词|关键字|Keywords)', s):
            continue
        out.append((no, s))
    return out


def strip_md(s):
    s = re.sub(r'\$[^$]*\$', 'X', s)
    s = re.sub(r'\*\*|__|`', '', s)
    s = re.sub(r'\[(\d+(?:[-–,，]\d+)*)\]', '', s)
    return s
