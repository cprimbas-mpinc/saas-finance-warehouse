# 0001 · dbt on DuckDB as the reference stack

**Status:** Accepted · 2026-10-19

## Context
The project has to be runnable by anyone in seconds: a hiring manager, a reviewer, a CI runner. It also has to look like the stack a real finance data team uses.

## Decision
Model in dbt and run on DuckDB, with an in-process database file and no credentials. Keep SQL close to ANSI so it ports to Snowflake or BigQuery.

## Consequences
- Clone-to-results in one command with no accounts; CI runs the full warehouse on every commit.
- dbt gives lineage, tests and documentation conventions that transfer directly to a production team.
- DuckDB-specific syntax (`arg_max`, `qualify`, `generate_series`) would need small edits for other warehouses. That's an accepted cost, isolated to a few models.
- Scale isn't demonstrated here; that's the job of the production notes in the README.
