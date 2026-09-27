"""Ingest: bereinigtes CSV -> validiertes, kanonisches Parquet (Plan §5.1)."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .config import PipelineConfig
from .entities import EntityRegistry
from .schema import (
    CANONICAL_COLUMNS,
    RAW_COLUMNS,
    ValidationError,
    validate_raw,
    validate_year_shares,
)


def load_raw(cfg: PipelineConfig) -> pd.DataFrame:
    df = pd.read_csv(cfg.raw_csv)
    missing = [c for c in RAW_COLUMNS if c not in df.columns]
    if missing:
        raise ValidationError(f"Fehlende Spalten in {cfg.raw_csv.name}: {missing}")
    return df


def ensure_other_world(df: pd.DataFrame, registry: EntityRegistry,
                       cfg: PipelineConfig) -> pd.DataFrame:
    """OTHER_WORLD prüfen oder ergänzen (Plan §2, §5.6 Schritt 2).

    Falls der Datensatz OTHER_WORLD enthält, wird dessen Anteil gegen
    remainder_share geprüft (validate_year_shares). Andernfalls wird die
    Entität aus der Differenz Weltbevölkerung - Summe erfasster Länder
    erzeugt.
    """
    ow = registry.other_world()
    if (df["Country"] == ow.source_names[0]).any():
        return df

    rows = []
    for year, g in df.groupby("Year"):
        represented = g["Population"].sum()
        world = g["World_population"].iloc[0]
        remainder_pop = float(world - represented)
        if remainder_pop < 0:
            raise ValidationError(
                f"{year}: Weltbevölkerung {world} < Summe der Länder {represented}"
            )
        rows.append({
            "Country": ow.source_names[0],
            "Macroarea": np.nan,
            "Year": int(year),
            "Population": remainder_pop,
            "Energy_consumption": np.nan,
            "World_population": float(world),
            "World_share": remainder_pop / world,
            "Per_capita_energy_consumption": np.nan,
        })
    other = pd.DataFrame(rows, columns=RAW_COLUMNS)
    return pd.concat([df, other], ignore_index=True)


def build_canonical(cfg: PipelineConfig, registry: EntityRegistry) -> pd.DataFrame:
    """CSV -> kanonischer DataFrame (entity_id + year ist der Schlüssel)."""
    raw = load_raw(cfg)
    raw = ensure_other_world(raw, registry, cfg)

    validate_raw(raw, cfg.year_min, cfg.year_max, cfg.share_tolerance)
    validate_year_shares(raw, registry.other_world().source_names[0],
                         cfg.remainder_tolerance)

    unresolved = sorted(
        name for name in raw["Country"].unique()
        if registry.by_source(name) is None
    )
    if unresolved:
        raise ValidationError(
            f"Keine Entität im Register für Quellnamen: {unresolved}"
        )

    # Entitäten ohne Daten (z.B. Israel vor 1950) sind erlaubt: sie werden
    # im Solver passiv behandelt und im Renderer ohne Werte dargestellt.
    missing_sources = sorted(
        e.id for e in registry
        if not e.source_names and not e.is_other_world
    )
    if missing_sources:
        raise ValidationError(f"Entitäten ohne Quellnamen: {missing_sources}")

    raw = raw.copy()
    raw["entity_id"] = raw["Country"].map(lambda c: registry.by_source(c).id)
    raw["country_name"] = raw["Country"]
    raw["macroarea"] = raw["Macroarea"].fillna("")
    raw["is_other_world"] = raw["entity_id"] == cfg.other_world_id

    out = raw.rename(columns={
        "Year": "year",
        "Population": "population",
        "Energy_consumption": "energy_consumption",
        "World_population": "world_population",
        "World_share": "world_share",
        "Per_capita_energy_consumption": "per_capita_energy_consumption",
    })

    out = out[CANONICAL_COLUMNS].sort_values(
        ["entity_id", "year"], kind="stable").reset_index(drop=True)

    # Kanonische Invarianten
    assert not out.duplicated(subset=["entity_id", "year"]).any()
    assert set(out["year"]) == set(cfg.years)
    return out


def run_ingest(cfg: PipelineConfig, registry: EntityRegistry) -> Path:
    """CSV -> data/intermediate/canonical.parquet."""
    df = build_canonical(cfg, registry)
    cfg.intermediate.mkdir(parents=True, exist_ok=True)
    out = cfg.intermediate / "canonical.parquet"
    df.to_parquet(out, index=False)
    print(f"[ingest] {len(df)} Zeilen, {df['entity_id'].nunique()} Entitäten, "
          f"{df['year'].min()}-{df['year'].max()} -> {out}")
    return out


def load_canonical(cfg: PipelineConfig) -> pd.DataFrame:
    path = cfg.intermediate / "canonical.parquet"
    if not path.is_file():
        raise FileNotFoundError(
            f"{path} fehlt – zuerst 'ingest' ausführen."
        )
    return pd.read_parquet(path)


def targets_for_year(canonical: pd.DataFrame, registry: EntityRegistry,
                     year: int, min_target_share: float = 0.0,
                     metric: str = "world_share"
                     ) -> tuple[np.ndarray, np.ndarray]:
    """Zielgewichte je Entität + passive Maske für ein Jahr.

    metric (Kartogramm-Fläche, siehe pipeline.yaml data.target_metric):
      - "world_share": Anteil an der Weltbevölkerung (Standard).
      - "energy_consumption": Anteil am Gesamtweltenergieverbrauch.
      - "per_capita_energy_consumption": Anteil am Wert Energie pro
        Kopf (Fläche proportional zum Pro-Kopf-Verbrauch).

    Für energy-Varianten gelten Entitäten ohne Messwert in der
    gewählten Kennzahl als passiv (kein Ziel, Dichte 1 im Flow-Solver,
    sie driften mit und behalten näherungsweise ihre Fläche) – z.B.
    OTHER_WORLD und Israel vor 1950. Da der Solver die Zielflächen
    auf die Summe der aktiven Entitäten normiert (carto_flow.solve),
    bleibt die Gesamtkartenfläche erhalten.

    Rückgabe: (targets, passive) – Länge = Anzahl Entitäten, Reihenfolge
    wie das Register. Entitäten ohne Zeile im Jahr (Israel vor 1950)
    oder mit Anteil 0 sind passiv: kein Ziel, Dichte 1 im Flow-Solver.

    min_target_share > 0: Zielanteile werden auf diesen Anteil
    aufgestockt (Water-Filling; die verbleibenden Entitäten werden
    entsprechend renormiert, die Summe bleibt 1).
    Grund: Anteile unterhalb der Auflösung des 110m-Mesh (z.B. Panama
    1820 mit 9.5e-7 = 128 km² Zielfläche, kleiner als eine Gitter-
    zelle) sind geometrisch nicht darstellbar; die Abweichung ist im
    Manifest und Qualitätsbericht dokumentiert.
    """
    valid_metrics = ("world_share", "energy_consumption",
                     "per_capita_energy_consumption")
    if metric not in valid_metrics:
        raise ValueError(
            f"Unbekannte Zielkennzahl '{metric}' – erlaubt: {valid_metrics}")

    n = len(registry)
    targets = np.zeros(n, dtype=float)
    have_data = np.zeros(n, dtype=bool)

    g = canonical[canonical["year"] == year]
    by_id = g.set_index("entity_id")[metric]
    for i, e in enumerate(registry):
        if e.id not in by_id.index:
            continue
        v = float(by_id.loc[e.id])
        if np.isfinite(v) and v > 0:
            targets[i] = v
            have_data[i] = True

    # Kennzahl-Summe normieren (world_share ist bereits normiert)
    total = float(targets.sum())
    if total > 0:
        targets /= total
    else:
        # Keine Daten in dieser Kennzahl für dieses Jahr (z.B. Energie
        # vor 1820 in wenigen Ländern): alle Entitäten passiv, die
        # Karte bleibt in diesem Jahr unverzerrt.
        return targets, np.ones(n, dtype=bool)

    passive = ~have_data

    if min_target_share > 0:
        targeted = have_data & (targets > 0)
        small = targeted & (targets < min_target_share)
        if small.any():
            n_small = int(small.sum())
            targets[small] = min_target_share
            rest = targeted & ~small
            rest_sum = targets[rest].sum()
            if rest_sum > 0:
                budget = 1.0 - n_small * min_target_share
                targets[rest] *= budget / rest_sum

    return targets, passive
