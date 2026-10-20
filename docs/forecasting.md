# ARR forecast

`python -m finance_semantic forecast [months]` · MCP tool `forecast_arr` · code: [`finance_semantic/forecast.py`](../finance_semantic/forecast.py)

## What it forecasts

The ARR **bridge**, not just ending ARR, because the bridge is what Finance plans against and what a CFO will ask about ("how much of that is new logos versus expansion?"):

```
ending ARR = beginning ARR + new + reactivation + expansion + contraction + churn
```

Every input is a governed metric from the semantic layer (`query_metrics` on the ARR bridge), so the forecast starts from the same certified history as the board numbers. Each forecast month's beginning ARR is the prior month's forecast ending ARR, and the first month starts from the last actual month.

## Method

Drivers come from a trailing window (default 6 months, allowed 3 to 12):

| Bridge line | Driver | Why |
|---|---|---|
| New, reactivation | Average dollars per month | New-logo ARR depends on sales capacity, not on the size of the base |
| Expansion, contraction, churn | Average monthly rate on beginning ARR | These scale with the installed base |

Then the bridge is rolled forward month by month.

## Is it any good? The backtest

A forecast with no accuracy record is an opinion. The model is scored with a **rolling-origin backtest**: from every month with at least 12 months of history, forecast up to 6 months ahead using only the data available then, and compare with what actually happened. The same is done for a naive baseline: a least-squares straight line through the same trailing window of ending ARR. The model only earns trust where it beats doing nothing clever.

Results on the demo data (36 months, last actual 2025-12):

| Horizon | Origins | Driver MAPE | Naive MAPE | Driver bias |
|---|---|---|---|---|
| +1 month | 23 | 2.1% | 2.3% | -0.3% |
| +2 months | 22 | 2.9% | 3.3% | -1.1% |
| +3 months | 21 | 3.8% | 4.2% | -1.8% |
| +4 months | 20 | 4.5% | 4.5% | -2.8% |
| +5 months | 19 | 4.7% | 4.9% | -3.7% |
| +6 months | 18 | 5.0% | 4.9% | -4.5% |

The honest reading:

- **The driver model is modestly better than a straight line out to about 5 months, and no better at 6.** The edge is small. Its real advantage is that it explains the number: a planner can change the new-ARR assumption or the churn rate and see what moves.
- **It under-forecasts, and the bias grows with the horizon.** Quarterly new-logo ARR more than doubled over the three years of history, and a trailing average always lags a rising series. The fix belongs in the inputs (a sales-capacity or pipeline driver for new ARR), not in a fudge factor.
- **Small sample.** 18 to 23 origins over overlapping windows is enough to compare two methods, not enough for confident statistics.

## The range

The low and high values are the 10th and 90th percentiles of the backtest's own errors at each horizon, applied to the point forecast (`actual = forecast / (1 + error)`), rather than an assumed normal distribution. Because the model has run low historically, the range is skewed upward. It always contains the point forecast. It is an empirical band, not a statistical guarantee.

## What it doesn't know

- Pipeline, bookings or sales capacity: new ARR is a trailing average.
- Seasonality: there isn't enough history to estimate it honestly.
- Known events: price changes, a large renewal at risk, a product launch.

That's why the output is marked `certified: false` and the MCP server tells assistants to present it as a projection with its assumptions, not as a reported number.

## How it would grow in production

Replace the new-ARR driver with pipeline × win rate by segment, add renewal-cohort churn from contract end dates, and keep the backtest running each close so the accuracy record is always current.
