"""The governance linter passes on the shipped catalog and catches the mistakes it exists to catch."""

from __future__ import annotations

import shutil
from pathlib import Path

import yaml

from finance_semantic.catalog import SEMANTIC_DIR, load_catalog
from finance_semantic.governance import lint_catalog


def test_shipped_catalog_is_clean():
    assert lint_catalog(load_catalog()) == []


def broken_catalog(tmp_path: Path, mutate) -> list[str]:
    target = tmp_path / "semantic_layer"
    shutil.copytree(SEMANTIC_DIR, target)
    spec = yaml.safe_load((target / "metrics.yml").read_text())
    mutate(spec)
    (target / "metrics.yml").write_text(yaml.safe_dump(spec, sort_keys=False))
    return lint_catalog(load_catalog(target))


def test_flags_a_synonym_shared_by_two_metrics(tmp_path):
    findings = broken_catalog(tmp_path, lambda s: s["metrics"]["billings"]["synonyms"].append("revenue"))
    assert any("'revenue' maps to more than one metric" in f for f in findings)


def test_flags_a_balance_rolled_up_by_sum(tmp_path):
    def mutate(spec):
        spec["semantic_models"]["retention_cohort"]["measures"]["cohort_arr_today"]["time_agg"] = "sum"
    findings = broken_catalog(tmp_path, mutate)
    assert any("nrr: percent metric rolls up over time with 'sum'" in f for f in findings)


def test_flags_missing_owner_and_thin_description(tmp_path):
    def mutate(spec):
        spec["metrics"]["arr"]["owner"] = ""
        spec["metrics"]["arr"]["description"] = "ARR."
    findings = broken_catalog(tmp_path, mutate)
    assert "arr: no owner" in findings
    assert "arr: description is too short to define the metric" in findings
