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
import numpy as np
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


def rotate_longitudes(world: gpd.GeoDataFrame, seam_lon: float,
                      excluded: set[str]) -> gpd.GeoDataFrame:
    """Längengrade rotieren, sodass die Naht (±180°) nur Ozean trifft.

    Natural Earth schneidet die Welt am Antimeridian – mitten durch
    Tschukotka. Der Globus-Renderer bildet die Kartogramm-Ebene per
    inverser Equal-Earth-Projektion auf die Kugel ab; dort läuft die
    künstliche Schnittkante als gerade, der echten Küste nicht folgende
    Linie durchs Land (Benutzerbericht). Wir verlegen die Naht auf den
    Meridian ``seam_lon`` (lon' = wrap(lon - seam_lon - 180°)): Russlands
    Festland- und Tschukotka-Teile liegen dann auf derselben Seite und
    verschmelzen im Dissolve zu einer durchgehenden Küste.

    Hart geprüft: kein (nicht ausgeschlossenes) Feature darf den
    Meridian berühren – sonst würden beim Wrap Polygone zerrissen.
    """
    from shapely.geometry import LineString

    def wrap(lon: float) -> float:
        return ((lon - seam_lon - 180.0 + 540.0) % 360.0) - 180.0

    def is_identity() -> bool:
        # seam_lon ≡ 180 (mod 360) => wrap(lon - 360) == lon: Identität
        return abs(((seam_lon - 180.0) % 360.0)) < 1e-9

    if is_identity():
        print("[geometry] Naht-Meridian ±180° (keine Rotation)")
        return world

    meridian = LineString([(seam_lon, -90), (seam_lon, 90)])
    guard = meridian.buffer(0.1)  # Sicherheitsabstand zum Meridian
    offenders = sorted({
        name for name, geom in zip(world["NAME"], world.geometry)
        if name not in excluded and not geom.is_empty
        and geom.intersects(guard)
    })
    if offenders:
        raise ValueError(
            f"Naht-Meridian {seam_lon}° trifft Features {offenders} – "
            "seam_lon in pipeline.yaml auf einen ozeanischen Meridian "
            "setzen (Antarktis ist ausgeschlossen)")

    def _shift(lon: float, lat: float) -> tuple[float, float]:
        return (wrap(lon), lat)

    world = world.copy()
    world["geometry"] = world.geometry.apply(
        lambda g: shapely.ops.transform(_shift, g) if not g.is_empty else g)
    print(f"[geometry] Längengrade rotiert: Naht bei {seam_lon}° "
          f"(Kartenmitte {wrap(0.0):+.2f}°)")
    return world


def _repair_snap_degenerations(geom, prec: float):
    """Teile mit nach Gitter-Rundung invaliden Ringen konsolidieren.

    Genutzt wird shapely.set_precision im selben Raster mit
    mode='valid_output': küssende/überlappende Mikrostrukturen
    werden konsistent aufgelöst, alle Koordinaten liegen danach
    exakt auf dem Gitter von build_mesh. Die Part-Anzahl je
    Eingangs-Polygon muss erhalten bleiben (sonst ValueError – die
    Namenszuordnung von OTHER_WORLD würde sonst still verfehlen).
    """
    if geom is None or geom.is_empty:
        return geom

    from shapely.geometry import MultiPolygon, Polygon

    def _snap_coords(coords):
        xy = np.asarray(coords)
        S = np.column_stack([
            np.round(xy[:, 0] / prec) * prec,
            np.round(xy[:, 1] / prec) * prec])
        if len(S) > 1 and (S[0] == S[-1]).all():
            S = S[:-1]
        return S

    def ring_invalid(coords) -> bool:
        S = _snap_coords(coords)
        return len(S) < 3 or not Polygon(S).is_valid

    def repair_part(poly):
        if poly.geom_type != "Polygon" or poly.is_empty:
            return poly
        # 1) Gitter-Snap des Teils simulieren (exakt wie build_mesh)
        rings = [poly.exterior.coords, *(h.coords for h in poly.interiors)]
        if not any(ring_invalid(r) for r in rings):
            return poly  # Snap bleibt valide: Teil unangetastet lassen
        snapped = Polygon(
            _snap_coords(poly.exterior.coords),
            [ _snap_coords(h.coords) for h in poly.interiors ])
        # 2) make_valid löst die Mikro-Struktur auf (wirft keine
        #    TopologyException, anders als set_precision direkt)
        fixed = shapely.make_valid(snapped)
        polys = ([fixed] if fixed.geom_type == "Polygon"
                 else [g for g in getattr(fixed, "geoms", [])
                       if g.geom_type == "Polygon" and not g.is_empty])
        # 3) Nur den größten Teil behalten: verworfen wird ausschließlich
        #    die haarfeine Degeneration (z.B. Sudans 30-µm-Kuss-Keil,
        #    ~2.000 m²). Größere Flächenverluste sind ein Datenfehler.
        polys.sort(key=lambda p: -p.area)
        dropped = sum(p.area for p in polys[1:])
        if dropped > max(1e-8 * polys[0].area, 1.0e4):
            raise ValueError(
                f"Snap-Reparatur würde {dropped:.0f} m² verwerfen "
                f"({dropped / polys[0].area:.2e} des Teils) – zu groß, "
                f"bbox {poly.bounds}")
        # 4) Zurück aufs Gitter (valid_output; Eingabe ist jetzt valide)
        sp = shapely.set_precision(polys[0], prec, mode="valid_output")
        sp_polys = ([sp] if sp.geom_type == "Polygon"
                    else [g for g in getattr(sp, "geoms", [])
                          if g.geom_type == "Polygon" and not g.is_empty])
        if len(sp_polys) != 1 or not sp_polys[0].is_valid:
            raise ValueError(
                f"Snap-Reparatur ergab {len(sp_polys)} invalide(s) Teil(e) "
                f"– bbox {poly.bounds}")
        return sp_polys[0]

    if geom.geom_type == "Polygon":
        return repair_part(geom)
    if geom.geom_type == "MultiPolygon":
        return MultiPolygon([repair_part(p) for p in geom.geoms
                             if not p.is_empty])
    return geom


def build_entity_geometries(cfg: PipelineConfig,
                             registry: EntityRegistry) -> gpd.GeoDataFrame:
    """GeoDataFrame mit einer (Multi-)Polygon-Geometrie je Entität.

    Reihenfolge = Register-Reihenfolge; CRS = Equal Earth (cfg.crs).
    """
    world = load_natural_earth(cfg)
    world = world.rename(columns={"ADM0_A3": "Code"})
    world["Code"] = world["Code"].astype(str).str.strip()
    world["geometry"] = world.geometry.buffer(0)  # Reparatur
    world = rotate_longitudes(world, cfg.seam_lon, set(cfg.exclude_features))
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
            # Deterministische gespeicherte Teilreihenfolge – sie dient
            # unten und in topology._iter_parts als stabile Tie-Break-
            # Basis. ACHTUNG: Diese Sortierung läuft noch in GRAD; die
            # eigentliche Namenszuordnung geschieht nach der Projektion
            # (Meter-Ordnung, weiter unten im Modul).
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

    # --- Snap-Degenerations-Reparatur ---------------------------------
    # build_mesh dedupliziert Vertices über ein 0.001-m-Gitter
    # (vertex_precision_m). Natural Earth enthält an einigen Stellen
    # „küssende“ Grenzvertices (z.B. Sudans Westspitze: ein Ring-
    # vertex liegt exakt kollinear auf einer nicht-nachbarten
    # Kante). Ob der eingerundete Ring danach gültig bleibt oder
    # sich um Mikrometer schneidet, hängt an der sub-mm-Position –
    # die Längengrad-Rotation (seam_lon) verschiebt genau diese.
    # Reparatur: Teile, deren gittergerundeter Ring invalid wird,
    # werden mit shapely.set_precision im selben Raster (valid_
    # output) konsolidiert. Part-Anzahl muss erhalten bleiben –
    # die Namenszuordnung weiter unten prüft das hart.
    gdf["geometry"] = [
        _repair_snap_degenerations(g, cfg.vertex_precision_m)
        for g in gdf.geometry
    ]

    if cfg.simplify_tolerance_m > 0:
        # Nur auf explizite Anforderung: bricht gemeinsame Grenzen auf
        # (dokumentiert); Standard ist 0 – siehe Modul-Docstring.
        gdf["geometry"] = gdf.geometry.simplify(
            cfg.simplify_tolerance_m, preserve_topology=True)

    # --- Namenszuordnung der Polygon-Teile (Restliche Welt) -----------
    # topology._iter_parts sortiert Polygon-Teile beim Mesh-Bau nach
    # (-Fläche, Bounds) im PROJIZIERTEN CRS (Meter). Oben wurden die
    # part_names dagegen in Grad mitgeordnet – bei 63 von 97 Teilen
    # wichen die Ordnungen ab, und die Ländernamen wanderten auf die
    # falschen Teile (z. B. hieß der Mongolei-Ring „Sudan“ und umge-
    # kehrt). Hier werden die Namen in exakt die Iterationsreihen-
    # folge gebracht, die _iter_parts erzeugt: gleicher Schlüssel im
    # selben CRS, beide Starts von derselben gespeicherten Teil-
    # reihenfolge (stabile Sortierung -> identisches Ergebnis).
    # Die Ring-/Vertex-Reihenfolge des Mesh ändert sich dadurch NICHT
    # – die gecachten Frames bleiben gültig.
    if "part_names" in gdf.columns:
        for i in range(len(gdf)):
            names_i = gdf.at[i, "part_names"]
            if not names_i:
                continue
            geom = gdf.geometry.iloc[i]
            parts = (list(geom.geoms) if geom.geom_type == "MultiPolygon"
                     else [geom])
            if len(parts) != len(names_i):
                raise ValueError(
                    f"Entität {i}: {len(parts)} Polygon-Teile, aber "
                    f"{len(names_i)} Namen – Zuordnung unzulässig")
            order = sorted(
                range(len(parts)),
                key=lambda k: (-parts[k].area, parts[k].bounds[0],
                               parts[k].bounds[1]))
            gdf.at[i, "part_names"] = [names_i[k] for k in order]

    for entity in registry:
        geom = gdf.geometry.iloc[entity.index]
        if geom.area <= 0:
            raise ValueError(f"{entity.id}: Fläche <= 0 nach Projektion")

    total = float(gdf.geometry.area.sum())
    print(f"[geometry] {len(gdf)} Entitäten, CRS {gdf.crs.to_epsg()}, "
          f"Gesamtfläche {total / 1e6:,.0f} km²")
    return gdf
