"""Read-only, sandboxed access to the DuckDB warehouse."""

from __future__ import annotations

import os
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]


def default_warehouse_path() -> Path:
    return Path(os.environ.get("WAREHOUSE_PATH", ROOT / "warehouse.duckdb"))


class Warehouse:
    """Every connection is read-only and blocks file and network access from SQL, and that setting is
    locked so a query can't switch it back on. Opened per call so it never blocks a dbt rebuild."""

    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path else default_warehouse_path()
        if not self.path.exists():
            raise FileNotFoundError(f"Warehouse not found at {self.path}. Build it first: python run_pipeline.py")

    def _connect(self) -> duckdb.DuckDBPyConnection:
        return duckdb.connect(str(self.path), read_only=True,
                              config={"enable_external_access": False, "lock_configuration": True})

    def fetch(self, sql: str, params: list | None = None) -> tuple[list[str], list[tuple]]:
        con = self._connect()
        try:
            rel = con.execute(sql, params or [])
            cols = [d[0] for d in rel.description]
            return cols, rel.fetchall()
        finally:
            con.close()

    def records(self, sql: str, params: list | None = None) -> list[dict]:
        cols, rows = self.fetch(sql, params)
        return [{c: to_json(v) for c, v in zip(cols, r, strict=True)} for r in rows]

    def month_bounds(self) -> tuple[date, date]:
        _, rows = self.fetch("select min(month_start), max(month_start) from int_month_spine")
        return rows[0]

    def dimension_values(self, dimension: str) -> list[str]:
        _, rows = self.fetch(f'select distinct "{dimension}" from dim_customers where "{dimension}" is not null order by 1')
        return [r[0] for r in rows]

    def built_at(self) -> str:
        ts = datetime.fromtimestamp(self.path.stat().st_mtime, tz=timezone.utc)
        return ts.strftime("%Y-%m-%d %H:%M UTC")


def to_json(v):
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if isinstance(v, float):
        return round(v, 6)
    return v
