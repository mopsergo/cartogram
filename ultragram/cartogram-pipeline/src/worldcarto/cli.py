"""CLI der Cartogram-Pipeline (Plan §9).

    PYTHONPATH=src python -m worldcarto.cli <command>

Commands:
    validate       Minimalvalidierung der Rohdaten (Plan §2)
    ingest         CSV -> kanonisches Parquet (Plan §5.1)
    mesh           Ausgangsgeometrie + kanonisches Mesh + Triangulierung
    solve [--years ...] [--solver NAME]  Jahres-Keyframes (mit Cache)
    export         Browserartefakte (Plan §6) + Kopie nach web/public
    debug-frames   Matplotlib-PNGs für Testjahre (Plan §4)
    build          alles: ingest -> mesh -> solve -> export
    quality        Qualitätsbericht zusammenfassen
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

from . import __version__
from .config import config_hash, load_config
from .entities import load_registry
from .ingest import load_canonical, run_ingest, targets_for_year
from .mesh_io import load_mesh, save_mesh
from .solvers import resolve_chain
from .solvers.carto_flow import CartoFlowSolver  # noqa: F401 (Registrierung)
from .solvers.cartogram_cpp import CartogramCppSolver  # noqa: F401
from .solvers.legacy_tiles import LegacyTilesSolver  # noqa: F401


def _mesh_path(cfg) -> Path:
    return cfg.build_cache / "mesh"


def _build_or_load_mesh(cfg, registry, force: bool = False):
    import hashlib
    base = _mesh_path(cfg)
    h = hashlib.sha256()
    h.update(config_hash(cfg).encode())
    from .config import file_sha256
    h.update(file_sha256(cfg.natural_earth).encode())
    tag = h.hexdigest()[:16]
    stamp = base.with_suffix(".stamp")
    if (not force and stamp.is_file() and stamp.read_text() == tag
            and base.with_suffix(".npz").is_file()):
        print(f"[mesh] Cache-Treffer ({tag})")
        return load_mesh(base)
    from .geometry import build_entity_geometries
    from .topology import build_mesh
    from .triangulate import coverage_error, triangulate_mesh
    gdf = build_entity_geometries(cfg, registry)
    mesh = build_mesh(gdf, registry.ids(),
                      vertex_precision_m=cfg.vertex_precision_m,
                      crs=cfg.crs)
    triangulate_mesh(mesh)
    cov = coverage_error(mesh)
    print(f"[mesh] {mesh.num_vertices} Vertices, {len(mesh.rings)} Ringe, "
          f"{len(mesh.triangles)} Dreiecke, Triangulierungs-Abdeckung "
          f"{cov:.2e}")
    if cov > 1e-3:
        print("[mesh] WARNUNG: Triangulierung deckt Polygone nicht exakt",
              file=sys.stderr)
    save_mesh(mesh, base)
    stamp.write_text(tag)
    return mesh


def cmd_validate(args) -> int:
    cfg = load_config()
    registry = load_registry()
    from .ingest import build_canonical
    df = build_canonical(cfg, registry)
    print(f"[validate] OK: {len(df)} Zeilen, "
          f"{df['entity_id'].nunique()} Entitäten, "
          f"{cfg.year_min}-{cfg.year_max}, Shares summieren auf 1.0")
    return 0


def cmd_ingest(args) -> int:
    cfg = load_config()
    registry = load_registry()
    run_ingest(cfg, registry)
    return 0


def cmd_mesh(args) -> int:
    cfg = load_config()
    registry = load_registry()
    _build_or_load_mesh(cfg, registry, force=args.force)
    return 0


def cmd_solve(args) -> int:
    cfg = load_config()
    registry = load_registry()
    canonical = load_canonical(cfg)
    mesh = _build_or_load_mesh(cfg, registry)
    solver, errors = resolve_chain(cfg.solver_chain, config=cfg.flow)
    for e in errors:
        print(f"[solve] {e}")
    print(f"[solve] Solver: {solver.name} {solver.version}")
    mesh_hash = (_mesh_path(cfg).with_suffix(".stamp").read_text()
                 if _mesh_path(cfg).with_suffix(".stamp").is_file()
                 else "mesh")
    from .temporal import build_keyframes
    build_keyframes(cfg, mesh, solver, years=args.years,
                    mesh_hash=mesh_hash, canonical=canonical)
    return 0


def _load_frames(cfg, mesh):
    """Gespeicherte Frame-Caches laden (build-cache/frames).

    Fällt auf einen bestehenden Index zurück, falls der erwartete
    (hash-versionierte) Index fehlt – z.B. wenn sich Kosmetik in den
    Konfigurationen geändert hat, die Frames selbst aber gültig sind
    (Targets-Hash verprobt jede Frame-Datei). Der gefundene Index wird
    unter dem erwarteten Namen neu abgelegt.
    """
    mesh_hash = (_mesh_path(cfg).with_suffix(".stamp").read_text()
                 if _mesh_path(cfg).with_suffix(".stamp").is_file()
                 else "mesh")
    from .temporal import frames_index_path
    index_path = frames_index_path(cfg, mesh_hash)
    if not index_path.is_file():
        candidates = sorted(index_path.parent.glob("index_*.json"))
        for cand in candidates:
            data = json.loads(cand.read_text())
            missing = [e["file"] for e in data.values()
                       if not (index_path.parent / e["file"]).is_file()]
            if not missing and data:
                print(f"[frames] Erwarteter Index fehlt; übernehme "
                      f"{cand.name} ({len(data)} Frames)")
                index_path.write_text(cand.read_text())
                break
    if not index_path.is_file():
        return None, mesh_hash
    index = json.loads(index_path.read_text())
    frames = []
    for ck in sorted(index, key=lambda k: index[k]["year"]):
        data = np.load(index_path.parent / index[ck]["file"])
        stats = json.loads(str(data["stats_json"]))
        if "errors" in data:
            stats["errors"] = np.asarray(data["errors"])
        frames.append({
            "year": index[ck]["year"],
            "positions": data["positions"],
            "stats": stats,
            "intermediate": False,
            "targets": data["targets"],
            "passive": data["passive"],
        })
    return frames, mesh_hash


def cmd_export(args) -> int:
    import numpy as np  # noqa: F401
    cfg = load_config()
    registry = load_registry()
    canonical = load_canonical(cfg)
    mesh = _build_or_load_mesh(cfg, registry)
    frames, _ = _load_frames(cfg, mesh)
    if not frames:
        print("[export] Keine gelösten Frames gefunden – zuerst 'solve'",
              file=sys.stderr)
        return 1
    from .export import export
    export(cfg, registry, mesh, frames, canonical)
    return 0


def cmd_debug_frames(args) -> int:
    import numpy as np
    cfg = load_config()
    registry = load_registry()
    canonical = load_canonical(cfg)
    mesh = _build_or_load_mesh(cfg, registry)
    frames, _ = _load_frames(cfg, mesh)
    if not frames:
        print("[debug] Keine Frames – zuerst 'solve'", file=sys.stderr)
        return 1
    by_year = {round(f["year"]): f for f in frames}
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    from .debug import render_frame
    from .export import build_values
    years = args.years or cfg.test_years
    for year in years:
        frame = by_year.get(year)
        if frame is None:
            print(f"[debug] Jahr {year} nicht gelöst – übersprungen")
            continue
        values = build_values(cfg, registry, canonical, [frame])[0]
        p = render_frame(mesh, frame["positions"], values, frame["year"],
                         frame["stats"].get("p90_error"),
                         out_dir / f"frame_{year}.png", ghost=mesh.positions)
        print(f"[debug] {p}")
    return 0


def cmd_quality(args) -> int:
    import pandas as pd
    cfg = load_config()
    path = cfg.dist / "cartogram" / "v1" / "quality.parquet"
    if not path.is_file():
        print("[quality] quality.parquet fehlt – zuerst 'export'",
              file=sys.stderr)
        return 1
    q = pd.read_parquet(path)
    frames = q.drop_duplicates("frame")
    print(f"[quality] {frames['frame'].nunique()} Frames")
    bad = frames[frames["quality_problems"] != "[]"]
    if len(bad):
        print(f"[quality] {len(bad)} Frames mit Problemen:")
        for _, r in bad.iterrows():
            print(f"  {r['year']}: {r['quality_problems']}")
    else:
        print("[quality] alle Frames gültig (keine Qualitätsprobleme)")
    per_frame = q.groupby("frame").agg(
        year=("year", "first"), p90=("p90_area_error", "first"),
        max_err=("max_area_error", "first"))
    print(per_frame.describe().to_string())
    return 0


def cmd_build(args) -> int:
    for fn in (cmd_ingest, cmd_mesh, cmd_solve, cmd_export):
        code = fn(argparse.Namespace(**vars(args)))
        if code != 0:
            return code
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="worldcarto", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", action="version",
                        version=f"worldcarto {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("validate", help="Rohdaten validieren")
    sub.add_parser("ingest", help="CSV -> kanonisches Parquet")

    p_mesh = sub.add_parser("mesh", help="kanonisches Mesh bauen")
    p_mesh.add_argument("--force", action="store_true")

    p_solve = sub.add_parser("solve", help="Jahres-Keyframes lösen")
    p_solve.add_argument("--years", type=int, nargs="*", default=None)

    sub.add_parser("export", help="Browserartefakte exportieren")

    p_dbg = sub.add_parser("debug-frames", help="Debug-PNGs rendern")
    p_dbg.add_argument("--years", type=int, nargs="*", default=None)
    p_dbg.add_argument("--out", default="debug_frames")

    sub.add_parser("quality", help="Qualitätsbericht anzeigen")
    sub.add_parser("verify-stability",
                   help="Exportierte Keyframes auf Sprünge prüfen")

    sub.add_parser("build", help="ingest -> mesh -> solve -> export")

    args = parser.parse_args(argv)
    handlers = {
        "validate": cmd_validate, "ingest": cmd_ingest, "mesh": cmd_mesh,
        "solve": cmd_solve, "export": cmd_export,
        "debug-frames": cmd_debug_frames, "quality": cmd_quality,
        "build": cmd_build,
        "verify-stability": lambda args: cmd_verify_stability(),
    }
    return handlers[args.command](args)


def cmd_verify_stability() -> int:
    from .stability import verify_stability
    return verify_stability()


if __name__ == "__main__":
    raise SystemExit(main())
