"""Reparatur ungültiger Polygone nach dem Solver-Lauf.

Starke Verformungen (Israel 7x-Expansion, Kanada 1820 ~150x-
Kontraktion) können Ring-Selbstüberschneidungen erzeugen. Für die
betroffenen Entitäten ersetzt die Reparatur die Verschiebung der
EIGENEN Ringvertices (Küstenlinien und interne Punkte, die zu genau
einer Entität gehören) durch eine starr skalierte Originalform:

    rigid(v) = anker_aktuell + (original(v) - anker_original) * f
    mit f = sqrt(zielfläche / originalfläche), per Sekante nachgestellt

Stabilität über die Zeit (Animation) – keine diskreten Zustände:
- Anker je POLYGON-TEIL an der aktuellen Flow-Position des Teils
  (nicht am geografischen Ursprung): mehrteilige Entitäten wie
  OTHER_WORLD driften teilweise mit, und die reparierte Form bleibt
  dort, wo der Flow sie hingelegt hat.
- Immer vollstarre Platzierung (kein Teilblend): Blends zwischen
  Flow- und starrer Form wären ein diskreter Zustand, der zwischen
  Jahren flackert (40 % Verschiebungsdifferenz).
- Flächenkorrektur per Sekante NUR im gültigen Bereich: die
  Gültigkeitssonde der Erstreparatur klärt, ob die starre Platzierung
  überhaupt ein gültiges Polygon ergeben kann.
  - Reparierbar (z. B. Argentinien, Kanada): die Zielfläche ist ein
    sinnvolles Signal; die Sekante sucht LOKAL im Fenster des
    Vorjahres (Becken-Kontinuität statt Neusuche über den ganzen
    Raum – sonst springt das Optimum zwischen Jahren).
  - Unreparierbar (UdSSR: die Flow-Grenzvertices selbst sind ver-
    heddert, das Placement ist bei JEDEM f ungültig): der Flächen-
    wert eines selbstüberschneidenden Rings ist Shoelace-Müll –
    KEINE Suche. f gleitet rein mit sqrt(Zielfläche).
- Hysterese: einmal reparierte Entitäten bleiben repariert
  (force_repair) – pro Entität höchstens EIN Moduswechsel (Flow ->
  starr) statt jährlichem Flackern. Der Wechsel selbst (erste
  Reparatur) ist ein einmaliger, dokumentierter Übergang.
- Geteilte Grenzvertices behalten ihre Flow-Position: Nachbarn werden
  nicht gezerrt, Grenzen bleiben gekoppelt.
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
                            prev_state: dict | None = None,
                            skip_repair: set[str] = frozenset(),
                            max_passes: int = 3,
                            log=print) -> tuple[np.ndarray, list[str], dict, list[str]]:
    """Repariert ungültige (oder forcierte) Entitäten.

    prev_state: Hysterese-Zustand des Vorjahres (repair_info:
    eid -> {"f": Skalierungsfaktor, "target": Zielfläche}). Entitäten
    darin bleiben repariert; ihre Flächensuche bleibt LOKAL im
    Fenster des Vorjahres (Becken-Kontinuität).

    skip_repair: Entitäten ohne brauchbares valides Placement – der
    Flow bleibt (Ring-Ungültigkeit als dokumentierte Warnung, wie
    die interior Folds). Sobald der Flow wieder gültig ist, wird die
    Entität neu entschieden (rein intern: die Darstellung wechselt
    nie – es bleibt immer der Flow).

    Rückgabe: (positions, repaired_ids, info, skipped_ids) mit
      info[eid] = {"f": Skalierungsfaktor, "target": Zielfläche}
      für Diagnose und als Zustand für das Folgejahr.
    """
    positions = positions.copy()
    targeted = ~passive & (targets > 0)
    areas = mesh.areas(positions)
    scale = areas[targeted].sum() / max(targets[targeted].sum(), 1e-12)
    target_areas = targets * scale

    original_areas = mesh.areas(mesh.positions)
    repaired: set[str] = set()
    skipped_new: set[str] = set()
    info: dict = {}

    # Vertex -> Anzahl besitzender Entitäten (nur Ringvertices zählen)
    vertex_use = np.zeros(mesh.num_vertices, dtype=int)
    for ei in range(mesh.num_entities):
        for v in entity_ring_vertices(mesh, ei):
            vertex_use[v] += 1

    prev_state = prev_state or {}
    force_all = set(force_repair) | set(prev_state)

    # Flow-Ungültigkeit des EINGANGS-Zustands (vor jeder Reparatur):
    # Re-Armierung übersprungener Entitäten, deren Flow wieder gültig
    # ist – sie werden beim nächsten ungültigen Jahr neu entschieden.
    flow_invalid = {
        mesh.entity_ids[ei] for ei, poly in enumerate(mesh.polygons(positions))
        if poly is None or not poly.is_valid}
    skip_live = set(skip_repair) & flow_invalid

    for _ in range(max_passes):
        invalid = [
            ei for ei, poly in enumerate(mesh.polygons(positions))
            if (poly is None or not poly.is_valid)
            and mesh.entity_ids[ei] not in repaired
            and mesh.entity_ids[ei] not in skip_live
        ]
        forced = [
            ei for ei in range(mesh.num_entities)
            if mesh.entity_ids[ei] in force_all
            and mesh.entity_ids[ei] not in repaired
            and mesh.entity_ids[ei] not in skip_live
        ]
        todo = sorted(set(invalid) | set(forced))
        if not todo:
            break
        for ei in todo:
            eid = mesh.entity_ids[ei]
            if original_areas[ei] <= 0 or target_areas[ei] <= 0:
                continue
            status, f = _repair_entity(
                mesh, positions, ei, target_areas[ei],
                original_areas[ei], vertex_use, prev=prev_state.get(eid),
                log=log)
            if status == "repaired":
                repaired.add(eid)
                info[eid] = {"f": round(f, 4),
                             "target": float(target_areas[ei]),
                             "mode": "area"}
            elif status == "skip":
                skipped_new.add(eid)
                skip_live.add(eid)
                log(f"[repair] {eid}: keine brauchbare starre Platzung "
                    "(> 25 % Flächenfehler) – Flow bleibt, Ungültigkeit "
                    "dokumentiert")

    # Sticky Skip: neu Gescheute und Alte mit weiterhin ungültigem Flow
    # bleiben gesperrt; Flow wieder gültig -> neu entscheidbar.
    skipped_all = sorted(skip_live | skipped_new)
    return positions, sorted(repaired), info, skipped_all


def _entity_polygon(mesh: Mesh, positions: np.ndarray, ei: int):
    """Shapely-Polygon EINER Entität (günstige Gültigkeits-/Flächensonde
    statt mesh.polygons für alle 73 Entitäten je Aufruf)."""
    import shapely
    from shapely.geometry import MultiPolygon
    x, y = positions[:, 0], positions[:, 1]
    polys = []
    for ext_idx, hole_idxs in mesh.entity_parts[ei]:
        _, ext, _ = mesh.rings[ext_idx]
        shell = np.column_stack([x[ext], y[ext]])
        holes = [np.column_stack([x[mesh.rings[h][1]], y[mesh.rings[h][1]]])
                 for h in hole_idxs]
        try:
            p = shapely.polygons(shell, holes=holes or None)
        except Exception:
            p = None
        if p is not None and not p.is_empty:
            polys.append(p)
    if not polys:
        return None
    return polys[0] if len(polys) == 1 else MultiPolygon(polys)


def _area_search(probe, f0: float, target: float,
                 f_lo: float, f_hi: float, steps: int = 4):
    """Lokale Sekantensuche im Fenster [f_lo, f_hi], Best-Tracking.

    Nur GÜLTIGE Platzungen zählen (der Shoelace-Flächenwert eines
    selbstüberschneidenden Rings ist Müll). Übernommen wird der
    beste Maßstab nur bei klarer Verbesserung (20 % Puffer gegen
    Becken-Wechsel); das Fenster wandert mit dem Vorjahres-f mit ->
    Becken-Kontinuität: das Ergebnis ist stetig in den Eingaben,
    kein Springen zwischen Jahren.
    """
    a0, ok0 = probe(f0)
    if not ok0 or a0 <= 0 or target <= 0:
        return f0, None
    err_start = abs(a0 / target - 1.0)
    best_f, best_err = f0, err_start
    f_cur, a_cur = f0, a0
    for _ in range(steps):
        if best_err <= 0.02:
            break
        # Empfindlichkeit k vor Ort messen: erst aufwärts, sonst
        # abwärts (Fensterränder beachten).
        f_probe = a_probe = None
        for cand in (min(f_cur * 1.25, f_hi), max(f_cur / 1.25, f_lo)):
            if cand != f_cur:
                a_c, ok_c = probe(cand)
                if ok_c and a_c > 0:
                    f_probe, a_probe = cand, a_c
                    break
        if f_probe is None or a_probe == a_cur:
            break
        k = math.log(a_probe / a_cur) / math.log(f_probe / f_cur)
        if abs(k) <= 0.02:
            break
        f_next = min(max(f_cur * (target / a_cur) ** (1.0 / k), f_lo), f_hi)
        if f_next == f_cur:
            break
        a_next, ok_next = probe(f_next)
        if not ok_next or a_next <= 0:
            break
        err = abs(a_next / target - 1.0)
        if err < best_err:
            best_f, best_err = f_next, err
        f_cur, a_cur = f_next, a_next
    # Akzeptanzpuffer: nur übernehmen, wenn die Fläche sich klar
    # verbessert (kein Springen zwischen beinahe gleich guten Becken).
    if best_err < 0.8 * err_start:
        return best_f, best_err
    return f0, err_start


def _repair_entity(mesh: Mesh, positions: np.ndarray, ei: int,
                   target_area: float, original_area: float,
                   vertex_use: np.ndarray,
                   prev: dict | None = None,
                   log=print) -> tuple[str, float | None]:
    """Starr skalierte Originalform an den aktuellen Flow-Ankern.

    Rückgabe: ("repaired", f) bei Erfolg, ("skip", None) wenn keine
    brauchbare Platzung existiert (<= 25 % Flächenfehler im gültigen
    Bereich – sonst bleibt der ehrliche Flow), ("noop", None) wenn
    die Entität gar nicht platzierbar ist (keine eigenen Vertices).

    prev: Zustand des Vorjahres ({"f", "target"}) -> gleitende
    Fortführung: Referenz folgt den glatten Zielflächen, die
    Flächensuche bleibt LOKAL im Fenster des Vorjahres
    (Becken-Kontinuität).
    """
    all_ids = entity_ring_vertices(mesh, ei)
    if not len(all_ids):
        return "noop", None
    parts = _part_vertices(mesh, ei)
    own = all_ids[vertex_use[all_ids] == 1]
    if not len(own):
        return "noop", None

    # Starre Zieldarstellung: Originalform je Teil um den aktuellen
    # Teil-Anker (Flow-Position), Skalierung f auf die Zielfläche.
    def placement(f_try: float) -> np.ndarray:
        cand = positions.copy()
        for part_ids in parts:
            cur_anchor = positions[part_ids].mean(axis=0)
            orig_anchor = mesh.positions[part_ids].mean(axis=0)
            for v in part_ids:
                if vertex_use[v] == 1:
                    cand[v] = cur_anchor + (
                        mesh.positions[v] - orig_anchor) * f_try
        return cand

    def probe(f_try: float):
        poly = _entity_polygon(mesh, placement(f_try), ei)
        if poly is None:
            return 0.0, False
        return float(poly.area), bool(poly.is_valid)

    # Startmaßstab: geometrisch sinnvoll (Original -> Ziel)
    f_start = float(np.sqrt(target_area / original_area))

    if prev is not None and prev.get("f", 0) > 0 and prev.get("target", 0) > 0:
        # --- Gleitende Fortführung (Hysterese)
        f0 = float(prev["f"]) * math.sqrt(target_area / prev["target"])
        f_lo = max(0.5 * f0, 0.05 * f_start)
        f_hi = min(2.0 * f0, 20.0 * f_start)
        f, err = _area_search(probe, f0, target_area, f_lo, f_hi)
        positions[...] = placement(f)
        return "repaired", f

    # --- Erstreparatur: feine Gültigkeits-/Flächensonde über
    # [0.02, 20] x Startmaßstab; beste valide Platzierung nach
    # Flächenfehler. Schmale Taschen (Argentinien 1820: nutzbares f
    # liegt bei 0.15 x Start) brauchen eine feine Abtastung.
    best_f, best_err = None, None
    for q in np.geomspace(0.02, 20.0, 25):
        a, ok = probe(f_start * float(q))
        if ok and a > 0:
            err = abs(a / target_area - 1.0)
            if best_err is None or err < best_err:
                best_f, best_err = f_start * float(q), err
    if best_f is None or best_err > 0.25:
        # Keine brauchbare Platzung: der Flow bleibt (Ring-Validität
        # als dokumentierte Warnung, Fläche = ehrliche Flow-Fläche).
        return "skip", None

    # lokale Sekante im Pocket der besten Sonde (validitätsgeprüft,
    # Best-Tracking, 20 % Akzeptanzpuffer)
    f, err = _area_search(probe, best_f, target_area,
                          best_f / 1.5, best_f * 1.5)
    positions[...] = placement(f)
    log(f"[repair] {mesh.entity_ids[ei]}: starre Originalform an "
        f"Flow-Ankern (Faktor {f:.3f}, Start {f_start:.3f}, "
        f"Flächenfehler {err:.3f})")
    return "repaired", f
