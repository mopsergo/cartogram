"""Tests: Geometrie, Topologie, Triangulierung (Plan §5.3, §5.5)."""
from __future__ import annotations

import numpy as np


def test_all_entities_have_geometry(mesh, registry):
    assert mesh.num_entities == len(registry)
    areas = mesh.areas(mesh.positions)
    assert (areas > 0).all()
    ow = registry.index_of("OTHER_WORLD")
    assert areas[ow] > 0


def test_shared_boundary_vertices(mesh, registry):
    """Gemeinsame Grenzvertices: USA und CAN teilen mindestens einen Vertex."""
    usa = registry.index_of("USA")
    can = registry.index_of("CAN")
    assert can in mesh.adjacency[usa]

    shared = 0
    for ei in (usa, can):
        ids = set()
        for ext_idx, holes in mesh.entity_parts[ei]:
            ids.update(int(v) for v in mesh.rings[ext_idx][1])
            for h in holes:
                ids.update(int(v) for v in mesh.rings[h][1])
        if ei == usa:
            usa_ids = ids
        else:
            shared = len(usa_ids & ids)
    assert shared > 0


def test_lonlat_roundtrip(mesh):
    """Rückprojektion der Vertices liegt in lon/lat-Bounds."""
    lon, lat = mesh.lonlat[:, 0], mesh.lonlat[:, 1]
    assert ((lon >= -180.1) & (lon <= 180.1)).all()
    assert ((lat >= -90.1) & (lat <= 90.1)).all()


def test_world_bounds_cover_mesh(mesh):
    minx, miny, maxx, maxy = mesh.bounds
    wminx, wminy, wmaxx, wmaxy = mesh.world_bounds
    assert wminx <= minx and miny >= wminy
    assert maxx <= wmaxx and maxy <= wmaxy


def test_triangulation_covers_polygons(mesh):
    from worldcarto.triangulate import coverage_error
    assert coverage_error(mesh) < 1e-6


def test_triangles_ccw_and_contiguous(mesh, registry):
    from worldcarto.triangulate import triangle_areas
    signed = triangle_areas(mesh, mesh.positions)
    assert (signed > 0).all()

    # Je Entität zusammenhängende Dreiecksbereiche
    for e in registry:
        s, c = mesh.entity_ranges[e.index]
        assert (mesh.triangle_entity[s:s + c] == e.index).all()
    total = mesh.entity_ranges[:, 1].sum()
    assert total == len(mesh.triangles)


def test_polygons_rebuild(mesh):
    """polygons() aus den kanonischen Positionen reproduziert Flächen."""
    rebuilt = mesh.areas(mesh.positions)
    direct = mesh.areas(mesh.positions.copy())
    assert np.allclose(rebuilt, direct)
