"""Explain a metric's change between two periods: the grounded facts variance commentary is written from.

An LLM asked "why did ARR move?" will happily invent a story. This module does the arithmetic first,
deterministically and from governed definitions only, and returns facts that reconcile exactly:

  * Headline: the metric in both periods, the change and the % change.
  * Drivers: for balances with a roll-forward (ARR, deferred revenue), the flows that moved it
    (new + reactivation + expansion + contraction + churn = change in ARR); for metrics that are a sum
    of parts (net new ARR), the change in each part. The unexplained residual is reported, and is $0
    when the bridge foots.
  * Contributions by dimension (segment, region, industry):
      - additive metrics: each value's change and share of the total change;
      - ratio metrics (NRR, GRR, ARPA): an exact mix / rate split. Mix is the effect of the weights
        shifting toward segments above or below the average; rate is the change within each segment.
  * Facts: short plain-English sentences built only from those numbers, for a person or a model to
    write commentary from, plus the SQL behind every number.
"""

from __future__ import annotations

import dataclasses
from datetime import date

from .catalog import Catalog, Metric, SemanticError
from .compiler import SemanticQuery, compile_query
from .nl import _first_of_quarter, _shift_months

GRAIN_MONTHS = {"month": 1, "quarter": 3, "year": 12}

# Balances whose change is fully explained by flows during the period: metric -> [(component, sign)].
ROLLFORWARDS = {
    "arr": [("new_arr", 1), ("reactivation_arr", 1), ("expansion_arr", 1), ("contraction_arr", 1),
            ("churned_arr", 1)],
    "deferred_revenue": [("billings", 1), ("recognized_revenue", -1)],
}
# Flows that are the sum of other flows: the change in the total is the sum of the changes in the parts.
SUM_OF_PARTS = {
    "net_new_arr": ["new_arr", "reactivation_arr", "expansion_arr", "contraction_arr", "churned_arr"],
}


@dataclasses.dataclass(frozen=True)
class Period:
    label: str
    grain: str
    start: date
    end: date


def parse_period(text: str, grain: str | None = None) -> Period:
    """'2025-12' (month), '2025-Q4' (quarter) or '2025' (year)."""
    t = str(text).strip().upper()
    try:
        if len(t) == 4:
            y = int(t)
            return Period(t, "year", date(y, 1, 1), date(y, 12, 1))
        if "-Q" in t:
            y, q = t.split("-Q")
            start = date(int(y), 3 * (int(q) - 1) + 1, 1)
            return Period(f"{int(y)}-Q{int(q)}", "quarter", start, _shift_months(start, 2))
        y, m = (int(p) for p in t[:7].split("-"))
        start = date(y, m, 1)
        if grain in ("quarter", "year"):
            return period_containing(start, grain)
        return Period(f"{start:%Y-%m}", "month", start, start)
    except (ValueError, TypeError) as e:
        raise SemanticError(f"Couldn't read period '{text}'. Use YYYY-MM, YYYY-Qn or YYYY.") from e


def period_containing(month: date, grain: str) -> Period:
    if grain == "month":
        return Period(f"{month:%Y-%m}", "month", month, month)
    if grain == "quarter":
        start = _first_of_quarter(month)
        return Period(f"{start.year}-Q{(start.month - 1) // 3 + 1}", "quarter", start, _shift_months(start, 2))
    if grain == "year":
        return Period(str(month.year), "year", date(month.year, 1, 1), date(month.year, 12, 1))
    raise SemanticError("Grain must be month, quarter or year.")


def comparison_period(p: Period, compare_to: str) -> Period:
    if compare_to not in ("prior_period", "prior_year"):
        raise SemanticError("compare_to must be 'prior_period' or 'prior_year'.")
    back = GRAIN_MONTHS[p.grain] if compare_to == "prior_period" else 12
    return period_containing(_shift_months(p.start, -back), p.grain)


def _component_catalog(catalog: Catalog, metric: Metric) -> tuple[Catalog, str, str]:
    """A ratio's numerator and denominator as simple metrics, so they compile through the same
    governed measures as everything else (no hand-written SQL)."""
    num = dataclasses.replace(metric, name=f"{metric.name}__numerator", type="simple", measure=metric.numerator,
                              numerator=None, denominator=None)
    den = dataclasses.replace(metric, name=f"{metric.name}__denominator", type="simple", measure=metric.denominator,
                              numerator=None, denominator=None)
    extended = dataclasses.replace(catalog, metrics={**catalog.metrics, num.name: num, den.name: den})
    return extended, num.name, den.name


class _Runner:
    def __init__(self, layer, catalog: Catalog):
        self.layer, self.catalog, self.sql = layer, catalog, []

    def rows(self, metrics: list[str], grain: str, start: date, end: date, group_by: list[str] | None = None):
        compiled = compile_query(self.catalog, SemanticQuery(metrics=metrics, group_by=group_by or [], grain=grain,
                                                             start=start, end=end, limit=5000))
        self.sql.append({"sql": compiled.sql, "params": [str(p) for p in compiled.params]})
        return self.layer.warehouse.records(compiled.sql, compiled.params)

    def at(self, metrics: list[str], cur: Period, cmp: Period, group_by: list[str] | None = None) -> dict:
        """{(period_label, dim_value...): row} for the two periods."""
        out = {}
        for p in (cmp, cur):
            for r in self.rows(metrics, p.grain, p.start, p.end, group_by):
                if r["period"] == p.label:
                    out[(p.label, *(r[d] for d in group_by or []))] = r
        return out

    def flows_between(self, metrics: list[str], after: date, through: date) -> dict[str, float]:
        """Each flow summed over the months after `after` through `through`."""
        rows = self.rows(metrics, "month", _shift_months(after, 1), through)
        return {m: sum(float(r[m] or 0) for r in rows) for m in metrics}


def _num(v) -> float:
    return float(v or 0)


def fmt(value: float | None, kind: str, signed: bool = False) -> str:
    if value is None:
        return "n/a"
    sign = ("+" if value > 0 else "-" if value < 0 else "") if signed else ("-" if value < 0 else "")
    v = abs(value)
    if kind == "currency":
        return f"{sign}${v:,.0f}"
    if kind == "percent":
        return f"{sign}{v * 100:.1f} pts" if signed else f"{sign}{v:.1%}"
    if kind == "count":
        return f"{sign}{v:,.0f}"
    return f"{sign}{v:,.2f}"


def _additive_contributions(run: _Runner, metric: Metric, dim: str, cur: Period, cmp: Period, total: float) -> dict:
    data = run.at([metric.name], cur, cmp, [dim])
    values = sorted({k[1] for k in data})
    items = []
    for v in values:
        before, after = _num(data.get((cmp.label, v), {}).get(metric.name)), _num(data.get((cur.label, v), {}).get(metric.name))
        change = after - before
        items.append({dim: v, "comparison": before, "current": after, "change": change,
                      "share_of_change": change / total if total else None})
    items.sort(key=lambda i: abs(i["change"]), reverse=True)
    return {"method": "additive", "items": items, "sum_of_changes": sum(i["change"] for i in items)}


def _ratio_contributions(run: _Runner, metric: Metric, dim: str, cur: Period, cmp: Period) -> dict:
    catalog, num, den = _component_catalog(run.catalog, metric)
    sub = _Runner(run.layer, catalog)
    data = sub.at([num, den], cur, cmp, [dim])
    run.sql += sub.sql
    totals = {}
    for p in (cmp, cur):
        n = sum(_num(r[num]) for k, r in data.items() if k[0] == p.label)
        d = sum(_num(r[den]) for k, r in data.items() if k[0] == p.label)
        totals[p.label] = (n, d)
    r0 = totals[cmp.label][0] / totals[cmp.label][1] if totals[cmp.label][1] else None
    items = []
    for v in sorted({k[1] for k in data}):
        n0, d0 = (_num(data.get((cmp.label, v), {}).get(x)) for x in (num, den))
        n1, d1 = (_num(data.get((cur.label, v), {}).get(x)) for x in (num, den))
        w0 = d0 / totals[cmp.label][1] if totals[cmp.label][1] else 0.0
        w1 = d1 / totals[cur.label][1] if totals[cur.label][1] else 0.0
        rate0 = n0 / d0 if d0 else None
        rate1 = n1 / d1 if d1 else None
        base = rate0 if rate0 is not None else r0
        # Centered mix effect: moving weight toward a segment above the average helps, below hurts.
        mix = (w1 - w0) * ((base or 0) - (r0 or 0))
        rate = w1 * ((rate1 or 0) - (base or 0)) if w1 else 0.0
        items.append({dim: v, "comparison_rate": rate0, "current_rate": rate1, "comparison_weight": w0,
                      "current_weight": w1, "mix_effect": mix, "rate_effect": rate, "total_effect": mix + rate})
    items.sort(key=lambda i: abs(i["total_effect"]), reverse=True)
    return {"method": "mix_rate", "items": items,
            "mix_effect": sum(i["mix_effect"] for i in items), "rate_effect": sum(i["rate_effect"] for i in items),
            "weights": f"share of {metric.denominator.name}"}


def explain_change(layer, metric: str, period: str | None = None, compare_to: str = "prior_period",
                   grain: str = "month", dimensions: list[str] | None = None, top_n: int = 3) -> dict:
    catalog: Catalog = layer.catalog
    m = catalog.metric(metric)
    first, last = layer.warehouse.month_bounds()
    if grain not in GRAIN_MONTHS:
        raise SemanticError("Grain must be month, quarter or year.")
    cur = parse_period(period, grain) if period else period_containing(last, grain)
    cmp = comparison_period(cur, compare_to)
    if cur.end > last:
        raise SemanticError(f"Data ends {last:%Y-%m}; {cur.label} isn't complete.")
    if cmp.start < first:
        raise SemanticError(f"Data starts {first:%Y-%m}; there's no {cmp.label} to compare {cur.label} with.")

    run = _Runner(layer, catalog)
    head = run.at([m.name], cur, cmp)
    before = head.get((cmp.label,), {}).get(m.name)
    after = head.get((cur.label,), {}).get(m.name)
    if before is None or after is None:
        raise SemanticError(f"No {m.label} value for {cmp.label if before is None else cur.label}.")
    before, after = float(before), float(after)
    change = after - before
    pct = change / abs(before) if before else None
    kind = m.format

    # ------------------------------------------------------------------ drivers
    drivers = None
    if m.name in ROLLFORWARDS:
        parts = ROLLFORWARDS[m.name]
        flows = run.flows_between([p for p, _ in parts], cmp.end, cur.end)
        components = [{"component": p, "label": catalog.metric(p).label, "amount": sign * flows[p]} for p, sign in parts]
        drivers = {"method": "roll-forward",
                   "explanation": f"{m.label} at the end of {cur.label} = {m.label} at the end of {cmp.label} + "
                                  "the flows in between",
                   "components": components,
                   "unexplained": change - sum(c["amount"] for c in components)}
    elif m.name in SUM_OF_PARTS:
        parts = SUM_OF_PARTS[m.name]
        data = run.at(parts, cur, cmp)
        components = [{"component": p, "label": catalog.metric(p).label,
                       "amount": _num(data.get((cur.label,), {}).get(p)) - _num(data.get((cmp.label,), {}).get(p))}
                      for p in parts]
        drivers = {"method": "sum of parts", "explanation": f"change in {m.label} = sum of the changes in its parts",
                   "components": components, "unexplained": change - sum(c["amount"] for c in components)}

    # ------------------------------------------------------------------ contributions by dimension
    allowed = set.intersection(*[set(catalog.models[x].dimensions) for x in m.models])
    dims = [d.lower() for d in (dimensions or list(catalog.dimensions))]
    unknown = [d for d in dims if d not in catalog.dimensions]
    if unknown:
        raise SemanticError(f"Unknown dimension(s) {', '.join(unknown)}. Available: {', '.join(catalog.dimensions)}")
    notes = []
    skipped = [d for d in dims if d not in allowed]
    if skipped:
        notes.append(f"{m.label} is only defined at the company level for: {', '.join(skipped)}.")
    contributions = {}
    for d in (d for d in dims if d in allowed):
        if m.type == "ratio":
            contributions[d] = _ratio_contributions(run, m, d, cur, cmp)
        else:
            c = _additive_contributions(run, m, d, cur, cmp, change)
            if abs(c["sum_of_changes"] - change) > 0.5:
                notes.append(f"{d} values don't sum to the company total (difference "
                             f"{fmt(change - c['sum_of_changes'], kind)}); a customer may map to no {d}.")
            contributions[d] = c

    # ------------------------------------------------------------------ facts
    direction = "up" if change > 0 else "down" if change < 0 else "flat"
    pct_text = f" ({pct:+.1%})" if pct is not None and kind != "percent" else ""
    size = f"{abs(change) * 100:.1f} pts" if kind == "percent" else fmt(abs(change), kind)
    facts = [f"{m.label} was {fmt(after, kind)} in {cur.label}, {direction} {size}{pct_text} "
             f"from {fmt(before, kind)} in {cmp.label}."]
    if drivers:
        parts_text = ", ".join(f"{c['label']} {fmt(c['amount'], kind, True)}" for c in drivers["components"]
                               if abs(c["amount"]) >= 0.5)
        residual = drivers["unexplained"]
        facts.append(f"Drivers ({drivers['method']}): {parts_text}. "
                     + ("These fully explain the change." if abs(residual) < 0.5
                        else f"Unexplained: {fmt(residual, kind, True)}."))
        if change:
            biggest = max(drivers["components"], key=lambda c: abs(c["amount"]))
            facts.append(f"The largest driver was {biggest['label']} at {fmt(biggest['amount'], kind, True)}.")
    for d, c in contributions.items():
        key = "change" if c["method"] == "additive" else "total_effect"
        top = [i for i in c["items"] if abs(i[key]) >= (0.5 if kind != "percent" else 5e-5)][:top_n]
        if not top:
            continue
        if c["method"] == "additive":
            facts.append(f"By {d}: " + "; ".join(
                f"{i[d]} {fmt(i['change'], kind, True)}"
                + (f" ({i['share_of_change']:.0%} of the change)" if i["share_of_change"] is not None else "")
                for i in top) + ".")
            offsets = [i for i in c["items"] if change and i["change"] * change < 0]
            if offsets:
                o = offsets[0]
                facts.append(f"Largest offset by {d}: {o[d]} moved the other way, {fmt(o['change'], kind, True)}.")
        else:
            facts.append(f"By {d}: mix shift {fmt(c['mix_effect'], kind, True)}, rate change within each {d} "
                         f"{fmt(c['rate_effect'], kind, True)}. Largest: " + "; ".join(
                             f"{i[d]} {fmt(i['total_effect'], kind, True)} "
                             f"(rate {fmt(i['comparison_rate'], kind)} to {fmt(i['current_rate'], kind)})" for i in top) + ".")

    return {
        "metric": m.name, "label": m.label, "definition": m.description, "format": kind,
        "certified": m.certified,
        "period": cur.label, "compared_to": cmp.label, "comparison": compare_to,
        "current_value": after, "comparison_value": before, "change": change, "change_pct": pct,
        "drivers": drivers, "contributions": contributions,
        "facts": facts, "notes": notes,
        "commentary_guidance": ("Write commentary only from these facts and numbers. Lead with the change and "
                                "its largest driver, name the biggest offset, and don't speculate about causes "
                                "the data doesn't show; ask the metric owner instead."),
        "sql": run.sql, "data_window": layer._window(),
    }
