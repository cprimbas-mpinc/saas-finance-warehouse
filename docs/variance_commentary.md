# Explaining a change: grounded input for variance commentary

`python -m finance_semantic explain <metric>` · MCP tool `explain_change` · code: [`finance_semantic/explain.py`](../finance_semantic/explain.py) · decision record: [ADR 0005](adr/0005-decompose-before-commentary.md)

Every close, someone writes "ARR grew X, driven by Y, partly offset by Z." This tool does the arithmetic behind that sentence from governed definitions, so the person (or the model) writing it starts from facts that tie.

## What it returns

| Part | What it is | How it reconciles |
|---|---|---|
| Headline | The metric in both periods, the change and % change | Same numbers as `query_metrics` |
| Drivers | **Roll-forward** for balances: ARR = prior ARR + new + reactivation + expansion + contraction + churn; deferred revenue = prior + billings − recognized revenue. **Sum of parts** for net new ARR. | `unexplained` is reported and is $0 when the bridge foots |
| Contributions | Each segment, region and industry's share of the change | Additive metrics: contributions sum to the change |
| Mix vs rate | For ratios (NRR, GRR, ARPA): how much came from the weights shifting between segments, and how much from changes within each segment | Mix + rate equals the change exactly |
| Facts | Short sentences built only from the numbers above | Every number in them comes from the decomposition |
| SQL | Every query that produced a number | Compiled from the catalog, parameters bound |

Compare with the prior period (default) or the same period last year, at month, quarter or year grain:

```
python -m finance_semantic explain arr
python -m finance_semantic explain arr --period 2025-Q4 --vs prior_year
python -m finance_semantic explain nrr --grain quarter --by segment
python -m finance_semantic explain deferred_revenue --json
```

## The mix/rate split

For a ratio R = Σ wᵢ·rᵢ, where wᵢ is segment i's share of the denominator and rᵢ is its own ratio:

```
ΔR = Σ (w₁ᵢ − w₀ᵢ)·(r₀ᵢ − R₀)   mix: weight moving toward segments above (or below) the old average
   + Σ  w₁ᵢ·(r₁ᵢ − r₀ᵢ)        rate: change within each segment, at today's weights
```

The two terms add to the change exactly. A segment that didn't exist in the comparison period is valued at the old average, so it contributes no mix effect and its whole effect shows up as rate.

## Worked example: ARR, December 2025

```
$ python -m finance_semantic explain arr
- ARR was $13,280,400 in 2025-12, up $296,400 (+2.3%) from $12,984,000 in 2025-11.
- Drivers (roll-forward): New ARR +$306,000, Expansion ARR +$70,200, Contraction ARR -$19,800, Churned ARR -$60,000. These fully explain the change.
- The largest driver was New ARR at +$306,000.
- By segment: Mid-Market +$195,000 (66% of the change); SMB +$101,400 (34% of the change).
- By region: North America +$149,400 (50% of the change); EMEA +$123,000 (41% of the change); APAC +$24,000 (8% of the change).
- By industry: Healthcare +$143,400 (48% of the change); Education +$70,200 (24% of the change); Logistics +$43,200 (15% of the change).
- Largest offset by industry: Retail moved the other way, -$11,400.
```

An example draft written only from those facts:

> ARR closed December at $13.28M, up $296K (+2.3%) on November. New logos added $306K and expansion $70K, partly offset by $60K of churn and $20K of contraction. Mid-Market drove two-thirds of the growth and SMB the rest; Enterprise ARR was flat. Retail was the only industry to shrink (−$11K).

Everything in that paragraph can be checked against a fact. What it doesn't say is *why* Retail shrank. The data can't answer that, so the commentary shouldn't guess.

## Worked example: a mix effect

```
$ python -m finance_semantic explain arpa --by segment
- ARR per customer was $44,715 in 2025-12, down $843 (-1.8%) from $45,558 in 2025-11.
- By segment: mix shift -$962, rate change within each segment +$120. Largest: Enterprise -$638 (rate $206,186 to $206,186); SMB -$321 (rate $12,020 to $11,978); Mid-Market +$116 (rate $50,904 to $51,292).
```

A naive reading says ARPA fell 1.8%, so pricing or discounting is getting worse. The decomposition says the opposite: ARPA *rose* $120 within segments, and the decline is entirely mix, because the month added smaller customers and Enterprise's share of the base fell. Enterprise ARPA didn't move at all. That distinction changes the conversation in a business review, and a test (`test_arpa_decline_is_mix_not_price`) holds the tool to it.

## Limits

- Drivers exist only where a definition declares an identity (a roll-forward or sum of parts). Ratios get mix/rate by dimension, not a driver bridge.
- Contributions are one dimension at a time. Segment × region interactions aren't split out.
- It explains *where* a change came from, never *why*. Causes belong to the people who own the accounts.
