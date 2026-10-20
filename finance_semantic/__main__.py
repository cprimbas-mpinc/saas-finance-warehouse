"""Command line for the semantic layer, so you can try it without an MCP client.

    python -m finance_semantic ask "ARR by segment last 6 months"
    python -m finance_semantic metrics
    python -m finance_semantic saved [name]
    python -m finance_semantic controls
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
        print("  ".join(h.ljust(w) for h, w in zip(headers, widths)))
        print("  ".join("-" * w for w in widths))
        for row in table:
            print("  ".join(v.rjust(w) if i else v.ljust(w) for i, (v, w) in enumerate(zip(row, widths))))
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
    sub.add_parser("serve", help="run the MCP server on stdio")
    args = ap.parse_args(argv)

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
        elif args.cmd == "controls":
            print_result(layer.control_status(include_exceptions=False))
    except SemanticError as e:
        sys.exit(f"Error: {e}")


if __name__ == "__main__":
    main()
