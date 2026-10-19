"""Run the whole pipeline with one command:

    python run_pipeline.py            # data with planted control exceptions (the demo)
    python run_pipeline.py --clean    # same company, no planted exceptions: every control passes

Steps: generate source extracts -> dbt build (models + data tests + controls) -> evidence package.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def run(cmd: list[str], env: dict) -> None:
    print(f"\n$ {' '.join(cmd)}", flush=True)
    result = subprocess.run(cmd, cwd=ROOT, env=env)
    if result.returncode != 0:
        sys.exit(result.returncode)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--clean", action="store_true", help="generate data without planted exceptions")
    ap.add_argument("--workdir", default=None,
                    help="write data, warehouse and evidence here instead of the repo (used by the test suite)")
    args = ap.parse_args()

    base = Path(args.workdir).resolve() if args.workdir else ROOT
    raw, evidence, warehouse = base / "data" / "raw", base / "evidence", base / "warehouse.duckdb"
    env = {**os.environ, "WAREHOUSE_PATH": str(warehouse), "DBT_PROFILES_DIR": str(ROOT)}
    if warehouse.exists():
        warehouse.unlink()

    dbt = shutil.which("dbt")
    if not dbt:
        sys.exit("dbt not found. Install dependencies first: pip install -r requirements.txt")

    run([sys.executable, "scripts/generate_data.py", "--out", str(raw)] + (["--clean"] if args.clean else []), env)
    run([dbt, "build", "--vars", f"{{raw_path: '{raw.as_posix()}'}}",
         "--target-path", str(base / "target")], env)
    run([sys.executable, "scripts/build_evidence.py", "--warehouse", str(warehouse),
         "--raw", str(raw), "--out", str(evidence)], env)


if __name__ == "__main__":
    main()
