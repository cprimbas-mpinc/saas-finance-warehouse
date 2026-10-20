"""Compile a semantic query (metrics x dimensions x time) into one parameterized DuckDB SQL statement.

Only names declared in the catalog ever reach the SQL text; every user-supplied value (dates,
filter values) is passed as a bound parameter. That's what makes it safe to put an LLM in front.

Aggregation happens in two passes per semantic model:
  1. within each month: the measure's `agg` (sum, count_distinct, ...)
  2. months -> requested grain: the measure's `time_agg`
       sum   for flows (new ARR, revenue)
       last  for balances (ARR, customers, deferred revenue) = the value in the period's last month
       first for opening balances (beginning ARR)
Ratios are computed after both passes from the rolled-up numerator and denominator, never averaged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .catalog import Catalog, Measure, SemanticError

GRAINS = ("month", "quarter", "year")
MAX_LIMIT = 5000


@dataclass
class SemanticQuery:
    metrics: list[str]
    group_by: list[str] = field(default_factory=list)
    grain: str = "month"
    start: date | None = None          # first month included (first-of-month)
    end: date | None = None            # last month included (first-of-month)
    filters: dict[str, list[str]] = field(default_factory=dict)
    limit: int = 500

    def describe(self) -> str:
        parts = [", ".join(self.metrics)]
        if self.group_by:
            parts.append("by " + ", ".join(self.group_by))
        parts.append(f"{self.grain}ly from {self.start:%Y-%m} to {self.end:%Y-%m}" if self.start and self.end
                     else f"by {self.grain}")
        if self.filters:
            parts.append("where " + "; ".join(f"{k} in ({', '.join(v)})" for k, v in self.filters.items()))
        return ", ".join(parts)


@dataclass
class CompiledQuery:
    sql: str
    params: list
    columns: list[dict]   # [{name, kind: period|dimension|metric, format?}]


def _q(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _agg(measure: Measure) -> str:
    if measure.agg == "count_distinct":
        return f"count(distinct {measure.expr})"
    return f"{measure.agg}({measure.expr})"


def _time_agg(measure: Measure) -> str:
    col = _q(measure.column)
    return {"sum": f"sum({col})", "last": f"arg_max({col}, _month)", "first": f"arg_min({col}, _month)"}[measure.time_agg]


def _period_label(grain: str) -> str:
    return {
        "month": "strftime(period_start, '%Y-%m')",
        "quarter": "cast(year(period_start) as varchar) || '-Q' || cast(quarter(period_start) as varchar)",
        "year": "cast(year(period_start) as varchar)",
    }[grain]


def compile_query(catalog: Catalog, q: SemanticQuery) -> CompiledQuery:
    if not q.metrics:
        raise SemanticError("Ask for at least one metric.")
    if q.grain not in GRAINS:
        raise SemanticError(f"Grain must be one of {', '.join(GRAINS)}")
    if q.start is None or q.end is None or q.start > q.end:
        raise SemanticError("A valid start and end month are required (start <= end).")
    metrics = [catalog.metric(m) for m in dict.fromkeys(m.lower() for m in q.metrics)]
    group_by = list(dict.fromkeys(d.lower() for d in q.group_by))
    for dim in group_by + list(q.filters):
        if dim not in catalog.dimensions:
            raise SemanticError(f"Unknown dimension '{dim}'. Available: {', '.join(catalog.dimensions)}")

    # Measures needed, grouped by the semantic model that owns them.
    by_model: dict[str, list[Measure]] = {}
    for metric in metrics:
        for measure in metric.measures:
            if measure not in by_model.setdefault(measure.model, []):
                by_model[measure.model].append(measure)

    params: list = []
    ctes = []
    for model_name, measures in by_model.items():
        model = catalog.models[model_name]
        unsupported = [d for d in group_by + list(q.filters) if d not in model.dimensions]
        if unsupported:
            names = [m.name for m in metrics if model_name in m.models]
            raise SemanticError(f"{', '.join(names)} can't be split or filtered by {', '.join(unsupported)}; "
                                f"it is only defined at the company level.")
        dims = ", ".join(_q(d) for d in group_by)
        where = [f"{_q(model.time_column)} between ? and ?"]
        params += [q.start, q.end]
        for dim, values in q.filters.items():
            if not values:
                raise SemanticError(f"Filter on '{dim}' has no values")
            where.append(f"{_q(dim)} in ({', '.join('?' for _ in values)})")
            params += list(values)
        inner = (f"select {_q(model.time_column)} as _month{', ' + dims if dims else ''}, "
                 + ", ".join(f"{_agg(m)} as {_q(m.column)}" for m in measures)
                 + f" from {_q(model.table)} where {' and '.join(where)} group by all")
        outer = (f"select cast(date_trunc('{q.grain}', _month) as date) as period_start{', ' + dims if dims else ''}, "
                 + ", ".join(f"{_time_agg(m)} as {_q(m.column)}" for m in measures)
                 + f" from ({inner}) group by all")
        ctes.append((model_name, outer))

    keys = ", ".join(["period_start"] + [_q(d) for d in group_by])
    from_clause = _q(ctes[0][0])
    for name, _ in ctes[1:]:
        from_clause += f" full outer join {_q(name)} using ({keys})"

    select_cols = [f"{_period_label(q.grain)} as period"] + [_q(d) for d in group_by]
    columns = [{"name": "period", "kind": "period"}] + [{"name": d, "kind": "dimension"} for d in group_by]
    for metric in metrics:
        if metric.type == "ratio":
            expr = f"cast({_q(metric.numerator.column)} as double) / nullif({_q(metric.denominator.column)}, 0)"
        else:
            expr = _q(metric.measure.column)
        select_cols.append(f"{expr} as {_q(metric.name)}")
        columns.append({"name": metric.name, "kind": "metric", "format": metric.format, "label": metric.label})

    limit = max(1, min(int(q.limit), MAX_LIMIT))
    sql = ("with " + ", ".join(f"{_q(name)} as ({body})" for name, body in ctes)
           + f" select {', '.join(select_cols)} from {from_clause}"
           + f" order by period_start{', ' + ', '.join(_q(d) for d in group_by) if group_by else ''} limit {limit}")
    return CompiledQuery(sql=sql, params=params, columns=columns)
