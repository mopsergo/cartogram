"""
Pro-Kopf-Energieverbrauch (kWh/Kopf) je Land, 1820-2020.

Kombiniert den Gesamtverbrauch (TableA13, Mtoe) mit der Bevoelkerung
(TableP2, Tausend) zu einem Werte-Grid, das exakt parallel zum Store
der Hauptkarte liegt (gleiche Laender-Reihenfolge, gleiche Jahre) –
Geometrie, Masken und Restyle-Logik lassen sich damit 1:1 wiederverwenden.

1 Mtoe = 11,63 TWh = 1,163e10 kWh
"""
from __future__ import annotations

import copy
from pathlib import Path

import pandas as pd

from meshdata import height_of

BASE = Path(__file__).resolve().parent
POP_CSV = BASE / "datasets" / "TableP2_population_per_country_annual.csv"

KWH_PER_MTOE = 1.163e10
UNIT = "kWh/Kopf"


def _de(v):
    if v is None:
        v = 0.0
    return f"{v:,.1f}".translate(str.maketrans({",": "\u202f", ".": ","}))


def _kwh(mtoe, pop_thousands):
    """Verbrauch (Mtoe) / Bevoelkerung (Tausend) -> kWh pro Kopf."""
    if mtoe is None or pop_thousands is None or not pop_thousands > 0:
        return None
    return round(mtoe * KWH_PER_MTOE / (pop_thousands * 1000.0), 1)


def _pop(series, year):
    if series is None:
        return None
    p = series.get(year)
    if p is None or pd.isna(p):
        return None
    return float(p)


def compute(store):
    """Pro-Kopf-Daten passend zum Store der Hauptkarte (gleiche Reihenfolge).

    Liefert values_pc (Grid parallel zu store.values), vmax_pc, tops_pc
    (Top 10 je Jahr) und avg_pc (Welt-O je Jahr, aus TOTAL).
    """
    names, years, values = store["names"], store["years"], store["values"]

    pop = pd.read_csv(POP_CSV)
    piv = pop.pivot(index="Country", columns="Year", values="Population_000")
    total_pop = (pop[pop["Country"] == "TOTAL"]
                 .set_index("Year")["Population_000"])

    values_pc = []
    for ci, country in enumerate(names):
        s = piv.loc[country] if country in piv.index else None
        values_pc.append(
            [_kwh(values[ci][yi], _pop(s, year))
             for yi, year in enumerate(years)]
        )

    vmax_pc = max((v for row in values_pc for v in row if v), default=0.0)

    tops_pc = []
    for yi in range(len(years)):
        ranked = sorted(enumerate(values_pc),
                        key=lambda r: -(r[1][yi] or 0))[:10]
        tops_pc.append([[ci, round(v[yi], 1)]
                        for ci, v in ranked if v[yi] is not None])

    avg_pc = [_kwh(store["total"][yi], _pop(total_pop, year))
              for yi, year in enumerate(years)]

    print(f"[percapita] {len(values_pc)} Laender, max {vmax_pc:,.0f} {UNIT}, "
          f"Welt-O {avg_pc[-1]:,.0f} {UNIT} ({years[-1]})")
    return dict(values_pc=values_pc, vmax_pc=round(vmax_pc, 1),
                tops_pc=tops_pc, avg_pc=avg_pc)


def build_traces(mesh_traces, store, year0=1820, mode="sqrt"):
    """Mesh3d-Traces mit Pro-Kopf-Hoehen im Startjahr (fuer Tab 2).

    Kopiert die Geometrie der Hauptkarte (x/y/i/j/k/vertexcolor) und setzt
    nur Hoehen (z) und Hover-Namen neu.
    """
    yi0 = store["years"].index(year0)
    out = []
    for t, tr in enumerate(mesh_traces):
        ci = store["traceCountry"][t]
        v = store["values_pc"][ci][yi0]
        h = height_of(v, store["vmax_pc"], mode)
        tr2 = copy.deepcopy(tr)
        tr2["z"] = [h if m else 0.0 for m in store["ztop"][t]]
        tr2["name"] = f"{store['names'][ci]}: {_de(v)} {UNIT}"
        out.append(tr2)
    return out


if __name__ == "__main__":
    from meshdata import build

    _, _, st, _ = build(year0=1820, mode="sqrt")
    st.update(compute(st))
    print("Jahre:", st["years"][:3], "...", st["years"][-1])
    for ci in (0, st["names"].index("USA")):
        n = st["names"][ci]
        print(f"{n}: 1820={st['values_pc'][ci][0]} "
              f"2020={st['values_pc'][ci][-1]} {UNIT}")
    print("Top 10 pro Kopf 2020:",
          [(st["names"][ci], v) for ci, v in st["tops_pc"][-1][:5]])
