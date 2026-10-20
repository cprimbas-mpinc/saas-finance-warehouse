# Changelog

## Unreleased

- **ARR forecast:** driver-based forecast of the ARR bridge (`python -m finance_semantic forecast`, MCP tool `forecast_arr`) with a rolling-origin backtest against a straight-line trend and ranges from the backtest's own errors. The metrics snapshot now carries the forecast and its track record. See `docs/forecasting.md`.
- **Control exception log:** `rpt_control_exception_log` tracks each control finding to an owner, root cause, status and due date, flags unassigned and overdue items, and is surfaced in the evidence package and `get_control_status`. Controls are registered once in a single macro.
- **Catalog governance:** `python -m finance_semantic lint` checks owners, descriptions, synonym collisions, time roll-up rules and resolver round-trips; CI fails on any finding.
- **Engineering:** ruff linting, `pyproject.toml`, CI on Python 3.10 to 3.12 with the evidence package uploaded as a build artifact, and four architecture decision records in `docs/adr/`.

## 0.2.0 (2026-10-20)

- **Semantic layer:** 19 governed metrics across ARR, retention, revenue, billings, deferred revenue and GL reconciliation, defined in `semantic_layer/metrics.yml`, with explicit time roll-ups (flows sum, balances take period-end) and ratio metrics computed from rolled-up parts.
- **Curated saved queries:** ARR bridge, board KPI scorecard, retention by segment, segment mix, revenue tie-out, billings vs revenue.
- **Plain-English resolver:** deterministic question → metric/dimension/time mapping that reports how it read the question.
- **MCP server:** 8 read-only tools (`ask`, `list_metrics`, `describe_metric`, `query_metrics`, `list_saved_queries`, `run_saved_query`, `get_control_status`, `run_sql`) over a sandboxed, read-only warehouse connection.
- **CLI:** `python -m finance_semantic ask "..."`.
- New marts `fct_customer_retention_pairs` and `fct_billings`; region and industry on the MRR and revenue facts; staging materialized as tables so the built warehouse is self-contained.
- Test suite grows from 9 to 46 tests.

## 0.1.0 (2026-10-19)

- dbt + DuckDB warehouse: ARR bridge, cohort NRR/GRR, ratable revenue, deferred revenue roll-forward, subledger-to-GL reconciliation.
- Eight SOX-style controls as code with generated evidence, and tests proving each catches its planted error and nothing else.
