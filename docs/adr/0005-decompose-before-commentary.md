# 0005 · Decompose the change deterministically before any model writes commentary

**Status:** Accepted · 2026-10-20

## Context
Variance commentary ("ARR grew $296K, mostly Mid-Market new logos, partly offset by churn") is one of the most requested uses of LLMs in Finance, and one of the riskiest. Asked to explain a movement from raw numbers, a model does arithmetic in its head, picks drivers that sound right, and fills gaps with plausible causes. The draft reads well and doesn't tie.

## Decision
Split the work. `explain_change` does every calculation in code from governed definitions: the change, the roll-forward or sum-of-parts drivers, additive contributions by dimension, and an exact mix/rate split for ratios. It returns short factual sentences built from those numbers, plus the SQL. The model's job is narrower: choose emphasis and write prose from the facts. The MCP server's instructions tell it not to add causes the data doesn't show.

## Consequences
- Every number in the commentary traces to a fact, and every fact traces to SQL. A reviewer checks the facts once instead of re-deriving each sentence.
- Decompositions are tested to reconcile exactly (bridges foot, contributions sum, mix + rate equals the change), so a draft can't be built on a decomposition that doesn't add up.
- The tool says *where* the change came from, not *why*. "Retail contracted" is a fact; "Retail contracted because of tariffs" is a question for the account owner. That limit is deliberate.
- New metrics only get drivers when someone declares a roll-forward or sum-of-parts identity for them, which is a definition decision, not a model's guess.
