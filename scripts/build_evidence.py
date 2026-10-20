"""Build the control evidence package and a metrics snapshot from the warehouse.

Outputs (in --out, default evidence/):
    control_evidence.md        One page per run: what was tested, on what data, result, exceptions found
    exceptions/<CONTROL>.csv   Full exception detail for each control that found something
    metrics_snapshot.md        ARR bridge, retention and reconciliation summary for the period
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import yaml

ROOT = Path(__file__).resolve().parents[1]


def money(x) -> str:
    if x is None:
        return ""
    x = float(x)
    return f"-${abs(x):,.0f}" if x < 0 else f"${x:,.0f}"


def md_table(rows: list[tuple], headers: list[str]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out += ["| " + " | ".join("" if v is None else str(v) for v in r) + " |" for r in rows]
    return "\n".join(out)


def fingerprint(raw: Path) -> list[tuple[str, int, str]]:
    rows = []
    for f in sorted(raw.glob("*.csv")):
        data = f.read_bytes()
        rows.append((f.name, data.count(b"\n") - 1, hashlib.sha256(data).hexdigest()[:16]))
    return rows


def forecast_section(warehouse: str) -> list[str]:
    """Six-month ARR forecast from the semantic layer, with its backtest, so the projection and its
    track record travel together."""
    sys.path.insert(0, str(ROOT))
    from finance_semantic import FinanceSemanticLayer

    fc = FinanceSemanticLayer(warehouse_path=warehouse).forecast_arr(months=6)
    a = fc["assumptions"]
    return [
        "## ARR forecast, next 6 months (projection, uncertified)",
        "",
        f"Driver-based bridge forecast from the last actual month ({fc['last_actual_month']}). Trailing "
        f"{a['trailing_window_months']}-month drivers: new {money(a['new_arr_per_month'])}/month, expansion "
        f"{a['monthly_expansion_rate']:.2%}/month, contraction {a['monthly_contraction_rate']:.2%}/month, churn "
        f"{a['monthly_churn_rate']:.2%}/month. Method and caveats: [docs/forecasting.md](../docs/forecasting.md).",
        "",
        md_table([(r["period"], money(r["beginning_arr"]), money(r["new_arr"] + r["reactivation_arr"]),
                   money(r["expansion_arr"]), money(r["contraction_arr"] + r["churned_arr"]), money(r["arr"]),
                   money(r["arr_low"]), money(r["arr_high"])) for r in fc["forecast"]],
                 ["Month", "Beginning", "New + reactivation", "Expansion", "Contraction + churn", "Ending",
                  "Low (p10)", "High (p90)"]),
        "",
        "Backtest (rolling origin) versus a straight-line trend:",
        "",
        md_table([(f"+{b['horizon_months']}", b["origins_tested"], f"{b['driver_mape']:.1%}",
                   f"{b['naive_mape']:.1%}", f"{b['driver_bias']:+.1%}") for b in fc["backtest"]["by_horizon"]],
                 ["Months ahead", "Origins", "Driver MAPE", "Naive MAPE", "Driver bias"]),
        "",
    ]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--warehouse", default=str(ROOT / "warehouse.duckdb"))
    ap.add_argument("--raw", default=str(ROOT / "data" / "raw"))
    ap.add_argument("--out", default=str(ROOT / "evidence"))
    args = ap.parse_args()

    out, raw = Path(args.out), Path(args.raw)
    (out / "exceptions").mkdir(parents=True, exist_ok=True)
    for old in (out / "exceptions").glob("*.csv"):
        old.unlink()

    matrix = yaml.safe_load((ROOT / "controls" / "control_matrix.yml").read_text())["controls"]
    con = duckdb.connect(args.warehouse, read_only=True)
    run_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    manifest = json.loads((raw / "seeded_exceptions.json").read_text())

    # ------------------------------------------------------------------ control evidence
    summary, details = [], []
    for ctl in matrix:
        rel = con.sql(f"select * from {ctl['model']}")
        cols, rows = rel.columns, rel.fetchall()
        result = "PASS" if not rows else "EXCEPTION"
        summary.append((ctl["id"], ctl["name"], ctl["frequency"], ctl["owner"], len(rows), f"**{result}**"))
        block = [
            f"### {ctl['id']} · {ctl['name']}",
            f"- **Risk:** {ctl['risk']}",
            f"- **Control objective:** {ctl['objective']}",
            f"- **Assertion:** {ctl['assertion']} · **Type:** {ctl['type']}, {ctl['nature']} · **Frequency:** {ctl['frequency']}",
            f"- **Population tested:** model `{ctl['model']}` over the full reporting window",
            f"- **Result:** {result} ({len(rows)} exception{'s' if len(rows) != 1 else ''})",
        ]
        if rows:
            csv_path = out / "exceptions" / f"{ctl['id']}.csv"
            con.sql(f"copy (select * from {ctl['model']}) to '{csv_path.as_posix()}' (header, delimiter ',')")
            shown = [c for c in cols if c != "exception_key"]
            sample = [tuple(r[cols.index(c)] for c in shown) for r in rows[:5]]
            block += ["", md_table(sample, shown), "",
                      f"Full detail: `exceptions/{ctl['id']}.csv`. Follow-up: owner to investigate, document root cause, and correct or support each item before close sign-off."]
        details.append("\n".join(block))

    fp = fingerprint(raw)
    evidence = [
        "# Control Evidence Package",
        "",
        f"**Company:** Halyard Software, Inc. (synthetic) · **Run:** {run_at} · **Data mode:** {manifest['mode']} (seed {manifest['seed']})",
        "",
        "Each control below is an automated query over the full population (not a sample). A control model returns only exception rows, so an empty result is the evidence of operating effectiveness for the run.",
        "",
        "## Summary",
        "",
        md_table(summary, ["Control", "Name", "Frequency", "Owner", "Exceptions", "Result"]),
        "",
        "## Data tested",
        "",
        "Source files are fingerprinted so a reviewer can confirm the evidence came from this exact data.",
        "",
        md_table(fp, ["File", "Rows", "SHA-256 (first 16)"]),
        "",
        "## Exception log",
        "",
        "Every exception found, tracked to resolution. `unassigned` = found but not yet triaged; "
        "`cleared` = logged earlier and no longer found by the controls.",
        "",
        md_table(con.sql("""
            select control_id, exception_key, status, coalesce(owner, ''), coalesce(cast(due_date as varchar), ''),
                   coalesce(cast(days_to_resolve as varchar), ''),
                   case when is_overdue then '**overdue** (' || days_open || ' days open)' else '' end,
                   coalesce(root_cause, '')
            from rpt_control_exception_log order by control_id, exception_key""").fetchall(),
                 ["Control", "Exception", "Status", "Owner", "Due", "Days to resolve", "Aging", "Root cause"]),
        "",
        "## Control detail",
        "",
        "\n\n".join(details),
        "",
    ]
    (out / "control_evidence.md").write_text("\n".join(evidence), encoding="utf-8")

    # ------------------------------------------------------------------ metrics snapshot
    bridge = con.sql("""
        select strftime(month_start, '%Y-%m'), beginning_arr, new_arr, expansion_arr, reactivation_arr,
               contraction_arr, churned_arr, ending_arr, paying_customers
        from rpt_arr_rollforward order by month_start desc limit 12""").fetchall()[::-1]
    retention = con.sql("""
        select strftime(month_start, '%Y-%m'), cohort_customers, net_revenue_retention, gross_revenue_retention
        from rpt_net_revenue_retention where month(month_start) in (3, 6, 9, 12) order by month_start""").fetchall()
    recon = con.sql("""
        select strftime(month_start, '%Y-%m'), subledger_revenue, gl_revenue, revenue_variance,
               subledger_deferred_revenue, gl_deferred_revenue
        from rpt_revenue_reconciliation order by month_start desc limit 6""").fetchall()[::-1]
    segments = con.sql("""
        select segment, count(*) filter (where is_active), sum(current_arr)
        from dim_customers group by 1 order by 3 desc""").fetchall()

    snapshot = [
        "# Metrics Snapshot",
        "",
        f"Halyard Software, Inc. (synthetic data) · generated {run_at}",
        "",
        "## ARR bridge, last 12 months",
        "",
        md_table([(m, money(b), money(n), money(e), money(r), money(c), money(ch), money(end), p)
                  for m, b, n, e, r, c, ch, end, p in bridge],
                 ["Month", "Beginning", "New", "Expansion", "Reactivation", "Contraction", "Churn", "Ending", "Customers"]),
        "",
        "## Retention (trailing 12 months, customer cohort)",
        "",
        md_table([(m, n, f"{nrr:.1%}", f"{grr:.1%}") for m, n, nrr, grr in retention],
                 ["Month", "Cohort customers", "NRR", "GRR"]),
        "",
        "## Ending ARR by segment",
        "",
        md_table([(s, n, money(a)) for s, n, a in segments], ["Segment", "Active customers", "ARR"]),
        "",
        "## Revenue reconciliation, last 6 months",
        "",
        md_table([(m, money(s), money(g), money(v), money(sd), money(gd)) for m, s, g, v, sd, gd in recon],
                 ["Month", "Subledger revenue", "GL revenue", "Variance", "Subledger deferred", "GL deferred"]),
        "",
    ]
    con.close()  # the semantic layer opens its own sandboxed connection
    snapshot += forecast_section(args.warehouse)
    (out / "metrics_snapshot.md").write_text("\n".join(snapshot), encoding="utf-8")

    for row in summary:
        print(f"  {row[0]:<7} {row[5].strip('*'):<10} {row[4]:>3}  {row[1]}")
    print(f"Evidence written to {out}")


if __name__ == "__main__":
    main()
