"""Fixtures: Mesh einmal bauen und für alle Tests wiederverwenden."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from worldcarto.config import load_config  # noqa: E402
from worldcarto.entities import load_registry  # noqa: E402


@pytest.fixture(scope="session")
def cfg():
    return load_config()


@pytest.fixture(scope="session")
def registry():
    return load_registry()


@pytest.fixture(scope="session")
def canonical(cfg, registry):
    from worldcarto.ingest import build_canonical
    return build_canonical(cfg, registry)


@pytest.fixture(scope="session")
def mesh(cfg, registry):
    from worldcarto.geometry import build_entity_geometries
    from worldcarto.topology import build_mesh
    from worldcarto.triangulate import triangulate_mesh
    gdf = build_entity_geometries(cfg, registry)
    m = build_mesh(gdf, registry.ids(),
                   vertex_precision_m=cfg.vertex_precision_m, crs=cfg.crs)
    triangulate_mesh(m)
    return m
