"""Reparatur ungültiger Polygone nach dem Solver-Lauf.

Starke Verformungen (Israel 7x-Expansion, Kanada 1820 ~150x-
Kontraktion) können Ring-Selbstüberschneidungen erzeugen. Für die
betroffenen Entitäten ersetzt die Reparatur die Verschiebung der
EIGENEN Ringvertices (Küstenlinien und interne Punkte, die zu genau
einer Entität gehören) durch eine starr skalierte Originalform:

    rigid(v) = anker_aktuell + (original(v) - anker_original) * f
    mit f = sqrt(zielfläche / originalfläche)

Stabilität über die Zeit (Animation):
- Anker je POLYGON-TEIL an der aktuellen Flow-Position des Teils
  (nicht am geografischen Ursprung): mehrteilige Entitäten wie
  OTHER_WORLD driften teilweise mit, und die reparierte Form bleibt
  dort, wo der Flow sie hingelegt hat – kein Zurückteleportieren.
- Hysterese: einmal reparierte Entitäten bleiben repariert
  (force_repair), solange die Reparatur gültige Polygone liefert.
  Dadurch gibt es pro Entität höchstens EINEN Moduswechsel (Flow ->
  starr) statt jährlichem Flackern zwischen beiden Darstellungen.
- Geteilte Grenzvertices behalten ihre Flow-Position: Nachbarn werden
  nicht gezerrt, Grenzen bleiben gekoppelt.
- Flächenkorrektur-Iteration: f wird 2-3x nachgestellt, bis die
  reparierte Fläche dem Ziel entspricht (Flow-Endpunkte können um
  10-20 % daneben liegen).
"""
from __future__ import annotations

import math

import numpy as np

from .topology import Mesh


def entity_ring_vertices(mesh: Mesh, ei: int) -> np.ndarray:
    ids: set[int] = set()
    for ext_idx, holes in mesh.entity_parts[ei]:
        ids.update(int(v) for v in mesh.rings[ext_idx][1])
        for h in holes:
            ids.update(int(v) for v in mesh.rings[h][1])
    return np.asarray(sorted(ids), dtype=int)


def _part_vertices(mesh: Mesh, ei: int) -> list[np.ndarray]:
    """Ringvertex-IDs je Polygon-Teil der Entität."""
    parts: list[np.ndarray] = []
    for ext_idx, hole_idxs in mesh.entity_parts[ei]:
        ids: set[int] = set(int(v) for v in mesh.rings[ext_idx][1])
        for h in hole_idxs:
            ids.update(int(v) for v in mesh.rings[h][1])
        parts.append(np.asarray(sorted(ids), dtype=int))
    return parts


def repair_invalid_polygons(mesh: Mesh, positions: np.ndarray,
                            targets: np.ndarray, passive: np.ndarray,
                            force_repair: set[str] = frozenset(),
                            max_passes: int = 3,
                            log=print) -> tuple[np.ndarray, list[str], dict]:
    """Repariert ungültige (oder forcierte) Entitäten.

    Rückgabe: (positions, repaired_ids, info) mit je Entität:
      info[eid] = {"anchor": (x, y) je Teil, "f": Skalierungsfaktor}
    für Diagnose/Qualitätsbericht.
    """
    positions = positions.copy()
    targeted = ~passive & (targets > 0)
    areas = mesh.areas(positions)
    scale = areas[targeted].sum() / max(targets[targeted].sum(), 1e-12)
    target_areas = targets * scale

    original_areas = mesh.areas(mesh.positions)
    repaired: set[str] = set()
    info: dict = {}

    # Vertex -> Anzahl besitzender Entitäten (nur Ringvertices zählen)
    vertex_use = np.zeros(mesh.num_vertices, dtype=int)
    for ei in range(mesh.num_entities):
        for v in entity_ring_vertices(mesh, ei):
            vertex_use[v] += 1

    for _ in range(max_passes):
        invalid = [
            ei for ei, poly in enumerate(mesh.polygons(positions))
            if poly is None or not poly.is_valid
        ]
        forced = [
            ei for ei in range(mesh.num_entities)
            if mesh.entity_ids[ei] in force_repair
            and mesh.entity_ids[ei] not in repaired
        ]
        todo = sorted(set(invalid) | set(forced))
        if not todo:
            break
        for ei in todo:
            eid = mesh.entity_ids[ei]
            if original_areas[ei] <= 0 or target_areas[ei] <= 0:
                continue
            if _repair_entity(mesh, positions, ei, target_areas[ei],
                              original_areas[ei], vertex_use, info, log):
                repaired.add(eid)

    return positions, sorted(repaired), info


def _repair_entity(mesh: Mesh, positions: np.ndarray, ei: int,
                   target_area: float, original_area: float,
                   vertex_use: np.ndarray,
                   info: dict, log) -> bool:
    """Starr skalierte Originalform an den aktuellen Flow-Ankern.

    True, wenn die Entität übernommen wurde (gültiges Polygon).
    """
    all_ids = entity_ring_vertices(mesh, ei)
    if not len(all_ids):
        return False
    parts = _part_vertices(mesh, ei)
    own = all_ids[vertex_use[all_ids] == 1]
    if not len(own):
        return False

    # Starre Zieldarstellung: Originalform je Teil um den aktuellen
    # Teil-Anker, Skalierung f auf die Zielfläche.
    def rigid_positions(f: float) -> np.ndarray:
        out = positions.copy()
        for part_ids in parts:
            cur_anchor = positions[part_ids].mean(axis=0)
            orig_anchor = mesh.positions[part_ids].mean(axis=0)
            for v in part_ids:
                if vertex_use[v] == 1:
                    out[v] = cur_anchor + (
                        mesh.positions[v] - orig_anchor) * f
        return out

    f = float(np.sqrt(target_area / original_area))
    best = None
    for w_try in (1.0, 0.6, 0.3):
        cand = positions.copy()
        rigid = rigid_positions(f)
        own_mask = vertex_use[own] == 1
        cand[own[own_mask]] = (
            (1.0 - w_try) * positions[own[own_mask]]
            + w_try * rigid[own[own_mask]])
        poly = mesh.polygons(cand)[ei]
        if poly is not None and poly.is_valid:
            best = (cand, w_try)
            break
    if best is None:
        poly = mesh.polygons(positions)[ei]
        if poly is not None and poly.is_valid:
            # Flow bleibt gültiger als jede starre Variante
            return False
        # Flow ungültig und keine starre Variante gültig: w=1.0 als
        # letztes Mittel (besser als ein gefaltetes Polygon)
        log(f"[repair] {mesh.entity_ids[ei]}: nur w=1.0 gültig, "
             f"Flow-Polygon ungültig")
        best = (rigid_positions(f), 1.0)

    positions_new, w = best

    # Flächenkorrektur: f so einstellen, dass die reparierte Fläche
    # das Ziel trifft – aber NUR, wenn die Fläche überhaupt auf f
    # reagiert. Die geteilten Grenzvertices bleiben fix; ist die
    # Fläche grenzdominiert (z.B. Libyen: langer Landgrenzbogen,
    # kurze Küste), bringt das Zuschnüren der Küste nichts und würde
    # nur die Form zerstören. Kriterium: Empfindlichkeit
    # k = d(log Fläche)/d(log f) >= 0.3, sonst bleibt der geometrisch
    # sinnvolle Startmaßstab. Das Ergebnis wird nur übernommen, wenn
    # es besser UND das Polygon gültig bleibt.
    def placement(f_try: float) -> np.ndarray:
        cand = positions.copy()
        rigid = rigid_positions(f_try)
        cand[own[own_mask]] = (
            (1.0 - w) * positions[own[own_mask]]
            + w * rigid[own[own_mask]])
        return cand

    def area_of(pos: np.ndarray) -> float:
        poly = mesh.polygons(pos)[ei]
        return poly.area if poly is not None else 0.0

    f_start = f
    a_start = area_of(placement(f_start))
    best_f, best_err = f_start, None
    if a_start > 0 and target_area > 0:
        best_err = abs(a_start / target_area - 1)
        if best_err > 0.02:
            # Empfindlichkeit der Fläche auf f messen
            f_probe = f_start * 1.25
            a_probe = area_of(placement(f_probe))
            k = None
            if a_probe > 0 and a_probe != a_start:
                k = (math.log(a_probe / a_start)) / \
                    (math.log(f_probe / f_start))
            if k is not None and k >= 0.3:
                f_prev, a_prev = f_start, a_start
                f_cur, a_cur = f_probe, a_probe
                for _ in range(8):
                    if a_cur <= 0 or abs(a_cur / target_area - 1) <= 0.02:
                        break
                    # Empfindlichkeit aus den letzten zwei Punkten
                    if a_cur != a_prev and f_cur != f_prev:
                        k_new = (math.log(a_cur / a_prev)) / \
                                (math.log(f_cur / f_prev))
                        if k_new >= 0.3:
                            k = k_new
                    f_next = f_cur * (target_area / a_cur) ** (1.0 / k)
                    f_next = min(max(f_next, f_start * 0.5), f_start * 2.0)
                    a_next = area_of(placement(f_next))
                    f_prev, a_prev, f_cur, a_cur = f_cur, a_cur, f_next, a_next
                    if a_next > 0:
                        err = abs(a_next / target_area - 1)
                        if err < best_err:
                            best_f, best_err = f_next, err
            elif k is not None and k < 0.3:
                best_f, best_err = f_start, best_err  # grenzdominiert

    if best_f != f_start:
        cand = placement(best_f)
        poly = mesh.polygons(cand)[ei]
        if poly is not None and poly.is_valid:
            f = best_f
        # ungültig -> f_start bleibt (best war bereits gültig)

    positions[...] = placement(f)
    info[mesh.entity_ids[ei]] = {"w": w, "f": round(f, 4)}
    log(f"[repair] {mesh.entity_ids[ei]}: starre Originalform an "
        f"Flow-Ankern (w={w}, Faktor {f:.3f})")
    return True
