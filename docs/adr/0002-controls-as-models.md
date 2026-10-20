# 0002 · Controls are models that return exception rows

**Status:** Accepted · 2026-10-19

## Context
SOX-style controls are usually spreadsheets and screenshots assembled at quarter end. dbt tests can express checks, but a test result is pass/fail: the exceptions themselves aren't queryable afterward.

## Decision
Each control is a dbt model under `models/controls/` that returns only exception rows, with a stable `exception_key`. A warn-severity test on each model reports findings without failing the build. `ctl_summary` rolls up counts, and `scripts/build_evidence.py` writes the evidence package.

## Consequences
- Exceptions are data: they can be exported, tracked to resolution and served through the MCP server.
- A control finding something doesn't break the pipeline, which matches how close works: findings are investigated, not blocking.
- Data-integrity tests (keys, schedules summing to invoices) stay error-severity, because those mean the pipeline itself is wrong.
- The control set is tested for design: on seeded data each control must catch exactly its planted error.
