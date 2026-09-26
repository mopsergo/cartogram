"""
Flow-basiertes Kartogramm (dichte-angleichende Kartenprojektion).

Implementiert den "fast flow-based"-Ansatz aus Gastner, Seguy & More,
PNAS 2018 (https://pmc.ncbi.nlm.nih.gov/articles/PMC5877977/):

- lineare Dichte-Entnahme   rho(x,y,t) = (1-t)*rho0(x,y) + t*rho_bar  [Gl. 4]
- Geschwindigkeitsfeld      v = grad(G)/rho(t)  mit  Laplace(G) = rho0 - rho_bar
  (Neumann-Rand, geloest per Spiegelungs-FFT; entspricht Gl. 5-7)
- Integration dr/dt = v(r,t) fuer t in [0,1] (Praediktor-Korrektor-Mittelpunkt)
- Gauss-Stabilisierung von rho0 + aeussere Iteration, bis die Flaechen
  der Laender ihre Zielwerte (proportional zur Bevoelkerung) treffen.

Ziel hier: LANDFLAECHE proportional zur Bevoelkerung (TableP2), die
SAEULENHOEHE bleibt der Gesamtverbrauch (TableA13) und wird wie in Tab 1
per Slider animiert. Laender ohne Datensatz-Eintrag treiben passiv mit
(Dichte 1), ebenso Ozean und Kuestenlinien.

Die Verschiebungen werden als SNAPSHOTS (alle 10 Jahre) berechnet und
gecacht; die App interpoliert zwischen ihnen, sodass die Flaeche mit
dem Jahres-Slider mitwaechst. Build-Skript: build_cartograms.py
"""
from __future__ import annotations

import copy
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
import shapely
from shapely.geometry import shape

from meshdata import SPECIAL, _parts, _simplify

BASE = Path(__file__).resolve().parent
GEOJSON = BASE / "datasets" / "ne_110m_admin_0_countries.geojson"
POP_CSV = BASE / "datasets" / "TableP2_population_per_country_annual.csv"
CACHE = BASE / "cartogram_cache.json"

RES = 0.5          # Rasterweite in Grad
BLUR = 0.6         # Gauss-Stabilisierung (Zellen)
STEPS = 80         # Integrationsschritte pro Runde (t: 0 -> 1)
MAX_ITER = 15      # aeussere Iterationen
TOL = 0.04         # Ziel: 90 % der Laender unter 4 % Fehler

ANTARCTICS = {"Antarctica", "Fr. S. Antarctic Lands"}

_COLLECT_CACHE = None


# ---------------------------------------------------------------- Sammeln

def _collect(names):
    """Alle Land-Kuestenvertices (global dedupliziert) + Ring-IDs je Land.

    Liefert:
      xs, ys      – Original-Koordinaten (Reihenfolge = Vertex-ID)
      data_rings  – [country_index] -> [(ext_ids, [hole_ids...]), ...]
      coast_ids   – flache Liste aller Kuesten-Vertex-IDs (0.35-Simplifizierung)
    """
    global _COLLECT_CACHE
    if _COLLECT_CACHE is not None and _COLLECT_CACHE[0] is names:
        return _COLLECT_CACHE[1]
    geo = json.loads(GEOJSON.read_text())
    by_name = {f["properties"]["NAME"]: shape(f["geometry"])
               for f in geo["features"]}

    xs, ys = [], []
    idx = {}

    def vid(x, y):
        key = (round(x, 9), round(y, 9))
        i = idx.get(key)
        if i is None:
            i = len(xs)
            idx[key] = i
            xs.append(x)
            ys.append(y)
        return i

    def ring_ids(ring):
        coords = list(ring.coords)
        if len(coords) > 1 and coords[0] == coords[-1]:
            coords = coords[:-1]
        if len(coords) < 3:
            return []
        return [vid(x, y) for x, y in coords]

    data_rings = []
    for country in names:
        geoms = [by_name[n] for n in SPECIAL.get(country, [country])
                 if n in by_name]
        if not geoms:
            data_rings.append([])
            continue
        merged = shapely.union_all(geoms) if len(geoms) > 1 else geoms[0]
        merged = _simplify(merged)
        parts = []
        for poly in _parts(merged):
            ext = ring_ids(poly.exterior)
            holes = [ring_ids(r) for r in poly.interiors]
            holes = [h for h in holes if len(h) >= 3]
            if len(ext) >= 3:
                parts.append((ext, holes))
        data_rings.append(parts)

    coast_ids = []
    for f in geo["features"]:
        if f["properties"]["NAME"] in ANTARCTICS:
            continue
        g = shape(f["geometry"]).simplify(0.35, preserve_topology=True)
        for poly in _parts(g):
            for ring in [poly.exterior, *poly.interiors]:
                coast_ids.extend(ring_ids(ring))

    # Ring-Vertices der Laender OHNE Datensatz (gleiche 0.18-Loesung wie
    # meshdata fuer den grauen No-Data-Trace) – sie muessen mitwandern,
    # sonst reisst die Graeflaeche beim Interpolieren.
    used_ne = set()
    for country in names:
        for n in SPECIAL.get(country, [country]):
            if n in by_name:
                used_ne.add(n)
    for f in geo["features"]:
        name = f["properties"]["NAME"]
        if name in used_ne or name in ANTARCTICS:
            continue
        for poly in _parts(_simplify(shape(f["geometry"]))):
            for ring in [poly.exterior, *poly.interiors]:
                ring_ids(ring)

    result = (xs, ys, data_rings, coast_ids)
    _COLLECT_CACHE = (list(names), result)
    return result


def orig_xy(names):
    """Originale (unverzerrte) Koordinaten aller Landvertices, geflachtet."""
    xs, ys, _, _ = _collect(list(names))
    out = []
    for x, y in zip(xs, ys):
        out.append(float(x))
        out.append(float(y))
    return out


def vertex_rows(orig_flat, traces):
    """Pro Trace: Zeilen-Index je Vertex nach Original-Koordinate (-1 = None)."""
    key2row = {}
    for r in range(0, len(orig_flat), 2):
        key2row[(round(orig_flat[r], 9), round(orig_flat[r + 1], 9))] = r // 2
    out = []
    for tr in traces:
        xs, ys = tr.get("x") or [], tr.get("y") or []
        rows = []
        for i in range(len(xs)):
            if xs[i] is None:
                rows.append(-1)
                continue
            rows.append(key2row.get(
                (round(float(xs[i]), 9), round(float(ys[i]), 9)), -1))
        out.append(rows)
    return out


def _polygons(xs, ys, parts):
    """Shapely-Polygone je Land aus Vertex-IDs (fuer Flaeche/Raster)."""
    out = []
    for ext, holes in parts:
        try:
            p = shapely.Polygon(
                list(zip([xs[i] for i in ext], [ys[i] for i in ext])),
                holes=[list(zip([xs[i] for i in h], [ys[i] for i in h]))
                       for h in holes])
            if not p.is_empty:
                out.append(p)
        except Exception:
            continue
    return out


# ------------------------------------------------- Raster / Dichte / Poisson

def _blur(f, sigma):
    """Separierbare Gauss-Glaettung mit Reflexion am Rand."""
    if sigma <= 0:
        return f
    r = int(3 * sigma) + 1
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    k /= k.sum()

    def conv1(a, axis):
        pad = [(0, 0)] * a.ndim
        pad[axis] = (r, r)
        ap = np.pad(a, pad, mode="edge")
        out = np.empty_like(a)
        sl = [slice(None)] * a.ndim
        for o in range(len(k)):
            sl[axis] = slice(o, o + a.shape[axis])
            out = out + k[o] * ap[tuple(sl)]
        return out

    return conv1(conv1(f, 0), 1)


def _poisson_neumann(rhs, dx, dy):
    """Loest Laplace(G) = rhs mit Neumann-Rand per Spiegelungs-FFT."""
    n1, n2 = rhs.shape
    m = np.zeros((2 * n1, 2 * n2))
    m[:n1, :n2] = rhs
    m[:n1, n2:] = rhs[:, ::-1]
    m[n1:, :n2] = rhs[::-1, :]
    m[n1:, n2:] = rhs[::-1, ::-1]
    f = np.fft.fft2(m)
    k1 = 2 * np.pi * np.fft.fftfreq(2 * n1, d=dx)
    k2 = 2 * np.pi * np.fft.fftfreq(2 * n2, d=dy)
    k2m = k1[:, None] ** 2 + k2[None, :] ** 2
    k2m[0, 0] = 1.0
    psi = np.fft.ifft2(-f / k2m).real[:n1, :n2]
    return psi


def _sample(field, lon, lat, lon0, lat0, res):
    """Bilineare Interpolation eines (lat, lon)-Gitters an Punkten."""
    n1, n2 = field.shape
    fx = (lon - lon0) / res
    fy = (lat - lat0) / res
    i0 = np.clip(np.floor(fx).astype(int), 0, n2 - 2)
    j0 = np.clip(np.floor(fy).astype(int), 0, n1 - 2)
    tx = np.clip(fx - i0, 0, 1)
    ty = np.clip(fy - j0, 0, 1)
    f = field
    return ((1 - tx) * (1 - ty) * f[j0, i0] + tx * (1 - ty) * f[j0, i0 + 1]
            + (1 - tx) * ty * f[j0 + 1, i0] + tx * ty * f[j0 + 1, i0 + 1])


# ------------------------------------------------------------------- Flow

_CACHE_MEMO = None


def _load_cache():
    """Cache einmal je Prozess laden (prueft Bevoelkerungs-/Geo-Dateien)."""
    global _CACHE_MEMO
    if _CACHE_MEMO is not None:
        return _CACHE_MEMO
    stamp = {"pop": POP_CSV.stat().st_mtime,
             "geo": GEOJSON.stat().st_mtime,
             "res": RES}
    cache = None
    try:
        c = json.loads(CACHE.read_text())
        if c.get("stamp") == stamp and isinstance(c.get("snapshots"), dict):
            cache = c
    except Exception:
        pass
    if cache is None:
        cache = {"stamp": stamp, "snapshots": {}}
    _CACHE_MEMO = cache
    return cache


def build(store, year=2020):
    """Verschiebungs-Dict {(rx,ry): (nx,ny)} fuer ein Bevoelkerungsjahr.

    Snapshots werden in cartogram_cache.json gehalten (invalidiert, wenn
    Bevoelkerungs- oder Geometriedatei sich aendern).
    """
    key = str(year)
    cache = _load_cache()
    if key in cache["snapshots"]:
        disp = {(e[0], e[1]): (e[2], e[3])
                for e in cache["snapshots"][key]}
        print(f"[cartogram] {len(disp)} Vertices aus Cache "
              f"(Bevoelkerung {year})")
        return disp, {}

    disp, stats = _compute(store, year)
    cache["snapshots"][key] = [[k[0], k[1], v[0], v[1]]
                               for k, v in disp.items()]
    CACHE.write_text(json.dumps(cache))
    return disp, stats


def _compute(store, year):
    """Der Rechenkern: eine flow-basierte Loesung fuer ein Jahr."""
    t0 = time.time()
    names = store["names"]
    xs, ys, data_rings, coast_ids = _collect(names)
    xs = np.array(xs, dtype=float)
    ys = np.array(ys, dtype=float)
    oxs, oys = xs.copy(), ys.copy()      # Original fuer das Dict am Ende

    pop = pd.read_csv(POP_CSV)
    pop = pop[pop["Year"] == year].set_index("Country")["Population_000"]
    P = np.array([float(pop.get(c, 0.0)) or 0.0 for c in names])

    lon0, lat0 = -180.0 + RES / 2, -90.0 + RES / 2
    nx, ny = int(360 / RES), int(180 / RES)

    # Ziel: Flaeche_k proportional P_k, Summe = aktuelle Summe
    target = None
    stats = {"year": year, "iters": 0, "max_err": None, "examples": {},
             "trace": []}

    for it in range(MAX_ITER):
        # --- Flaechen (exakt, via Shapely) -> Dichte je Land
        areas = np.array(
            [sum(p.area for p in _polygons(xs, ys, data_rings[ci]))
             for ci in range(len(names))])
        if target is None:
            scale = areas[P > 0].sum() / max(P[P > 0].sum(), 1e-9)
            target = P * scale

        # --- Raster: Zelle -> Land-Index (nur Datenlaender, slice-weise)
        cell_owner = np.full(ny * nx, -1, dtype=np.int32)
        counts = np.zeros(len(names), dtype=np.int64)
        for ci in range(len(names)):
            polys = _polygons(xs, ys, data_rings[ci])
            for p in polys:
                x0, y0, x1, y1 = p.bounds
                i0 = max(int(np.floor((x0 - RES - lon0) / RES)), 0)
                i1 = min(int(np.ceil((x1 + RES - lon0) / RES)), nx - 1)
                j0 = max(int(np.floor((y0 - RES - lat0) / RES)), 0)
                j1 = min(int(np.ceil((y1 + RES - lat0) / RES)), ny - 1)
                if i0 > i1 or j0 > j1:
                    continue
                shapely.prepare(p)
                sub = (slice(j0, j1 + 1), slice(i0, i1 + 1))
                gx_sub, gy_sub = np.meshgrid(
                    lon0 + RES * np.arange(i0, i1 + 1),
                    lat0 + RES * np.arange(j0, j1 + 1))
                rows = cell_owner.reshape(ny, nx)
                flat = rows[sub].ravel()
                free = flat == -1
                if not free.any():
                    continue
                inside = shapely.contains_xy(p, gx_sub.ravel()[free],
                                             gy_sub.ravel()[free])
                sel_local = np.nonzero(free)[0][inside]
                flat[sel_local] = ci
                rows[sub] = flat.reshape(j1 - j0 + 1, i1 - i0 + 1)
                counts[ci] += len(sel_local)

        # --- Dichte: exakte Flaeche je Land (nicht Zellenzahl!), neutral 1
        rho = np.ones(ny * nx)
        used = P > 0
        s = areas[used].sum() / max(P[used].sum(), 1e-9)
        for ci in range(len(names)):
            if counts[ci] > 0 and P[ci] > 0 and areas[ci] > 1e-9:
                rho[cell_owner == ci] = s * P[ci] / areas[ci]
        rho = rho.reshape(ny, nx)
        rho = _blur(rho, BLUR)
        rho /= rho.mean()
        rho = np.clip(rho, 0.05, None)

        # --- Poisson + Geschwindigkeitsfeld
        g_pot = _poisson_neumann(rho - 1.0, RES, RES)
        dvx = np.gradient(g_pot, RES, axis=1)
        dvy = np.gradient(g_pot, RES, axis=0)

        # --- Integration t: 0 -> 1 (alle Vertices gleichzeitig)
        px, py = xs.copy(), ys.copy()
        for s in range(STEPS):
            t = s / STEPS
            dt = 1.0 / STEPS

            def vel(qx, qy, tt):
                r_t = (1 - tt) * _sample(rho, qx, qy, lon0, lat0, RES) + tt
                vx = _sample(dvx, qx, qy, lon0, lat0, RES) / r_t
                vy = _sample(dvy, qx, qy, lon0, lat0, RES) / r_t
                return vx, vy

            vx0, vy0 = vel(px, py, t)
            mx, my = px + 0.5 * dt * vx0, py + 0.5 * dt * vy0
            vx1, vy1 = vel(mx, my, t + 0.5 * dt)
            px += dt * vx1
            py += dt * vy1

        px = np.clip(px, -179.99, 179.99)
        py = np.clip(py, -89.99, 89.99)
        xs, ys = px, py
        stats["iters"] = it + 1

        # --- Flaechenfehler (nach der Advektion)
        areas_end = np.array(
            [sum(p.area for p in _polygons(xs, ys, data_rings[ci]))
             for ci in range(len(names))])
        err = np.abs(areas_end - target) / np.maximum(target, 1e-9)
        err[P <= 0] = 0.0
        stats["max_err"] = float(np.max(err))
        stats["p90_err"] = float(np.quantile(err, 0.9))
        worst = np.argsort(err)[-3:][::-1]
        stats["examples"] = {
            names[i]: (round(areas_end[i] / max(target[i], 1e-9), 3),
                       round(err[i], 3)) for i in worst
        }
        if stats["p90_err"] < TOL:
            break
        stats["trace"].append(round(stats["p90_err"], 3))

    disp = {(round(float(ox), 9), round(float(oy), 9)): (float(nx_), float(ny_))
            for ox, oy, nx_, ny_ in zip(oxs, oys, xs, ys)}

    stats["seconds"] = round(time.time() - t0, 1)
    print(f"[cartogram] {year}: {stats['iters']} Iterationen, "
          f"max. Flaechenfehler {stats['max_err']:.1%} "
          f"(90% unter {stats['p90_err']:.1%}), "
          f"{len(disp)} Vertices verschoben, {stats['seconds']}s")
    return disp, stats


def snapshots(store, years):
    """Verschiebungen fuer mehrere Bevoelkerungsjahre (Cache je Jahr)."""
    out = {}
    for y in years:
        out[y], _ = build(store, year=y)
    return out


# ----------------------------------------------------------------- Patches

def patch_trace(trace, disp):
    """x/y eines Traces (Mesh3d/scatter3d) verschieben (Kopie)."""
    tr = copy.deepcopy(trace)
    xs, ys = tr.get("x"), tr.get("y")
    if not xs:
        return tr
    for i in range(len(xs)):
        if xs[i] is None:
            continue
        d = disp.get((round(float(xs[i]), 9), round(float(ys[i]), 9)))
        if d:
            xs[i], ys[i] = d
    return tr


def build_traces(mesh_traces, store, disp, year0=1820, mode="sqrt"):
    """Kartogramm-Traces: wie Tab 1 (Gesamtverbrauch), aber verzerrte Basis."""
    from meshdata import height_of

    yi0 = store["years"].index(year0)
    out = []
    for t, tr in enumerate(mesh_traces):
        ci = store["traceCountry"][t]
        v = store["values"][ci][yi0]
        h = height_of(v, store["vmax"], mode)
        tr2 = patch_trace(tr, disp)
        tr2["z"] = [h if m else 0.0 for m in store["ztop"][t]]
        out.append(tr2)
    return out
