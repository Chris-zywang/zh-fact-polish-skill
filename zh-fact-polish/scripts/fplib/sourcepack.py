"""Validate per-excerpt provenance against explicitly supplied source blocks."""
import re

HEADER = re.compile(r'(?m)^\[来源\d+\]')
URL = re.compile(r'https?://[^\s：:）)]+')


def evidence_entries(raw, material, is_news=False):
    """Return independently validated excerpts; invalid input stays pending.

    Raw input supports both the original single excerpt and an excerpts array.
    This validates byte-for-byte provenance, not whether a source is truthful or
    whether each excerpt supports the entire claim.
    """
    fragments = raw.get('excerpts')
    if not isinstance(fragments, list):
        fragments = [{'excerpt': raw.get('excerpt', ''),
                      'verdict': raw.get('verdict', ''), 'note': raw.get('note', '')}]
    headers = list(HEADER.finditer(material))
    out = []
    for item in fragments[:8]:
        if not isinstance(item, dict):
            continue
        excerpt, verdict = item.get('excerpt', ''), item.get('verdict', '')
        valid = isinstance(excerpt, str) and verdict in ('支持', '矛盾', '未找到')
        url = ''
        if valid and excerpt:
            if is_news and excerpt in material:
                url = 'material.md'
            elif not is_news:
                candidates = set()
                for i, h in enumerate(headers):
                    end = headers[i+1].start() if i+1 < len(headers) else len(material)
                    block = material[h.start():end]
                    if excerpt in block:
                        m = URL.search(block)
                        if m:
                            candidates.add(m.group().rstrip('。.,;；'))
                if len(candidates) == 1:
                    url = next(iter(candidates))
        if not valid or (verdict in ('支持', '矛盾') and not url):
            out.append({'url': '', 'excerpt': '', 'agent_verdict': '未找到',
                        'note': '摘录无效或来源不能唯一定位，保留待核'})
        else:
            out.append({'url': url, 'excerpt': excerpt if url else '',
                        'agent_verdict': verdict, 'note': str(item.get('note', ''))[:500]})
    return out or [{'url': '', 'excerpt': '', 'agent_verdict': '未找到', 'note': '没有有效摘录'}]
