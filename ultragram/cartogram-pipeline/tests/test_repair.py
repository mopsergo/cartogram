"""Regressionstests für die Reparatur (repair.py).

Kern-Szenario: Sprünge zwischen Jahren (Animation).

- Die gemischte Fläche (starre eigene Küste + geteilte Grenzvertices
  an Flow-Positionen) ist als Funktion von f nicht monoton; der
  Shoelace-Wert eines selbstüberschneidenden Rings ist Müll. Eine
  jährliche Neusuche ließ das Optimal-f springen (UdSSR: 6.700 km
  Vertex-Sprünge 1856-1881).
- Deshalb: Erstreparatur nur mit feiner Gültigkeits-/Flächensonde
  (reparieren verlangt eine valide Platzung mit <= 25 % Flächen-
  fehler, sonst bleibt der ehrbare Flow); Folgereparaturen suchen
  LOKAL im Fenster des Vorjahres (Becken-Kontinuität).
- Skip ist sticky, wird aber bei wieder gültigem Flow neu entschieden
  (rein intern – dargestellt wird immer der Flow).
"""
from __future__ import annotations

import numpy as np

from worldcarto.repair import (entity_ring_vertices,
                               repair_invalid_polygons)


def _targets(canonical, registry, cfg):
    from worldcarto.ingest import targets_for_year
    return targets_for_year(canonical, registry, 1820,
                            min_target_share=cfg.min_target_share)


def _f_start(mesh, pos, targets, passive, ei):
    """Startmaßstab exakt wie in repair_invalid_polygons."""
    targeted = ~passive & (targets > 0)
    scale = mesh.areas(pos)[targeted].sum() \
        / max(targets[targeted].sum(), 1e-12)
    return float(np.sqrt(targets[ei] * scale
                         / mesh.areas(mesh.positions)[ei]))


def _garbage_flow(mesh, ei):
    """Flow-artige Positionen: eigene Vertices der Entität gespiegelt
    (Polygon wird ungültig), geteilte Grenzvertices bleiben geo-
    grafisch (wie beim echten Flow: Nachbarn bleiben gekoppelt)."""
    pos = mesh.positions.copy()
    ids = entity_ring_vertices(mesh, ei)
    anchor = pos[ids].mean(axis=0)
    pos[ids, 0] = 2 * anchor[0] - pos[ids, 0]  # x-Spiegelung am Anker
    return pos


def _silent(*a, **k):
    pass


def _squeezed_flow(mesh, ei, factor):
    """Realistischer Test-Flow: die Ringvertices der Entität werden
    um ihren Zentroid uniform gestaucht (geteilte Grenzvertices
    wandern mit – Nachbarn bleiben gekoppelt), wie ein konvergierter
    Kartogramm-Flow. Das starre Placement beim Stauchfaktor
    reproduziert den Ring exakt (Anker = Fixpunkt der Stauchung)."""
    pos = mesh.positions.copy()
    ids = entity_ring_vertices(mesh, ei)
    c0 = mesh.positions[ids].mean(axis=0)
    pos[ids] = c0 + (pos[ids] - c0) * factor
    return pos


def test_first_repair_on_placable_flow(mesh, canonical, registry, cfg):
    """Erstreparatur bei platzierbarer Entität: die feine Sonde findet
    eine valide Platzung nahe der Zielfläche (<= 25 % Fehler)."""
    targets, passive = _targets(canonical, registry, cfg)
    ei = registry.index_of("ARG")
    pos = _squeezed_flow(mesh, ei, 0.16)
    f_start = _f_start(mesh, pos, targets, passive, ei)

    out, repaired, info, skipped = repair_invalid_polygons(
        mesh, pos, targets, passive, force_repair={"ARG"}, log=_silent)
    assert "ARG" in repaired and "ARG" not in skipped
    f = info["ARG"]["f"]
    assert 0.02 * f_start * 0.99 <= f <= 20.0 * f_start * 1.01
    assert "target" in info["ARG"]  # Zustand für das Folgejahr


def test_skip_when_no_good_placement(mesh, canonical, registry, cfg):
    """Kein brauchbares Placement (gespiegelter Müll-Flow): der Flow
    bleibt (Positionen unverändert), Entität wird sticky geskippt
    (Regression: Brasilien 1820 – einzig valides Pocket bei 25x
    Zielfläche würde die Entität riesig aufblähen)."""
    targets, passive = _targets(canonical, registry, cfg)
    ei = registry.index_of("ARG")
    pos = _garbage_flow(mesh, ei)
    own = entity_ring_vertices(mesh, ei)

    out, repaired, info, skipped = repair_invalid_polygons(
        mesh, pos, targets, passive, force_repair={"ARG"}, log=_silent)
    assert "ARG" in skipped and "ARG" not in repaired
    assert np.array_equal(out[own], pos[own])  # Flow bleibt unverändert

    # Sticky: ein weiterer Versuch entscheidet nicht neu.
    out2, _, _, skipped2 = repair_invalid_polygons(
        mesh, out, targets, passive, force_repair={"ARG"},
        skip_repair=set(skipped), log=_silent)
    assert "ARG" in skipped2
    assert np.array_equal(out2[own], out[own])


def test_smooth_f_evolution_local_window(mesh, canonical, registry, cfg):
    """Hysterese: f gleitet mit sqrt(Zielfläche) weiter; die
    Flächensuche bleibt LOKAL im Fenster [0.5, 2] x Vorjahres-f
    (Regression: UdSSR 1856-1881, f flippte um Größenordnungen)."""
    targets, passive = _targets(canonical, registry, cfg)
    ei = registry.index_of("ARG")
    pos = _squeezed_flow(mesh, ei, 0.16)
    targeted = ~passive & (targets > 0)
    scale = mesh.areas(pos)[targeted].sum() \
        / max(targets[targeted].sum(), 1e-12)
    t_area = targets[ei] * scale

    # fabrizierter Vorjahres-Zustand (f und Zielfläche konsistent)
    state = {"ARG": {"f": 0.16, "target": t_area}}
    fs = [0.16]
    mult = 1.0
    for growth in (1.05, 1.05, 1.21):
        mult *= growth
        # Nur ARGs Anteil wächst (Skalierung aller Ziele würde durch
        # die Normalisierung aufgehoben); kumulativ, damit das
        # Verhältnis zum Vorjahr wirklich growth ist.
        t_year = targets.copy()
        t_year[ei] *= mult
        _, repaired, info, _ = repair_invalid_polygons(
            mesh, pos, t_year, passive,
            prev_state=state, log=_silent)
        assert "ARG" in repaired  # Hysterese: bleibt repariert
        f_new, expected = info["ARG"]["f"], fs[-1] * np.sqrt(growth)
        # Auf dem gestauchten Flow ist die Zielfläche bei f=Stauch-
        # faktor exakt erreichbar -> die lokale Suche findet sie
        # nahe der Referenz (kein Sprung aus dem Fenster).
        assert expected * 0.9 <= f_new <= expected * 1.1, \
            f"f verlässt das lokale Becken: {fs[-1]:.4f} -> {f_new:.4f} " \
            f"(erwartet ~{expected:.4f})"
        fs.append(f_new)
        state = info

    # Gesamtdrift folgt den Zielen; eine Neusuche über den ganzen Raum
    # (der alte Fehler) springt um Größenordnungen – weit außerhalb
    # dieser Bänder.
    assert 0.4 * np.sqrt(1.05 * 1.05 * 1.21) <= fs[-1] / fs[0] \
        <= 2.6 * np.sqrt(1.05 * 1.05 * 1.21)


def test_hysteresis_overrules_validity(mesh, canonical, registry, cfg):
    """Einmal repariert = repariert, auch wenn die Flow-Form des
    Jahres gültig wäre (kein Flackern zwischen Flow und starr)."""
    targets, passive = _targets(canonical, registry, cfg)
    ei = registry.index_of("ARG")
    pos = mesh.positions.copy()  # gültige Polygone
    t_area = 0.5**2 * mesh.areas(mesh.positions)[ei]
    _, repaired, _, _ = repair_invalid_polygons(
        mesh, pos, targets, passive,
        prev_state={"ARG": {"f": 0.5, "target": t_area}},
        log=_silent)
    assert "ARG" in repaired
