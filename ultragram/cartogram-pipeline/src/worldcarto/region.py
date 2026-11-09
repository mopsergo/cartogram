"""Regions-Läufe (config.active_region): Geometrie-Zuschnitt.

Eigenes Modul statt geometry.py: der Mesh-Stamp hasht geometry.py –
eine Änderung dort würde die Meshes (und damit alle gelösten Frames)
der Welt-Läufe ungültig machen, obwohl deren Geometrie gleich bleibt.
"""
from __future__ import annotations

import geopandas as gpd
import pyproj
from shapely.geometry import MultiPolygon


def keep_parts_in_bbox(gdf: gpd.GeoDataFrame, bbox, seam_lon: float
                       ) -> gpd.GeoDataFrame:
    """Polygon-Teile außerhalb eines Kastens verwerfen.

    bbox = [lon_min, lat_min, lon_max, lat_max] in echten Grad (vor der
    Naht-Rotation); lon_min > lon_max = Kasten über den Antimeridian
    (z. B. [-30, 30, -168.5, 85]: Europa bis Tschukotka). Entscheidend
    ist ein repräsentativer Punkt je Teil – Länder werden nicht
    zerschnitten, nur ferne Teile entfallen (Französisch-Guayana bei
    Frankreich zöge die Regions-Bounds sonst bis nach Südamerika).

    gdf: Ergebnis von geometry.build_entity_geometries (projiziert,
    Längengrade um die Naht rotiert).
    """
    lon0, lat0, lon1, lat1 = (float(v) for v in bbox)
    to_lonlat = pyproj.Transformer.from_crs(gdf.crs, "EPSG:4326",
                                            always_xy=True)

    def inside(part) -> bool:
        c = part.representative_point()
        lon_rot, lat = to_lonlat.transform(c.x, c.y)
        # Naht-Rotation zurückdrehen (Umkehrung von rotate_longitudes)
        lon = ((lon_rot + seam_lon + 180.0 + 540.0) % 360.0) - 180.0
        in_lon = (lon0 <= lon <= lon1 if lon0 <= lon1
                  else lon >= lon0 or lon <= lon1)
        return in_lon and lat0 <= lat <= lat1

    gdf = gdf.copy()
    geoms = []
    for eid, geom in zip(gdf["entity_id"], gdf.geometry):
        parts = (list(geom.geoms) if geom.geom_type == "MultiPolygon"
                 else [geom])
        kept = [p for p in parts if not p.is_empty and inside(p)]
        if not kept:
            raise ValueError(f"{eid}: kein Polygon-Teil im Regions-Kasten")
        if len(kept) < len(parts):
            print(f"[region] {eid}: {len(parts) - len(kept)} Teil(e) "
                  f"außerhalb des Kastens {list(bbox)} verworfen")
        geoms.append(MultiPolygon(kept) if len(kept) > 1 else kept[0])
    gdf["geometry"] = geoms
    return gdf
