# 0003 · A governed semantic layer, not text-to-SQL, behind the AI interface

**Status:** Accepted · 2026-10-20

## Context
People want to ask finance questions in plain English, and LLMs make that easy to build. The easy build is an LLM writing SQL against warehouse tables. In finance that fails quietly: summing a balance across a quarter, averaging ratios, double counting through a join. Each produces a plausible wrong number.

## Decision
Separate language from math. Metric definitions live in `semantic_layer/metrics.yml` with explicit aggregation and time roll-up rules. A compiler turns a structured request into parameterized SQL using only catalog names. The language layer (the built-in resolver, or an LLM client over MCP) only chooses metrics, dimensions and time windows.

## Consequences
- The answer to "ARR last quarter" is the same in the board deck, the CLI and a chat with Claude.
- Every response carries its interpretation, definitions and SQL, so a person can audit it.
- User input never reaches SQL text, which removes injection risk even with an LLM in the loop.
- Questions outside the catalog aren't answered by default. `run_sql` exists as a labeled, sandboxed escape hatch, and the right long-term fix is adding the metric.
