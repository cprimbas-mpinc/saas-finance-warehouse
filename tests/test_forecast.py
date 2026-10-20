"""The ARR forecast: the bridge it projects must foot, it must start from the last actual month, its
range must contain it, and the backtest must be scored on every origin it claims."""

from __future__ import annotations

from datetime import date
from itertools import pairwise

import pytest

from finance_semantic.forecast import BRIDGE, Month, backtest, driver_forecast, naive_forecast

FLOWS = ["new_arr", "reactivation_arr", "expansion_arr", "contraction_arr", "churned_arr"]


@pytest.fixture(scope="module")
def forecast(layer):
    return layer.forecast_arr(months=6, window=6)


def test_forecast_bridge_foots_every_month(forecast):
    for row in forecast["forecast"]:
        assert row["beginning_arr"] + sum(row[f] for f in FLOWS) == pytest.approx(row["arr"], abs=0.05)


def test_forecast_starts_from_last_actual_and_chains(forecast, layer):
    rows = forecast["forecast"]
    actual = layer.query_metrics(["arr"], last_n_periods=1)["rows"][0]
    assert forecast["last_actual_month"] == actual["period"]
    assert rows[0]["beginning_arr"] == pytest.approx(actual["arr"])
    assert rows[0]["period"] == "2026-01"
    for prev, cur in pairwise(rows):
        assert cur["beginning_arr"] == pytest.approx(prev["arr"], abs=0.05)


def test_range_contains_the_forecast(forecast):
    for row in forecast["forecast"]:
        assert row["arr_low"] <= row["arr"] <= row["arr_high"]
    widths = [r["arr_high"] - r["arr_low"] for r in forecast["forecast"]]
    assert widths[-1] > widths[0], "uncertainty should grow with the horizon"


def test_backtest_scores_every_horizon(forecast):
    by_h = forecast["backtest"]["by_horizon"]
    assert [b["horizon_months"] for b in by_h] == list(range(1, 7))
    # 36 months of history, first origin at month 12: one fewer origin per extra month of horizon.
    assert [b["origins_tested"] for b in by_h] == [23 - h for h in range(6)]
    assert all(b["driver_mape"] >= 0 and b["naive_mape"] >= 0 for b in by_h)


def test_forecast_reports_its_assumptions_and_is_uncertified(forecast):
    a = forecast["assumptions"]
    assert a["trailing_window_months"] == 6
    assert a["new_arr_per_month"] > 0 and a["monthly_churn_rate"] < 0
    assert forecast["certified"] is False


def test_inputs_are_clamped(layer):
    out = layer.forecast_arr(months=40, window=1)
    assert len(out["forecast"]) == 12
    assert out["assumptions"]["trailing_window_months"] == 3


def _history(months: int, new: float, expansion_rate: float, churn_rate: float) -> list[Month]:
    arr, out = 1_000_000.0, []
    for i in range(months):
        values = {"beginning_arr": arr, "new_arr": new, "reactivation_arr": 0.0,
                  "expansion_arr": arr * expansion_rate, "contraction_arr": 0.0, "churned_arr": arr * churn_rate}
        arr = arr + new + values["expansion_arr"] + values["churned_arr"]
        values["arr"] = arr
        out.append(Month(date(2023 + i // 12, i % 12 + 1, 1), values))
    return out


def test_driver_model_is_exact_when_drivers_are_stable():
    """If the business really runs on constant drivers, the driver model has zero error and the
    straight line doesn't: the backtest must be able to tell the two apart."""
    history = _history(30, new=50_000, expansion_rate=0.01, churn_rate=-0.005)
    result = backtest(history, horizon=6, window=6)
    for b in result["by_horizon"]:
        assert b["driver_mape"] == pytest.approx(0, abs=1e-12)
        assert b["naive_mape"] > 0


def test_naive_baseline_extends_a_straight_line():
    history = _history(12, new=10_000, expansion_rate=0.0, churn_rate=0.0)  # ARR grows exactly 10K/month
    assert naive_forecast(history, 3, 6) == pytest.approx([history[-1].values["arr"] + 10_000 * h for h in (1, 2, 3)])
    assert set(driver_forecast(history, 1, 6)[0]) == {"period", *BRIDGE}
