"""Jahres-Keyframes (Plan §5.6) mit Build-Cache.

Für jedes Jahr 1820 bis 2020:
1. Zielgewicht World_share laden
2. OTHER_WORLD prüfen (bereits im Ingest, Plan §2)
3. Direct Solve vom kanonischen Ausgangszustand
4. Optional Warm-Start vom Vorjahr (pipeline.yaml: temporal.warm_start)
5. Beide Kandidaten validieren (quality.validate_keyframe)
6. Besten gültigen Kandidaten speichern

Übergangsprüfung: lineare Vertex-Interpolation zwischen zwei Keyframes
auf Dreiecksinversion prüfen; im Fehlerfall löst Python einen zusätz-
lichen Zwischen-Keyframe mit gemittelten Zielgewichten (Plan §5.6).

Alle Ergebnisse werden in build-cache/ je Jahr gespeichert; der Cache
ist über Solver- und Konfigurations-Hash versioniert (Plan §4).
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np

from .config import PipelineConfig
from .ingest import load_canonical, targets_for_year
from .quality import KeyframeReport, check_transition, validate_keyframe
from .topology import Mesh


def _solver_hash(cfg: PipelineConfig, mesh_hash: str) -> str:
    import hashlib
    h = hashlib.sha256()
    h.update(mesh_hash.encode())
    h.update(json.dumps(cfg.solver_chain, sort_keys=True).encode())
    h.update(json.dumps(cfg.flow, sort_keys=True).encode())
    h.update(json.dumps(cfg.legacy_tiles, sort_keys=True).encode())
    h.update(str(cfg.warm_start).encode())
    h.update(str(cfg.max_area_error_p90).encode())
    return h.hexdigest()[:16]


def frames_index_path(cfg: PipelineConfig, mesh_hash: str) -> Path:
    """Pfad des Frame-Index (schlüsselführend für Cache-Treffer)."""
    return cfg.build_cache / "frames" / f"index_{_solver_hash(cfg, mesh_hash)}.json"


def _targets_hash(mesh: Mesh, targets: np.ndarray) -> str:
    import hashlib
    h = hashlib.sha256()
    h.update(np.asarray(targets, dtype=np.float64).tobytes())
    return h.hexdigest()[:16]


def solve_year(mesh: Mesh, targets: np.ndarray, passive: np.ndarray,
               cfg: PipelineConfig, solver,
               prev_positions: np.ndarray | None,
               year: float,
               force_repair: set[str] | None = None
               ) -> tuple[np.ndarray, dict, dict]:
    """Kandidaten rechnen, validieren, besten wählen.

    force_repair: Hysterese – Entitäts-IDs, die im Vorjahr repariert
    wurden und repariert bleiben (siehe repair.py: pro Entität
    höchstens EIN Moduswechsel Flow->starr, kein jährliches Flackern).

    Rückgabe: (positions, stats, reports) – reports: name -> KeyframeReport.
    """
    from .quality import pick_best

    candidates: dict[str, object] = {"direct": solver.solve(
        mesh, targets, passive, initial_positions=None)}
    threshold = cfg.area_error_threshold(year)
    fold_threshold = cfg.inverted_fraction_threshold(year)
    reports: dict[str, KeyframeReport] = {
        "direct": validate_keyframe(
            mesh, candidates["direct"].positions, targets, passive, cfg,
            prev_positions=prev_positions,
            max_area_error_p90=threshold,
            max_inverted_fraction=fold_threshold)}

    if cfg.warm_start and prev_positions is not None:
        warm = solver.solve(mesh, targets, passive,
                            initial_positions=prev_positions)
        candidates["warm"] = warm
        reports["warm"] = validate_keyframe(
            mesh, warm.positions, targets, passive, cfg,
            prev_positions=prev_positions,
            max_area_error_p90=threshold,
            max_inverted_fraction=fold_threshold)

    name, report = pick_best(reports)
    if name is None:
        raise RuntimeError(f"Jahr {year}: kein Kandidat berechenbar")

    chosen = candidates[name]
    positions = chosen.positions
    stats = dict(chosen.stats)
    stats["candidate"] = name

    # --- Reparatur: ungültige Polygone durch starr skalierte
    # Originalformen ersetzen (siehe repair.py), danach neu bewerten.
    from .repair import repair_invalid_polygons
    positions, repaired, repair_info = repair_invalid_polygons(
        mesh, positions, targets, passive,
        force_repair=force_repair or set())
    if repaired:
        stats["repaired_entities"] = repaired
        stats["repair_info"] = repair_info
        report = validate_keyframe(mesh, positions, targets, passive, cfg,
                                   prev_positions=prev_positions,
                                   max_area_error_p90=threshold,
                                   max_inverted_fraction=fold_threshold)
        # Qualitätsdaten nach der Reparatur führen (nicht die
        # Flow-Vorlösung)
        stats["errors"] = report.area_errors
        stats["p90_error"] = report.p90_error
        stats["max_error"] = report.max_error
    if report.warnings:
        stats["quality_warnings"] = report.warnings

    if not report.valid:
        # Kein Kandidat erfüllt alle Kriterien: den besten trotzdem
        # nehmen, aber die Probleme dokumentieren (Qualitätsbericht).
        stats["quality_problems"] = report.problems
        print(f"[temporal] WARNUNG Jahr {year}: Kandidat {name} ungültig: "
              f"{report.problems}")

    return positions, stats, reports


def _cache_path(cache_dir: Path, year: float) -> Path:
    """Cache-Datei je Frame (Jahreswerte inkl. Zwischen-Keyframes)."""
    return cache_dir / f"frame_{year}.npz".replace(".", "_")


def _jsonable(obj):
    """Macht Solver-Statistik JSON-serialisierbar (ndarray -> Liste)."""
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()
                if k not in ("errors", "history")}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, (np.floating, np.integer)):
        return obj.item()
    return obj


def build_keyframes(cfg: PipelineConfig, mesh: Mesh, solver,
                    years: list[int] | None = None,
                    mesh_hash: str = "mesh",
                    canonical: object = None,
                    progress: bool = True) -> list[dict]:
    """Keyframes für alle Jahre erzeugen (mit Cache + Übergangsprüfung).

    Rückgabe: Liste von Frames:
        {"year": 1950.0, "positions": (V,2), "stats": {...}, "intermediate": False}
    """
    if canonical is None:
        canonical = load_canonical(cfg)
    if years is None:
        years = cfg.years

    from .entities import load_registry
    registry = load_registry()

    from .temporal import frames_index_path as _index_path
    cache_dir = cfg.build_cache / "frames"
    cache_dir.mkdir(parents=True, exist_ok=True)
    index_path = _index_path(cfg, mesh_hash)
    index = {}
    if index_path.is_file():
        index = json.loads(index_path.read_text())

    frames: list[dict] = []
    prev_positions: np.ndarray | None = None
    prev_targets: np.ndarray | None = None
    prev_passive: np.ndarray | None = None
    prev_year: float | None = None
    repaired_ids: set[str] = set()  # Hysterese (siehe repair.py)

    t0 = time.time()
    for pos_year in years:
        targets, passive = targets_for_year(
            canonical, registry, pos_year,
            min_target_share=cfg.min_target_share)
        floored = [
            mesh.entity_ids[i] for i in range(mesh.num_entities)
            if not passive[i] and targets[i] > 0
            and targets[i] <= cfg.min_target_share * (1 + 1e-9)
        ]
        thash = _targets_hash(mesh, targets)
        ck = f"{pos_year:.4f}:{thash}"

        if ck in index and (cache_dir / index[ck]["file"]).is_file():
            data = np.load(cache_dir / index[ck]["file"])
            positions = data["positions"]
            stats = json.loads(str(data["stats_json"]))
            stats["errors"] = np.asarray(data["errors"])
            stats["from_cache"] = True
            repaired_ids = set(stats.get("repaired_entities", []))
        else:
            positions, stats, _ = solve_year(
                mesh, targets, passive, cfg, solver,
                prev_positions if cfg.warm_start else None, pos_year,
                force_repair=repaired_ids)
            stats["from_cache"] = False
            stats["floored_entities"] = floored
            repaired_ids = set(stats.get("repaired_entities", []))
            fname = f"frame_{index_path.stem}_{pos_year}.npz"
            np.savez_compressed(
                cache_dir / fname, positions=positions,
                stats_json=json.dumps(_jsonable(stats)),
                errors=np.asarray(stats["errors"]),
                targets=targets, passive=passive)
            index[ck] = {"file": fname, "year": pos_year}
            index_path.write_text(json.dumps(index))

        frames.append({"year": float(pos_year), "positions": positions,
                       "stats": stats, "intermediate": False,
                       "targets": targets, "passive": passive})
        if progress:
            p90 = stats.get("p90_error")
            p90s = f"{p90:.4f}" if isinstance(p90, float) else "?"
            print(f"[temporal] {pos_year}: {stats.get('candidate', '?')} "
                  f"p90={p90s} iter={stats.get('iterations', '?')} "
                  f"({stats.get('seconds', '?')}s)"
                  + (" [Cache]" if stats.get("from_cache") else ""))

        # --- Übergangsprüfung zum Vorjahr (Plan §5.6)
        if prev_positions is not None and cfg.insert_intermediate_frames:
            bad = check_transition(mesh, prev_positions, positions,
                                   cfg.transition_samples)
            if bad:
                mid = (prev_year + pos_year) / 2.0
                print(f"[temporal] Übergang {prev_year}->{pos_year} invertiert "
                      f"bei t={bad}; löse Zwischen-Keyframe {mid}")
                mid_targets = 0.5 * (prev_targets + targets)
                mid_passive = passive & prev_passive
                mid_pos, mid_stats, _ = solve_year(
                    mesh, mid_targets, mid_passive, cfg, solver, None, mid,
                    force_repair=repaired_ids)
                frames.append({"year": mid, "positions": mid_pos,
                               "stats": mid_stats, "intermediate": True,
                               "targets": mid_targets,
                               "passive": mid_passive})

        prev_positions = positions
        prev_targets = targets
        prev_passive = passive
        prev_year = float(pos_year)

    # Zwischen-Keyframes einsortieren (jährigen Rahmen lassen)
    frames.sort(key=lambda f: f["year"])

    if progress:
        n_inter = sum(1 for f in frames if f["intermediate"])
        print(f"[temporal] {len(frames)} Keyframes ({n_inter} Zwischen-"
              f"keyframes), {time.time() - t0:.0f}s")
    return frames
