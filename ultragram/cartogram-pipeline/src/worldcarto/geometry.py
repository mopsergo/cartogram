"""Ausgangsgeometrie (Plan §5.3).

- vollständige Natural-Earth-Geometrie laden (lokal bevorzugt, URL-Fallback)
- Geometrien reparieren
- Entitäten nach Registry dissolven (historische Aggregate)
- nicht beanspruchte Gebiete als OTHER_WORLD aufnehmen – seit der
  Nutzeranforderung OHNE Dissolve: die einzelnen Länder bleiben
  als eigene Polygon-Teile erkennbar (ohne konfigurierte
  Ausschlüsse wie die Antarktis)
- in die flächentreue Equal-Earth-Projektion überführen

Natural Earth 110m ist bereits generalisiert und teilt Grenzvertices
exakt zwischen Nachbarn; die konfigurierbare Zusatz-Vereinfachung ist
deshalb standardmäßig deaktiviert (simplify_tolerance_m: 0), damit
gemeinsame Grenzen erhalten bleiben.
"""
from __future__ import annotations

import geopandas as gpd
import shapely
from shapely.geometry import MultiPolygon
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
            # Kein Dissolve: Die einzelnen Länder bleiben als eigen-
            # ständige Polygon-Teile erhalten – im Kartogramm sind die
            # tatsächlich vorhandenen Länder als eigene Formen erkennbar
            # (Benutzeranforderung). Geteilte Grenzen benachbarter
            # Mitglieder werden beim Mesh-Bau über die Koordinaten-
            # Dedupe zu einer gemeinsamen Vertex-Kette verschweißt,
            # Polygone kacheln also ohne Überlappung.
            # Zusätzlich wird je Polygon-Teil der Natural-Earth-Länder-
            # name geführt (Spalte part_names) – Renderer-Tooltip und
            # Detailpanel zeigen damit das konkrete Land, auch ohne
            # eigene Datenwerte.
            named: list[tuple[str, object]] = []
            for code, g in rest:
                nm = name_by_code.get(code, code)
                if g.geom_type == "MultiPolygon":
                    named.extend((nm, p) for p in g.geoms
                                 if not p.is_empty)
                elif not g.is_empty:
                    named.append((nm, g))
            if not named:
                raise ValueError(f"{entity.id}: leere Geometrie")
            # Deterministische Reihenfolge: exakt der Sortierung von
            # topology._iter_parts folgend, damit Namen und Ringe
            # deckungsgleich bleiben.
            named.sort(key=lambda t: (-t[1].area,
                                      t[1].bounds[0], t[1].bounds[1]))
            merged = (MultiPolygon([p for _, p in named])
                      if len(named) > 1 else named[0][1])
            part_names = [nm for nm, _ in named]
            print(f"[geometry] OTHER_WORLD aus {len(named)} Polygon-"
                  f"Teilen ({len(rest)} Features, ohne "
                  f"{sorted(excluded)}) – nicht verschmolzen, "
                  f"Ländergrenzen und -namen bleiben erhalten")
        else:
            geoms = [by_code[c] for c in members]
            if not geoms:
                raise ValueError(f"{entity.id}: leere Geometrie")
            # Historische Aggregate (z.B. UdSSR) bleiben verschmolzen:
            # eine Datenentität = eine Form.
            merged = unary_union(geoms) if len(geoms) > 1 else geoms[0]
            if merged.is_empty:
                raise ValueError(f"{entity.id}: leere Geometrie nach Dissolve")
            part_names = []
        records.append({"entity_id": entity.id, "geometry": merged,
                        "part_names": part_names})

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
