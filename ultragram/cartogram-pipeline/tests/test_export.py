"""Tests: Exportvertrag (Plan §6) – Layouts, Prüfsummen, Decodierung."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest


@pytest.fixture(scope="module")
def exported(cfg, registry, mesh, canonical, tmp_path_factory):
    from worldcarto.export import export
    from worldcarto.solvers.carto_flow import CartoFlowSolver

    out = tmp_path_factory.mktemp("dist") / "cartogram" / "v1"
    solver = CartoFlowSolver({
        "grid_width": 256, "blur_sigma": 1.2, "steps": 40,
        "max_iterations": 3, "area_tolerance": 0.05,
    })
    targets, passive = _targets(canonical, registry, 2020)
    result = solver.solve(mesh, targets, passive)
    frames = [{
        "year": 2020.0, "positions": result.positions,
        "stats": result.stats, "intermediate": False,
        "targets": targets, "passive": passive,
    }]
    cfg_nocopy = _no_web_copy(cfg)
    export(cfg_nocopy, registry, mesh, frames, canonical, out_dir=out)
    return out, frames


def _targets(canonical, registry, year):
    from worldcarto.ingest import targets_for_year
    return targets_for_year(canonical, registry, year)


def _no_web_copy(cfg):
    import copy
    c = copy.copy(cfg)
    c.web_public = None
    return c


def test_expected_files(exported):
    out, _ = exported
    expected = {
        "manifest.json", "entities.json", "topology.bin",
        "positions.f32", "values.f32", "labels.f32", "indices.u32",
        "surface_vertex_to_canonical.u32", "region_draw_ranges.u32",
        "boundary_rings.u32", "flags.u8", "quality.parquet",
        "positions_original.f32", "vertices_lonlat.f32",
    }
    names = {p.name for p in out.iterdir()}
    assert expected <= names, expected - names


def test_manifest_consistency(exported, mesh):
    out, _ = exported
    manifest = json.loads((out / "manifest.json").read_text())
    dims = manifest["dimensions"]
    assert dims["num_entities"] == mesh.num_entities
    assert dims["num_vertices"] == mesh.num_vertices
    assert dims["num_triangles"] == len(mesh.triangles)
    assert manifest["years"]["frames"][0]["year"] == 2020.0
    assert manifest["crs"]["epsg"] == 8857

    # Prüfsummenstimmen mit den Dateien überein
    for name, info in manifest["files"].items():
        data = (out / name).read_bytes()
        assert len(data) == info["bytes"], name
        assert hashlib.sha256(data).hexdigest() == info["sha256"], name


def test_positions_layout(exported, mesh):
    out, frames = exported
    data = np.fromfile(out / "positions.f32", dtype="<f4")
    n_f, n_v = len(frames), mesh.num_vertices
    assert data.size == n_f * n_v * 2
    pos = data.reshape(n_f, n_v, 2)
    assert np.isfinite(pos).all()


def test_values_layout_and_nan(exported, registry):
    out, _ = exported
    data = np.fromfile(out / "values.f32", dtype="<f4")
    values = data.reshape(1, len(registry), 4)
    ow = registry.index_of("OTHER_WORLD")
    isr = registry.index_of("ISR")
    assert np.isnan(values[0, ow, 2])      # OTHER_WORLD: keine Energie
    assert np.isnan(values[0, ow, 3])
    assert values[0, isr, 1] > 0           # Israel 2020: Weltanteil
    chn = registry.index_of("CHN")
    assert values[0, chn, 1] > 0.1         # China > 10% der Weltbevölkerung


def test_flags(exported, registry):
    out, _ = exported
    flags = np.fromfile(out / "flags.u8", dtype=np.uint8)
    assert int(flags[registry.index_of("OTHER_WORLD")]) & 1 == 1
    assert int(flags[registry.index_of("SUN")]) & 0b10  # historisch
    assert int(flags[registry.index_of("AUT")]) == 0


def test_boundary_rings_layout(exported, mesh):
    out, _ = exported
    data = np.fromfile(out / "boundary_rings.u32", dtype="<u4")
    num_rings = int(data[0])
    assert num_rings == len(mesh.rings)
    pos = 1
    total = 0
    for _ in range(num_rings):
        owner, n, is_hole = int(data[pos]), int(data[pos + 1]), int(data[pos + 2])
        assert 0 <= owner < mesh.num_entities
        assert n >= 3
        ids = data[pos + 3:pos + 3 + n]
        assert ids.max() < mesh.num_vertices
        total += n
        pos += 3 + n
    assert data.size == 1 + 3 * num_rings + total


def test_topology_bin_magic(exported):
    out, _ = exported
    data = (out / "topology.bin").read_bytes()
    assert data[:4] == b"WCTP"


def test_entities_json(exported, registry):
    out, _ = exported
    meta = json.loads((out / "entities.json").read_text())
    assert len(meta["entities"]) == len(registry)
    ids = [e["id"] for e in meta["entities"]]
    assert ids == registry.ids()
    assert meta["entities"][registry.index_of("SUN")]["historical_aggregate"]


def test_quality_parquet(exported):
    out, _ = exported
    import pandas as pd
    q = pd.read_parquet(out / "quality.parquet")
    assert len(q) == q["entity_id"].nunique()  # 1 Frame
    assert {"year", "entity_id", "area_error"} <= set(q.columns)
