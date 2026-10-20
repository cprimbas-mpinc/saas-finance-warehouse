"""Command line for the semantic layer, so you can try it without an MCP client.

    python -m finance_semantic ask "ARR by segment last 6 months"
    python -m finance_semantic metrics
    python -m finance_semantic saved [name]
    python -m finance_semantic controls
    python -m finance_semantic lint           # catalog governance checks (CI runs this)
    python -m finance_semantic forecast [months]
    python -m finance_semantic serve          # start the MCP server on stdio
"""

from __future__ import annotations

import argparse
import json
import sys

from .catalog import SemanticError


def fmt(value, kind: str | None) -> str:
    if value is None:
        return ""
    if kind == "currency":
        return f"-${abs(value):,.0f}" if value < 0 else f"${value:,.0f}"
    if kind == "percent":
        return f"{value:.1%}"
    if kind == "count":
        return f"{value:,.0f}"
    return str(value)


def print_result(result: dict) -> None:
    if "error" in result:
        print(f"Error: {result['error']}")
        return
    understood = result.get("question_as_understood", {})
    if understood.get("query") or understood.get("title"):
        print("Understood as:", understood.get("query") or understood.get("title"))
        if understood.get("matched"):
            print("  matched:", "; ".join(understood["matched"]))
        if understood.get("ignored_words"):
            print("  ignored:", ", ".join(understood["ignored_words"]))
    if "controls" in result:
        print(result["summary"])
        for c in result["controls"]:
            print(f"  {c['control_id']:<7} {c['result']:<10} {c['exception_count']:>3}  {c['name']}")
        return
    cols = result.get("columns") or [{"name": k} for k in (result["rows"][0] if result.get("rows") else {})]
    if result.get("rows"):
        headers = [c.get("label", c["name"]) for c in cols]
        table = [[fmt(r[c["name"]], c.get("format")) for c in cols] for r in result["rows"]]
        widths = [max(len(h), *(len(row[i]) for row in table)) for i, h in enumerate(headers)]
        print()
        print("  ".join(h.ljust(w) for h, w in zip(headers, widths, strict=True)))
        print("  ".join("-" * w for w in widths))
        for row in table:
            print("  ".join(v.rjust(w) if i else v.ljust(w) for i, (v, w) in enumerate(zip(row, widths, strict=True))))
    for note in result.get("notes", []):
        print("Note:", note)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m finance_semantic", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("ask", help="ask a plain-English question")
    a.add_argument("question", nargs="+")
    a.add_argument("--sql", action="store_true", help="also print the generated SQL")
    a.add_argument("--json", action="store_true", help="print the raw JSON result")
    sub.add_parser("metrics", help="list governed metrics")
    s = sub.add_parser("saved", help="list saved queries, or run one by name")
    s.add_argument("name", nargs="?")
    sub.add_parser("controls", help="show control status")
    sub.add_parser("lint", help="run catalog governance checks")
    f = sub.add_parser("forecast", help="driver-based ARR forecast with backtest")
    f.add_argument("months", nargs="?", type=int, default=6)
    sub.add_parser("serve", help="run the MCP server on stdio")
    args = ap.parse_args(argv)

    if args.cmd == "lint":
        from .catalog import load_catalog
        from .governance import lint_catalog
        findings = lint_catalog(load_catalog())
        for f in findings:
            print("FAIL", f)
        print(f"{len(findings)} finding(s)" if findings else "Catalog OK: all governance checks passed")
        sys.exit(1 if findings else 0)

    if args.cmd == "serve":
        from .server import main as serve
        serve()
        return

    from .service import FinanceSemanticLayer
    try:
        layer = FinanceSemanticLayer()
    except FileNotFoundError as e:
        sys.exit(str(e))

    try:
        if args.cmd == "ask":
            result = layer.ask(" ".join(args.question))
            if args.json:
                print(json.dumps(result, indent=2, default=str))
                return
            print_result(result)
            if args.sql and result.get("sql"):
                print("\nSQL:\n" + result["sql"] + "\nparams: " + ", ".join(result["params"]))
        elif args.cmd == "metrics":
            for m in layer.list_metrics()["metrics"]:
                dims = ", ".join(m["dimensions"]) or "company level only"
                print(f"{m['name']:<20} {m['label']:<34} by: {dims}")
        elif args.cmd == "saved":
            if args.name:
                print_result(layer.run_saved_query(args.name))
            else:
                for q in layer.list_saved_queries()["saved_queries"]:
                    print(f"{q['name']:<22} {q['title']}: {q['description']}")
        elif args.cmd == "forecast":
            out = layer.forecast_arr(months=args.months)
            a = out["assumptions"]
            print(f"Last actual {out['last_actual_month']}: {fmt(out['last_actual_arr'], 'currency')} ARR")
            print(f"Drivers (trailing {a['trailing_window_months']} months): new {fmt(a['new_arr_per_month'], 'currency')}/mo, "
                  f"expansion {a['monthly_expansion_rate']:.2%}/mo, contraction {a['monthly_contraction_rate']:.2%}/mo, "
                  f"churn {a['monthly_churn_rate']:.2%}/mo\n")
            print(f"{'Month':<9}{'ARR forecast':>15}{'Low':>15}{'High':>15}")
            for r in out["forecast"]:
                print(f"{r['period']:<9}{fmt(r['arr'], 'currency'):>15}{fmt(r['arr_low'], 'currency'):>15}"
                      f"{fmt(r['arr_high'], 'currency'):>15}")
            print(f"\n{'Backtest':<9}{'Driver MAPE':>15}{'Naive MAPE':>15}{'Origins':>15}")
            for b in out["backtest"]["by_horizon"]:
                print(f"{'+' + str(b['horizon_months']) + ' mo':<9}{b['driver_mape']:>15.1%}{b['naive_mape']:>15.1%}"
                      f"{b['origins_tested']:>15}")
        elif args.cmd == "controls":
            print_result(layer.control_status(include_exceptions=False))
    except SemanticError as e:
        sys.exit(f"Error: {e}")


if __name__ == "__main__":
    main()
