"""Resolve a plain-English question into a semantic-layer request.

Deterministic on purpose: the same question always maps to the same metric definitions, and the
resolver reports exactly how it read the question (and which words it didn't use), so a person can
check the interpretation before trusting the number. An LLM client sitting on top of the MCP server
can do richer language understanding and call `query_metrics` directly; either way, every number
comes from the same governed definitions.

Matching rules, in order:
  1. control / SOX questions -> control status
  2. curated saved-query phrases ("ARR bridge", "board KPIs") -> that saved query
  3. metric names, labels and synonyms, longest phrase first, so "net revenue retention" never
     also matches "revenue"
  4. "by segment" / "which region" -> group by; dimension values ("enterprise", "EMEA") -> filters
  5. grain words ("quarterly") and time phrases ("last 6 months", "Q3 2025", "since 2024", "in 2025")
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from datetime import date

from .catalog import Catalog

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
MONTH_WORDS = {"january": 1, "february": 2, "march": 3, "april": 4, "june": 6, "july": 7, "august": 8,
               "september": 9, "sept": 9, "october": 10, "november": 11, "december": 12, **MONTHS}
NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
                "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "eighteen": 18, "twenty four": 24}
DIM_WORDS = {"segment": "segment", "segments": "segment", "region": "region", "regions": "region",
             "geo": "region", "geography": "region", "industry": "industry", "industries": "industry",
             "vertical": "industry", "verticals": "industry"}
VALUE_ALIASES = {"mid market": "Mid-Market", "midmarket": "Mid-Market", "small business": "SMB",
                 "enterprise customers": "Enterprise", "europe": "EMEA", "asia": "APAC"}
CONTROL_WORDS = r"\b(controls?|sox|exceptions?|audit evidence|control status|deficienc(y|ies))\b"
TREND_WORDS = r"\b(trend|trending|over time|history|historical|trajectory)\b"
STOPWORDS = {"what", "is", "are", "was", "were", "our", "the", "a", "an", "of", "for", "in", "on", "to",
             "how", "much", "many", "show", "me", "give", "tell", "and", "vs", "versus", "with", "by",
             "per", "each", "did", "do", "does", "we", "have", "has", "been", "this", "that", "please",
             "can", "you", "i", "my", "it", "at", "as", "from", "since", "last", "past", "over", "which",
             "had", "up", "down", "be", "compare", "compared", "between", "current", "currently",
             "today", "now", "latest", "month", "months", "quarter", "quarters", "year", "years", "trend",
             "split", "broken", "across", "all", "total", "number", "s", "gl", "ledger"}


@dataclass
class Resolution:
    kind: str                                  # metrics | saved_query | controls | unresolved
    metrics: list[str] = field(default_factory=list)
    group_by: list[str] = field(default_factory=list)
    filters: dict[str, list[str]] = field(default_factory=dict)
    grain: str = "month"
    start: date | None = None
    end: date | None = None
    saved_query: str | None = None
    matched: list[str] = field(default_factory=list)       # phrases recognized, for transparency
    ignored: list[str] = field(default_factory=list)       # words not used
    notes: list[str] = field(default_factory=list)


def _first_of_quarter(d: date) -> date:
    return date(d.year, 3 * ((d.month - 1) // 3) + 1, 1)


def _shift_months(d: date, n: int) -> date:
    y, m = divmod(d.month - 1 + n, 12)
    return date(d.year + y, m + 1, 1)


def period_window(end_month: date, grain: str, n: int) -> tuple[date, date]:
    """The last n complete-or-current periods of `grain` ending with the period containing end_month."""
    if grain == "month":
        return _shift_months(end_month, -(n - 1)), end_month
    if grain == "quarter":
        return _shift_months(_first_of_quarter(end_month), -3 * (n - 1)), end_month
    return date(end_month.year - (n - 1), 1, 1), end_month


class _Text:
    """Lower-cased question with a mask so each word is consumed by at most one rule."""

    def __init__(self, question: str):
        t = question.lower().replace("’", "'")
        t = re.sub(r"[^a-z0-9\-\s]", " ", t)
        t = t.replace("-", " ")
        self.text = re.sub(r"\s+", " ", t).strip()
        self.used = [False] * len(self.text)

    def take(self, pattern: str) -> list[re.Match]:
        found = []
        for m in re.finditer(pattern, self.text):
            if not any(self.used[m.start():m.end()]):
                found.append(m)
                for i in range(m.start(), m.end()):
                    self.used[i] = True
        return found

    def leftover(self) -> list[str]:
        chars = "".join(c if not u else " " for c, u in zip(self.text, self.used, strict=True))
        return [w for w in chars.split() if w not in STOPWORDS and not w.isdigit()]


def _phrase_pattern(phrase: str) -> str:
    words = re.sub(r"[^a-z0-9\s]", " ", phrase.lower().replace("-", " ")).split()
    return r"\b" + r"\s+".join(map(re.escape, words)) + r"s?\b"


def _anchor(match_text: str) -> tuple[date, date, str] | None:
    """Parse one time expression into (start, end, unit)."""
    m = re.fullmatch(r"q([1-4]) (?:fy)?(20\d\d)", match_text)
    if m:
        q, y = int(m.group(1)), int(m.group(2))
        return date(y, 3 * q - 2, 1), date(y, 3 * q, 1), "quarter"
    m = re.fullmatch(r"([a-z]+) (20\d\d)", match_text)
    if m and m.group(1) in MONTH_WORDS:
        d = date(int(m.group(2)), MONTH_WORDS[m.group(1)], 1)
        return d, d, "month"
    m = re.fullmatch(r"(?:fy)?(20\d\d)", match_text)
    if m:
        y = int(m.group(1))
        return date(y, 1, 1), date(y, 12, 1), "year"
    return None


def resolve(question: str, catalog: Catalog, bounds: tuple[date, date],
            dimension_values: dict[str, list[str]]) -> Resolution:
    first_month, last_month = bounds
    t = _Text(question)
    r = Resolution(kind="metrics")

    # 1. Controls
    if re.search(CONTROL_WORDS, t.text):
        r.kind = "controls"
        r.matched.append("control status")
        return r

    # 2. Curated saved queries
    phrases = sorted(((p, sq.name) for sq in catalog.saved_queries.values() for p in sq.phrases),
                     key=lambda x: -len(x[0]))
    for phrase, name in phrases:
        if t.take(_phrase_pattern(phrase)):
            r.kind, r.saved_query = "saved_query", name
            r.matched.append(f"saved query '{name}' ('{phrase}')")
            break

    # 3. Metrics, longest phrase first
    vocab: list[tuple[str, str]] = []
    for metric in catalog.metrics.values():
        for phrase in {metric.name.replace("_", " "), metric.label.lower(), *metric.synonyms}:
            vocab.append((phrase.lower(), metric.name))
    vocab.sort(key=lambda x: -len(x[0]))
    hits: list[tuple[int, str, str]] = []
    for phrase, name in vocab:
        for m in t.take(_phrase_pattern(phrase)):
            hits.append((m.start(), name, phrase))
    for _, name, phrase in sorted(hits):
        if name not in r.metrics:
            r.metrics.append(name)
            r.matched.append(f"metric {name} ('{phrase}')")

    # 4. Dimensions: group-by and filter values
    dim_alt = "|".join(sorted(DIM_WORDS, key=len, reverse=True))
    for m in t.take(rf"\b(?:by|per|for each|across|split by|broken down by|which|what)\s+(?:customer\s+)?({dim_alt})\b"):
        dim = DIM_WORDS[m.group(1)]
        if dim not in r.group_by:
            r.group_by.append(dim)
            r.matched.append(f"group by {dim}")
    value_map: dict[str, tuple[str, str]] = {}
    for dim, values in dimension_values.items():
        for v in values:
            value_map[v.lower().replace("-", " ")] = (dim, v)
    for alias, canonical in VALUE_ALIASES.items():
        for dim, values in dimension_values.items():
            if canonical in values:
                value_map[alias] = (dim, canonical)
    for phrase in sorted(value_map, key=len, reverse=True):
        if t.take(_phrase_pattern(phrase)):
            dim, value = value_map[phrase]
            r.filters.setdefault(dim, [])
            if value not in r.filters[dim]:
                r.filters[dim].append(value)
                r.matched.append(f"filter {dim} = {value}")
    for m in t.take(rf"\b({dim_alt})\b"):  # a bare "segment" usually means "by segment"
        dim = DIM_WORDS[m.group(1)]
        if dim not in r.group_by and dim not in r.filters:
            r.group_by.append(dim)
            r.matched.append(f"group by {dim}")

    # 5. Grain
    grain_set = False
    for pattern, grain in [(r"\b(monthly|by month|per month|each month|month over month|mom)\b", "month"),
                           (r"\b(quarterly|by quarter|per quarter|each quarter|quarter over quarter|qoq)\b", "quarter"),
                           (r"\b(yearly|annually|annual|by year|per year|each year|year over year|yoy)\b", "year")]:
        if t.take(pattern):
            r.grain, grain_set = grain, True
            r.matched.append(f"grain {grain}")
            break

    # 6. Time
    n_alt = "|".join(sorted(NUMBER_WORDS, key=len, reverse=True))
    rel = t.take(rf"\b(?:last|past|previous|trailing|prior)\s+(\d+|{n_alt})\s+(months?|quarters?|years?)\b")
    single = t.take(r"\b(?:last|past|previous|prior)\s+(month|quarter)\b")
    ttm = t.take(r"\b(ttm|ltm|trailing twelve months|trailing 12 months|last twelve months|last year|past year)\b")
    ytd = t.take(r"\b(ytd|year to date|this year)\b")
    since = bool(t.take(r"\bsince\b"))
    month_alt = "|".join(sorted(MONTH_WORDS, key=len, reverse=True))
    anchors = [a for a in (_anchor(m.group(0)) for m in
                           t.take(rf"\b(?:q[1-4] (?:fy)?20\d\d|(?:{month_alt}) 20\d\d|(?:fy)?20\d\d)\b")) if a]
    point_in_time = bool(t.take(r"\b(now|today|current|currently|latest|as of)\b"))

    if rel:
        raw, unit = rel[0].group(1), rel[0].group(2).rstrip("s")
        n = int(raw) if raw.isdigit() else NUMBER_WORDS[raw]
        if not grain_set:
            r.grain = unit
        if unit == r.grain:
            r.start, r.end = period_window(last_month, r.grain, n)
        else:  # e.g. "quarterly over the last 18 months"
            r.start, r.end = period_window(last_month, unit, n)
        r.matched.append(f"last {n} {unit}s")
    elif single:
        unit = single[0].group(1)
        if not grain_set:
            r.grain = unit
        r.start, r.end = period_window(last_month, unit, 1)
        r.matched.append(f"latest {unit}")
    elif ttm:
        r.start, r.end = period_window(last_month, "month", 12)
        if not grain_set:
            r.grain = "month"
        r.matched.append("trailing 12 months")
    elif ytd:
        r.start, r.end = date(last_month.year, 1, 1), last_month
        if not grain_set:
            r.grain = "year"
        r.matched.append("year to date")
    elif anchors:
        if since:
            r.start, r.end = anchors[0][0], last_month
            if not grain_set:
                r.grain = "month"
            r.matched.append(f"since {r.start:%Y-%m}")
        elif len(anchors) >= 2:
            r.start, r.end = anchors[0][0], anchors[-1][1]
            if not grain_set:
                r.grain = "month"
            r.matched.append(f"{r.start:%Y-%m} to {r.end:%Y-%m}")
        else:
            r.start, r.end, unit = anchors[0]
            if not grain_set:
                r.grain = unit
            r.matched.append(f"{unit} {r.start:%Y-%m}" if unit != "year" else f"year {r.start.year}")
    elif grain_set or re.search(TREND_WORDS, t.text):
        defaults = {"month": 12, "quarter": 4, "year": 3}
        r.start, r.end = period_window(last_month, r.grain, defaults[r.grain])
        r.matched.append(f"default window: last {defaults[r.grain]} {r.grain}s")
    elif r.kind != "saved_query":
        r.start, r.end = last_month, last_month
        if r.metrics:
            r.notes.append(f"No time period given, so this is the latest month in the data ({last_month:%Y-%m}).")

    # Keep the window inside the data.
    if r.start and r.start < first_month:
        r.notes.append(f"Data starts {first_month:%Y-%m}; the window was trimmed to fit.")
        r.start = first_month
    if r.end and r.end > last_month:
        r.notes.append(f"Data ends {last_month:%Y-%m}; the window was trimmed to fit.")
        r.end = last_month
    if r.start and r.end and r.start > r.end:
        r.kind = "unresolved"
        r.notes.append(f"That period is outside the data ({first_month:%Y-%m} to {last_month:%Y-%m}).")
        return r
    if point_in_time:
        r.matched.append("point in time")

    r.ignored = t.leftover()
    if r.kind == "metrics" and not r.metrics:
        r.kind = "unresolved"
        words = r.ignored or t.text.split()
        vocab_phrases = [p for p, _ in vocab]
        guesses = []
        for w in words:
            guesses += [catalog_name for p, catalog_name in vocab
                        if p in difflib.get_close_matches(w, vocab_phrases, n=3, cutoff=0.75)]
        suggestions = list(dict.fromkeys(guesses))[:5]
        r.notes.append("I couldn't find a metric in that question."
                       + (f" Did you mean: {', '.join(suggestions)}?" if suggestions else "")
                       + " Use list_metrics to see everything available.")
    return r
