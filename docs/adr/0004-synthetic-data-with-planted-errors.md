# 0004 · Synthetic data with a manifest of planted errors

**Status:** Accepted · 2026-10-19

## Context
A public portfolio can't use real financial data. Controls are only convincing if you can see them catch something.

## Decision
`scripts/generate_data.py` builds a deterministic synthetic company (seeded RNG) and, by default, plants specific, realistic errors, recording each one in `seeded_exceptions.json`. A `--clean` mode builds the same company with nothing planted.

## Consequences
- Tests can assert exact outcomes: every planted error caught by its control, nothing else flagged; clean data passes everything.
- Billing errors are planted before the GL is generated, so they flow through to the ledger the way real errors do.
- The data is simpler than reality (monthly service periods, one currency). Those limits are documented in `docs/metric_definitions.md` and the roadmap.
