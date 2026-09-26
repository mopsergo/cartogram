"""carto_flow – flow-basierter Cartogramm-Solver (Plan §5.4).

Implementiert den "fast flow-based"-Ansatz aus Gastner, Seguy & More,
PNAS 2018, als Weiterentwicklung des im Repo bewährten
mopsogram-Prototyps (cartogram.py), angepasst auf:

- die flächentreue Equal-Earth-Ebene (statt Längen-/Breitengrade):
  gleiche Zellfläche => Dichten physikalisch konsistent,
- das kanonische Mesh mit festen Vertex-IDs,
- Direct Solve (vom kanonischen Ausgangszustand) UND Warm-Start
  (vom Keyframe des Vorjahres) als Kandidaten (Plan §5.6),
- passive Entitäten (ohne Zielgewicht, z.B. Israel vor 1950):
  Dichte 1, sie driften mit (wie im mopsogram die No-Data-Länder).

Ablauf pro äußerer Iteration:
1. exakte Polygonflächen je Entität aus den aktuellen Positionen
2. Raster: Zelle -> Entität; Dichte je Zelle = s * target / area
   (passive Entitäten und Ozean: Dichte 1)
3. Gauß-Stabilisierung, Mittelwertnormierung, Untergrenze
4. Laplace(G) = rho - 1 mit Neumann-Rand per Spiegelungs-FFT
5. Integration dr/dt = grad(G)/rho(t), t: 0 -> 1 (Prädiktor-Korrektor)
6. Flächenfehler prüfen; Abbruch bei p90 < Toleranz

Die Zielgewichte (World_share) summieren sich je Jahr auf 1; die
Skalierung hält die Gesamtkartenfläche konstant.
"""
from __future__ import annotations

import time

import numpy as np
import shapely

from ..topology import Mesh
from . import SolveResult, register_solver

DEFAULTS = {
    "grid_width": 1024,
    "blur_sigma": 1.5,
    "steps": 60,
    "max_iterations": 12,
    "area_tolerance": 0.05,
    "min_density": 0.05,
}


@register_solver
class CartoFlowSolver:
    name = "carto_flow"
    version = "1.0.0"

    def __init__(self, config: dict | None = None):
        self.cfg = {**DEFAULTS, **(config or {})}

    # ------------------------------------------------------------ Gitter

    def _grid(self, mesh: Mesh) -> tuple[float, float, int, int, float]:
        """Zellgröße, Ursprung, Zellzahlen (nx, ny) aus den Weltbounds."""
        minx, miny, maxx, maxy = mesh.world_bounds
        nx = int(self.cfg["grid_width"])
        cell = (maxx - minx) / nx
        ny = int(np.ceil((maxy - miny) / cell))
        return cell, (minx + cell / 2, miny + cell / 2), nx, ny, cell

    # ------------------------------------------------------- Rasterdichte

    def _rasterize(self, mesh: Mesh, positions: np.ndarray,
                   nx: int, ny: int, origin: tuple[float, float],
                   cell: float) -> np.ndarray:
        """Zelle -> Entitäts-Index (-1 = Ozean)."""
        owner = np.full(ny * nx, -1, dtype=np.int32)
        polys = mesh.polygons(positions)
        x0 = origin[0] - cell / 2
        y0 = origin[1] - cell / 2
        for ei, poly in enumerate(polys):
            if poly is None or poly.is_empty:
                continue
            parts = ([poly] if poly.geom_type == "Polygon"
                     else list(poly.geoms))
            for p in parts:
                bminx, bminy, bmaxx, bmaxy = p.bounds
                i0 = max(int(np.floor((bminx - x0) / cell)), 0)
                i1 = min(int(np.ceil((bmaxx - x0) / cell)), nx - 1)
                j0 = max(int(np.floor((bminy - y0) / cell)), 0)
                j1 = min(int(np.ceil((bmaxy - y0) / cell)), ny - 1)
                if i0 > i1 or j0 > j1:
                    continue
                shapely.prepare(p)
                rows = owner.reshape(ny, nx)
                sub = (slice(j0, j1 + 1), slice(i0, i1 + 1))
                gx, gy = np.meshgrid(
                    x0 + cell * (np.arange(i0, i1 + 1) + 0.5),
                    y0 + cell * (np.arange(j0, j1 + 1) + 0.5))
                flat = rows[sub].ravel()
                free = flat == -1
                if not free.any():
                    continue
                inside = shapely.contains_xy(p, gx.ravel()[free],
                                              gy.ravel()[free])
                sel = np.nonzero(free)[0][inside]
                flat[sel] = ei
                rows[sub] = flat.reshape(j1 - j0 + 1, i1 - i0 + 1)
        return owner

    @staticmethod
    def _blur(f: np.ndarray, sigma: float) -> np.ndarray:
        """Separierbare Gauß-Glättung mit Randreflexion (mopsogram)."""
        if sigma <= 0:
            return f
        r = int(3 * sigma) + 1
        k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
        k /= k.sum()

        def conv1(a, axis):
            pad = [(0, 0)] * a.ndim
            pad[axis] = (r, r)
            ap = np.pad(a, pad, mode="edge")
            out = np.zeros_like(a)
            sl = [slice(None)] * a.ndim
            for o in range(len(k)):
                sl[axis] = slice(o, o + a.shape[axis])
                out = out + k[o] * ap[tuple(sl)]
            return out

        return conv1(conv1(f, 0), 1)

    @staticmethod
    def _poisson_neumann(rhs: np.ndarray, cell: float) -> np.ndarray:
        """Laplace(G) = rhs, Neumann-Rand, Spiegelungs-FFT (mopsogram)."""
        n1, n2 = rhs.shape
        m = np.zeros((2 * n1, 2 * n2))
        m[:n1, :n2] = rhs
        m[:n1, n2:] = rhs[:, ::-1]
        m[n1:, :n2] = rhs[::-1, :]
        m[n1:, n2:] = rhs[::-1, ::-1]
        f = np.fft.rfft2(m)
        k1 = 2 * np.pi * np.fft.fftfreq(2 * n1, d=cell)   # Achse 0: voll
        k2 = 2 * np.pi * np.fft.rfftfreq(2 * n2, d=cell)  # Achse 1: halb
        k2m = k1[:, None] ** 2 + k2[None, :] ** 2
        k2m[0, 0] = 1.0
        psi = np.fft.irfft2(-f / k2m, s=m.shape)[:n1, :n2]
        return psi

    @staticmethod
    def _sample(field: np.ndarray, x: np.ndarray, y: np.ndarray,
                origin: tuple[float, float], cell: float) -> np.ndarray:
        """Bilineare Interpolation eines Zellgitters an Punkten."""
        n1, n2 = field.shape
        fx = (x - origin[0]) / cell
        fy = (y - origin[1]) / cell
        i0 = np.clip(np.floor(fx).astype(int), 0, n2 - 2)
        j0 = np.clip(np.floor(fy).astype(int), 0, n1 - 2)
        tx = np.clip(fx - i0, 0, 1)
        ty = np.clip(fy - j0, 0, 1)
        f = field
        return ((1 - tx) * (1 - ty) * f[j0, i0] + tx * (1 - ty) * f[j0, i0 + 1]
                + (1 - tx) * ty * f[j0 + 1, i0] + tx * ty * f[j0 + 1, i0 + 1])

    # ------------------------------------------------------------- solve

    def solve(self, mesh: Mesh, targets: np.ndarray, passive: np.ndarray,
              initial_positions: np.ndarray | None = None) -> SolveResult:
        t_start = time.time()
        cell, origin, nx, ny, _ = self._grid(mesh)
        targets = np.asarray(targets, dtype=float)
        passive = np.asarray(passive, dtype=bool)
        targeted = ~passive & (targets > 0)
        if not targeted.any():
            raise ValueError("Keine Entität mit Zielgewicht")

        pos = (np.array(initial_positions, dtype=float).copy()
               if initial_positions is not None
               else mesh.positions.copy())
        if pos.shape != mesh.positions.shape:
            raise ValueError("initial_positions haben falsche Form")

        minx, miny, maxx, maxy = mesh.world_bounds
        eps = cell * 1e-3

        max_iter = int(self.cfg["max_iterations"])
        steps = int(self.cfg["steps"])
        tol = float(self.cfg["area_tolerance"])
        min_density = float(self.cfg["min_density"])
        sigma = float(self.cfg["blur_sigma"])

        # Zielflächen: Summe = aktuelle Gesamtfläche der zielten Entitäten
        # (Gesamtkartenfläche bleibt konstant; Plan §8: Fläche = World_share)
        stats = {"iterations": 0, "p90_error": None, "max_error": None,
                 "errors": None, "seconds": None, "candidate":
                     "warm" if initial_positions is not None else "direct"}
        target_areas = None
        history: list[float] = []

        for it in range(max_iter):
            areas = mesh.areas(pos)
            if target_areas is None:
                scale = areas[targeted].sum() / targets[targeted].sum()
                target_areas = targets * scale
                target_areas[~targeted] = 0.0

            owner = self._rasterize(mesh, pos, nx, ny, origin, cell)

            # Dichte: zielende Entität -> s * target / area (exakte Fläche,
            # nicht Zellenzahl), passive Entität und Ozean -> 1
            rho = np.ones(ny * nx)
            s = areas[targeted].sum() / max(targets[targeted].sum(), 1e-12)
            owner2d = owner.reshape(ny, nx)
            for ei in np.nonzero(targeted)[0]:
                if areas[ei] <= 1e-9:
                    continue
                rho[owner == ei] = s * targets[ei] / areas[ei]
            rho = self._blur(rho.reshape(ny, nx), sigma)
            rho /= rho.mean()
            rho = np.clip(rho, min_density, None)

            g_pot = self._poisson_neumann(rho - 1.0, cell)
            dvx = np.gradient(g_pot, cell, axis=1)
            dvy = np.gradient(g_pot, cell, axis=0)

            px, py = pos[:, 0], pos[:, 1]
            dt = 1.0 / steps
            for st in range(steps):
                t = st * dt

                def vel(qx, qy, tt):
                    r_t = (1 - tt) * self._sample(rho, qx, qy, origin, cell) + tt
                    vx = self._sample(dvx, qx, qy, origin, cell) / r_t
                    vy = self._sample(dvy, qx, qy, origin, cell) / r_t
                    return vx, vy

                vx0, vy0 = vel(px, py, t)
                mx, my = px + 0.5 * dt * vx0, py + 0.5 * dt * vy0
                vx1, vy1 = vel(mx, my, t + 0.5 * dt)
                px = px + dt * vx1
                py = py + dt * vy1

            pos[:, 0] = np.clip(px, minx + eps, maxx - eps)
            pos[:, 1] = np.clip(py, miny + eps, maxy - eps)

            stats["iterations"] = it + 1
            areas_end = mesh.areas(pos)
            err = np.zeros(len(targets))
            err[targeted] = (np.abs(areas_end - target_areas)[targeted]
                             / np.maximum(target_areas[targeted], 1e-12))
            stats["p90_error"] = float(np.quantile(err[targeted], 0.9))
            stats["max_error"] = float(err[targeted].max())
            stats["errors"] = err
            history.append(stats["p90_error"])
            if stats["p90_error"] < tol:
                break

        stats["history"] = history
        stats["seconds"] = round(time.time() - t_start, 2)
        return SolveResult(positions=pos, stats=stats)
