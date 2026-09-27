"""Konfigurations-Ladung (Plan §9: configs/*.yaml).

Alle Pfade sind relativ zum cartogram-pipeline-Wurzelverzeichnis.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

BASE_DIR = Path(__file__).resolve().parents[2]  # cartogram-pipeline/

CONFIG_FILES = ("entities.yaml", "pipeline.yaml", "solver.yaml", "visualization.yaml")

#: Zielkennzahl -> Export-Varianten-Ordner (dist/cartogram/<dir> bzw.
#: web/public/cartogram/<dir>). Der Renderer lädt v1 vollständig und
#: die positions.f32 der weiteren Varianten zusätzlich (gleiche Topologie).
VARIANT_DIRS = {
    "world_share": "v1",
    "energy_consumption": "v2",
    "per_capita_energy_consumption": "v3",
}

#: Anzeigelabels der Varianten (Renderer + Dokumentation)
VARIANT_LABELS = {
    "world_share": "Bevölkerungsanteil",
    "energy_consumption": "Gesamtenergie",
    "per_capita_energy_consumption": "Energie pro Kopf",
}


def _load_yaml(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _resolve(base: Path, value: str | Path) -> Path:
    p = Path(value)
    return p if p.is_absolute() else (base / p).resolve()


def file_sha256(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def config_hash(cfg: "PipelineConfig") -> str:
    """Hash über alle Konfigurationsdateien (Cache-Invalidierung, Plan §4)."""
    h = hashlib.sha256()
    for name in CONFIG_FILES:
        h.update(name.encode())
        h.update(file_sha256(BASE_DIR / "configs" / name).encode())
    return h.hexdigest()[:16]


@dataclass
class PipelineConfig:
    raw_csv: Path
    natural_earth: Path
    natural_earth_url: str
    intermediate: Path
    build_cache: Path
    dist: Path
    web_public: Path | None

    year_min: int
    year_max: int
    share_tolerance: float
    remainder_tolerance: float
    other_world_id: str

    crs: str
    exclude_features: list[str]
    simplify_tolerance_m: float
    vertex_precision_m: float

    test_years: list[int]
    warm_start: bool
    transition_samples: list[float]
    insert_intermediate_frames: bool
    max_area_error_p90: float
    max_vertex_displacement_share: float

    solver_chain: list[str]
    flow: dict = field(default_factory=dict)
    legacy_tiles: dict = field(default_factory=dict)
    visualization: dict = field(default_factory=dict)

    #: Zielkennzahl der Kartogramm-Fläche (data.target_metric in
    #: pipeline.yaml). Bestimmt, worauf die Fläche jeder Entität
    #: normiert wird – und damit den Export-Varianten-Ordner.
    target_metric: str = "world_share"
    max_inverted_area_fraction: float = 0.08
    min_target_share: float = 0.0
    max_area_error_p90_early: float = 0.12
    early_years_until: int = 1870
    max_inverted_area_fraction_early: float = 0.20
    # Reserviert (wird aktuell nicht als hartes Kriterium verwendet;
    # Degeneration wird über die Faltflächen-Quote erfasst)
    min_triangle_area_frac: float = 1.0e-9

    def area_error_threshold(self, year: float) -> float:
        """Jahres-abhängiger p90-Flächenfehler-Schwellwert."""
        if year < self.early_years_until:
            return self.max_area_error_p90_early
        return self.max_area_error_p90

    @property
    def variant_dir(self) -> str:
        """Export-Ordner der Zielkennzahl (dist/cartogram/<variant>)."""
        try:
            return VARIANT_DIRS[self.target_metric]
        except KeyError:
            raise ValueError(
                f"Unbekannte Zielkennzahl '{self.target_metric}' – "
                f"erlaubt: {sorted(VARIANT_DIRS)}") from None

    def inverted_fraction_threshold(self, year: float) -> float:
        """Jahres-abhängiger Schwellwert für die gefaltete Fläche."""
        if year < self.early_years_until:
            return max(self.max_inverted_area_fraction,
                       self.max_inverted_area_fraction_early)
        return self.max_inverted_area_fraction

    @property
    def years(self) -> list[int]:
        return list(range(self.year_min, self.year_max + 1))


def load_config(target_metric: str | None = None) -> PipelineConfig:
    entities = _load_yaml(BASE_DIR / "configs" / "entities.yaml")
    pipeline = _load_yaml(BASE_DIR / "configs" / "pipeline.yaml")
    solver = _load_yaml(BASE_DIR / "configs" / "solver.yaml")
    viz = _load_yaml(BASE_DIR / "configs" / "visualization.yaml")

    paths = pipeline["paths"]
    data = pipeline["data"]
    geo = pipeline["geometry"]
    temporal = pipeline["temporal"]
    quality = temporal["quality"]

    web_public = paths.get("web_public")
    return PipelineConfig(
        raw_csv=_resolve(BASE_DIR, paths["raw_csv"]),
        natural_earth=_resolve(BASE_DIR, paths["natural_earth"]),
        natural_earth_url=paths["natural_earth_url"],
        intermediate=_resolve(BASE_DIR, paths["intermediate"]),
        build_cache=_resolve(BASE_DIR, paths["build_cache"]),
        dist=_resolve(BASE_DIR, paths["dist"]),
        web_public=_resolve(BASE_DIR, web_public) if web_public else None,
        year_min=int(data["year_min"]),
        year_max=int(data["year_max"]),
        share_tolerance=float(data["share_tolerance"]),
        remainder_tolerance=float(data["remainder_tolerance"]),
        other_world_id=data["other_world_id"],
        min_target_share=float(data.get("min_target_share", 0.0)),
        target_metric=target_metric or data.get("target_metric", "world_share"),
        crs=geo["crs"],
        exclude_features=list(geo["exclude_features"]),
        simplify_tolerance_m=float(geo["simplify_tolerance_m"]),
        vertex_precision_m=float(geo["vertex_precision_m"]),
        test_years=[int(y) for y in temporal["test_years"]],
        warm_start=bool(temporal["warm_start"]),
        transition_samples=[float(t) for t in temporal["transition_samples"]],
        insert_intermediate_frames=bool(temporal["insert_intermediate_frames"]),
        max_area_error_p90=float(quality["max_area_error_p90"]),
        max_vertex_displacement_share=float(quality["max_vertex_displacement_share"]),
        min_triangle_area_frac=float(
            quality.get("min_triangle_area_frac", 1.0e-9)),
        max_inverted_area_fraction=float(quality.get("max_inverted_area_fraction", 0.08)),
        max_area_error_p90_early=float(quality.get("max_area_error_p90_early", 0.12)),
        early_years_until=int(quality.get("early_years_until", 1870)),
        max_inverted_area_fraction_early=float(
            quality.get("max_inverted_area_fraction_early", 0.20)),
        solver_chain=list(solver["solver_chain"]),
        flow=dict(solver.get("flow") or {}),
        legacy_tiles=dict(solver.get("legacy_tiles") or {}),
        visualization=dict(viz),
    )


def load_entity_registry() -> dict:
    """Rohes Entitäten-Register (entities.yaml)."""
    return _load_yaml(BASE_DIR / "configs" / "entities.yaml")
