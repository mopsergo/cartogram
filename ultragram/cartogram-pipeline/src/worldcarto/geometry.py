"""Ausgangsgeometrie (Plan §5.3).

- vollständige Natural-Earth-Geometrie laden (lokal bevorzugt, URL-Fallback)
- Geometrien reparieren
- Entitäten nach Registry dissolven (historische Aggregate)
- nicht beanspruchte Gebiete zu OTHER_WORLD zusammenfassen
  (ohne konfigurierte Ausschlüsse wie die Antarktis)
- in die flächentreue Equal-Earth-Projektion überführen

Natural Earth 110m ist bereits generalisiert und teilt Grenzvertices
exakt zwischen Nachbarn; die konfigurierbare Zusatz-Vereinfachung ist
deshalb standardmäßig deaktiviert (simplify_tolerance_m: 0), damit
gemeinsame Grenzen erhalten bleiben.
"""
from __future__ import annotations

import geopandas as gpd
import shapely
from shapely.ops import unary_union

from .config import PipelineConfig
from .entities import EntityRegistry


def load_natural_earth(cfg: PipelineConfig) -> gpd.GeoDataFrame:
    """Lokale Quelle bevorzugt, sonst Download-Fallback (Plan §4)."""
    if cfg.natural_earth.is_file():
        world = gpd.read_file(cfg.natural_earth)
        print(f"[geometry] Natural Earth lokal: {cfg.natural_earth.name} "
              f"({len(world)} Features)")
    else:
        print(f"[geometry] Lokale Datei fehlt, lade {cfg.natural_earth_url}")
        world = gpd.read_file(cfg.natural_earth_url)
    return world


def build_entity_geometries(cfg: PipelineConfig,
                             registry: EntityRegistry) -> gpd.GeoDataFrame:
    """GeoDataFrame mit einer (Multi-)Polygon-Geometrie je Entität.

    Reihenfolge = Register-Reihenfolge; CRS = Equal Earth (cfg.crs).
    """
    world = load_natural_earth(cfg)
    world = world.rename(columns={"ADM0_A3": "Code"})
    world["Code"] = world["Code"].astype(str).str.strip()
    world["geometry"] = world.geometry.buffer(0)  # Reparatur

    by_code = {
        code: geom for code, geom in zip(world["Code"], world.geometry)
    }
    name_by_code = {
        code: name for code, name in zip(world["Code"], world["NAME"])
    }

    excluded = set(cfg.exclude_features)
    claimed: set[str] = set()

    records = []
    for entity in registry:
        members = [c for c in entity.geometry_members if c in by_code]
        missing = [c for c in entity.geometry_members if c not in by_code]
        if missing:
            raise ValueError(
                f"{entity.id}: keine Natural-Earth-Geometrie für {missing}"
            )
        if not members and not entity.is_other_world:
            raise ValueError(f"{entity.id}: keine Geometrie-Mitglieder definiert")
        claimed.update(members)

        if entity.is_other_world:
            rest = [
                (code, geom) for code, geom in by_code.items()
                if code not in claimed and name_by_code.get(code) not in excluded
            ]
            geoms = [g for _, g in rest]
            print(f"[geometry] OTHER_WORLD aus {len(geoms)} nicht beanspruchten "
                  f"Features (ohne {sorted(excluded)})")
        else:
            geoms = [by_code[c] for c in members]

        if not geoms:
            raise ValueError(f"{entity.id}: leere Geometrie")
        merged = unary_union(geoms) if len(geoms) > 1 else geoms[0]
        if merged.is_empty:
            raise ValueError(f"{entity.id}: leere Geometrie nach Dissolve")
        records.append({"entity_id": entity.id, "geometry": merged})

    gdf = gpd.GeoDataFrame(records, geometry="geometry", crs=world.crs)

    # Antarktis-Check: ausgeschlossene Features (per NAME) dürfen von
    # keiner Entität beansprucht worden sein.
    excluded = set(cfg.exclude_features)
    bad = world[world["NAME"].isin(excluded)]
    if not bad.empty:
        claimed_excluded = sorted(set(bad["Code"]) & claimed)
        if claimed_excluded:
            raise ValueError(
                f"Ausgeschlossene Features sind von Entitäten beansprucht: "
                f"{claimed_excluded}")

    gdf = gdf.to_crs(cfg.crs)

    if cfg.simplify_tolerance_m > 0:
        # Nur auf explizite Anforderung: bricht gemeinsame Grenzen auf
        # (dokumentiert); Standard ist 0 – siehe Modul-Docstring.
        gdf["geometry"] = gdf.geometry.simplify(
            cfg.simplify_tolerance_m, preserve_topology=True)

    for entity in registry:
        geom = gdf.geometry.iloc[entity.index]
        if geom.area <= 0:
            raise ValueError(f"{entity.id}: Fläche <= 0 nach Projektion")

    total = float(gdf.geometry.area.sum())
    print(f"[geometry] {len(gdf)} Entitäten, CRS {gdf.crs.to_epsg()}, "
          f"Gesamtfläche {total / 1e6:,.0f} km²")
    return gdf
