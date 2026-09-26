"""legacy_tiles – Recycelter Tile-Prototyp aus bassogram (Plan §4).

Portierung von bassogram/cartogram_macroarea_temporal_3a.py auf das
kanonische Mesh und den Solver-Vertrag. Der Bassogram-Prototyp legte
MACROAREA-Cluster als Tile-Mengen (Anzahl via Largest-Remainder aus
den Zielgewichten, Größe über TILE_SIZE) und löste deren Layout mit
einem Kraftmodell (Anker-Feder, Overlap-Repulsion entlang der
minimalen Translation, Nachbar-Anziehung, Dämpfung) plus harte
Overlapprojektion; Positionen wurden über Jahre warmgestartet.

Übernommen 1:1 (Makroebene):
- allocate_tile_counts: Floor + Largest-Remainder, Summe exakt
- Kraftmodell + _project_overlaps (Gauss-Seidel, tiefste Überlappung
  zuerst, gewichtet mit Tile-Zahlen)
- Warm-Start über die Clusterpositionen des Vorjahres

Anpassung an das kanonische Mesh (dokumentiert):
- Statt Tile-Raster: Form-erhaltende Rigid-Skalierung jedes Makro-
  clusters auf seine Ziel-Tilfläche (das Mesh liefert die Fein-
  geometrie; das Sampling echter Kacheln entfällt). Alle Entitäten
  eines Clusters erhalten dieselbe Transform, damit geteilte Grenz-
  vertices innerhalb des Clusters konsistent bleiben.
- Die LÄNDER-Feinverteilung des Prototyps (Tile-Partition innerhalb
  eines Makroclusters) ist auf dem gemeinsamen Mesh nicht darstellbar
  (eine Vertexposition je ID); Entitäten behalten innerhalb ihres
  Clusters ihre geografische Flächenrelation.
- OTHER_WORLD ist im Tile-Look der feste Hintergrundrahmen (kein
  eigener Cluster, keine Skalierung): Er umschließt alle Cluster und
  hat als zusammenhängende Hülle keine sinnvolle Rigid-Transform.
- Grenzen ZWISCHEN Clustern können aufreißen – wie die getrennten
  Tile-Cluster des Prototyps.

Modus für visuelle Vergleiche, schnelle Prototypen und
Regressionstests – nicht der primäre Produktions-Solver.
"""
from __future__ import annotations

import math

import numpy as np

from ..topology import Mesh
from . import SolveResult, register_solver

DEFAULTS = {
    "total_tiles": 3000,
    "iterations": 400,
    "overlap_strength": 0.3,
    "neighbor_strength": 0.8,
    "anchor_strength": 0.9,
    "damping": 0.8,
}


def allocate_tile_counts(values: np.ndarray, total: int) -> np.ndarray:
    """Floor + Largest-Remainder: Summe der Tiles == total, min 1.

    Port von allocate_tile_counts aus dem Bassogram-Prototyp.
    """
    values = np.asarray(values, dtype=float)
    shares = values / values.sum() * total
    counts = np.maximum(np.floor(shares), 1).astype(int)
    remainder = shares - np.floor(shares)

    diff = total - int(counts.sum())
    if diff > 0:
        idx = np.argsort(-remainder)[:diff]
        counts[idx] += 1
    elif diff < 0:
        eligible = np.nonzero(counts > 1)[0]
        order = eligible[np.argsort(remainder[eligible])[:abs(diff)]]
        counts[order] -= 1
    return counts


@register_solver
class LegacyTilesSolver:
    name = "legacy_tiles"
    version = "1.0.0"

    def __init__(self, config: dict | None = None):
        self.cfg = {**DEFAULTS, **(config or {})}

    def solve(self, mesh: Mesh, targets: np.ndarray, passive: np.ndarray,
              initial_positions: np.ndarray | None = None) -> SolveResult:
        import pandas as pd  # nur für die Cluster-Tabelle

        cfg = self.cfg
        targets = np.asarray(targets, dtype=float)
        passive = np.asarray(passive, dtype=bool)
        targeted = ~passive & (targets > 0)
        if not targeted.any():
            raise ValueError("Keine Entität mit Zielgewicht")

        n_e = mesh.num_entities
        clusters = _macro_clusters(mesh)
        n_c = len(clusters)

        # --- Zielgewicht je Cluster (Summe der Entitätsanteile) ------
        cluster_targets = np.zeros(n_c)
        for ci in range(n_c):
            cluster_targets[ci] = sum(
                targets[ei] for ei in clusters[ci] if targeted[ei])

        entity_areas = mesh.areas(mesh.positions)
        total_land = float(entity_areas.sum())
        total_tiles = int(cfg["total_tiles"])
        tile_area = total_land / total_tiles
        counts = allocate_tile_counts(cluster_targets, total_tiles)

        # --- Vertices je Cluster (alle Ringvertices der Entitäten) ---
        cluster_vertices: list[np.ndarray] = []
        for ci in range(n_c):
            ids = set()
            for ei in clusters[ci]:
                for ext_idx, holes in mesh.entity_parts[ei]:
                    ids.update(int(v) for v in mesh.rings[ext_idx][1])
                    for h in holes:
                        ids.update(int(v) for v in mesh.rings[h][1])
            cluster_vertices.append(np.asarray(sorted(ids), dtype=int))

        # --- Cluster-Anker (geografischer Schwerpunkt) ---------------
        centroids = np.zeros((n_c, 2))
        for ci in range(n_c):
            ids = cluster_vertices[ci]
            centroids[ci] = mesh.positions[ids].mean(axis=0)

        # --- Skalierungsfaktoren auf Ziel-Tilfläche -------------------
        factors = np.ones(n_c)
        for ci in range(n_c):
            area = float(sum(entity_areas[ei] for ei in clusters[ci]))
            if area > 1e-9:
                factors[ci] = math.sqrt(counts[ci] * tile_area / area)

        # --- Cluster-Bounds (um den Schwerpunkt skaliert) --------------
        records = []
        for ci in range(n_c):
            ids = cluster_vertices[ci]
            c = centroids[ci]
            xy = c + (mesh.positions[ids] - c) * factors[ci]
            anchor = centroids[ci]
            start = anchor
            if initial_positions is not None:
                start = initial_positions[ids].mean(axis=0)
            records.append({
                "cluster": ci,
                "n_tiles": int(counts[ci]),
                "factor": factors[ci],
                "anchor_x": anchor[0], "anchor_y": anchor[1],
                "x": start[0], "y": start[1],
                "minx": float(xy[:, 0].min()), "miny": float(xy[:, 1].min()),
                "maxx": float(xy[:, 0].max()), "maxy": float(xy[:, 1].max()),
            })
        table = pd.DataFrame(records)

        # --- Nachbarschaft: Cluster mit gemeinsamen Vertices ----------
        vertex_cluster = np.full(mesh.num_vertices, -1, dtype=int)
        for ci in range(n_c):
            vertex_cluster[cluster_vertices[ci]] = ci
        pairs = set()
        for ei in range(n_e):
            ids = set()
            for ext_idx, holes in mesh.entity_parts[ei]:
                ids.update(int(v) for v in mesh.rings[ext_idx][1])
                for h in holes:
                    ids.update(int(v) for v in mesh.rings[h][1])
            cs = {int(vertex_cluster[v]) for v in ids if vertex_cluster[v] >= 0}
            for a in cs:
                for b in cs:
                    if a < b:
                        pairs.add((a, b))

        self._optimize_clusters(
            table, sorted(pairs),
            n_iterations=int(cfg["iterations"]),
            overlap_strength=float(cfg["overlap_strength"]),
            neighbor_strength=float(cfg["neighbor_strength"]),
            anchor_strength=float(cfg["anchor_strength"]),
            damping=float(cfg["damping"]),
            max_step=float(max(table["maxx"] - table["minx"]) * 0.5),
        )

        # --- Finalize: Rigid-Transform je Cluster ---------------------
        # Grenzvertices zwischen Clustern: Mittel der beteiligten
        # Cluster-Transforms (visuell glattester Tile-Look; die
        # Nachbarn teilen sich den Grenzverlauf). Entity-Flächen
        # sind in diesem Vergleichsmodus bewusst näherungsweise – der
        # Prototyp re-tilete Länder innerhalb des Makroclusters, was
        # auf dem gemeinsamen Mesh (eine Position je Vertex-ID) nicht
        # darstellbar ist; die Aussage des Modus ist das Cluster-Layout.
        transforms: list[tuple[int, float, float, float]] = []
        for _, row in table.iterrows():
            ci = int(row["cluster"])
            transforms.append((ci, factors[ci],
                               row["x"] - row["anchor_x"],
                               row["y"] - row["anchor_y"]))

        acc = np.zeros_like(mesh.positions)
        cnt = np.zeros(mesh.num_vertices)
        for ci, f, dx, dy in transforms:
            ids = cluster_vertices[ci]
            c = centroids[ci]
            acc[ids, 0] += mesh.positions[ids, 0] * f + c[0] * (1 - f) + dx
            acc[ids, 1] += mesh.positions[ids, 1] * f + c[1] * (1 - f) + dy
            cnt[ids] += 1.0
        pos = mesh.positions.copy()
        has = cnt > 0
        pos[has] = acc[has] / cnt[has, None]

        # --- Statistik über Cluster-Flächenfehler ---------------------
        stats_errors = np.zeros(n_e)
        areas = mesh.areas(pos)
        scale = areas[targeted].sum() / targets[targeted].sum()
        stats_errors[targeted] = (
            np.abs(areas - targets * scale)[targeted]
            / np.maximum((targets * scale)[targeted], 1e-12))
        stats = {
            "candidate": "warm" if initial_positions is not None else "direct",
            "p90_error": float(np.quantile(stats_errors[targeted], 0.9)),
            "max_error": float(stats_errors[targeted].max()),
            "errors": stats_errors,
            "iterations": int(cfg["iterations"]),
            "mode": "macroarea_tiles",
            "note": ("Vergleichsmodus: Entity-Flächenfehler sind an "
                     "Clustergrenzen näherungsweise (gemeinsames Mesh); "
                     "Aussage ist das Makro-Cluster-Layout."),
        }
        return SolveResult(positions=pos, stats=stats)

    # ------------------------------------------------------ Optimizer

    @staticmethod
    def _optimize_clusters(clusters, pairs, n_iterations,
                           overlap_strength, neighbor_strength,
                           anchor_strength, damping, max_step):
        """Force-Layout + Overlap-Projektion (Port aus bassogram)."""
        n = len(clusters)
        velocity = np.zeros((n, 2))
        x_col = clusters.columns.get_loc("x")
        y_col = clusters.columns.get_loc("y")

        def bounds(i):
            r = clusters.iloc[i]
            dx = r["x"] - r["anchor_x"]
            dy = r["y"] - r["anchor_y"]
            return (r["minx"] + dx, r["miny"] + dy,
                    r["maxx"] + dx, r["maxy"] + dy)

        for _ in range(n_iterations):
            forces = np.zeros((n, 2))

            # A. Anker-Feder
            for i in range(n):
                r = clusters.iloc[i]
                forces[i, 0] += anchor_strength * (r["anchor_x"] - r["x"])
                forces[i, 1] += anchor_strength * (r["anchor_y"] - r["y"])

            # B. Overlap-Repulsion entlang der MTV
            for i in range(n):
                b_i = bounds(i)
                for j in range(i + 1, n):
                    b_j = bounds(j)
                    ox = min(b_i[2], b_j[2]) - max(b_i[0], b_j[0])
                    oy = min(b_i[3], b_j[3]) - max(b_i[1], b_j[1])
                    if ox <= 0 or oy <= 0:
                        continue
                    if ox <= oy:
                        s = 1.0 if clusters.iloc[j]["x"] >= clusters.iloc[i]["x"] else -1.0
                        ux, uy, push = s, 0.0, ox * overlap_strength
                    else:
                        s = 1.0 if clusters.iloc[j]["y"] >= clusters.iloc[i]["y"] else -1.0
                        ux, uy, push = 0.0, s, oy * overlap_strength
                    forces[i, 0] -= ux * push
                    forces[i, 1] -= uy * push
                    forces[j, 0] += ux * push
                    forces[j, 1] += uy * push

            # C. Nachbar-Anziehung
            for i, j in pairs:
                r_i, r_j = clusters.iloc[i], clusters.iloc[j]
                dx = r_j["x"] - r_i["x"]
                dy = r_j["y"] - r_i["y"]
                dist = math.hypot(dx, dy)
                if dist < 1e-9:
                    continue
                desired = 0.5 * max(
                    (r_i["maxx"] - r_i["minx"]) + (r_j["maxx"] - r_j["minx"]),
                    (r_i["maxy"] - r_i["miny"]) + (r_j["maxy"] - r_j["miny"]))
                gap = dist - desired
                if gap <= 0:
                    continue
                ux, uy = dx / dist, dy / dist
                attraction = gap * neighbor_strength
                forces[i, 0] += ux * attraction
                forces[i, 1] += uy * attraction
                forces[j, 0] -= ux * attraction
                forces[j, 1] -= uy * attraction

            # D. Geschwindigkeit + Dämpfung + Schrittbegrenzung
            velocity = velocity * damping + forces
            speed = np.hypot(velocity[:, 0], velocity[:, 1])
            too_fast = speed > max_step
            if too_fast.any():
                velocity[too_fast] *= (max_step / speed[too_fast])[:, None]
            pos_start = clusters[["x", "y"]].to_numpy(dtype=float).copy()
            for i in range(n):
                clusters.iat[i, x_col] += velocity[i, 0]
                clusters.iat[i, y_col] += velocity[i, 1]

            # E. Overlap-Projektion (harte Nebenbedingung)
            LegacyTilesSolver._project_overlaps(clusters, bounds)

            # F. Geschwindigkeit aus der tatsächlichen Positionsänderung
            pos_end = clusters[["x", "y"]].to_numpy(dtype=float)
            velocity = pos_end - pos_start
            speed = np.hypot(velocity[:, 0], velocity[:, 1])
            too_fast = speed > max_step
            if too_fast.any():
                velocity[too_fast] *= (max_step / speed[too_fast])[:, None]

    @staticmethod
    def _project_overlaps(clusters, bounds, max_sweeps: int = 10):
        """Port von project_overlaps: tiefste Überlappung zuerst."""
        n = len(clusters)
        x_col = clusters.columns.get_loc("x")
        y_col = clusters.columns.get_loc("y")

        def scan():
            found = []
            for i in range(n):
                b_i = bounds(i)
                for j in range(i + 1, n):
                    b_j = bounds(j)
                    ox = min(b_i[2], b_j[2]) - max(b_i[0], b_j[0])
                    oy = min(b_i[3], b_j[3]) - max(b_i[1], b_j[1])
                    if ox > 0 and oy > 0:
                        found.append((min(ox, oy), i, j))
            return found

        for _ in range(max_sweeps):
            pairs = scan()
            if not pairs:
                return
            pairs.sort(key=lambda p: -p[0])
            for _, i, j in pairs:
                b_i = bounds(i)
                b_j = bounds(j)
                ox = min(b_i[2], b_j[2]) - max(b_i[0], b_j[0])
                oy = min(b_i[3], b_j[3]) - max(b_i[1], b_j[1])
                if ox <= 0 or oy <= 0:
                    continue
                mi = float(clusters.iloc[i]["n_tiles"])
                mj = float(clusters.iloc[j]["n_tiles"])
                mtot = mi + mj
                pen = min(ox, oy)
                if ox <= oy:
                    s = 1.0 if clusters.iloc[j]["x"] >= clusters.iloc[i]["x"] else -1.0
                    clusters.iat[i, x_col] -= s * pen * (mj / mtot)
                    clusters.iat[j, x_col] += s * pen * (mi / mtot)
                else:
                    s = 1.0 if clusters.iloc[j]["y"] >= clusters.iloc[i]["y"] else -1.0
                    clusters.iat[i, y_col] -= s * pen * (mj / mtot)
                    clusters.iat[j, y_col] += s * pen * (mi / mtot)


def _macro_clusters(mesh: Mesh) -> list[list[int]]:
    """Cluster je Makroregion; OTHER_WORLD bleibt Rahmen (kein Cluster)."""
    from ..entities import load_registry
    registry = load_registry()
    by_code: dict[str, list[int]] = {}
    for e in registry:
        if e.is_other_world:
            continue
        by_code.setdefault(e.macroarea, []).append(e.index)
    clusters = sorted(by_code.values(), key=lambda lst: lst[0])
    return clusters
