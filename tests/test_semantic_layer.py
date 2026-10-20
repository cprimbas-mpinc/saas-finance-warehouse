"""The semantic layer must give the same answers as the warehouse's own reports, roll time up
correctly (flows sum, balances take period-end), and never let user input reach the SQL text."""

from __future__ import annotations

from datetime import date

import duckdb
import pytest
from conftest import open_warehouse

from finance_semantic import SemanticError, load_catalog
from finance_semantic.nl import resolve


def by_period(result, metric):
    return {r["period"]: r[metric] for r in result["rows"]}


def test_catalog_loads_and_every_metric_compiles(layer):
    catalog = load_catalog()
    assert len(catalog.metrics) >= 15
    for name in catalog.metrics:
        assert layer.query_metrics([name], last_n_periods=1)["row_count"] == 1


def test_monthly_arr_matches_the_arr_bridge(layer, seeded):
    con = open_warehouse(seeded)
    expected = {f"{m:%Y-%m}": float(v) for m, v in con.sql(
        "select month_start, ending_arr from rpt_arr_rollforward").fetchall()}
    got = by_period(layer.query_metrics(["arr"], start="2023-01", end="2025-12", limit=5000), "arr")
    assert got == expected


def test_quarterly_rollup_uses_period_end_for_balances_and_sums_flows(layer):
    monthly = layer.query_metrics(["arr", "new_arr", "beginning_arr"], start="2025-07", end="2025-09")
    quarterly = layer.query_metrics(["arr", "new_arr", "beginning_arr"], grain="quarter", start="2025-07", end="2025-09")
    q = quarterly["rows"][0]
    m = monthly["rows"]
    assert q["period"] == "2025-Q3"
    assert q["arr"] == m[-1]["arr"]                                  # balance: September's value
    assert q["beginning_arr"] == m[0]["beginning_arr"]               # opening balance: July's value
    assert q["new_arr"] == pytest.approx(sum(r["new_arr"] for r in m))  # flow: summed


def test_net_new_arr_equals_change_in_arr(layer):
    rows = layer.query_metrics(["beginning_arr", "net_new_arr", "arr"], grain="quarter", last_n_periods=4)["rows"]
    for r in rows:
        assert r["beginning_arr"] + r["net_new_arr"] == pytest.approx(r["arr"])


def test_nrr_matches_the_retention_report(layer, seeded):
    con = open_warehouse(seeded)
    expected = {f"{m:%Y-%m}": float(v) for m, v in con.sql(
        "select month_start, net_revenue_retention from rpt_net_revenue_retention").fetchall()}
    got = by_period(layer.query_metrics(["nrr"], start="2024-01", end="2025-12", limit=5000), "nrr")
    for period, value in got.items():
        assert round(value, 4) == pytest.approx(expected[period])


def test_segments_sum_to_the_total(layer):
    total = layer.query_metrics(["arr", "recognized_revenue"], last_n_periods=1)["rows"][0]
    split = layer.query_metrics(["arr", "recognized_revenue"], group_by=["segment"], last_n_periods=1)["rows"]
    assert sum(r["arr"] or 0 for r in split) == pytest.approx(total["arr"])
    assert sum(r["recognized_revenue"] or 0 for r in split) == pytest.approx(total["recognized_revenue"])


def test_revenue_variance_surfaces_the_planted_topside_entry(layer):
    rows = layer.query_metrics(["revenue_variance"], start="2025-01", end="2025-12")["rows"]
    flagged = {r["period"]: r["revenue_variance"] for r in rows if r["revenue_variance"]}
    assert flagged == {"2025-06": 25000.0}


def test_company_level_metrics_refuse_a_segment_split(layer):
    with pytest.raises(SemanticError, match="company level"):
        layer.query_metrics(["deferred_revenue"], group_by=["segment"])


def test_unknown_names_are_rejected(layer):
    with pytest.raises(SemanticError, match="Unknown metric"):
        layer.query_metrics(["ebitda"])
    with pytest.raises(SemanticError, match="Unknown dimension"):
        layer.query_metrics(["arr"], group_by=["customer_id; drop table x"])


def test_filter_values_are_bound_parameters_not_sql(layer):
    result = layer.query_metrics(["arr"], filters={"segment": ["SMB' or '1'='1"]}, last_n_periods=1)
    assert result["rows"] == [] or all(r["arr"] is None for r in result["rows"])
    assert "or '1'='1" not in result["sql"]


def test_run_sql_allows_one_select_and_nothing_else(layer):
    assert layer.run_sql("select count(*) as n from dim_customers")["rows"][0]["n"] > 0
    for bad in ["drop table dim_customers", "select 1; select 2",
                "copy dim_customers to 'out.csv'", "attach 'other.db' as o"]:
        with pytest.raises(SemanticError):
            layer.run_sql(bad)
    with pytest.raises(duckdb.Error):  # sandbox: no file access even inside a SELECT
        layer.run_sql("select * from read_csv('data/raw/customers.csv')")


def test_control_status_reports_planted_exceptions(layer):
    status = layer.control_status()
    results = {c["control_id"]: c["result"] for c in status["controls"]}
    assert results["REV-02"] == "PASS" and results["ARR-01"] == "PASS"
    assert sum(1 for v in results.values() if v == "EXCEPTION") == 6


# ---------------------------------------------------------------------------- natural language

DIMS = {"segment": ["Enterprise", "Mid-Market", "SMB"], "region": ["APAC", "EMEA", "North America"],
        "industry": ["Education", "Financial Services", "Healthcare", "Logistics", "Manufacturing", "Media", "Retail"]}
BOUNDS = (date(2023, 1, 1), date(2025, 12, 1))

NL_CASES = [
    # question, kind, metrics, group_by, grain, start, end, filters
    ("What is our ARR?", "metrics", ["arr"], [], "month", "2025-12", "2025-12", {}),
    ("ARR by segment last 6 months", "metrics", ["arr"], ["segment"], "month", "2025-07", "2025-12", {}),
    ("annual recurring revenue trend", "metrics", ["arr"], [], "month", "2025-01", "2025-12", {}),
    ("net revenue retention for EMEA last 4 quarters", "metrics", ["nrr"], [], "quarter", "2025-01", "2025-12",
     {"region": ["EMEA"]}),
    ("revenue in Q3 2025", "metrics", ["recognized_revenue"], [], "quarter", "2025-07", "2025-09", {}),
    ("quarterly net new ARR in 2025", "metrics", ["net_new_arr"], [], "quarter", "2025-01", "2025-12", {}),
    ("NRR vs GRR by segment", "metrics", ["nrr", "grr"], ["segment"], "month", "2025-12", "2025-12", {}),
    ("how many enterprise customers do we have", "metrics", ["paying_customers"], [], "month", "2025-12", "2025-12",
     {"segment": ["Enterprise"]}),
    ("which industry has the most churned ARR in 2025", "metrics", ["churned_arr"], ["industry"], "year",
     "2025-01", "2025-12", {}),
    ("new logos since March 2025", "metrics", ["new_logos"], [], "month", "2025-03", "2025-12", {}),
    ("deferred revenue last quarter", "metrics", ["deferred_revenue"], [], "quarter", "2025-10", "2025-12", {}),
]


@pytest.mark.parametrize("question,kind,metrics,group_by,grain,start,end,filters", NL_CASES)
def test_resolver_reads_common_questions(question, kind, metrics, group_by, grain, start, end, filters):
    r = resolve(question, load_catalog(), BOUNDS, DIMS)
    assert r.kind == kind
    assert r.metrics == metrics
    assert r.group_by == group_by
    assert r.grain == grain
    assert (f"{r.start:%Y-%m}", f"{r.end:%Y-%m}") == (start, end)
    assert r.filters == filters


def test_net_revenue_retention_never_also_matches_revenue():
    r = resolve("net revenue retention", load_catalog(), BOUNDS, DIMS)
    assert r.metrics == ["nrr"]


@pytest.mark.parametrize("question,saved", [
    ("show me the ARR bridge", "arr_bridge"), ("board KPIs", "board_kpis"),
    ("does revenue tie to the GL?", "revenue_tie_out"), ("retention by segment", "retention_by_segment")])
def test_curated_phrases_route_to_saved_queries(question, saved):
    r = resolve(question, load_catalog(), BOUNDS, DIMS)
    assert (r.kind, r.saved_query) == ("saved_query", saved)


def test_control_questions_route_to_control_status():
    assert resolve("any SOX control exceptions?", load_catalog(), BOUNDS, DIMS).kind == "controls"


def test_unknown_metric_is_unresolved_with_a_hint():
    r = resolve("what's our burn rate", load_catalog(), BOUNDS, DIMS)
    assert r.kind == "unresolved"
    assert any("couldn't find a metric" in n for n in r.notes)


def test_out_of_range_period_is_unresolved():
    assert resolve("ARR in 2019", load_catalog(), BOUNDS, DIMS).kind == "unresolved"


def test_ask_end_to_end(layer):
    result = layer.ask("ARR by segment last 3 months")
    assert result["row_count"] == 9
    assert result["certified"] is True
    assert "matched" in result["question_as_understood"]
