"""Recheck final sentences using registered evidence, without network requests."""
from . import claims, evidence, text


def normalized(value):
    return ''.join(value.translate(str.maketrans({'“': '"', '”': '"', '‘': "'", '’': "'"})).split())


def assess(output, ledger, material=None):
    lookup = {}
    for entry in ledger.get('claims', []):
        if entry.get('action') == '删除':
            continue
        for value in (entry.get('text', ''), entry.get('new_text', '')):
            for sentence in text.split_sentences(value):
                lookup.setdefault(normalized(sentence), {})[entry['id']] = entry
    body, _, _ = text.split_body_refs(output)
    final_claims = claims.extract(text.paragraphs(body), material)
    checks = []
    for claim in final_claims:
        key = normalized(claim['text'])
        origins = lookup.get(key, {})
        # Only a contiguous, complete final sentence may inherit an original record.
        # Similarity, partial numeric matches and ambiguous origins never qualify.
        if not origins and len(key) >= 6:
            candidates = {}
            for original, entries in lookup.items():
                if key in original:
                    candidates.update(entries)
            if len(candidates) == 1:
                origins = candidates
        if len(origins) != 1:
            label, reasons = '待验证', ['最终事实句未唯一关联到登记的原句或 new_text；请登记修改句及对应证据']
        else:
            origin = next(iter(origins.values()))
            edited_sentences = {normalized(s) for s in text.split_sentences(origin.get('new_text', ''))}
            final_evidence = origin.get('final_evidence') if any(key == s or (len(key) >= 6 and key in s) for s in edited_sentences) else None
            label, reasons, _ = evidence.judge(claim, final_evidence if final_evidence is not None else origin.get('evidence'),
                                              material, online=False)
        checks.append({'text': claim['text'], 'line': claim['line'], 'ledger_ids': sorted(origins),
                       'label': label, 'reasons': reasons})
    return checks
