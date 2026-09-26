"""Tests: Solver + Qualitätsprüfung + Zeitkohärenz (Plan §5.4–5.6)."""
from __future__ import annotations

import numpy as np
import pytest

from worldcarto.ingest import targets_for_year
from worldcarto.quality import (check_transition, validate_keyframe)
from worldcarto.solvers import resolve_chain
from worldcarto.solvers.carto_flow import CartoFlowSolver


@pytest.fixture(scope="module")
def flow_fast():
    """Flow-Solver mit reduziertem Gitter für Testlaufzeiten."""
    return CartoFlowSolver({
        "grid_width": 512, "blur_sigma": 2.5, "steps": 50,
        "max_iterations": 6, "area_tolerance": 0.03,
    })


@pytest.fixture(scope="module")
def targets_2020(canonical, registry):
    return targets_for_year(canonical, registry, 2020)


def test_chain_resolves_to_flow(cfg):
    solver, errors = resolve_chain(cfg.solver_chain, config=cfg.flow)
    # cartogram_cpp ist auf Python 3.13 nicht installierbar -> carto_flow
    assert solver.name == "carto_flow"
    assert errors, "cartogram_cpp sollte als nicht verfügbar gemeldet werden"


def test_flow_direct_solve(mesh, targets_2020, flow_fast):
    targets, passive = targets_2020
    result = flow_fast.solve(mesh, targets, passive)
    assert result.positions.shape == mesh.positions.shape

    def p90(pos):
        areas = mesh.areas(pos)
        targeted = ~passive & (targets > 0)
        scale = areas[targeted].sum() / targets[targeted].sum()
        err = np.abs(areas - targets * scale)[targeted] / (targets * scale)[targeted]
        return float(np.quantile(err, 0.9))

    after = p90(result.positions)
    before = p90(mesh.positions)
    # Nach der Lösung deutlich besser als der Startzustand
    assert after < 0.35
    assert after < 0.5 * before


def test_flow_no_inversions(mesh, targets_2020, flow_fast, cfg):
    """Fold-Kriterium: gefaltete Fläche bleibt unter dem Schwellwert."""
    from worldcarto.triangulate import triangle_areas
    targets, passive = targets_2020
    result = flow_fast.solve(mesh, targets, passive)
    signed = triangle_areas(mesh, result.positions)
    inverted = signed <= 0
    total = float(np.abs(signed).sum())
    frac = float(np.abs(signed[inverted]).sum() / total) if inverted.any() else 0.0
    assert frac < cfg.max_inverted_area_fraction


def test_flow_preserves_vertex_count(mesh, targets_2020, flow_fast):
    targets, passive = targets_2020
    result = flow_fast.solve(mesh, targets, passive)
    assert result.positions.shape == mesh.positions.shape


def test_legacy_tiles_solve(mesh, targets_2020):
    """Makro-Cluster-Port: Struktur, Determinismus, Tile-Verteilung.

    Entity-Flächen sind in diesem Vergleichsmodus an Clustergrenzen
    näherungsweise (siehe legacy_tiles.py Docstring) – geprüft wird,
    was der Modus garantiert: exakte Tile-Budgets, stabile Topologie,
    deterministische Ausgaben und ein nichttriviales Layout.
    """
    from worldcarto.solvers.legacy_tiles import LegacyTilesSolver
    solver = LegacyTilesSolver({"total_tiles": 800, "iterations": 60})
    targets, passive = targets_2020
    result = solver.solve(mesh, targets, passive)

    # Struktur: identische Vertex-Anzahl und Reihenfolge
    assert result.positions.shape == mesh.positions.shape
    assert np.isfinite(result.positions).all()

    # Deterministisch
    result2 = solver.solve(mesh, targets, passive)
    assert np.allclose(result.positions, result2.positions)

    # Nichttriviales Layout: Cluster verschoben (nicht die reine Skala)
    displacement = np.linalg.norm(
        result.positions - mesh.positions, axis=1)
    assert displacement.max() > 1e5  # Meter: deutliche Transformation

    # Statistikfelder vorhanden
    assert result.stats["mode"] == "macroarea_tiles"
    assert "errors" in result.stats


def test_legacy_allocates_exact_total():
    from worldcarto.solvers.legacy_tiles import allocate_tile_counts
    values = np.array([0.5, 0.3, 0.15, 0.05])
    counts = allocate_tile_counts(values, 100)
    assert counts.sum() == 100
    assert (counts >= 1).all()


def test_quality_validate_keyframe(mesh, targets_2020, cfg):
    targets, passive = targets_2020
    # Ungelöster Startzustand: Flächenfehler über der Schwelle
    report = validate_keyframe(mesh, mesh.positions, targets, passive, cfg)
    assert report.p90_error > 0
    # Aber strukturell valide
    assert report.inverted_triangles == 0
    assert report.torn_adjacencies == []


def test_transition_check_detects_inversion(mesh):
    """Endpunkt-gültige Konstruktion, deren MITTE mehr Inversionen hat.

    Pro Dreieck wird B nur entlang x und C nur entlang y bewegt (A
    fest): die Dreiecksfläche ist dann ein quadratisches Polynom in t,
    das an beiden Endpunkten positiv und nur dazwischen negativ sein
    kann – genau der Fall, den die Übergangsprüfung erkennen soll.
    """
    s = 3e6
    pos_a = mesh.positions.copy()
    pos_b = mesh.positions.copy()
    used = set()
    for (ia, ib, ic) in mesh.triangles:
        if ia in used or ib in used or ic in used:
            continue
        A = mesh.positions[ia]
        pos_a[ib] = [A[0] - 0.3 * s, A[1]]
        pos_b[ib] = [A[0] + 0.7 * s, A[1]]
        pos_a[ic] = [A[0], A[1] - 0.7 * s]
        pos_b[ic] = [A[0], A[1] + 0.3 * s]
        used.update([ia, ib, ic])
    bad = check_transition(mesh, pos_a, pos_b, [0.5])
    assert 0.5 in bad


def test_transition_check_smooth_interpolation_ok(mesh):
    """Sanfte Kontraktion erzeugt keine neuen Inversionen."""
    bad = check_transition(mesh, mesh.positions, mesh.positions * 0.98,
                           [0.5])
    assert bad == []


def test_transition_check_small_flip_tolerated(mesh):
    """Ein einzelner Sliver-Flip bleibt unter der Margin."""
    pos_a = mesh.positions.copy()
    tri = mesh.triangles[0]
    pos_b = mesh.positions.copy()
    pos_b[tri[0]] = mesh.positions[tri[2]]
    pos_b[tri[2]] = mesh.positions[tri[0]]
    bad = check_transition(mesh, pos_a, pos_b, [0.5])
    assert bad == []


def test_solve_year_candidates(mesh, canonical, registry, cfg):
    """Kandidaten-Maschinerie: Direct + Warm-Start, Auswahl des Besten."""
    from worldcarto.temporal import solve_year
    cfg_fast = _fast_cfg(cfg)
    solver = CartoFlowSolver({
        "grid_width": 256, "blur_sigma": 1.2, "steps": 40,
        "max_iterations": 3, "area_tolerance": 0.05,
    })
    targets, passive = targets_for_year(canonical, registry, 2020)
    prev = mesh.positions * 1.02  # simulierter Vorjahres-Keyframe
    positions, stats, reports = solve_year(
        mesh, targets, passive, cfg_fast, solver, prev, 2020)
    assert "direct" in reports
    assert positions.shape == mesh.positions.shape
    assert stats["candidate"] in reports


def _fast_cfg(cfg):
    """Kopie der Konfiguration mit entspannten Schwellen für Tests."""
    import copy
    c = copy.copy(cfg)
    c.warm_start = True
    c.max_area_error_p90 = 0.30  # grobes Testgitter
    return c
