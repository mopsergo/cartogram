"""Tests: Regions-Läufe (Europa mit/ohne Russland, config.active_region)."""
from __future__ import annotations

import dataclasses

import pytest

from worldcarto.entities import load_registry
from worldcarto.topology import padded_bounds

EUROPE = {"id": "europe", "label": "Europa", "macroareas": ["WE", "EE"],
          "exclude_entities": [], "domain_padding": 0.3}
EUROPE_NORUS = {**EUROPE, "id": "europe_norus",
                "exclude_entities": ["RUS"]}


@pytest.mark.parametrize("region, n", [(EUROPE, 38), (EUROPE_NORUS, 37)])
def test_region_registry(region, n):
    reg = load_registry(region=region)
    assert len(reg) == n
    assert not reg.has_other_world
    assert {e.macroarea for e in reg} == {"WE", "EE"}
    assert [e.index for e in reg] == list(range(n))
    assert ("RUS" in reg.ids()) == (region is EUROPE)


def test_world_registry_unchanged(registry):
    assert registry.has_other_world
    assert len(registry) == 167


@pytest.mark.parametrize("region", [EUROPE, EUROPE_NORUS])
def test_region_canonical_shares(cfg, region):
    from worldcarto.ingest import build_canonical
    reg = load_registry(region=region)
    rcfg = dataclasses.replace(cfg, region=region)
    can = build_canonical(rcfg, reg)
    assert set(can["entity_id"]) == set(reg.ids())
    sums = can.groupby("year")["world_share"].sum()
    assert ((sums - 1.0).abs() < 1e-9).all()
    # Bezugsgröße ist die Regionsbevölkerung, nicht die Welt
    pop = can.groupby("year")["population"].sum()
    world = can.groupby("year")["world_population"].first()
    assert ((pop / world - 1.0).abs() < 1e-9).all()


def test_padded_bounds():
    assert padded_bounds((0, 0, 10, 4), 0.3) == (-3.0, -3.0, 13.0, 7.0)


def test_keep_parts_in_bbox_across_antimeridian():
    import geopandas as gpd
    from shapely.geometry import MultiPolygon, box

    from worldcarto.region import keep_parts_in_bbox
    europe = box(0, 45, 10, 55)
    guiana = box(-54, 2, -52, 5)          # wie Französisch-Guayana
    chukotka = box(-180, 64, -172, 68)    # jenseits des Antimeridians
    gdf = gpd.GeoDataFrame(
        {"entity_id": ["A"]},
        geometry=[MultiPolygon([europe, guiana, chukotka])], crs="EPSG:4326")
    # seam_lon 180 = keine Rotation; Kasten über den Antimeridian
    out = keep_parts_in_bbox(gdf, [-30, 30, -168.5, 85], 180.0)
    kept = out.geometry.iloc[0]
    assert len(kept.geoms) == 2
    assert not kept.intersects(guiana)
    assert kept.intersects(chukotka) and kept.intersects(europe)
