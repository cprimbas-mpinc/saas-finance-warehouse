"""MCP server: exposes the governed finance semantic layer to any MCP client (Claude Desktop, Claude
Code, other agents). Every tool is read-only.

Run:  python mcp_server.py            (stdio, for Claude Desktop / Claude Code)
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from .catalog import SemanticError
from .service import FinanceSemanticLayer

logging.basicConfig(level=logging.WARNING)  # stdio transport: never print to stdout

INSTRUCTIONS = """\
You are connected to the finance data warehouse for Halyard Software, Inc. (synthetic data), a B2B SaaS
company. Every number comes from governed metric definitions in a semantic layer.

How to answer finance questions:
1. For a plain-English question, call `ask` first. Report its `question_as_understood` so the user can
   check the interpretation, and any `notes`.
2. If `ask` can't resolve it, or you need finer control, call `list_metrics`, then `query_metrics`.
3. For recurring views (ARR bridge, board KPIs, revenue tie-out) use `run_saved_query`.
4. For "do the numbers tie?" or SOX / control questions, call `get_control_status`.
5. Use `run_sql` only for questions no metric covers, and say the result is uncertified.
State the metric definition when it matters to the answer. If the user asks how a number was computed,
show the returned SQL. Contraction and churn are negative numbers; NRR and GRR are ratios (1.05 = 105%).
"""

mcp = MCPServer("saas-finance-warehouse", instructions=INSTRUCTIONS, version="0.2.0")
READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)


@lru_cache(maxsize=1)
def layer() -> FinanceSemanticLayer:
    return FinanceSemanticLayer()


def _safe(fn, *args, **kwargs) -> dict[str, Any]:
    try:
        return fn(*args, **kwargs)
    except (SemanticError, FileNotFoundError) as e:
        return {"error": str(e)}


@mcp.tool(annotations=READ_ONLY)
def ask(question: str) -> dict[str, Any]:
    """Answer a plain-English finance question ("ARR by segment last 6 months", "NRR in Q3 2025",
    "does revenue tie to the GL?") using governed metric definitions. Returns the interpretation,
    the result rows, definitions, and the SQL that produced them."""
    return _safe(layer().ask, question)


@mcp.tool(annotations=READ_ONLY)
def list_metrics() -> dict[str, Any]:
    """List every governed metric with its definition, format, owner, the dimensions it can be split
    by, and its synonyms; plus available dimensions, time grains, and the data window."""
    return _safe(layer().list_metrics)


@mcp.tool(annotations=READ_ONLY)
def describe_metric(metric: str) -> dict[str, Any]:
    """Full definition of one metric: formula, source tables, owner, certification and example SQL."""
    return _safe(layer().describe_metric, metric)


@mcp.tool(annotations=READ_ONLY)
def query_metrics(metrics: list[str], group_by: list[str] | None = None, grain: str = "month",
                  start: str | None = None, end: str | None = None, last_n_periods: int | None = None,
                  filters: dict[str, list[str]] | None = None, limit: int = 500) -> dict[str, Any]:
    """Structured metric query. metrics: names from list_metrics. group_by: dimensions (segment,
    region, industry). grain: month | quarter | year. start/end: YYYY-MM (inclusive), or last_n_periods
    to count back from the latest month. filters: {dimension: [values]}."""
    return _safe(layer().query_metrics, metrics=metrics, group_by=group_by, grain=grain, start=start,
                 end=end, last_n_periods=last_n_periods, filters=filters, limit=limit)


@mcp.tool(annotations=READ_ONLY)
def list_saved_queries() -> dict[str, Any]:
    """List curated, recurring views (ARR bridge, board KPIs, retention by segment, revenue tie-out...)."""
    return _safe(layer().list_saved_queries)


@mcp.tool(annotations=READ_ONLY)
def run_saved_query(name: str, start: str | None = None, end: str | None = None) -> dict[str, Any]:
    """Run a curated view by name. Optional start/end (YYYY-MM) override its default window."""
    return _safe(layer().run_saved_query, name, start=start, end=end)


@mcp.tool(annotations=READ_ONLY)
def get_control_status(include_exceptions: bool = True) -> dict[str, Any]:
    """SOX-style control results from the latest build: each control's objective, owner, PASS or
    EXCEPTION, and the exception detail to investigate."""
    return _safe(layer().control_status, include_exceptions=include_exceptions)


@mcp.tool(annotations=READ_ONLY)
def run_sql(sql: str, limit: int = 200) -> dict[str, Any]:
    """Escape hatch: one read-only SELECT against the warehouse (sandboxed: no writes, no file or network
    access). Results are uncertified; prefer query_metrics for any number that will be reported."""
    return _safe(layer().run_sql, sql, limit=limit)


def main() -> None:
    mcp.run("stdio")


if __name__ == "__main__":
    main()
