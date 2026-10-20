"""Catalog governance checks: the review a metrics owner would do before a definition ships.

Run with `python -m finance_semantic lint`; CI fails the build on any finding.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from .catalog import Catalog
from .nl import resolve

ROLLUP_BY_FORMAT = {
    # A balance metric that sums across months, or a count of customers that does, is almost always a bug.
    "count": {"sum", "last"},
    "currency": {"sum", "last", "first"},
    "percent": {"last"},
}


def lint_catalog(catalog: Catalog) -> list[str]:
    findings: list[str] = []

    # Every metric is documented, owned and explicitly certified or not.
    for m in catalog.metrics.values():
        if len(m.description) < 30:
            findings.append(f"{m.name}: description is too short to define the metric")
        if not m.owner:
            findings.append(f"{m.name}: no owner")
        if not m.synonyms:
            findings.append(f"{m.name}: no synonyms; people won't find it by the words they use")
        for measure in m.measures:
            if measure.time_agg not in ROLLUP_BY_FORMAT[m.format]:
                findings.append(f"{m.name}: {m.format} metric rolls up over time with '{measure.time_agg}'")

    # No phrase may point at two different metrics; ambiguity there means two people get two numbers.
    phrase_owners: dict[str, set[str]] = defaultdict(set)
    for m in catalog.metrics.values():
        for phrase in {m.name.replace("_", " "), m.label.lower(), *(s.lower() for s in m.synonyms)}:
            phrase_owners[phrase].add(m.name)
    for phrase, owners in sorted(phrase_owners.items()):
        if len(owners) > 1:
            findings.append(f"phrase '{phrase}' maps to more than one metric: {', '.join(sorted(owners))}")

    # Saved-query phrases must not collide with each other.
    saved_owner: dict[str, str] = {}
    for sq in catalog.saved_queries.values():
        for phrase in sq.phrases:
            if phrase in saved_owner and saved_owner[phrase] != sq.name:
                findings.append(f"saved-query phrase '{phrase}' used by {saved_owner[phrase]} and {sq.name}")
            saved_owner[phrase] = sq.name

    # Round trip: each metric's own label, asked as a question, resolves to that metric alone.
    bounds = (date(2023, 1, 1), date(2025, 12, 1))
    for m in catalog.metrics.values():
        r = resolve(m.label, catalog, bounds, {})
        if r.kind != "metrics" or r.metrics != [m.name]:
            findings.append(f"{m.name}: asking for '{m.label}' resolves to {r.metrics or r.kind}")
    for sq in catalog.saved_queries.values():
        for phrase in sq.phrases:
            r = resolve(phrase, catalog, bounds, {})
            if r.saved_query != sq.name:
                findings.append(f"saved query {sq.name}: phrase '{phrase}' resolves to {r.saved_query or r.kind}")
    return findings
