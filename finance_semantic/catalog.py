"""Load and validate the semantic layer definitions (semantic_layer/*.yml)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SEMANTIC_DIR = ROOT / "semantic_layer"

AGGS = {"sum", "count", "count_distinct", "min", "max"}
TIME_AGGS = {"sum", "last", "first"}
FORMATS = {"currency", "percent", "count"}


class SemanticError(ValueError):
    """A request the semantic layer can't answer as asked. The message says why and what is allowed."""


@dataclass(frozen=True)
class Measure:
    model: str
    name: str
    expr: str
    agg: str
    time_agg: str

    @property
    def column(self) -> str:
        return f"{self.model}__{self.name}"


@dataclass(frozen=True)
class SemanticModel:
    name: str
    table: str
    time_column: str
    dimensions: tuple[str, ...]
    measures: dict[str, Measure]


@dataclass(frozen=True)
class Metric:
    name: str
    label: str
    type: str  # simple | ratio
    format: str
    description: str
    owner: str
    certified: bool
    synonyms: tuple[str, ...]
    measure: Measure | None = None
    numerator: Measure | None = None
    denominator: Measure | None = None

    @property
    def measures(self) -> list[Measure]:
        return [m for m in (self.measure, self.numerator, self.denominator) if m]

    @property
    def models(self) -> set[str]:
        return {m.model for m in self.measures}

    def formula(self) -> str:
        def show(m: Measure) -> str:
            return f"{m.agg}({m.expr}) from {m.model}, rolled up over time by {m.time_agg}"
        if self.type == "ratio":
            return f"[{show(self.numerator)}] / [{show(self.denominator)}]"
        return show(self.measure)


@dataclass(frozen=True)
class SavedQuery:
    name: str
    title: str
    description: str
    phrases: tuple[str, ...]
    query: dict


@dataclass
class Catalog:
    dimensions: dict[str, str]
    models: dict[str, SemanticModel]
    metrics: dict[str, Metric]
    saved_queries: dict[str, SavedQuery] = field(default_factory=dict)

    def metric(self, name: str) -> Metric:
        key = name.strip().lower()
        if key not in self.metrics:
            raise SemanticError(f"Unknown metric '{name}'. Available: {', '.join(sorted(self.metrics))}")
        return self.metrics[key]


def _resolve_measure(ref: str, models: dict[str, SemanticModel], metric: str) -> Measure:
    model_name, _, measure_name = ref.partition(".")
    if model_name not in models or measure_name not in models[model_name].measures:
        raise SemanticError(f"Metric '{metric}' references unknown measure '{ref}'")
    return models[model_name].measures[measure_name]


def load_catalog(directory: Path = SEMANTIC_DIR) -> Catalog:
    spec = yaml.safe_load((directory / "metrics.yml").read_text())
    dimensions = {k: v.get("description", "") for k, v in spec["dimensions"].items()}

    models: dict[str, SemanticModel] = {}
    for name, m in spec["semantic_models"].items():
        unknown = set(m["dimensions"]) - set(dimensions)
        if unknown:
            raise SemanticError(f"Semantic model '{name}' uses undeclared dimensions {sorted(unknown)}")
        measures = {}
        for mname, mspec in m["measures"].items():
            if mspec["agg"] not in AGGS or mspec["time_agg"] not in TIME_AGGS:
                raise SemanticError(f"Measure {name}.{mname} has an invalid agg or time_agg")
            measures[mname] = Measure(name, mname, str(mspec["expr"]), mspec["agg"], mspec["time_agg"])
        models[name] = SemanticModel(name, m["table"], m["time_column"], tuple(m["dimensions"]), measures)

    metrics: dict[str, Metric] = {}
    for name, ms in spec["metrics"].items():
        if ms["format"] not in FORMATS:
            raise SemanticError(f"Metric '{name}' has invalid format '{ms['format']}'")
        common = dict(name=name, label=ms["label"], type=ms["type"], format=ms["format"],
                      description=ms["description"], owner=ms.get("owner", ""),
                      certified=bool(ms.get("certified", False)), synonyms=tuple(ms.get("synonyms", [])))
        if ms["type"] == "simple":
            metrics[name] = Metric(**common, measure=_resolve_measure(ms["measure"], models, name))
        elif ms["type"] == "ratio":
            metrics[name] = Metric(**common, numerator=_resolve_measure(ms["numerator"], models, name),
                                   denominator=_resolve_measure(ms["denominator"], models, name))
        else:
            raise SemanticError(f"Metric '{name}' has unknown type '{ms['type']}'")
        if len(metrics[name].models) > 1:
            raise SemanticError(f"Metric '{name}' mixes semantic models; define it within one model")

    saved: dict[str, SavedQuery] = {}
    saved_path = directory / "saved_queries.yml"
    if saved_path.exists():
        for name, sq in yaml.safe_load(saved_path.read_text())["saved_queries"].items():
            for metric in sq["query"]["metrics"]:
                if metric not in metrics:
                    raise SemanticError(f"Saved query '{name}' uses unknown metric '{metric}'")
            saved[name] = SavedQuery(name, sq["title"], sq["description"], tuple(sq.get("phrases", [])), sq["query"])

    return Catalog(dimensions, models, metrics, saved)
