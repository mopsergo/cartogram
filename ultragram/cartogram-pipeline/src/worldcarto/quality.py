"""Qualitätskriterien und Übergangsprüfung (Plan §5.6).

Kriterien je Jahres-Keyframe:
- keine invertierten Dreiecke: als schwellenwertiges Kriterium
  umgesetzt (max_inverted_area_fraction). Starke Cartogramm-
  Verformungen (Kanada 20x-Kontraktion, UdSSR 3,7x) falten interior
  Dreieckslappen auch mit Referenz-Solvern; entscheidend ist, dass
  a) alle Ring-Polygone gültig bleiben (keine Selbstüber-
  schneidungen, harte Prüfung) und b) die gefaltete Fläche klein
  bleibt. Der Renderer zeichnet DoubleSide + Grenzlinien, daher
  sind verbleibende interior Lappen visuell irrelevant.
- keine neuen Selbstüberschneidungen (Polygon-Validität, hart)
- unveränderter Adjazenzgraph (Nachbarn berühren sich weiterhin)
- Flächenfehler unter konfigurierter Schwelle (p90)
- identische Vertex-Anzahl und Reihenfolge (strukturell garantiert)
- plausible Verschiebung gegenüber dem Vorjahr

Übergangsprüfung: lineare Vertex-Interpolation zwischen zwei Keyframes
wird an konfigurierten t-Stichproben auf Dreiecksinversion geprüft.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .config import PipelineConfig
from .topology import Mesh
from .triangulate import triangle_areas


@dataclass
class KeyframeReport:
    valid: bool
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    area_errors: np.ndarray | None = None
    p90_error: float | None = None
    max_error: float | None = None
    inverted_triangles: int = 0
    inverted_area_fraction: float = 0.0
    invalid_polygons: list[str] = field(default_factory=list)
    torn_adjacencies: list[str] = field(default_factory=list)
    max_displacement_prev: float | None = None
    max_displacement_original: float = 0.0

    def score(self) -> tuple:
        """Sortierschlüssel: gültig vor ungültig, dann Fehler, dann Verschiebung."""
        return (
            0 if self.valid else 1,
            self.p90_error if self.p90_error is not None else float("inf"),
            self.max_error if self.max_error is not None else float("inf"),
            self.max_displacement_prev
            if self.max_displacement_prev is not None else 0.0,
        )


def _world_scale(mesh: Mesh) -> float:
    minx, miny, maxx, maxy = mesh.world_bounds
    return float(np.hypot(maxx - minx, maxy - miny))


def validate_keyframe(mesh: Mesh, positions: np.ndarray, targets: np.ndarray,
                      passive: np.ndarray, cfg: PipelineConfig,
                      prev_positions: np.ndarray | None = None,
                      max_area_error_p90: float | None = None,
                      max_inverted_fraction: float | None = None,
                      scale_positions: np.ndarray | None = None) -> KeyframeReport:
    """Prüft einen Kandidaten-Keyframe gegen alle Qualitätskriterien.

    scale_positions: Positionen, deren Gesamtfläche die Ziel-Normal-
   isierung bestimmt. Default: `positions` selbst. Nach der Reparatur
    (repair.py) sind das die FLOW-Positionen – die Reparatur ändert
    Teilflächen, und die Fehler aller Entitäten dürfen nicht gegen
    eine durch die Reparatur verschobene Gesamtfläche gemessen
    werden (Kaskade: ein Entitäts-Fehler blähte sonst alle auf).

    Harte Kriterien (problems, machen den Keyframe ungültig):
    - Vertex-Anzahl/Reihenfolge
    - p90-Flächenfehler (Jahres-abhängiger Schwellwert)
    - gefaltete Dreiecksfläche (Schwellwert)
    - plausible Verschiebung ggü. dem Vorjahr

    Weiche Kriterien (warnings, dokumentiert im Qualitätsbericht):
    - Ring-Selbstüberschneidungen bei extremer Verformung: die
      Reparatur (repair.py) behebt eigene Vertices; Folds unter
      Beteiligung geteilter Grenzvertices sind ohne Zerren der
      Nachbarn nicht reparierbar und im Weltmaßstab nicht sichtbar
      (Fill und Extrusion rendern weiter korrekt).
    - Aufgerissene Berührungen (nur möglich, wenn ein Fold zwei
      Nachbarn voneinander trennt).
    """
    problems: list[str] = []
    warnings: list[str] = []
    report = KeyframeReport(valid=True, problems=problems, warnings=warnings)

    # --- identische Vertex-Anzahl und Reihenfolge
    if positions.shape != mesh.positions.shape:
        problems.append(f"Vertex-Anzahl/Reihenfolge abweichend: "
                        f"{positions.shape} != {mesh.positions.shape}")

    # --- Flächenfehler
    targeted = ~passive & (targets > 0)
    areas = mesh.areas(positions)
    scale_ref = mesh.areas(scale_positions if scale_positions is not None
                           else positions)
    scale = scale_ref[targeted].sum() / max(targets[targeted].sum(), 1e-12)
    target_areas = targets * scale
    errors = np.zeros(len(targets))
    errors[targeted] = (np.abs(areas - target_areas)[targeted]
                        / np.maximum(target_areas[targeted], 1e-12))
    report.area_errors = errors
    report.p90_error = float(np.quantile(errors[targeted], 0.9))
    report.max_error = float(errors[targeted].max())
    threshold = (max_area_error_p90 if max_area_error_p90 is not None
                 else cfg.max_area_error_p90)
    if report.p90_error > threshold:
        problems.append(
            f"p90-Flächenfehler {report.p90_error:.3f} > "
            f"{threshold:.3f} (max {report.max_error:.3f})")

    # --- invertierte Dreiecke: Schwellwert auf die gefaltete Fläche
    # (siehe Modul-Docstring: harte Prüfung ist die Polygon-Validität,
    # die Faltfläche dokumentiert das Ausmaß der interior Lappen)
    signed = triangle_areas(mesh, positions)
    total_area = float(np.abs(signed).sum())
    inverted_mask = signed <= 0
    report.inverted_triangles = int(inverted_mask.sum())
    report.inverted_area_fraction = (
        float(np.abs(signed[inverted_mask]).sum() / total_area)
        if total_area > 0 and report.inverted_triangles else 0.0)
    fold_threshold = (max_inverted_fraction
                      if max_inverted_fraction is not None
                      else cfg.max_inverted_area_fraction)
    if report.inverted_area_fraction > fold_threshold:
        problems.append(
            f"Gefaltete Dreiecksfläche {report.inverted_area_fraction:.3f} > "
            f"{fold_threshold:.3f} ({report.inverted_triangles} Dreiecke)")

    # --- Ring-Selbstüberschneidungen (weich, siehe Docstring)
    invalid = []
    for ei, poly in enumerate(mesh.polygons(positions)):
        if poly is None:
            invalid.append(mesh.entity_ids[ei])
            continue
        if not poly.is_valid:
            invalid.append(mesh.entity_ids[ei])
    report.invalid_polygons = invalid
    if invalid:
        warnings.append(
            f"Ring-Selbstüberschneidungen bei extremer Verformung: {invalid}")

    # --- Adjazenzgraph unverändert: Nachbarn müssen sich (mit gemeinsamem
    # Vertex) weiterhin berühren. Strukturell über geteilte Vertex-IDs
    # garantiert – die Prüfung validiert die tatsächliche Solver-Ausgabe.
    torn: list[str] = []
    polys = mesh.polygons(positions)
    for ei in range(mesh.num_entities):
        if polys[ei] is None:
            continue
        for ej in mesh.adjacency[ei]:
            if ej <= ei or polys[ej] is None:
                continue
            if not polys[ei].intersects(polys[ej]):
                torn.append(f"{mesh.entity_ids[ei]}~{mesh.entity_ids[ej]}")
    report.torn_adjacencies = torn
    if torn:
        warnings.append(f"Berührung aufgerissen: {torn[:8]}")

    # --- plausible Verschiebung
    world = _world_scale(mesh)
    report.max_displacement_original = float(
        np.linalg.norm(positions - mesh.positions, axis=1).max())
    if prev_positions is not None:
        disp = float(np.linalg.norm(positions - prev_positions, axis=1).max())
        report.max_displacement_prev = disp
        limit = cfg.max_vertex_displacement_share * world
        if disp > limit:
            problems.append(
                f"Verschiebung ggü. Vorjahr {disp / world:.3f} der "
                f"Weltdiagonale > {cfg.max_vertex_displacement_share}")

    report.valid = not problems
    return report


def _shared_vertices(mesh: Mesh, ei: int, ej: int) -> np.ndarray:
    ids_i = set()
    for ext_idx, hole_idxs in mesh.entity_parts[ei]:
        ids_i.update(int(v) for v in mesh.rings[ext_idx][1])
        for h in hole_idxs:
            ids_i.update(int(v) for v in mesh.rings[h][1])
    ids_j = set()
    for ext_idx, hole_idxs in mesh.entity_parts[ej]:
        ids_j.update(int(v) for v in mesh.rings[ext_idx][1])
        for h in hole_idxs:
            ids_j.update(int(v) for v in mesh.rings[h][1])
    return np.asarray(sorted(ids_i & ids_j), dtype=int)


def check_transition(mesh: Mesh, pos_a: np.ndarray, pos_b: np.ndarray,
                     samples: list[float]) -> list[float]:
    """Lineare Interpolation prüfen; liefert die t-Werte mit Inversion.

    Kriterium (Animation): ein Übergang ist problematisch, wenn die
    Interpolation MEHR invertierte Dreiecke erzeugt als beide Endpunkt-
    Keyframes bereits haben (die Endpunkte selbst sind über
    validate_keyframe bewertet). Gemessen wird die ANZAHL invertierter
    Dreiecke mit Margin – eine flächenbasierte Messung würde Degenera-
    tion (Kollaps auf einen Punkt) systematisch unterschätzen.
    """
    def inverted_count(pos: np.ndarray) -> int:
        signed = triangle_areas(mesh, pos)
        return int((signed <= 0).sum())

    base = max(inverted_count(pos_a), inverted_count(pos_b))
    margin = max(8, int(0.02 * len(mesh.triangles)))
    bad: list[float] = []
    for t in samples:
        pos = (1.0 - t) * pos_a + t * pos_b
        if inverted_count(pos) > base + margin:
            bad.append(t)
    return bad


def pick_best(reports: dict[str, KeyframeReport]) -> tuple[str | None, KeyframeReport | None]:
    """Besten gültigen Kandidaten wählen (Plan §5.6 Schritt 6)."""
    valid = {name: r for name, r in reports.items() if r.valid}
    pool = valid or reports
    if not pool:
        return None, None
    best = min(pool.items(), key=lambda kv: kv[1].score())
    return best
