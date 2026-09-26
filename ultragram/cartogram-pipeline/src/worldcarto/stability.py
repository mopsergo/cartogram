"""Stabilitätsprüfung der exportierten Keyframes (Plan §5.6).

Prüft auf den EXPORTIERARTEFAKTEN (positions.f32), ob die Animation
stabil ist: keine Springe zwischen aufeinanderfolgenden Jahren.
Kriterium je Entität:
- max. Vertexverschiebung zwischen Folgejahren < Schwelle (Welt-Diagonale)
- Flächenverlauf glatt: keine Zunahme-Sprung-Kombination
  (Fläche schrumpft >20 % und wächst danach wieder >20 %)

Aufruf:
    PYTHONPATH=src python3 -m worldcarto.cli verify-stability
"""
from __future__ import annotations

import json
import sys

import numpy as np

from .config import load_config
from .mesh_io import load_mesh


def verify_stability(max_disp_share: float = 0.01,
                     jump_share: float = 0.2) -> int:
    cfg = load_config()
    mesh = load_mesh(cfg.build_cache / "mesh")

    data_dir = cfg.dist / "cartogram" / "v1"
    manifest = json.loads((data_dir / "manifest.json").read_text())
    n_f = manifest["dimensions"]["num_frames"]
    n_v = manifest["dimensions"]["num_vertices"]
    positions = np.fromfile(data_dir / "positions.f32", dtype="<f4") \
        .reshape(n_f, n_v, 2).astype(np.float64)

    frames = manifest["years"]["frames"]
    world = float(np.hypot(mesh.world_bounds[2] - mesh.world_bounds[0],
                           mesh.world_bounds[3] - mesh.world_bounds[1]))
    disp_limit = max_disp_share * world

    problems = []

    # 1) Globale Vertexverschiebung zwischen Folgeframes
    for i in range(n_f - 1):
        d = np.linalg.norm(positions[i + 1] - positions[i], axis=1).max()
        if d > disp_limit:
            problems.append(
                f"{frames[i]['year']}->{frames[i+1]['year']}: "
                f"Verschiebung {d/1000:,.0f} km > {disp_limit/1000:,.0f} km")

    # 2) Flächenverlauf je Entität (Zusammenbruch + Erholung = Springen)
    for ei in range(mesh.num_entities):
        areas = np.array([_entity_area(mesh, positions[f], ei)
                          for f in range(n_f)])
        for i in range(1, n_f - 1):
            a0, a1, a2 = areas[i - 1], areas[i], areas[i + 1]
            if a0 <= 0:
                continue
            if (a1 < a0 * (1 - jump_share)
                    and a2 > a1 * (1 + jump_share)):
                problems.append(
                    f"{mesh.entity_ids[ei]} "
                    f"{frames[i]['year']}: Fläche {a0/1e6:,.0f} -> "
                    f"{a1/1e6:,.0f} -> {a2/1e6:,.0f} km² (Springen)")

    if problems:
        print(f"[stability] {len(problems)} Probleme:")
        for p in problems[:20]:
            print(f"  - {p}")
        return 1
    print(f"[stability] OK: {n_f} Frames, keine Sprünge "
          f"(Verschiebung < {disp_limit/1000:,.0f} km/Jahr)")
    return 0


def _entity_area(mesh, positions, ei: int) -> float:
    """Fläche einer Entität via Shoelace über alle Ring-Teile."""
    total = 0.0
    for ext_idx, hole_idxs in mesh.entity_parts[ei]:
        _, ext, _ = mesh.rings[ext_idx]
        total += _shoelace(positions, ext)
        for h in hole_idxs:
            _, hole, _ = mesh.rings[h]
            total -= abs(_shoelace(positions, hole))
    return abs(total)


def _shoelace(positions, ids) -> float:
    xy = positions[ids]
    x, y = xy[:, 0], xy[:, 1]
    return 0.5 * float(
        np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


if __name__ == "__main__":
    sys.exit(verify_stability())
