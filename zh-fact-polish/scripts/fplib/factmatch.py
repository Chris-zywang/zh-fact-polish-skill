"""Conservative key matching; this is not a general semantic entailment model.

Compare complete numeric tokens, dimensions, bounds, and local metric/time
bindings. Unknown paraphrases remain unverified rather than guessed correct.
"""
from dataclasses import dataclass
import math
import re
import unicodedata


_DIGIT = r"[+-]?\d+(?:,\d{3})*(?:\.\d+)?"
_SCALE = r"万亿|亿|万|千|billion|million|thousand"
_UNIT = (r"人次|平方公里|千米|公里|公顷|千克|公斤|毫秒|美元|亿元|万元|"
         r"persons?|people|species|percent|yuan|hours?|minutes?|seconds?|"
         r"GB|TB|kWh|%|‰|人|名|位|种|个|项|次|篇|部|份|台|辆|吨|克|元|亩|"
         r"米|小时|分钟|秒|岁|家|所|座|条|株|只|头|例|册|期|届|支|倍|度|号|周|天|年")
NUMBER = re.compile(rf"(?<![A-Za-z0-9_.])(?P<n>{_DIGIT})\s*"
                    rf"(?P<scale>{_SCALE})?\s*(?P<more>多|余)?\s*(?P<unit>{_UNIT})?", re.I)
SCALES = {"": 1, "千": 1e3, "万": 1e4, "亿": 1e8, "万亿": 1e12,
          "thousand": 1e3, "million": 1e6, "billion": 1e9}
FAMILIES = {"名": "person", "人": "person", "位": "person", "person": "person",
            "persons": "person", "people": "person", "种": "species", "species": "species",
            "元": "yuan", "yuan": "yuan", "美元": "usd", "%": "percent", "percent": "percent",
            "‰": "permille", "岁": "age", "年": "duration_year", "人次": "person_times",
            "公里": "length_km", "千米": "length_km", "千克": "mass_kg", "公斤": "mass_kg",
            "小时": "hour", "hour": "hour", "hours": "hour", "分钟": "minute",
            "minute": "minute", "minutes": "minute", "秒": "second", "second": "second", "seconds": "second"}
BOUND = re.compile(r"(不少于|不低于|不超过|不高于|至少|至多|最多|超过|高于|多于|低于|少于|"
                   r"不到|不足|大约|约为|约|近|at least|at most|more than|less than|about)\s*"
                   r"(?:为|有|达|只?解释[^，。；\d]{0,8})?\s*$", re.I)
BOUND_KIND = {"不少于": "ge", "不低于": "ge", "至少": "ge", "at least": "ge",
              "不超过": "le", "不高于": "le", "至多": "le", "最多": "le", "at most": "le",
              "超过": "gt", "高于": "gt", "多于": "gt", "more than": "gt",
              "低于": "lt", "少于": "lt", "不到": "lt", "不足": "lt", "less than": "lt"}
METRICS = {
    "revenue": r"销售额|营业收入|营收|sales revenue|revenue",
    "profit": r"净利润|利润|net profit|profit",
    "survival": r"成活率|survival rate",
    "penetration": r"普及率|penetration rate",
    "accuracy": r"准确率|accuracy",
    "population": r"人口|population",
    "internet_users": r"网民规模|internet users",
    "word_error": r"词错误率|word error rate",
    "phoneme_error": r"音素错误率|phoneme error rate",
}
METRIC_PATTERNS = {k: re.compile(v, re.I) for k, v in METRICS.items()}
EVENTS = {
    "release": r"公布|发布|披露|\breleased?\b", "survey": r"调查|普查|\bsurvey(?:ed)?\b",
    "found": r"成立|创立|创办|\bfounded\b", "acquire": r"收购|并购|\bacquired\b",
    "publish": r"发表|出版|刊发|\bpublished\b", "breakup": r"解体|\bdisintegrated\b|\bbroke up\b",
    "launch": r"发射|\blaunch(?:ed)?\b", "fire": r"起火|\bcaught fire\b",
    "failure": r"失败|\bfailed\b|\bfailure\b", "award": r"获奖|获颁|荣获|\bawarded\b",
}
EVENT_PATTERNS = {k: re.compile(v, re.I) for k, v in EVENTS.items()}
YEAR = re.compile(r"(?<!\d)((?:1[5-9]|20)\d{2})(?!\d)\s*年?")
SCOPE = re.compile(r"(?:头|前|首)([一二两三四五六七八九十\d]+)年|第([一二两三四五六七八九十\d]+)年|当年|首年")
COUNTRIES = {
    '英国': re.compile(r'英国|United Kingdom|\bUK\b|\bBritain\b|\bBritish\b', re.I),
    '美国': re.compile(r'美国|United States|(?-i:\bUSA?\b)|\bAmerican\b', re.I),
    '日本': re.compile(r'日本|\bJapan\b|\bJapanese\b', re.I),
}


def normalize(text):
    return unicodedata.normalize("NFKC", text or "")


def literal(text):
    return re.sub(r"[\s,，、\"“”‘’《》（）()「」。.!！?？]", "", normalize(text))


@dataclass(frozen=True)
class Amount:
    raw: str
    value: float
    family: str
    kind: str
    bound: str
    start: int
    end: int
    rounding: float = 0


def amounts(text):
    text = normalize(text)
    out = []
    for m in NUMBER.finditer(text):
        raw_n = m["n"].replace(",", "")
        scale = SCALES[(m["scale"] or "").lower()]
        unit = (m["unit"] or "").lower()
        value = float(raw_n) * scale
        family = FAMILIES.get(unit, unit)
        kind = "number"
        if scale == 1 and value.is_integer() and 1500 <= value <= 2099 and unit in ("", "年"):
            kind, family = "year", "year"
        elif not unit and re.match(r"\s*(?:月|日|时|点|:|：)", text[m.end():]):
            kind, family = "date", "date"
        prefix = BOUND.search(text[max(0, m.start() - 15):m.start()])
        bound = BOUND_KIND.get(prefix[1].lower(), "approx") if prefix else "eq"
        suffix = text[m.end():m.end() + 4]
        if m["more"]:
            bound = "gt"
        elif re.match(r"(?:及)?以上", suffix):
            bound = "ge"
        elif re.match(r"(?:及)?以下", suffix):
            bound = "le"
        elif suffix.startswith("左右"):
            bound = "approx"
        # Decimal notation with a large scale legitimately rounds e.g. 3.1亿.
        rounding = scale * 10 ** (-len(raw_n.split(".")[1])) / 2 if "." in raw_n and scale >= 1e4 else 0
        out.append(Amount(m.group().strip(), value, family, kind, bound, m.start(), m.end(), rounding))
    return out


def same_dimension(a, b):
    return a.kind == b.kind and (not a.family or not b.family or a.family == b.family)


def value_supported(a, b):
    if not same_dimension(a, b):
        return False
    equal = math.isclose(a.value, b.value, rel_tol=1e-10, abs_tol=1e-10)
    if a.bound == "eq":
        return b.bound == "eq" and (equal or (a.rounding > 0 and abs(a.value - b.value) < a.rounding))
    if a.bound == "approx":
        return b.bound in ("eq", "approx") and abs(a.value - b.value) <= max(abs(a.value) * .02, a.rounding, 1e-10)
    if a.bound == "lt":
        return (b.bound in ("lt", "le") and b.value < a.value) or (b.bound == "lt" and equal) or (b.bound == "eq" and b.value < a.value)
    if a.bound == "le":
        return b.bound in ("lt", "le", "eq") and (b.value < a.value or equal)
    if a.bound == "gt":
        return (b.bound in ("gt", "ge") and b.value > a.value) or (b.bound == "gt" and equal) or (b.bound == "eq" and b.value > a.value)
    if a.bound == "ge":
        return b.bound in ("gt", "ge", "eq") and (b.value > a.value or equal)
    return False


def metric_of(text, token):
    prefix = re.split(r"[。！？!?；;，,\n]", normalize(text)[:token.start])[-1][-45:]
    found = [(m.end(), key) for key, pattern in METRIC_PATTERNS.items() for m in pattern.finditer(prefix)]
    return max(found)[1] if found else None


def scope_of(text, token):
    # A source excerpt may introduce "当年" in the previous sentence. Preserve
    # that local context inside the same excerpt, but not across paragraph breaks.
    prefix = re.split(r"[；;\n]", normalize(text)[:token.start])[-1][-100:]
    found = list(SCOPE.finditer(prefix))
    if not found:
        return None
    m = found[-1]
    def n(s):
        return {"一": "1", "二": "2", "两": "2", "三": "3", "四": "4", "五": "5", "六": "6", "七": "7", "八": "8", "九": "9", "十": "10"}.get(s, s)
    if m[1]:
        return "first_year" if n(m[1]) == "1" else "first_years:" + n(m[1])
    if m[2]:
        return "first_year" if n(m[2]) == "1" else "ordinal_year:" + n(m[2])
    return "single_year" if m.group() == "当年" else "first_year"


def year_of(text, token):
    prefix = re.split(r"[。！？!?；;\n]", normalize(text)[:token.start])[-1]
    found = [a for a in amounts(prefix) if a.kind == 'year'
             and not re.search(r'(?:较|比|同比|相比|对比)\s*$', prefix[max(0, a.start - 5):a.start])]
    return str(int(found[-1].value)) if found else None


def bindings_supported(text, token, source, other):
    metric = metric_of(text, token)
    if metric and metric != metric_of(source, other):
        return False
    scope = scope_of(text, token)
    if scope and (scope != 'single_year' or metric) and scope != scope_of(source, other):
        return False
    year = year_of(text, token)
    other_year = year_of(source, other)
    if metric and year and year != other_year:
        return False
    return True


def year_events(text):
    """Bind event words to the latest preceding year within a sentence.

    Unknown ordering/paraphrases are deliberately not claimed to be understood.
    """
    pairs = set()
    previous_year = None
    for sentence in re.split(r"[。！？!?\n]", normalize(text)):
        years = [a for a in amounts(sentence) if a.kind == 'year']
        if not years:
            if previous_year:
                pairs.update((previous_year, event) for event, pattern in EVENT_PATTERNS.items() if pattern.search(sentence))
            continue
        if len(years) == 1:
            # In single-year sentences, English often places the date after the event.
            pairs.update((str(int(years[0].value)), event) for event, pattern in EVENT_PATTERNS.items() if pattern.search(sentence))
            previous_year = str(int(years[0].value))
            continue
        for i, y in enumerate(years):
            part = sentence[y.end:years[i + 1].start if i + 1 < len(years) else len(sentence)]
            for event, pattern in EVENT_PATTERNS.items():
                if pattern.search(part):
                    pairs.add((str(int(y.value)), event))
        previous_year = str(int(years[-1].value))
    return pairs


def report(claim, texts):
    """Return coverage, missing checks, and explicit same-field conflicts."""
    texts = [normalize(t) for t in texts if t]
    original = normalize(claim["text"])
    original_numbers = amounts(original)
    source_numbers = [(text, token) for text in texts for token in amounts(text)]
    k = claim["keys"]
    count = len(k["numbers"]) + len(k["years"]) + len(k["titles"]) + len(k["quotes"])
    if not count:
        return {"ratio": None, "missing": [], "conflicts": []}
    missing, conflicts = [], []
    for raw in k["numbers"]:
        selected = [a for a in original_numbers if literal(a.raw) == literal(raw)]
        if not selected:
            missing.append(f"数值无法可靠解析：{raw}")
            continue
        for a in selected:
            candidates = [(text, b) for text, b in source_numbers if value_supported(a, b)]
            if any(bindings_supported(original, a, text, b) for text, b in candidates):
                continue
            metric = metric_of(original, a)
            related = [(text, b) for text, b in source_numbers
                       if metric and metric_of(text, b) == metric and same_dimension(a, b)
                       and bindings_supported(original, a, text, b)]
            if related:
                conflicts.append(f"同一指标的数值或范围不一致：{raw}，证据为{'、'.join(b.raw for _, b in related)}")
            missing.append(f"{raw}（完整数值、单位、范围或指标绑定未获支持）")
            break
    for year in k["years"]:
        if not any(b.kind == "year" and str(int(b.value)) == year for _, b in source_numbers):
            missing.append(f"年份未出现：{year}")
    for title in k["titles"]:
        if not any(literal(title) in literal(text) for text in texts):
            missing.append(f"书名未出现：{title}")
    for quote in k["quotes"]:
        if not any(literal(quote) in literal(text) for text in texts):
            missing.append(f"完整引语未出现：{quote}")
    supported_events = set().union(*(year_events(t) for t in texts))
    for year, event in sorted(year_events(original) - supported_events):
        missing.append(f"年份与事件未在同一证据语境绑定：{year}/{event}")
    for country, pattern in COUNTRIES.items():
        if country in original and not any(pattern.search(t) for t in texts):
            missing.append(f"地域限定未由摘录支持：{country}")
    # A missing relation is a failed check even when all raw keys occur.
    ratio = 1.0 if not missing else max(0.0, 1 - len(missing) / count)
    return {"ratio": ratio, "missing": missing, "conflicts": conflicts}
