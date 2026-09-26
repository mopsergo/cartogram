"""Debug- und Regression-Rendering mit Matplotlib (Plan §4).

Rendert Keyframes als PNG: Cartogramm-Polygone, gefärbt nach
Per-Kopf-Energie (plasma_r wie im Bassogram-Prototyp), schwarze
Regiongrenzen, Ghost der unverzerrten Geometrie, Titel mit Jahr und
p90-Flächenfehler, plus Farbskala.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from .topology import Mesh  # noqa: E402


def render_frame(mesh: Mesh, positions: np.ndarray, values: np.ndarray,
                 year: float, p90: float | None, out_path: Path,
                 ghost: np.ndarray | None = None) -> Path:
    """values: (E, 4) – Komponente 3 = per_capita_energy_consumption."""
    fig, ax = plt.subplots(figsize=(12, 7), facecolor="white")
    cmap = plt.get_cmap("plasma_r")

    per_cap = values[:, 3]
    finite = np.isfinite(per_cap) & (per_cap > 0)
    if finite.any():
        vmin = float(np.log10(per_cap[finite].min()))
        vmax = float(np.log10(per_cap[finite].max()))
    else:
        vmin, vmax = 0.0, 1.0

    # Ghost der unverzerrten Geometrie
    if ghost is not None:
        for ei, poly in enumerate(mesh.polygons(ghost)):
            if poly is None:
                continue
            geoms = [poly] if poly.geom_type == "Polygon" else poly.geoms
            for p in geoms:
                xs, ys = p.exterior.xy
                ax.plot(xs, ys, color="#b8bec7", linewidth=0.5, zorder=1)

    for ei in range(mesh.num_entities):
        poly = mesh.polygons(positions)[ei]
        if poly is None:
            continue
        v = per_cap[ei]
        if np.isfinite(v) and v > 0:
            t = (np.log10(v) - vmin) / max(vmax - vmin, 1e-9)
            color = cmap(np.clip(t, 0, 1))
        else:
            color = (0.55, 0.55, 0.55, 1.0)
        geoms = [poly] if poly.geom_type == "Polygon" else poly.geoms
        for p in geoms:
            xs, ys = p.exterior.xy
            ax.fill(xs, ys, facecolor=color, edgecolor="black",
                    linewidth=0.4, zorder=3)
            for interior in p.interiors:
                ixs, iys = interior.xy
                ax.plot(ixs, iys, color="black", linewidth=0.4, zorder=3)

    ax.set_title(
        f"Animated Energy Cartogram – {year:.0f}"
        + (f"  (p90-Flächenfehler {p90:.3f})" if p90 is not None else ""),
        fontsize=13)
    ax.set_aspect("equal")
    ax.set_axis_off()

    sm = plt.cm.ScalarMappable(
        cmap=cmap, norm=plt.Normalize(vmin=10 ** vmin, vmax=10 ** vmax))
    sm.set_array([])
    cbar = fig.colorbar(sm, ax=ax, orientation="vertical", shrink=0.75)
    cbar.set_label("Energieverbrauch pro Kopf (kWh, logarithmisch)")

    fig.tight_layout()
    fig.savefig(out_path, dpi=140, facecolor="white")
    plt.close(fig)
    return out_path
