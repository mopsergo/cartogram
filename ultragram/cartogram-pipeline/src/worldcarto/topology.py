"""Kanonisches Mesh (Plan §5.5) und Topologie.

Ein gemeinsames Mesh wird einmal erzeugt:
- feste Vertex-IDs (global dedupliziert, gemeinsame Grenzvertices)
- feste Ringe je Entität (Exterior + Holes)
- feste Dreiecksindizes (siehe triangulate.py)
- feste Regionszuordnung
- keine jährliche Neutriangulierung

Da Natural Earth 110m Grenzvertices exakt teilt, führen benachbarte
Entitäten dieselben Vertex-IDs – gemeinsame Grenzen bleiben beim
Verformen gekoppelt (Plan §5.3 „gemeinsame Grenzen aufbauen").
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pyproj
import shapely
from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import unary_union


@dataclass
class Mesh:
    num_entities: int
    entity_ids: list[str]
    num_vertices: int

    #: Kanonische Ausgangspositionen (Equal Earth, Meter) – (V, 2)
    positions: np.ndarray
    #: Originale Längen-/Breitengrade je Vertex – (V, 2) Grad
    lonlat: np.ndarray

    #: Ringe: Liste von (entity_index, vertex_ids, is_hole)
    rings: list[tuple[int, np.ndarray, bool]]
    #: Polygon-Teile je Entität: [(exterior_ring_local_index, [hole_indices...])]
    entity_parts: list[list[tuple[int, list[int]]]]

    #: Dreiecke (T, 3) – je Entität zusammenhängend
    triangles: np.ndarray
    #: Entitäts-Index je Dreieck (T,)
    triangle_entity: np.ndarray
    #: (start_triangle, count) je Entität (E, 2)
    entity_ranges: np.ndarray

    #: Adjazenzgraph über gemeinsame Vertices: Menge je Entität
    adjacency: list[set[int]]

    #: Ausdehnung der Entitäten (Equal Earth, Meter)
    bounds: tuple[float, float, float, float]
    #: Volle Equal-Earth-Weltbounds (Ozean inklusive) – Gitterbasis
    world_bounds: tuple[float, float, float, float]

    #: Name je Ring (z.B. Natural-Earth-Ländername der Polygon-Teile
    #: von OTHER_WORLD; None = Entitätsname verwenden)
    ring_names: list[str | None] | None = None
    #: Exterior-Ring-Index je Dreieck (Tooltip/Panel: Dreieck -> Land)
    triangle_ring: "np.ndarray | None" = None

    def polygons(self, positions: np.ndarray) -> list[MultiPolygon | Polygon | None]:
        """Shapely-Polygone je Entität aus gegebenen Vertex-Positionen."""
        return polygons_for_mesh(self, positions)

    def areas(self, positions: np.ndarray) -> np.ndarray:
        """Flächen je Entität (0 für leere Entitäten)."""
        out = np.zeros(self.num_entities, dtype=float)
        for i, poly in enumerate(polygons_for_mesh(self, positions)):
            if poly is not None and not poly.is_empty:
                out[i] = poly.area
        return out

    def ring_vertex_mask(self) -> np.ndarray:
        """Maske der Vertices, die in mindestens einem Ring liegen."""
        mask = np.zeros(self.num_vertices, dtype=bool)
        for _, ids, _ in self.rings:
            mask[ids] = True
        return mask


def _iter_parts(geom):
    """Polygon-Teile eines (Multi-)Polygons in deterministischer Reihenfolge."""
    parts = []
    if geom.geom_type == "Polygon":
        parts = [geom]
    elif geom.geom_type == "MultiPolygon":
        parts = list(geom.geoms)
    # Deterministische Reihenfolge: Fläche absteigend, dann Bounds
    parts.sort(key=lambda p: (-p.area, p.bounds[0], p.bounds[1]))
    return parts


def build_mesh(gdf, entity_ids: list[str], vertex_precision_m: float = 1e-3,
               crs: str = "EPSG:8857", max_edge_m: float = 0.0) -> Mesh:
    """Kanonisches Mesh aus den projizierten Entitätsgeometrien.

    gdf: GeoDataFrame in cfg.crs, Reihenfolge == entity_ids.
    max_edge_m: > 0 -> Ringkanten werden auf diese Maximallänge
        unterteilt (adaptive Kantensubdivision). Erhöht die Auflösung
        des Mesh dort, wo die 110m-Generalisierung zu grob für starke
        Cartogramm-Verformungen ist; geteilte Grenzkanten erhalten
        identische Zwischenvertices (dedupliziert über Koordinaten).
    """
    n = len(entity_ids)
    assert len(gdf) == n

    prec = vertex_precision_m
    xs: list[float] = []
    ys: list[float] = []
    index: dict[tuple[int, int], int] = {}

    def vid(x: float, y: float) -> int:
        key = (int(round(x / prec)), int(round(y / prec)))
        i = index.get(key)
        if i is None:
            i = len(xs)
            index[key] = i
            xs.append(float(x))
            ys.append(float(y))
        return i

    def ring_ids(ring) -> list[int]:
        coords = list(ring.coords)
        if len(coords) > 1 and coords[0] == coords[-1]:
            coords = coords[:-1]
        return [vid(x, y) for x, y in coords]

    rings: list[tuple[int, np.ndarray, bool]] = []
    ring_names: list[str | None] = []
    entity_parts: list[list[tuple[int, list[int]]]] = []
    # Ländernamen je Polygon-Teil (geometry.py, Spalte part_names);
    # nur OTHER_WORLD führt echte Namen, sonst leer -> None
    names_col = (gdf["part_names"].tolist()
                 if hasattr(gdf, "columns") and "part_names" in gdf.columns
                 else None)

    for ei in range(n):
        geom = gdf.geometry.iloc[ei]
        ent_names = (names_col[ei] if names_col is not None
                     and ei < len(names_col) else []) or []
        parts = []
        for pi, poly in enumerate(_iter_parts(geom)):
            if poly.is_empty:
                continue
            name = ent_names[pi] if pi < len(ent_names) else None
            ext = ring_ids(poly.exterior)
            if len(ext) < 3:
                continue
            ext_idx = len(rings)
            rings.append((ei, np.asarray(ext, dtype=np.int64), False))
            ring_names.append(name)
            holes = []
            for interior in poly.interiors:
                h = ring_ids(interior)
                if len(h) >= 3:
                    h_idx = len(rings)
                    rings.append((ei, np.asarray(h, dtype=np.int64), True))
                    ring_names.append(name)
                    holes.append(h_idx)
            parts.append((ext_idx, holes))
        if not parts:
            raise ValueError(f"{entity_ids[ei]}: keine gültigen Polygon-Teile")
        entity_parts.append(parts)

    # --- Adaptive Kantensubdivision (optional) ----------------------
    if max_edge_m > 0:
        subdivided = []
        for ei, ids, is_hole in rings:
            new_ids = []
            m = len(ids)
            for k in range(m):
                a = int(ids[k])
                b = int(ids[(k + 1) % m])
                new_ids.append(a)
                ax, ay = xs[a], ys[a]
                bx, by = xs[b], ys[b]
                dist = math.hypot(bx - ax, by - ay)
                steps = int(math.ceil(dist / max_edge_m))
                for s in range(1, steps):
                    t = s / steps
                    new_ids.append(vid(ax + t * (bx - ax), ay + t * (by - ay)))
            subdivided.append((ei, np.asarray(new_ids, dtype=np.int64), is_hole))
        rings = subdivided

    positions = np.column_stack([np.asarray(xs), np.asarray(ys)])
    n_vertices = len(xs)

    # Originale Lon/Lat je kanonischem Vertex (für Globus + Referenz).
    # Rückprojektion der Vertexpositionen ist exakt und strukturunabhängig.
    inv = pyproj.Transformer.from_crs(
        pyproj.CRS.from_user_input(gdf.crs), pyproj.CRS.from_epsg(4326),
        always_xy=True)
    lon, lat = inv.transform(positions[:, 0], positions[:, 1])
    lonlat = np.column_stack([np.asarray(lon), np.asarray(lat)])

    # Adjazenz über gemeinsche Vertices (Plan §5.6: unveränderter
    # Adjazenzgraph – strukturell durch geteilte Vertex-IDs garantiert).
    vertex_entities: list[set[int]] = [set() for _ in range(n_vertices)]
    for ei, ids, _ in rings:
        for v in ids:
            vertex_entities[int(v)].add(ei)
    adjacency: list[set[int]] = [set() for _ in range(n)]
    for ves in vertex_entities:
        if len(ves) > 1:
            for a in ves:
                adjacency[a].update(ves.difference({a}))

    minx, miny = positions.min(axis=0)
    maxx, maxy = positions.max(axis=0)

    return Mesh(
        num_entities=n,
        entity_ids=list(entity_ids),
        num_vertices=n_vertices,
        positions=positions,
        lonlat=lonlat,
        rings=rings,
        entity_parts=entity_parts,
        triangles=np.zeros((0, 3), dtype=np.int64),  # gesetzt von triangulate
        triangle_entity=np.zeros(0, dtype=np.int64),
        entity_ranges=np.zeros((n, 2), dtype=np.int64),
        adjacency=adjacency,
        bounds=(float(minx), float(miny), float(maxx), float(maxy)),
        world_bounds=equal_earth_world_bounds(gdf.crs),
        ring_names=ring_names,
    )


def equal_earth_world_bounds(crs) -> tuple[float, float, float, float]:
    """Volle Equal-Earth-Weltbounds (für das Solver-Gitter inkl. Ozean).

    Pseudozylindrisch: maximale |x| am Äquator bei ±180°, maximale |y|
    an den Polen. Für andere CRS wird die bounding box der Projektion
    der Kugel-Halbachsen verwendet (hier nur für Equal Earth benutzt).
    """
    tr = pyproj.Transformer.from_crs(
        pyproj.CRS.from_epsg(4326), pyproj.CRS.from_user_input(crs),
        always_xy=True)
    x_eq, _ = tr.transform(180.0, 0.0)
    _, y_pole = tr.transform(0.0, 90.0)
    x_eq = abs(float(x_eq))
    y_pole = abs(float(y_pole))
    return (-x_eq, -y_pole, x_eq, y_pole)


def polygons_for_mesh(mesh: Mesh, positions: np.ndarray):
    """Shapely-(Multi-)Polygone je Entität aus Vertex-Positionen."""
    out: list[MultiPolygon | Polygon | None] = []
    x = positions[:, 0]
    y = positions[:, 1]
    for ei in range(mesh.num_entities):
        polys = []
        for ext_idx, hole_idxs in mesh.entity_parts[ei]:
            _, ext, _ = mesh.rings[ext_idx]
            shell = np.column_stack([x[ext], y[ext]])
            holes = [
                np.column_stack([x[mesh.rings[h][1]], y[mesh.rings[h][1]]])
                for h in hole_idxs
            ]
            try:
                p = shapely.polygons(shell, holes=holes or None)
            except Exception:
                p = None
            if p is not None and not p.is_empty:
                polys.append(p)
        if not polys:
            out.append(None)
        else:
            merged = polys[0] if len(polys) == 1 else MultiPolygon(polys)
            out.append(merged)
    return out
