"""End-to-end tests of the controls themselves (a test of design, in audit terms).

Two full pipeline runs on isolated copies of the data:
  * seeded: every planted exception must be caught by its control, and nothing else may be flagged
  * clean:  the same company with nothing planted must pass every control

Plus checks that the core finance outputs are internally consistent.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import duckdb
from conftest import open_warehouse

ROOT = Path(__file__).resolve().parents[1]
ALL_CONTROLS = {"REV-01", "REV-02", "BIL-01", "BIL-02", "DQ-01", "GL-01", "GL-02", "ARR-01"}


def connect(workdir: Path) -> duckdb.DuckDBPyConnection:
    return open_warehouse(workdir)


def control_results(workdir: Path) -> dict[str, int]:
    return dict(connect(workdir).sql("select control_id, exception_count from ctl_summary").fetchall())


# ---------------------------------------------------------------------------- control design

def test_every_planted_exception_is_caught_and_nothing_else(seeded):
    manifest = json.loads((seeded / "data" / "raw" / "seeded_exceptions.json").read_text())
    expected: dict[str, set[str]] = {}
    for e in manifest["exceptions"]:
        expected.setdefault(e["control_id"], set()).add(e["key"])

    con = connect(seeded)
    models = dict(con.sql("select control_id, control_model from ctl_summary").fetchall())
    assert set(models) == ALL_CONTROLS

    for control_id, model in models.items():
        found = {str(k) for (k,) in con.sql(f"select exception_key from {model}").fetchall()}
        assert found == expected.get(control_id, set()), f"{control_id}: expected {expected.get(control_id)}, got {found}"


def test_clean_data_passes_every_control(clean):
    results = control_results(clean)
    assert set(results) == ALL_CONTROLS
    assert all(n == 0 for n in results.values()), results


def test_evidence_package_is_written(seeded):
    evidence = (seeded / "evidence" / "control_evidence.md").read_text()
    for control_id in ALL_CONTROLS:
        assert control_id in evidence
    assert (seeded / "evidence" / "exceptions" / "REV-01.csv").exists()
    assert (seeded / "evidence" / "metrics_snapshot.md").exists()


# ---------------------------------------------------------------------------- finance logic

def test_arr_bridge_foots_and_rolls(clean):
    rows = connect(clean).sql("""
        select beginning_arr, new_arr, expansion_arr, reactivation_arr, contraction_arr, churned_arr, ending_arr
        from rpt_arr_rollforward order by month_start""").fetchall()
    prior_end = 0
    for beg, new, exp, react, contr, churn, end in rows:
        assert beg == prior_end
        assert beg + new + exp + react + contr + churn == end
        assert new >= 0 and exp >= 0 and react >= 0 and contr <= 0 and churn <= 0
        prior_end = end


def test_ending_arr_equals_active_contracts(clean):
    con = connect(clean)
    bridge = con.sql("select ending_arr from rpt_arr_rollforward where month_start = date '2025-12-01'").fetchone()[0]
    contracts = con.sql("""
        select sum(mrr) * 12 from stg_contract_lines
        where start_month <= date '2025-12-01' and (end_month is null or end_month >= date '2025-12-01')""").fetchone()[0]
    assert bridge == contracts


def test_revenue_schedule_recognizes_every_dollar_billed(clean):
    con = connect(clean)
    billed = con.sql("select sum(amount) from stg_invoices").fetchone()[0]
    scheduled = con.sql("select sum(recognized_amount) from int_invoice_revenue_schedule").fetchone()[0]
    assert billed == scheduled


def test_deferred_revenue_bridge_foots(clean):
    rows = connect(clean).sql("""
        select beginning_deferred_revenue, billings, recognized_revenue, ending_deferred_revenue
        from rpt_deferred_revenue_rollforward order by month_start""").fetchall()
    for beg, bill, rec, end in rows:
        assert beg + bill - rec == end


def test_retention_is_plausible(clean):
    rows = connect(clean).sql(
        "select net_revenue_retention, gross_revenue_retention from rpt_net_revenue_retention").fetchall()
    assert rows
    for nrr, grr in rows:
        assert 0 < grr <= 1
        assert nrr >= grr


def test_generator_is_deterministic(tmp_path):
    outs = []
    for name in ("a", "b"):
        out = tmp_path / name
        subprocess.run([sys.executable, str(ROOT / "scripts" / "generate_data.py"), "--out", str(out)], check=True,
                       capture_output=True)
        outs.append({f.name: f.read_bytes() for f in out.glob("*.csv")})
    assert outs[0] == outs[1]


# ---------------------------------------------------------------------------- exception log

def test_exception_log_tracks_every_finding(seeded):
    log = {(c, k): (s, overdue) for c, k, s, overdue in connect(seeded).sql(
        "select control_id, exception_key, status, is_overdue from rpt_control_exception_log").fetchall()}
    manifest = json.loads((seeded / "data" / "raw" / "seeded_exceptions.json").read_text())
    assert {(e["control_id"], e["key"]) for e in manifest["exceptions"]} == set(log)
    assert log[("REV-01", "2025-06-01")] == ("investigating", True)    # unsupported top-side entry, still open
    assert log[("DQ-01", manifest_key(manifest, "DQ-01"))][0] == "unassigned"  # found, never triaged
    assert sum(1 for s, _ in log.values() if s == "resolved") == 4


def test_exception_log_marks_fixed_items_cleared_on_clean_data(clean):
    statuses = [s for (s,) in connect(clean).sql("select status from rpt_control_exception_log").fetchall()]
    assert statuses and set(statuses) == {"cleared"}


def manifest_key(manifest: dict, control_id: str) -> str:
    return next(e["key"] for e in manifest["exceptions"] if e["control_id"] == control_id)
