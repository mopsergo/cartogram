"""Solver-Abstraktion (Plan §5.4).

    class CartogramSolver(Protocol):
        def solve(self, geometry, targets, config): ...

Implementierungen:
    cartogram_cpp    # Produktion laut Plan (externe Bindings, optional)
    carto_flow       # Flow-basierter Fallback/Benchmark – hier produktiv
    legacy_tiles     # recycelter Tile-Prototyp aus bassogram
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

import numpy as np


class SolverUnavailable(Exception):
    """Solver ist in dieser Umgebung nicht nutzbar (Kette fällt zurück)."""


@dataclass
class SolveResult:
    """Ergebnis eines Solver-Laufs: Vertex-Positionen (V, 2) + Statistik."""
    positions: np.ndarray
    stats: dict = field(default_factory=dict)


@runtime_checkable
class CartogramSolver(Protocol):
    name: str
    version: str

    def solve(self, mesh, targets: np.ndarray, passive: np.ndarray,
              initial_positions: np.ndarray | None = None) -> SolveResult:
        """Erzeugt verzerrte Positionen für Zielgewichte `targets`.

        mesh         – kanonisches Mesh (topology.Mesh)
        targets      – (E,) Zielgewichte (World_share); 0 für passive
        passive      – (E,) bool: Entität ohne Daten (kein Ziel, driftet)
        initial_positions – Warm-Start (z.B. Keyframe des Vorjahres) oder
                       None für Direct Solve vom kanonischen Ausgangszustand
        """
        ...


_REGISTRY: dict[str, type] = {}


def register_solver(cls):
    _REGISTRY[cls.name] = cls
    return cls


# Alle Implementierungen registrieren (carto_flow, cartogram_cpp,
# legacy_tiles). cartogram_cpp wirft erst bei Instanziierung
# SolverUnavailable, wenn die Bindings fehlen.
from . import carto_flow as _carto_flow  # noqa: E402,F401
from . import cartogram_cpp as _cartogram_cpp  # noqa: E402,F401
from . import legacy_tiles as _legacy_tiles  # noqa: E402,F401


def get_solver_class(name: str) -> type:
    if name not in _REGISTRY:
        raise KeyError(f"Unbekannter Solver {name!r}; verfügbar: {sorted(_REGISTRY)}")
    return _REGISTRY[name]


def resolve_chain(chain: list[str], **solver_kwargs) -> tuple[object, list[str]]:
    """Ersten verfügbaren Solver der Kette liefern (Plan: Fallback)."""
    errors: list[str] = []
    for name in chain:
        try:
            return get_solver_class(name)(**solver_kwargs), errors
        except SolverUnavailable as exc:
            errors.append(f"{name}: {exc}")
    raise RuntimeError("Kein verfügbarer Solver in Kette " f"{chain}: {errors}")
