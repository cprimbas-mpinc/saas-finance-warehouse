# Architecture Decision Records

Short records of the decisions that shape this project: the context, the choice, and what it costs. New decisions get the next number; superseded ones stay, marked as such, so the reasoning history is preserved.

| # | Decision | Status |
|---|---|---|
| [0001](0001-dbt-and-duckdb.md) | dbt on DuckDB as the reference stack | Accepted |
| [0002](0002-controls-as-models.md) | Controls are models that return exception rows | Accepted |
| [0003](0003-semantic-layer-over-text-to-sql.md) | A governed semantic layer, not text-to-SQL, behind the AI interface | Accepted |
| [0004](0004-synthetic-data-with-planted-errors.md) | Synthetic data with a manifest of planted errors | Accepted |
| [0005](0005-decompose-before-commentary.md) | Decompose the change deterministically before any model writes commentary | Accepted |
