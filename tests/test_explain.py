"""explain_change: every decomposition must reconcile exactly to the change it claims to explain,
because commentary written from facts that don't tie is worse than no commentary."""

from __future__ import annotations

import pytest

from finance_semantic.catalog import SemanticError
from finance_semantic.explain import comparison_period, parse_period


def value(layer, metric: str, grain: str, period: str) -> float:
    rows = layer.query_metrics([metric], grain=grain, start="2023-01", end="2025-12", limit=5000)["rows"]
    return next(r[metric] for r in rows if r["period"] == period)


def test_arr_change_matches_the_warehouse_and_the_bridge_foots(layer):
    out = layer.explain_change("arr")
    assert (out["period"], out["compared_to"]) == ("2025-12", "2025-11")
    assert out["change"] == pytest.approx(value(layer, "arr", "month", "2025-12") - value(layer, "arr", "month", "2025-11"))
    assert [c["component"] for c in out["drivers"]["components"]] == [
        "new_arr", "reactivation_arr", "expansion_arr", "contraction_arr", "churned_arr"]
    assert out["drivers"]["unexplained"] == pytest.approx(0, abs=0.01)


def test_year_over_year_quarter_bridge_still_foots(layer):
    """Twelve months of flows between Q4 2024 and Q4 2025 must add up to the change in ending ARR."""
    out = layer.explain_change("arr", period="2025-Q4", compare_to="prior_year")
    assert (out["period"], out["compared_to"]) == ("2025-Q4", "2024-Q4")
    assert out["drivers"]["unexplained"] == pytest.approx(0, abs=0.01)
    assert out["change"] == pytest.approx(value(layer, "arr", "quarter", "2025-Q4")
                                          - value(layer, "arr", "quarter", "2024-Q4"))


def test_deferred_revenue_rolls_forward_from_billings_and_revenue(layer):
    out = layer.explain_change("deferred_revenue")
    amounts = {c["component"]: c["amount"] for c in out["drivers"]["components"]}
    assert amounts["billings"] > 0 and amounts["recognized_revenue"] < 0
    assert out["drivers"]["unexplained"] == pytest.approx(0, abs=0.01)
    assert out["contributions"] == {} and "company level" in out["notes"][0]


def test_sum_of_parts_metric_explains_its_change(layer):
    out = layer.explain_change("net_new_arr", period="2025-Q3", compare_to="prior_year")
    assert out["drivers"]["method"] == "sum of parts"
    assert out["drivers"]["unexplained"] == pytest.approx(0, abs=0.01)


@pytest.mark.parametrize("metric", ["arr", "recognized_revenue", "paying_customers", "new_arr"])
def test_additive_contributions_sum_to_the_change(layer, metric):
    out = layer.explain_change(metric, grain="quarter")
    assert set(out["contributions"]) == {"segment", "region", "industry"}
    for c in out["contributions"].values():
        assert c["method"] == "additive"
        assert c["sum_of_changes"] == pytest.approx(out["change"], abs=0.01)
    assert out["notes"] == []


@pytest.mark.parametrize("metric", ["nrr", "grr", "arpa"])
def test_ratio_mix_and_rate_effects_reconcile_exactly(layer, metric):
    out = layer.explain_change(metric, grain="quarter")
    for c in out["contributions"].values():
        assert c["method"] == "mix_rate"
        assert c["mix_effect"] + c["rate_effect"] == pytest.approx(out["change"], abs=1e-6)
        assert sum(i["current_weight"] for i in c["items"]) == pytest.approx(1)


def test_arpa_decline_is_mix_not_price(layer):
    """In 2025-12 ARPA fell while Enterprise ARPA didn't move: smaller customers were added, so the
    segment mix explains the drop. The decomposition has to say that, not blame pricing."""
    seg = layer.explain_change("arpa", dimensions=["segment"])["contributions"]["segment"]
    assert seg["mix_effect"] < 0 < seg["rate_effect"]
    enterprise = next(i for i in seg["items"] if i["segment"] == "Enterprise")
    assert enterprise["rate_effect"] == pytest.approx(0, abs=1e-6)


def test_facts_are_grounded_in_the_numbers(layer):
    out = layer.explain_change("arr")
    assert out["facts"][0] == "ARR was $13,280,400 in 2025-12, up $296,400 (+2.3%) from $12,984,000 in 2025-11."
    assert "These fully explain the change." in out["facts"][1]
    assert out["sql"] and all(s["sql"].startswith("with ") for s in out["sql"])
    assert out["certified"] is True


def test_period_parsing():
    assert parse_period("2025-Q4").start.month == 10
    assert parse_period("2025").grain == "year"
    assert parse_period("2025-11", "quarter").label == "2025-Q4"
    assert comparison_period(parse_period("2025-01"), "prior_period").label == "2024-12"
    assert comparison_period(parse_period("2025-Q1"), "prior_year").label == "2024-Q1"
    with pytest.raises(SemanticError):
        parse_period("last month")


def test_out_of_range_and_bad_inputs_fail_clearly(layer):
    with pytest.raises(SemanticError, match="no 2022-12"):
        layer.explain_change("arr", period="2023-01")
    with pytest.raises(SemanticError, match="isn't complete"):
        layer.explain_change("arr", period="2026-01")
    with pytest.raises(SemanticError, match="compare_to"):
        layer.explain_change("arr", compare_to="budget")
    with pytest.raises(SemanticError, match="Unknown dimension"):
        layer.explain_change("arr", dimensions=["salesperson"])
