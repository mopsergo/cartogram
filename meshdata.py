"""
Baut aus den Länder-Polygonen (Natural Earth 110m) extrudierte 3D-Prismen
(Plotly Mesh3d) - die "Höhe" jedes Landes entspricht seinem Energieverbrauch.

Historische Aggregate des Datensatzes (F. USSR, Czechoslovakia, Yugoslavia,
Eritrea & Ethiopia) werden als Vereinigung der Mitgliedsländer dargestellt.
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path

import pandas as pd
import shapely
from shapely.geometry import shape
from shapely.ops import triangulate, unary_union

BASE = Path(__file__).resolve().parent
DATA_CSV = BASE / "data" / "TableA13_energy_consumption_per_country_annual.csv"
GEOJSON = BASE / "data" / "ne_110m_admin_0_countries.geojson"

SIMPLIFY_TOL = 0.18   # Grad - Detailreduktion der Polygone (Weltmaßstab)
HMAX = 30.0           # maximale "Höhe" (in Grad-Äquivalenten) fuer vmax
MIN_AREA = 1e-8

# Datensatz-Name -> Natural-Earth-Namen (Vereinigungen als Liste)
SPECIAL = {
    "USA": ["United States of America"],
    "UK": ["United Kingdom"],
    "S. Arabia": ["Saudi Arabia"],
    "N. Zealand": ["New Zealand"],
    "Congo R.D.": ["Dem. Rep. Congo"],
    "Haïti": ["Haiti"],
    "Dominican Rep.": ["Dominican Rep."],
    "Czechoslovakia": ["Czechia", "Slovakia"],
    "F. USSR": [
        "Russia", "Ukraine", "Belarus", "Moldova", "Lithuania", "Latvia",
        "Estonia", "Georgia", "Armenia", "Azerbaijan", "Kazakhstan",
        "Uzbekistan", "Turkmenistan", "Kyrgyzstan", "Tajikistan",
    ],
    "Yugoslavia": [
        "Serbia", "Croatia", "Bosnia and Herz.", "Slovenia", "Montenegro",
        "North Macedonia",
    ],
    "Eritrea & Ethiopia": ["Ethiopia", "Eritrea"],
}

# Farben je Makroregion
MACRO_COLORS = {
    "WE": "#5aa9ff",   # Westeuropa
    "EE": "#ff5d73",   # Osteuropa
    "As": "#ffb02e",   # Asien
    "Af": "#ff8fd0",   # Afrika
    "ME": "#52d273",   # Naher Osten
    "LA": "#b085f5",   # Lateinamerika
    "O":  "#4dd6c8",   # Ozeanien
    "":   "#8b98a5",
}

MACRO_LABELS = {
    "WE": "Westeuropa",
    "EE": "Osteuropa",
    "As": "Asien",
    "Af": "Afrika",
    "ME": "Naher Osten",
    "LA": "Lateinamerika",
    "O": "Ozeanien",
    "": "Sonstige",
}


# ---------------------------------------------------------------- Helpers

def _parts(geom):
    """Alle (Multi)Polygon-Teile eines Geometrie-Objekts."""
    if geom is None or geom.is_empty:
        return
    if geom.geom_type == "Polygon":
        yield geom
    elif geom.geom_type == "MultiPolygon":
        yield from geom.geoms


def _simplify(geom):
    """Vereinfachung mit Fallback, falls kleine Inseln kollabieren."""
    s = geom.simplify(SIMPLIFY_TOL, preserve_topology=True)
    if (not s.is_empty and s.geom_type in ("Polygon", "MultiPolygon")
            and s.area > MIN_AREA):
        return s
    return geom


def _triangulate_part(poly):
    """Delaunay-Dreiecke, die vollstaendig im Polygon liegen."""
    out = []
    for t in triangulate(poly):
        if t.geom_type != "Polygon" or t.area <= 1e-10:
            continue
        if poly.covers(t):
            out.append(t)
    return out


def _hex_rgb(h):
    """Hex-Farbe -> (r, g, b) im Bereich 0-255 (so will es Mesh3d.vertexcolor)."""
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _darken(rgb, f):
    return tuple(c * f for c in rgb)


def height_of(v, vmax, mode="sqrt"):
    """Wert -> Hoehe (0..HMAX) fuer Modus linear/sqrt/log."""
    if v is None or v <= 0:
        return 0.0
    t = min(v / vmax, 1.0)
    if mode == "linear":
        u = t
    elif mode == "sqrt":
        u = t ** 0.5
    else:  # log
        u = math.log10(1 + 99 * t) / 2
    return HMAX * u


# ---------------------------------------------------------------- Builder

def build(year0=1820, mode="sqrt"):
    """Liefert (figure_data, store_payload) fuer die Dash-App."""
    t0 = time.time()

    df = pd.read_csv(DATA_CSV)
    total = df[df["Country"] == "TOTAL"].set_index("Year")["Energy_consumption_Mtoe"]
    df = df[df["Country"] != "TOTAL"]

    piv = df.pivot(index="Country", columns="Year",
                   values="Energy_consumption_Mtoe").sort_index()
    years = [int(c) for c in piv.columns]
    names = list(piv.index)
    values = [[round(float(v), 4) for v in piv.loc[n]] for n in names]
    macro = df.drop_duplicates("Country").set_index("Country")["Macroarea"].to_dict()
    vmax = max(max(row) for row in values)

    geo = json.loads(GEOJSON.read_text())
    by_name = {f["properties"]["NAME"]: shape(f["geometry"])
               for f in geo["features"]}

    traces = []        # Mesh3d-kwargs je Land
    ztops = []         # 0/1-Maske je Trace (1 = Deckel-Vertices)
    missing = []
    used = set()       # Natural-Earth-Namen, die der Datensatz abbildet

    for ci, country in enumerate(names):
        ne_names = SPECIAL.get(country, [country])
        geoms = []
        for n in ne_names:
            g = by_name.get(n)
            if g is None:
                missing.append(f"{country} -> {n}")
            else:
                geoms.append(g)
                used.add(n)
        if not geoms:
            print(f"[meshdata] WARNUNG: keine Geometrie fuer {country}")
            continue

        # erst vereinigen (exakte Binnengrenzen), dann vereinfachen
        merged = unary_union(geoms) if len(geoms) > 1 else geoms[0]
        merged = _simplify(merged)

        col = MACRO_COLORS.get(str(macro.get(country, "")), "#8b98a5")
        top_rgb = _hex_rgb(col)
        bot_rgb = _darken(top_rgb, 0.42)

        xs, ys, zt = [], [], []          # zt: 1=oben, 0=unten
        I, J, K = [], [], []

        for poly in _parts(merged):
            # Vertex-Indizes fuer Deckel (T) und Boden (B) je Ring anlegen
            rings = [poly.exterior, *poly.interiors]
            idx_of = {}
            for ring in rings:
                coords = list(ring.coords)
                if len(coords) > 1 and coords[0] == coords[-1]:
                    coords = coords[:-1]
                if len(coords) < 3:
                    continue
                t_ring, b_ring = [], []
                for x, y in coords:
                    base = len(xs)
                    xs.append(x); ys.append(y); zt.append(1)
                    t_ring.append(base)
                    idx_of[(round(x, 9), round(y, 9))] = base
                    xs.append(x); ys.append(y); zt.append(0)
                    b_ring.append(base + 1)
                m = len(t_ring)
                for k in range(m):          # Seitenwaende: 2 Dreiecke je Kante
                    k2 = (k + 1) % m
                    I += [t_ring[k], t_ring[k]]
                    J += [t_ring[k2], b_ring[k2]]
                    K += [b_ring[k2], b_ring[k]]

            # Deckel & Boden: Dreieckung
            for tri in _triangulate_part(poly):
                tx = [round(c[0], 9) for c in tri.exterior.coords[:3]]
                ty = [round(c[1], 9) for c in tri.exterior.coords[:3]]
                try:
                    ta = [idx_of[(tx[i], ty[i])] for i in range(3)]
                except KeyError:
                    continue
                ba = [a + 1 for a in ta]
                I += [ta[0], ba[0]]
                J += [ta[1], ba[1]]
                K += [ta[2], ba[2]]          # (a,b,c) oben, (a,c,b) unten

        if not I:
            print(f"[meshdata] WARNUNG: leeres Mesh fuer {country}")
            continue

        h0 = height_of(values[ci][years.index(year0)], vmax, mode)
        z = [h0 if m else 0.0 for m in zt]
        vcol = [top_rgb if m else bot_rgb for m in zt]

        traces.append(dict(
            type="mesh3d",
            x=xs, y=ys, z=z,
            i=I, j=J, k=K,
            vertexcolor=vcol,
            flatshading=False,
            lighting=dict(ambient=0.82, diffuse=0.75, specular=0.02,
                          roughness=0.9, fresnel=0.02),
            hovertemplate="<b>%{fullData.name}</b><extra></extra>",
            name=country,
            showlegend=False,
        ))
        ztops.append(zt)

    # Kuestenlinien als dezente Referenz (Trace 0)
    lines_x, lines_y, lines_z = [], [], []
    for f in geo["features"]:
        g = shape(f["geometry"]).simplify(0.35, preserve_topology=True)
        for poly in _parts(g):
            for ring in [poly.exterior, *poly.interiors]:
                coords = list(ring.coords)
                if len(coords) > 1 and coords[0] == coords[-1]:
                    coords = coords[:-1]
                if len(coords) < 3:
                    continue
                for x, y in coords:
                    lines_x.append(x); lines_y.append(y); lines_z.append(0.0)
                lines_x.append(None); lines_y.append(None); lines_z.append(None)
    coast = dict(type="scatter3d", mode="lines", x=lines_x, y=lines_y,
                 z=lines_z, line=dict(color="#26313f", width=1),
                 hoverinfo="skip", showlegend=False, name="coast")

    # Laender OHNE Eintrag im Datensatz: flache graue Flaechen ("keine
    # Daten"), damit die Karte vollstaendig wirkt und klar unterscheidet:
    # hier fehlen Daten - nicht: hier gibt es keinen Verbrauch.
    nd_x, nd_y, nd_name = [], [], []
    nd_i, nd_j, nd_k = [], [], []
    nd_idx = {}
    nd_countries = 0
    for f in geo["features"]:
        name = f["properties"]["NAME"]
        if name in used or name == "Antarctica":
            continue
        n_tris = 0
        for poly in _parts(_simplify(shape(f["geometry"]))):
            for tri in _triangulate_part(poly):
                ids = []
                for x, y in tri.exterior.coords[:3]:
                    key = (round(x, 9), round(y, 9))
                    if key not in nd_idx:
                        nd_idx[key] = len(nd_x)
                        nd_x.append(x)
                        nd_y.append(y)
                        nd_name.append(name)
                    ids.append(nd_idx[key])
                nd_i.append(ids[0])
                nd_j.append(ids[1])
                nd_k.append(ids[2])
                n_tris += 1
        if n_tris:
            nd_countries += 1

    nodata = None
    if nd_i:
        nodata = dict(
            type="mesh3d",
            x=nd_x, y=nd_y, z=[0.0] * len(nd_x),
            i=nd_i, j=nd_j, k=nd_k,
            vertexcolor=[_hex_rgb("#232d3b")] * len(nd_x),
            customdata=nd_name,
            hovertemplate="<b>%{customdata}</b><br>"
                          "keine Daten im Datensatz<extra></extra>",
            flatshading=False,
            lighting=dict(ambient=0.82, diffuse=0.75, specular=0.02,
                          roughness=0.9, fresnel=0.02),
            name="Keine Daten",
            showlegend=False,
        )

    # Top-10 je Jahr (fuer Seitenpanel)
    tops = []
    for yi in range(len(years)):
        ranked = sorted(enumerate(values), key=lambda r: -(r[1][yi] or 0))[:10]
        tops.append([[ci, round(v[yi], 4)] for ci, v in ranked])

    mesh_idx = list(range(1, len(traces) + 1))   # Trace-Indizes der Laender
    store = dict(
        years=years,
        names=names,
        values=values,
        colors=[MACRO_COLORS.get(str(macro.get(n, "")), "#8b98a5") for n in names],
        macro=[str(macro.get(n, "")) for n in names],
        macroLabels=MACRO_LABELS,
        ztop=ztops,
        traceIdx=mesh_idx,
        traceCountry=list(range(len(traces))),   # 1 Mesh je Land, sortiert
        vmax=round(vmax, 3),
        hmax=HMAX,
        total=[round(float(total.get(y, 0) or 0), 1) for y in years],
        tops=tops,
    )

    if missing:
        print("[meshdata] fehlende Zuordnungen:", ", ".join(missing))
    print(f"[meshdata] {len(traces)} Laender, "
          f"{sum(len(t['x']) for t in traces)} Vertices, "
          f"{sum(len(t['i']) for t in traces)} Flaechen, "
          f"+ {nd_countries} Laender ohne Daten (grau), "
          f"{time.time() - t0:.1f}s")
    return coast, traces, store, nodata


if __name__ == "__main__":
    coast, traces, store, nodata = build()
    print("Jahre:", store["years"][:3], "...", store["years"][-1])
    print("Beispiel-Name:", store["names"][0], store["values"][0][:5])
    print("No-Data-Trace:", nodata["name"], len(nodata["x"]), "Vertices")
