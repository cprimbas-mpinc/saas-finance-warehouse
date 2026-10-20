"""Shared fixtures: one full pipeline run on seeded data and one on clean data, each in its own
temp directory, reused across the whole test session."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def run_pipeline(workdir: Path, clean: bool) -> Path:
    cmd = [sys.executable, str(ROOT / "run_pipeline.py"), "--workdir", str(workdir)] + (["--clean"] if clean else [])
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    return workdir


@pytest.fixture(scope="session")
def seeded(tmp_path_factory) -> Path:
    return run_pipeline(tmp_path_factory.mktemp("seeded"), clean=False)


@pytest.fixture(scope="session")
def clean(tmp_path_factory) -> Path:
    return run_pipeline(tmp_path_factory.mktemp("clean"), clean=True)


@pytest.fixture(scope="session")
def layer(seeded):
    from finance_semantic import FinanceSemanticLayer
    return FinanceSemanticLayer(warehouse_path=seeded / "warehouse.duckdb")


def open_warehouse(workdir: Path) -> duckdb.DuckDBPyConnection:
    """Read-only connection with the same sandbox settings the semantic layer uses (DuckDB refuses
    two in-process connections to one file with different settings)."""
    return duckdb.connect(str(workdir / "warehouse.duckdb"), read_only=True,
                          config={"enable_external_access": False, "lock_configuration": True})
