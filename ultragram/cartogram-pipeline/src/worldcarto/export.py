"""Exportvertrag für TypeScript (Plan §6).

    dist/cartogram/<variante>/          (v1/v2/v3, siehe config.VARIANT_DIRS)
    ├── manifest.json
    ├── entities.json
    ├── topology.bin        (Statische Topologie als Bundle, s. u.)
    ├── positions.f32       [numFrames, numVertices, 2]  Equal-Earth-Meter
    ├── values.f32          [numFrames, numEntities, 4]
    │                       (population, world_share, energy_consumption,
    │                        per_capita_energy_consumption; NaN = keine Daten)
    ├── labels.f32          [numFrames, numEntities, 2]  Label-Anker
    ├── indices.u32         [numTriangles, 3]            Dreiecke
    ├── surface_vertex_to_canonical.u32 [numVertices]    Identität
    ├── region_draw_ranges.u32 [numEntities, 2]          (start, count) Dreiecke
    ├── boundary_rings.u32  [numRings, ...]  (s. Layout im Manifest)
    ├── flags.u8            [numEntities]   Bitfield
    ├── positions_original.f32 [numVertices, 2]  unverzerrt, Equal Earth
    ├── vertices_lonlat.f32 [numVertices, 2]   unverzerrt, lon/lat
    └── quality.parquet     Qualitätsbericht je Frame/Entität

Die zwei *_original/lonlat-Dateien sind dokumentierte Erweiterungen des
Plans (für die Referenz-Ghost-Ebene und den Reference Globe) und im
Manifest mit Layout und Prüfsumme eingetragen.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from . import __version__
from .config import VARIANT_LABELS, PipelineConfig, file_sha256
from .entities import EntityRegistry
from .topology import Mesh

FORMAT = "ultragram.cartogram.v1"


def _write_u32(path: Path, arr: np.ndarray) -> np.ndarray:
    arr = np.ascontiguousarray(arr, dtype="<u4")
    path.write_bytes(arr.tobytes())
    return arr


def _write_f32(path: Path, arr: np.ndarray) -> np.ndarray:
    arr = np.ascontiguousarray(arr, dtype="<f4")
    path.write_bytes(arr.tobytes())
    return arr


def _write_u8(path: Path, arr: np.ndarray) -> np.ndarray:
    arr = np.ascontiguousarray(arr, dtype="<u1")
    path.write_bytes(arr.tobytes())
    return arr


def label_anchors(mesh: Mesh, positions: np.ndarray) -> np.ndarray:
    """Label-Anker je Entität: repräsentativer Innenpunkt (Shapely)."""
    anchors = np.zeros((mesh.num_entities, 2), dtype=np.float64)
    for ei, poly in enumerate(mesh.polygons(positions)):
        if poly is None or poly.is_empty:
            # Fallback: Schwerpunkt der Ringvertices
            ids = []
            for ext_idx, _ in mesh.entity_parts[ei]:
                ids.extend(int(v) for v in mesh.rings[ext_idx][1])
            if ids:
                anchors[ei] = positions[ids].mean(axis=0)
        else:
            c = poly.representative_point()
            anchors[ei] = (c.x, c.y)
    return anchors


def build_values(cfg: PipelineConfig, registry: EntityRegistry,
                 canonical: pd.DataFrame, frames: list[dict]) -> np.ndarray:
    """values.f32: [numFrames, numEntities, 4] – NaN = keine Daten."""
    n_e = len(registry)
    n_f = len(frames)
    values = np.full((n_f, n_e, 4), np.nan, dtype=np.float64)

    col = {"population": 0, "world_share": 1,
           "energy_consumption": 2, "per_capita_energy_consumption": 3}

    for fi, frame in enumerate(frames):
        year = frame["year"]
        g = canonical[canonical["year"] == year]
        if g.empty and frame.get("intermediate"):
            # Zwischen-Keyframe: lineare Interpolation der Nachbarjahre
            y0 = int(np.floor(year))
            g0 = canonical[canonical["year"] == y0]
            g1 = canonical[canonical["year"] == y0 + 1]
            for e in registry:
                v0 = g0[g0["entity_id"] == e.id]
                v1 = g1[g1["entity_id"] == e.id]
                if len(v0) and len(v1):
                    t = year - y0
                    for cname, ci in col.items():
                        values[fi, e.index, ci] = (
                            float(v0[cname].iloc[0]) * (1 - t)
                            + float(v1[cname].iloc[0]) * t)
            continue
        for e in registry:
            row = g[g["entity_id"] == e.id]
            if row.empty:
                continue  # NaN bleibt (passive Entität, z.B. Israel < 1950)
            row = row.iloc[0]
            for cname, ci in col.items():
                values[fi, e.index, ci] = float(row[cname])
    return values


def build_topology_bundle(mesh: Mesh) -> dict:
    """topology.bin – statisches Bundle: Magie, Sektionen, Offsets (u32/LE).

    Layout (alles little-endian):
      [0]        magic "WCTP" als 4 Bytes (u8-weise in u32 gepackt)
      [1]        Version (1)
      [2]        num_rings
      [3]        num_entities
      danach je Ring: owner_entity, num_vertices, v0..v{n-1}
    """
    parts: list[np.ndarray] = []
    header = np.array([
        int.from_bytes(b"WCTP", "little"), 1,
        len(mesh.rings), mesh.num_entities], dtype="<u4")
    parts.append(header)
    for ei, ids, _is_hole in mesh.rings:
        parts.append(np.array([ei, len(ids)], dtype="<u4"))
        parts.append(np.asarray(ids, dtype="<u4"))
    return np.concatenate(parts)


def export(cfg: PipelineConfig, registry: EntityRegistry, mesh: Mesh,
           frames: list[dict], canonical: pd.DataFrame,
           out_dir: Path | None = None) -> Path:
    """Alle Artefakte nach <dist>/cartogram/<variante> schreiben + kopieren.

    Der Varianten-Ordner folgt aus der Zielkennzahl (config.VARIANT_DIRS:
    world_share -> v1, energy_consumption -> v2,
    per_capita_energy_consumption -> v3). Die Topologie-Dateien
    (indices, rings, entities, values, ...) sind über alle Varianten
    identisch; positions.f32 und quality.parquet sind variante-
    spezifisch (gleiche Auflösung, anderer Flächenmaßstab).
    """
    variant = cfg.variant_dir
    out = (out_dir or cfg.dist / "cartogram" / variant)
    out.mkdir(parents=True, exist_ok=True)
    if frames:
        shutil.rmtree(out, ignore_errors=True)
        out.mkdir(parents=True, exist_ok=True)

    n_f = len(frames)
    n_e = mesh.num_entities
    n_v = mesh.num_vertices

    # --- positions.f32 -------------------------------------------------
    positions = np.stack([f["positions"] for f in frames]).astype(np.float32)
    _write_f32(out / "positions.f32", positions)

    # --- values.f32 -----------------------------------------------------
    values = build_values(cfg, registry, canonical, frames)
    _write_f32(out / "values.f32", values)

    # --- labels.f32 ----------------------------------------------------
    labels = np.zeros((n_f, n_e, 2), dtype=np.float64)
    for fi, frame in enumerate(frames):
        labels[fi] = label_anchors(mesh, frame["positions"])
    _write_f32(out / "labels.f32", labels)

    # --- indices.u32 ----------------------------------------------------
    _write_u32(out / "indices.u32", mesh.triangles)

    # --- surface_vertex_to_canonical.u32 --------------------------------
    _write_u32(out / "surface_vertex_to_canonical.u32",
               np.arange(n_v, dtype=np.uint32))

    # --- region_draw_ranges.u32 -----------------------------------------
    _write_u32(out / "region_draw_ranges.u32", mesh.entity_ranges)

    # --- boundary_rings.u32 ---------------------------------------------
    ring_parts = [np.array([len(mesh.rings)], dtype="<u4")]
    for ei, ids, is_hole in mesh.rings:
        ring_parts.append(np.array([ei, len(ids), int(bool(is_hole))],
                                   dtype="<u4"))
        ring_parts.append(np.asarray(ids, dtype="<u4"))
    _write_u32(out / "boundary_rings.u32", np.concatenate(ring_parts))

    # --- Ländernamen der Polygon-Teile (Tooltip/Panel: Dreieck -> Land)
    if mesh.triangle_ring is not None and mesh.ring_names is not None:
        _write_u32(out / "triangle_ring.u32", mesh.triangle_ring)
        (out / "ring_names.json").write_text(
            json.dumps({"names": list(mesh.ring_names)},
                       ensure_ascii=False),
            encoding="utf-8")

    # --- flags.u8 ---------------------------------------------------------
    flags = np.zeros(n_e, dtype=np.uint8)
    for e in registry:
        flags[e.index] = ((1 << 0) if e.is_other_world else 0) \
            | ((1 << 1) if e.historical_aggregate else 0)
    _write_u8(out / "flags.u8", flags)

    # --- topology.bin -----------------------------------------------------
    (out / "topology.bin").write_bytes(build_topology_bundle(mesh).tobytes())

    # --- Dokumentierte Erweiterungen: unverzerrte Basis ------------------
    _write_f32(out / "positions_original.f32", mesh.positions)
    _write_f32(out / "vertices_lonlat.f32", mesh.lonlat)

    # --- entities.json -----------------------------------------------------
    entities_json = {
        "entities": [
            {
                "index": e.index,
                "id": e.id,
                "display_name": e.display_name,
                "macroarea": e.macroarea,
                "macroarea_label": registry.macroarea_label(e.macroarea),
                "is_other_world": e.is_other_world,
                "historical_aggregate": e.historical_aggregate,
                "geometry_members": list(e.geometry_members),
                "note": e.note,
            }
            for e in registry
        ],
    }
    (out / "entities.json").write_text(
        json.dumps(entities_json, ensure_ascii=False, indent=1),
        encoding="utf-8")

    # --- quality.parquet ----------------------------------------------------
    quality_rows = []
    for fi, frame in enumerate(frames):
        stats = frame.get("stats", {})
        for e in registry:
            err = None
            if stats.get("errors") is not None:
                val = float(stats["errors"][e.index])
                err = val if not frame["passive"][e.index] else None
            quality_rows.append({
                "frame": fi,
                "year": frame["year"],
                "intermediate": frame.get("intermediate", False),
                "entity_id": e.id,
                "area_error": err,
                "passive": bool(frame["passive"][e.index]),
                "candidate": stats.get("candidate"),
                "solver_iterations": stats.get("iterations"),
                "p90_area_error": stats.get("p90_error"),
                "max_area_error": stats.get("max_error"),
                "repaired": json.dumps(stats.get("repaired_entities", [])),
                "floored": json.dumps(stats.get("floored_entities", [])),
                "quality_problems": json.dumps(
                    stats.get("quality_problems", [])),
                "quality_warnings": json.dumps(
                    stats.get("quality_warnings", [])),
            })
    pd.DataFrame(quality_rows).to_parquet(out / "quality.parquet", index=False)

    # --- manifest.json -------------------------------------------------------
    manifest = build_manifest(cfg, registry, mesh, frames, values, out)
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"[export] {n_f} Frames, {n_e} Entitäten, {n_v} Vertices, "
          f"{len(mesh.triangles)} Dreiecke -> {out}")
    print(f"[export] Zielkennzahl Fläche: {cfg.target_metric} "
          f"(Variante {variant})")

    # --- Kopie für den Web-Dev-Server (web/public/cartogram/<variante>).
    # web_public ist der Basis-Ordner; enthält der Pfad (alte
    # Konfiguration) bereits die Variante, wird sie nicht angehängt.
    if cfg.web_public is not None:
        web_out = (cfg.web_public if cfg.web_public.name == variant
                   else cfg.web_public / variant)
        web_out.mkdir(parents=True, exist_ok=True)
        for f in out.iterdir():
            if f.is_file():
                shutil.copy2(f, web_out / f.name)
        print(f"[export] Artefakte nach {web_out} kopiert")
    return out


def build_manifest(cfg: PipelineConfig, registry: EntityRegistry,
                   mesh: Mesh, frames: list[dict], values: np.ndarray,
                   out: Path) -> dict:
    n_f, n_e, _ = values.shape
    files = {}
    for f in sorted(out.iterdir()):
        if f.is_file() and f.name != "manifest.json":
            files[f.name] = {
                "bytes": f.stat().st_size,
                "sha256": file_sha256(f),
            }

    # Globale Wertebereiche für die Skalen (Plan §8)
    finite = np.isfinite(values)
    ranges = {}
    for ci, name in enumerate(["population", "world_share",
                               "energy_consumption",
                               "per_capita_energy_consumption"]):
        v = values[:, :, ci][finite[:, :, ci]]
        ranges[name] = {"min": float(v.min()) if v.size else None,
                        "max": float(v.max()) if v.size else None}

    viz = cfg.visualization
    color_cfg = viz.get("color", {})
    height_cfg = viz.get("height", {})

    return {
        "format": FORMAT,
        "artifact_version": cfg.variant_dir,
        "target_metric": cfg.target_metric,
        "target_metric_label": VARIANT_LABELS.get(cfg.target_metric,
                                                  cfg.target_metric),
        "data_version": __version__,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "years": {
            "data_range": [cfg.year_min, cfg.year_max],
            "frames": [
                {"index": i, "year": f["year"],
                 "intermediate": bool(f.get("intermediate", False))}
                for i, f in enumerate(frames)
            ],
        },
        "dimensions": {
            "num_frames": n_f,
            "num_entities": n_e,
            "num_vertices": mesh.num_vertices,
            "num_triangles": int(len(mesh.triangles)),
            "num_rings": len(mesh.rings),
        },
        "arrays": {
            "positions": {"file": "positions.f32", "dtype": "<f4",
                          "shape": [n_f, mesh.num_vertices, 2]},
            "values": {"file": "values.f32", "dtype": "<f4",
                       "shape": [n_f, n_e, 4],
                       "components": ["population", "world_share",
                                      "energy_consumption",
                                      "per_capita_energy_consumption"],
                       "nan": "keine Daten"},
            "labels": {"file": "labels.f32", "dtype": "<f4",
                       "shape": [n_f, n_e, 2]},
            "indices": {"file": "indices.u32", "dtype": "<u4",
                        "shape": [len(mesh.triangles), 3]},
            "surface_vertex_to_canonical": {
                "file": "surface_vertex_to_canonical.u32", "dtype": "<u4",
                "shape": [mesh.num_vertices],
                "note": "Identität – Dreiecke nutzen direkt kanonische IDs"},
            "region_draw_ranges": {
                "file": "region_draw_ranges.u32", "dtype": "<u4",
                "shape": [n_e, 2], "components": ["start_triangle", "count"]},
            "boundary_rings": {
                "file": "boundary_rings.u32", "dtype": "<u4",
                "layout": ("[numRings] dann je Ring [owner_entity, "
                           "num_vertices, is_hole, v0..v{n-1}]")},
            "triangle_ring": {
                "file": "triangle_ring.u32", "dtype": "<u4",
                "shape": [len(mesh.triangles)],
                "note": ("Exterior-Ring-Index je Dreieck – mit "
                         "ring_names.json zeigt Tooltip/Panel das "
                         "konkrete Land (Natural-Earth-Länder der "
                         "Restliche-Welt-Entität)")},
            "ring_names": {
                "file": "ring_names.json",
                "note": ("Ländername je Ring (null = Entitätsname "
                         "verwenden); ältere Läufe ohne diese Datei "
                         "fallen darauf zurück")},
            "flags": {"file": "flags.u8", "dtype": "<u1", "shape": [n_e],
                      "bits": {"0": "is_other_world",
                               "1": "historical_aggregate"}},
            "positions_original": {
                "file": "positions_original.f32", "dtype": "<f4",
                "shape": [mesh.num_vertices, 2],
                "note": "unverzerrte Equal-Earth-Basis (Ghost-Ebene)"},
            "vertices_lonlat": {
                "file": "vertices_lonlat.f32", "dtype": "<f4",
                "shape": [mesh.num_vertices, 2],
                "note": "unverzerrte Längen-/Breitengrade (Reference Globe)"},
        },
        "crs": {
            "name": "Equal Earth",
            "epsg": 8857,
            "units": "meters",
            "note": "flächentreue Pseudozylinderprojektion (Plan §5.3)",
        },
        "units": {
            "population": "Personen",
            "world_share": "Anteil an der Weltbevölkerung (0..1)",
            "energy_consumption": "Mtoe",
            "per_capita_energy_consumption": "kWh pro Kopf",
            "positions": "Meter (Equal Earth)",
        },
        "scales": {
            "area": {"metric": cfg.target_metric,
                     "label": VARIANT_LABELS.get(cfg.target_metric,
                                                 cfg.target_metric),
                     "note": ("Fläche = Anteil an der gewählten Zielkennzahl "
                              "(data.target_metric); Entitäten ohne Wert "
                              "dieser Kennzahl sind passiv und behalten "
                              "näherungsweise ihre Fläche")},
            "color": {
                "metric": color_cfg.get("metric"),
                "transform": color_cfg.get("transform"),
                "ramp": color_cfg.get("ramp"),
                "available_metrics": color_cfg.get("available_metrics"),
                "value_ranges": ranges,
            },
            "height": {
                "metric": height_cfg.get("metric"),
                "transform": height_cfg.get("transform"),
                "max_fraction": height_cfg.get("max_fraction"),
                "formula": ("height = transform(max(value, 0) / "
                            "year_max) * max_fraction * world_width; "
                            "year_max = Maximum der Höhenkennzahl im "
                            "aktuellen Jahr; transform im Renderer "
                            "umschaltbar: sqrt (Standard, empfindlich) "
                            "oder linear"),
            },
        },
        "solver": {
            "chain": cfg.solver_chain,
            "per_frame": [
                {"index": i, "year": f["year"],
                 "candidate": f.get("stats", {}).get("candidate"),
                 "iterations": f.get("stats", {}).get("iterations"),
                 "p90_area_error": f.get("stats", {}).get("p90_error")}
                for i, f in enumerate(frames)
            ],
        },
        "inputs": {
            "raw_csv": {
                "path": str(cfg.raw_csv),
                "sha256": file_sha256(cfg.raw_csv),
            },
            "natural_earth": {
                "path": str(cfg.natural_earth),
                "sha256": file_sha256(cfg.natural_earth),
            },
        },
        "files": files,
        "entities_file": "entities.json",
        "quality_file": "quality.parquet",
    }
