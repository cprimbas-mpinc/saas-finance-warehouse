"""The semantic layer's public API: what the MCP server and the CLI both call.

Every answer carries its own audit trail: the interpretation of the question, the governed
definitions used, the exact SQL with its parameters, and the data's freshness.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb
import yaml

from .catalog import ROOT, Catalog, SemanticError, load_catalog
from .compiler import SemanticQuery, compile_query
from .nl import period_window, resolve
from .warehouse import Warehouse

MAX_SQL_ROWS = 1000


def parse_month(value: str | date | None) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value.replace(day=1)
    text = str(value).strip()
    for fmt_len in (7, 10):
        try:
            parts = [int(p) for p in text[:fmt_len].split("-")]
            return date(parts[0], parts[1], 1)
        except (ValueError, IndexError):
            continue
    raise SemanticError(f"Couldn't read '{value}' as a month. Use YYYY-MM.")


class FinanceSemanticLayer:
    def __init__(self, warehouse_path: Path | str | None = None, semantic_dir: Path | None = None):
        self.catalog: Catalog = load_catalog(semantic_dir) if semantic_dir else load_catalog()
        self.warehouse = Warehouse(warehouse_path)

    # ------------------------------------------------------------------ catalog
    def list_metrics(self) -> dict:
        return {
            "metrics": [{
                "name": m.name, "label": m.label, "description": m.description, "format": m.format,
                "certified": m.certified, "owner": m.owner,
                "dimensions": sorted(set.intersection(*[set(self.catalog.models[x].dimensions) for x in m.models])),
                "synonyms": list(m.synonyms),
            } for m in self.catalog.metrics.values()],
            "dimensions": self.catalog.dimensions,
            "grains": ["month", "quarter", "year"],
            "data_window": self._window(),
        }

    def describe_metric(self, name: str) -> dict:
        m = self.catalog.metric(name)
        _, last = self.warehouse.month_bounds()
        compiled = compile_query(self.catalog, SemanticQuery(metrics=[m.name], start=last, end=last))
        return {
            "name": m.name, "label": m.label, "description": m.description, "type": m.type,
            "formula": m.formula(), "format": m.format, "owner": m.owner, "certified": m.certified,
            "synonyms": list(m.synonyms),
            "source_tables": sorted({self.catalog.models[x].table for x in m.models}),
            "example_sql": compiled.sql, "example_params": [str(p) for p in compiled.params],
            "definition_doc": "docs/metric_definitions.md",
        }

    # ------------------------------------------------------------------ queries
    def query_metrics(self, metrics: list[str], group_by: list[str] | None = None, grain: str = "month",
                      start: str | None = None, end: str | None = None, last_n_periods: int | None = None,
                      filters: dict[str, list[str] | str] | None = None, limit: int = 500) -> dict:
        first, last = self.warehouse.month_bounds()
        notes = []
        if last_n_periods:
            s, e = period_window(last, grain, int(last_n_periods))
        else:
            s, e = parse_month(start) or first, parse_month(end) or last
        if s < first:
            notes.append(f"Data starts {first:%Y-%m}; start moved to fit.")
            s = first
        if e > last:
            notes.append(f"Data ends {last:%Y-%m}; end moved to fit.")
            e = last
        clean_filters = {k.lower(): ([v] if isinstance(v, str) else list(v)) for k, v in (filters or {}).items()}
        q = SemanticQuery(metrics=list(metrics), group_by=list(group_by or []), grain=grain, start=s, end=e,
                          filters=clean_filters, limit=limit)
        return self._run(q, notes)

    def _run(self, q: SemanticQuery, notes: list[str] | None = None, interpretation: dict | None = None) -> dict:
        compiled = compile_query(self.catalog, q)
        rows = self.warehouse.records(compiled.sql, compiled.params)
        notes = list(notes or [])
        if q.grain != "month" and q.end and q.end.month % (3 if q.grain == "quarter" else 12) != 0:
            notes.append(f"The last {q.grain} is partial (data ends {q.end:%Y-%m}); balances show that month's value.")
        metrics = [self.catalog.metric(m) for m in q.metrics]
        return {
            "question_as_understood": interpretation or {"query": q.describe()},
            "columns": compiled.columns,
            "rows": rows,
            "row_count": len(rows),
            "definitions": {m.name: m.description for m in metrics},
            "certified": all(m.certified for m in metrics),
            "notes": notes,
            "sql": compiled.sql,
            "params": [str(p) for p in compiled.params],
            "data_window": self._window(),
        }

    # ------------------------------------------------------------------ saved queries
    def list_saved_queries(self) -> dict:
        return {"saved_queries": [{"name": s.name, "title": s.title, "description": s.description,
                                   "example_phrases": list(s.phrases)} for s in self.catalog.saved_queries.values()]}

    def run_saved_query(self, name: str, start: str | None = None, end: str | None = None) -> dict:
        if name not in self.catalog.saved_queries:
            raise SemanticError(f"Unknown saved query '{name}'. Available: {', '.join(self.catalog.saved_queries)}")
        sq = self.catalog.saved_queries[name]
        spec = dict(sq.query)
        if start or end:
            spec.pop("last_n_periods", None)
        result = self.query_metrics(metrics=spec["metrics"], group_by=spec.get("group_by"),
                                    grain=spec.get("grain", "month"), start=start, end=end,
                                    last_n_periods=spec.get("last_n_periods"), filters=spec.get("filters"))
        result["question_as_understood"] = {"saved_query": name, "title": sq.title, "description": sq.description,
                                            "query": result["question_as_understood"]["query"]}
        return result

    # ------------------------------------------------------------------ natural language
    def ask(self, question: str) -> dict:
        bounds = self.warehouse.month_bounds()
        dims = {d: self.warehouse.dimension_values(d) for d in self.catalog.dimensions}
        r = resolve(question, self.catalog, bounds, dims)
        interpretation = {"question": question, "matched": r.matched, "ignored_words": r.ignored}

        if r.kind == "controls":
            return {"question_as_understood": interpretation, **self.control_status()}
        if r.kind == "unresolved":
            return {"question_as_understood": interpretation, "rows": [], "notes": r.notes,
                    "hint": "Try naming a metric, e.g. 'ARR by segment last 6 months' or 'NRR in Q3 2025'."}
        if r.kind == "saved_query":
            start = f"{r.start:%Y-%m}" if r.start else None
            end = f"{r.end:%Y-%m}" if r.end else None
            result = self.run_saved_query(r.saved_query, start=start, end=end)
            result["question_as_understood"].update(interpretation)
            result["notes"] = r.notes + result["notes"]
            return result

        q = SemanticQuery(metrics=r.metrics, group_by=r.group_by, grain=r.grain, start=r.start, end=r.end,
                          filters=r.filters)
        interpretation["query"] = q.describe()
        return self._run(q, notes=r.notes, interpretation=interpretation)

    # ------------------------------------------------------------------ controls
    def control_status(self, include_exceptions: bool = True, max_exceptions: int = 25) -> dict:
        matrix = yaml.safe_load((ROOT / "controls" / "control_matrix.yml").read_text())["controls"]
        summary = {row["control_id"]: row for row in self.warehouse.records("select * from ctl_summary")}
        controls = []
        for ctl in matrix:
            s = summary.get(ctl["id"], {})
            entry = {"control_id": ctl["id"], "name": ctl["name"], "result": s.get("result"),
                     "exception_count": s.get("exception_count"), "objective": ctl["objective"],
                     "owner": ctl["owner"], "frequency": ctl["frequency"]}
            if include_exceptions and s.get("exception_count"):
                entry["exceptions"] = self.warehouse.records(
                    f'select * exclude (exception_key) from "{ctl["model"]}" limit {int(max_exceptions)}')
            controls.append(entry)
        log = self.warehouse.records(
            "select * from rpt_control_exception_log order by is_overdue desc, control_id, exception_key")
        open_items = [e for e in log if e["status"] in ("unassigned", "open", "investigating")]
        passed = sum(1 for c in controls if c["result"] == "PASS")
        return {"controls": controls,
                "summary": f"{passed} of {len(controls)} controls passed; {len(open_items)} exception(s) still open, "
                           f"{sum(1 for e in open_items if e['is_overdue'])} overdue, "
                           f"{sum(1 for e in open_items if e['status'] == 'unassigned')} awaiting triage",
                "exception_log": log,
                "data_window": self._window()}

    # ------------------------------------------------------------------ escape hatch
    def run_sql(self, sql: str, limit: int = 200) -> dict:
        statements = duckdb.extract_statements(sql)
        if len(statements) != 1 or statements[0].type != duckdb.StatementType.SELECT:
            raise SemanticError("Only a single read-only SELECT statement is allowed.")
        limit = max(1, min(int(limit), MAX_SQL_ROWS))
        body = statements[0].query.strip().rstrip(";")
        rows = self.warehouse.records(f"select * from ({body}) limit {limit}")
        return {"rows": rows, "row_count": len(rows), "certified": False,
                "notes": ["Ad-hoc SQL: not a governed metric definition. Prefer query_metrics for reported numbers."],
                "sql": body}

    def _window(self) -> dict:
        first, last = self.warehouse.month_bounds()
        return {"first_month": f"{first:%Y-%m}", "last_month": f"{last:%Y-%m}", "built_at": self.warehouse.built_at()}
