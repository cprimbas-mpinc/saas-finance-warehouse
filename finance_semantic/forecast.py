"""Driver-based ARR forecast, built on the governed metrics, with an honest backtest.

The model forecasts the ARR bridge, not just the ending number, because that's what Finance
actually plans against:

    ending ARR = beginning ARR + new + reactivation + expansion + contraction + churn

  * new and reactivation ARR: trailing-window average dollars per month
  * expansion, contraction, churn: trailing-window average *rate* on beginning ARR

A naive baseline (straight-line trend on ending ARR over the same trailing window) is backtested
alongside it on rolling origins. Both errors are reported, so the forecast is only trusted to the
extent it beats doing nothing clever. Prediction intervals come from the backtest's own error
distribution by horizon, rather than from an assumed distribution.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .nl import _shift_months

BRIDGE = ["beginning_arr", "new_arr", "reactivation_arr", "expansion_arr", "contraction_arr", "churned_arr", "arr"]
RATE_DRIVERS = ["expansion_arr", "contraction_arr", "churned_arr"]
DOLLAR_DRIVERS = ["new_arr", "reactivation_arr"]


@dataclass
class Month:
    period: date
    values: dict[str, float]


def _drivers(history: list[Month], window: int) -> dict[str, float]:
    recent = history[-window:]
    out = {d: sum(m.values[d] for m in recent) / len(recent) for d in DOLLAR_DRIVERS}
    for d in RATE_DRIVERS:
        rates = [m.values[d] / m.values["beginning_arr"] for m in recent if m.values["beginning_arr"]]
        out[d] = sum(rates) / len(rates) if rates else 0.0
    return out


def driver_forecast(history: list[Month], horizon: int, window: int) -> list[dict]:
    drivers = _drivers(history, window)
    arr = history[-1].values["arr"]
    period = history[-1].period
    rows = []
    for _ in range(horizon):
        period = _shift_months(period, 1)
        row = {"period": period, "beginning_arr": arr}
        for d in DOLLAR_DRIVERS:
            row[d] = drivers[d]
        for d in RATE_DRIVERS:
            row[d] = arr * drivers[d]
        arr = arr + sum(row[d] for d in DOLLAR_DRIVERS + RATE_DRIVERS)
        row["arr"] = arr
        rows.append(row)
    return rows


def naive_forecast(history: list[Month], horizon: int, window: int) -> list[float]:
    """Least-squares straight line through the last `window` ending-ARR values, extended forward."""
    ys = [m.values["arr"] for m in history[-window:]]
    n = len(ys)
    x_mean, y_mean = (n - 1) / 2, sum(ys) / n
    denom = sum((x - x_mean) ** 2 for x in range(n)) or 1.0
    slope = sum((x - x_mean) * (y - y_mean) for x, y in enumerate(ys)) / denom
    intercept = y_mean - slope * x_mean
    return [intercept + slope * (n - 1 + h) for h in range(1, horizon + 1)]


def _quantile(values: list[float], q: float) -> float:
    s = sorted(values)
    if not s:
        return 0.0
    pos = (len(s) - 1) * q
    lo, hi = int(pos), min(int(pos) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def backtest(history: list[Month], horizon: int, window: int, min_train: int = 12) -> dict:
    """Rolling-origin backtest: forecast from every origin with enough history, score against actuals."""
    errors: dict[str, dict[int, list[float]]] = {"driver": {}, "naive": {}}
    origins = range(max(min_train, window), len(history) - 1)
    for origin in origins:
        train, actual = history[:origin + 1], history[origin + 1:origin + 1 + horizon]
        drv = driver_forecast(train, len(actual), window)
        nav = naive_forecast(train, len(actual), window)
        for h, (a, d, n) in enumerate(zip(actual, drv, nav, strict=True), start=1):
            truth = a.values["arr"]
            errors["driver"].setdefault(h, []).append((d["arr"] - truth) / truth)
            errors["naive"].setdefault(h, []).append((n - truth) / truth)
    by_horizon = []
    for h in range(1, horizon + 1):
        d, n = errors["driver"].get(h, []), errors["naive"].get(h, [])
        if not d:
            continue
        by_horizon.append({
            "horizon_months": h,
            "origins_tested": len(d),
            "driver_mape": sum(abs(e) for e in d) / len(d),
            "naive_mape": sum(abs(e) for e in n) / len(n),
            "driver_bias": sum(d) / len(d),
            "p10_error": _quantile(d, 0.10),
            "p90_error": _quantile(d, 0.90),
        })
    return {"origins": len(origins), "by_horizon": by_horizon}


def forecast_arr(layer, months: int = 6, window: int = 6) -> dict:
    """Forecast the ARR bridge `months` ahead from the latest actual month."""
    months = max(1, min(int(months), 12))
    window = max(3, min(int(window), 12))
    first, last = layer.warehouse.month_bounds()
    result = layer.query_metrics(BRIDGE, start=f"{first:%Y-%m}", end=f"{last:%Y-%m}", limit=5000)
    history = [Month(date.fromisoformat(r["period"] + "-01"), {k: float(r[k] or 0) for k in BRIDGE})
               for r in result["rows"]]
    bt = backtest(history, months, window)
    bands = {b["horizon_months"]: b for b in bt["by_horizon"]}
    rows = []
    for h, row in enumerate(driver_forecast(history, months, window), start=1):
        band = bands.get(h)
        low = high = None
        if band:
            # Backtest errors are (forecast - actual) / actual, so actual = forecast / (1 + error).
            # The range always contains the point forecast, even if every past error had one sign.
            low = min(row["arr"], row["arr"] / (1 + band["p90_error"]))
            high = max(row["arr"], row["arr"] / (1 + band["p10_error"]))
        rows.append({
            "period": f"{row['period']:%Y-%m}",
            **{k: round(row[k], 2) for k in BRIDGE},
            "arr_low": round(low, 2) if low is not None else None,
            "arr_high": round(high, 2) if high is not None else None,
        })
    drivers = _drivers(history, window)
    return {
        "method": "Driver-based ARR bridge forecast (see docs/forecasting.md)",
        "last_actual_month": f"{last:%Y-%m}",
        "last_actual_arr": history[-1].values["arr"],
        "assumptions": {
            "trailing_window_months": window,
            "new_arr_per_month": round(drivers["new_arr"], 2),
            "reactivation_arr_per_month": round(drivers["reactivation_arr"], 2),
            "monthly_expansion_rate": round(drivers["expansion_arr"], 5),
            "monthly_contraction_rate": round(drivers["contraction_arr"], 5),
            "monthly_churn_rate": round(drivers["churned_arr"], 5),
        },
        "forecast": rows,
        "backtest": {**bt, "by_horizon": [{k: (round(v, 4) if isinstance(v, float) else v) for k, v in b.items()}
                                          for b in bt["by_horizon"]]},
        "notes": ["Intervals are the 10th-90th percentile of backtest errors at each horizon, not a statistical guarantee.",
                  "The forecast assumes recent driver behavior continues; it has no view of pipeline or seasonality."],
        "certified": False,
    }
