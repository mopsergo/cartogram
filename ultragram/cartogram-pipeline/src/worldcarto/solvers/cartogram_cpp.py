"""cartogram_cpp – Produktionssolver laut Plan (§5.4), als optionaler
Wrapper um externe cartogram-cpp-Bindings.

Nutzt das PyPI-Paket `flowbasedcartograms` (Python-Bindings des
C++-Projekts https://github.com/Flow-based-Cartograms/cpp), wenn
installierbar. Zum Stand dieses Builds gibt es kein Rad für Python
3.13, daher ist der Solver hier nicht verfügbar und die Kette fällt
gemäß solver.yaml auf carto_flow zurück:

    solver_chain: [cartogram_cpp, carto_flow]

Sobald Bindings verfügbar sind, deckt dieser Adapter denselben
Mesh/Targets-Vertrag wie carto_flow ab (Gastner-Seguy-More Familie).
"""
from __future__ import annotations

import numpy as np

from ..topology import Mesh
from . import SolveResult, SolverUnavailable, register_solver


@register_solver
class CartogramCppSolver:
    name = "cartogram_cpp"
    version = "1.0.0"

    def __init__(self, config: dict | None = None):
        try:
            import flowbasedcartograms  # noqa: F401
        except ImportError as exc:
            raise SolverUnavailable(
                "Python-Bindings 'flowbasedcartograms' sind nicht "
                "installiert (kein Rad für Python 3.13); Kette fällt "
                "auf carto_flow zurück."
            ) from exc
        self.cfg = dict(config or {})

    def solve(self, mesh: Mesh, targets: np.ndarray, passive: np.ndarray,
              initial_positions: np.ndarray | None = None) -> SolveResult:
        import flowbasedcartograms as fbc

        if initial_positions is not None:
            # cartogram-cpp löst aus der Ausgangsgeometrie; ein Warm-Start
            # ist über die Bindings nicht vorgesehen.
            raise ValueError("cartogram_cpp unterstützt keinen Warm-Start")

        targets = np.asarray(targets, dtype=float)
        passive = np.asarray(passive, dtype=bool)
        targeted = ~passive & (targets > 0)
        if not targeted.any():
            raise ValueError("Keine Entität mit Zielgewicht")

        # GeoJSON-FeatureCollection aus dem kanonischen Mesh (Ausgangs-
        # positionen); Feature-ID = Entitäts-ID, Wert = Zielgewicht.
        features = []
        for ei in range(mesh.num_entities):
            if not targeted[ei]:
                continue
            poly = mesh.polygons(mesh.positions)[ei]
            features.append({
                "type": "Feature",
                "id": mesh.entity_ids[ei],
                "geometry": poly.__geo_interface__,
                "properties": {},
            })
        geometry = {"type": "FeatureCollection", "features": features}
        data = {mesh.entity_ids[ei]: float(targets[ei])
                for ei in np.nonzero(targeted)[0]}

        cartogram = fbc.Cartogram(geometry, data)
        result = cartogram.determine_cartogram()

        # Zurückmappen: die Bindings erhalten die Ring-Reihenfolge der
        # übergebenen Geometrie; kanonische Vertices werden über die
        # Ausgangskoordinaten identifiziert.
        pos = mesh.positions.copy()
        lookup = {(round(x, 6), round(y, 6)): i
                  for i, (x, y) in enumerate(mesh.positions)}

        def apply_geom(geom):
            if geom["type"] == "Polygon":
                return [geom["coordinates"]]
            return geom["coordinates"]

        for feat in result["features"]:
            for poly in apply_geom(feat["geometry"]):
                for ring in poly:
                    for x, y in ring:
                        i = lookup.get((round(x, 6), round(y, 6)))
                        if i is not None:
                            pos[i] = (x, y)

        return SolveResult(positions=pos, stats={"candidate": "direct",
                                                 "note": "cartogram_cpp"})
