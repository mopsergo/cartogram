"""Einmalige Triangulierung des kanonischen Mesh (Plan §5.5).

mapbox-earcut übernimmt Exterior + Holes je Polygon-Teil; benutzt
ausschließlich Ring-Vertices (keine Steiner-Punkte), sodass die
Dreiecksindizes direkt auf die kanonischen Vertex-IDs zeigen und die
Topologie für alle Jahres-Keyframes identisch bleibt.

Alle Dreiecke werden auf gegen den Uhrzeigersinn orientiert
(positive Signiertfläche) – Voraussetzung für konsistentes
Backface-Culling im Renderer.
"""
from __future__ import annotations

import numpy as np

import mapbox_earcut as earcut

from .topology import Mesh


def triangulate_mesh(mesh: Mesh) -> Mesh:
    """Setzt mesh.triangles / triangle_entity / entity_ranges (in place).

    Zusätzlich mesh.triangle_ring: Exterior-Ring-Index je Dreieck –
    ermöglicht die Zuordnung Dreieck -> Polygon-Teil (Ländername,
    siehe geometry.py / export.py ring_names).
    """
    all_tris: list[tuple[int, int, int]] = []
    tri_entity: list[int] = []
    tri_ring: list[int] = []
    ranges = np.zeros((mesh.num_entities, 2), dtype=np.int64)

    for ei in range(mesh.num_entities):
        start = len(all_tris)
        for ext_idx, hole_idxs in mesh.entity_parts[ei]:
            _, ext_ids, _ = mesh.rings[ext_idx]
            local_vids = list(int(v) for v in ext_ids)
            ends = [len(local_vids)]
            local_xy: list[tuple[float, float]] = []
            for v in ext_ids:
                local_xy.append((mesh.positions[int(v), 0],
                                 mesh.positions[int(v), 1]))
            for h_idx in hole_idxs:
                _, hole_ids, _ = mesh.rings[h_idx]
                for v in hole_ids:
                    local_xy.append((mesh.positions[int(v), 0],
                                     mesh.positions[int(v), 1]))
                local_vids.extend(int(v) for v in hole_ids)
                ends.append(len(local_vids))

            tris = earcut.triangulate_float64(
                np.asarray(local_xy, dtype=np.float64),
                np.asarray(ends, dtype=np.uint32))
            for t in range(0, len(tris), 3):
                a = local_vids[int(tris[t])]
                b = local_vids[int(tris[t + 1])]
                c = local_vids[int(tris[t + 2])]
                # Orientierung: CCW erzwingen (positive Signiertfläche)
                area = _signed_area(mesh.positions, a, b, c)
                if area < 0:
                    b, c = c, b
                all_tris.append((a, b, c))
                tri_entity.append(ei)
                tri_ring.append(ext_idx)
        ranges[ei] = (start, len(all_tris) - start)

    mesh.triangles = np.asarray(all_tris, dtype=np.int64)
    mesh.triangle_entity = np.asarray(tri_entity, dtype=np.int64)
    mesh.triangle_ring = np.asarray(tri_ring, dtype=np.int64)
    mesh.entity_ranges = ranges
    return mesh


def _signed_area(positions: np.ndarray, a: int, b: int, c: int) -> float:
    ax, ay = positions[a]
    bx, by = positions[b]
    cx, cy = positions[c]
    return 0.5 * ((bx - ax) * (cy - ay) - (cx - ax) * (by - ay))


def triangle_areas(mesh: Mesh, positions: np.ndarray) -> np.ndarray:
    """Signierte Flächen aller Dreiecke für gegebene Positionen."""
    tri = mesh.triangles
    p = positions
    a = p[tri[:, 0]]
    b = p[tri[:, 1]]
    c = p[tri[:, 2]]
    return 0.5 * ((b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1])
                  - (c[:, 0] - a[:, 0]) * (b[:, 1] - a[:, 1]))


def coverage_error(mesh: Mesh) -> float:
    """Max. relative Abweichung Dreiecksfläche vs. Polygonfläche je Entität.

    Prüft, dass die Triangulierung die Polygone vollständig abdeckt
    (Ear-Clipping deckt exakt; Abweichung ~ Rundung).
    """
    worst = 0.0
    poly_areas = mesh.areas(mesh.positions)
    for ei in range(mesh.num_entities):
        s, c = mesh.entity_ranges[ei]
        if c == 0:
            continue
        tri_area = float(np.abs(
            triangle_areas(mesh, mesh.positions)[s:s + c]).sum())
        ref = poly_areas[ei]
        if ref > 0:
            worst = max(worst, abs(tri_area - ref) / ref)
    return worst
