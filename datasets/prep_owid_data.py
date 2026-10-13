"""
Country-level prep table for the OWID run (1965-2025).

Builds owid_population_energy_1965_2025.csv in the same layout as
country_populationshare_energypercapita.csv (prep_data.py), so the
cartogram pipeline can solve it as a separate run
(`worldcarto.cli --dataset owid ...`, configs/datasets/owid.yaml):

    Country, Macroarea, Year, Population, Energy_consumption,
    World_population, World_share, Per_capita_energy_consumption

Sources (Our World in Data):
- owid_population/population-with-un-projections.csv
  UN World Population Prospects 2024: estimates 1950-2023, medium
  projection from 2024 (used for 2024-2025).
- owid_energy_mix/primary-energy-use-per-person.csv
  Primary energy per person (kWh; Energy Institute Statistical Review
  2026 + EIA), countries from 1965/1980, until 2025.

- Matching: OWID uses ISO alpha-3 codes, the entity register
  (configs/entities.yaml) Natural Earth ADM0_A3. The first geometry
  member of each entity is mapped via the Natural Earth ISO_A3_EH field
  (differs e.g. for Palestine PSX/PSE, South Sudan SDS/SSD). "Country"
  is written as the entity's first source name, so the pipeline's
  register resolves it unchanged.
- World_population: the OWID "World" row. Everything not covered by a
  map entity (small states, Taiwan, Kosovo, Western Sahara, ...) is the
  remainder, which the pipeline assigns to OTHER_WORLD.
- Per-capita energy of successor states: before a country's own series
  starts, the value of its historical aggregate is used (USSR 1965-1984
  for Russia, Ukraine, Kazakhstan, ...; Yugoslavia, Serbia and
  Montenegro, Czechoslovakia). Without it, most of Eurasia would have
  no energy value (grey, passive in the energy cartograms) until 1985.
- 2025: the EIA series ends in 2024, so ~90 countries (most of Africa,
  parts of Asia and Latin America) have no 2025 value. Their 2024
  per-capita value is carried forward (only into the final year, at
  most CARRY_FORWARD_YEARS), so the last frame is not half grey and
  the energy cartograms do not jump.
- Energy_consumption (Mtoe) = per-capita kWh x population / 1.163e10
  (1 Mtoe = 11.63 TWh, as in prep_data.py).

Run:  ../.venv/bin/python prep_owid_data.py   (from this directory)
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import yaml

BASE = Path(__file__).resolve().parent
REPO = BASE.parent
POP_CSV = BASE / "owid_population" / "population-with-un-projections.csv"
ENERGY_CSV = BASE / "owid_energy_mix" / "primary-energy-use-per-person.csv"
NE_GEOJSON = BASE / "ne_110m_admin_0_countries.geojson"
ENTITIES_YAML = REPO / "ultragram/cartogram-pipeline/configs/entities.yaml"
OUT_CSV = BASE / "owid_population_energy_1965_2025.csv"

YEAR_MIN, YEAR_MAX = 1965, 2025
KWH_PER_MTOE = 1.163e10
CARRY_FORWARD_YEARS = 1     # trailing gap filled with the last value

# Historical aggregates (OWID entity names) -> successor ISO codes
AGGREGATES = {
    "USSR": ["RUS", "UKR", "BLR", "KAZ", "UZB", "TKM", "KGZ", "TJK",
             "AZE", "ARM", "GEO", "MDA", "EST", "LVA", "LTU"],
    "Yugoslavia": ["SRB", "HRV", "SVN", "BIH", "MKD", "MNE"],
    "Serbia and Montenegro": ["SRB", "MNE"],
    "Czechoslovakia": ["CZE", "SVK"],
}

COLUMNS = [
    "Country", "Macroarea", "Year", "Population",
    "Energy_consumption", "World_population", "World_share",
    "Per_capita_energy_consumption",
]


def entity_iso_codes() -> list[tuple[str, str, str]]:
    """(source name, macroarea, ISO code) per map entity."""
    ne = json.load(open(NE_GEOJSON, encoding="utf-8"))
    iso_of = {}
    for f in ne["features"]:
        p = f["properties"]
        iso = p.get("ISO_A3_EH") or p.get("ISO_A3")
        iso_of[p["ADM0_A3"]] = iso if iso and iso != "-99" else p["ADM0_A3"]
    entities = yaml.safe_load(open(ENTITIES_YAML, encoding="utf-8"))["entities"]
    out = []
    for ent in entities:
        members = ent.get("geometry_members") or []
        if ent.get("is_other_world") or not members:
            continue
        out.append((ent["source_names"][0], ent["macroarea"],
                    iso_of.get(members[0], members[0])))
    return out


def prep() -> pd.DataFrame:
    years = range(YEAR_MIN, YEAR_MAX + 1)

    pop = pd.read_csv(POP_CSV)
    pop["value"] = pop["Population"].fillna(pop["Population (Projected)"])
    pop = pop[pop["Year"].between(YEAR_MIN, YEAR_MAX)]
    world = pop.loc[pop["Entity"] == "World"].set_index("Year")["value"]
    pop_by_code = {c: dict(zip(g["Year"], g["value"]))
                   for c, g in pop.dropna(subset=["Code"]).groupby("Code")}

    en = pd.read_csv(ENERGY_CSV)
    en_col = en.columns[-1]
    en_by_code = {c: dict(zip(g["Year"], g[en_col]))
                  for c, g in en.dropna(subset=["Code"]).groupby("Code")}
    en_agg = {n: dict(zip(g["Year"], g[en_col]))
              for n, g in en.groupby("Entity") if n in AGGREGATES}

    rows, missing_pop, filled, carried = [], [], {}, {}
    for name, macro, iso in entity_iso_codes():
        p_series = pop_by_code.get(iso)
        if p_series is None:
            missing_pop.append(name)
            continue
        e_series = dict(en_by_code.get(iso, {}))
        known = [y for y, v in e_series.items() if not pd.isna(v)]
        if known:
            last = max(known)
            for y in range(last + 1,
                           min(YEAR_MAX, last + CARRY_FORWARD_YEARS) + 1):
                e_series[y] = e_series[last]
                carried.setdefault(last, []).append(name)
        for y in years:
            p = p_series.get(y)
            if p is None or pd.isna(p):
                raise ValueError(f"{name} ({iso}): no population for {y}")
            pc = e_series.get(y)
            if pc is None or pd.isna(pc):
                pc = None
                for agg, succ in AGGREGATES.items():
                    if iso in succ and y in en_agg.get(agg, {}):
                        pc = en_agg[agg][y]
                        filled.setdefault(name, []).append(y)
                        break
            w = float(world[y])
            rows.append({
                "Country": name, "Macroarea": macro, "Year": y,
                "Population": float(p),
                "Energy_consumption":
                    float(pc) * float(p) / KWH_PER_MTOE if pc is not None else None,
                "World_population": w,
                "World_share": float(p) / w,
                "Per_capita_energy_consumption":
                    float(pc) if pc is not None else None,
            })
    if missing_pop:
        raise ValueError(f"no OWID population for: {missing_pop}")

    df = pd.DataFrame(rows, columns=COLUMNS)
    share_sum = df.groupby("Year")["World_share"].sum()
    if (share_sum > 1.0).any():
        raise ValueError(f"country shares exceed 1: {share_sum[share_sum > 1]}")
    for last, names in carried.items():
        print(f"carried forward from {last}: {len(names)} countries")
    print(f"successor states filled from aggregates: "
          + ", ".join(f"{k} {v[0]}-{v[-1]}" for k, v in filled.items()))
    return df


if __name__ == "__main__":
    df = prep()
    df.to_csv(OUT_CSV, index=False)
    share = df.groupby("Year")["World_share"].sum()
    with_energy = df.dropna(subset=["Per_capita_energy_consumption"]) \
        .groupby("Year")["Country"].count()
    print(f"{OUT_CSV.name}: {df['Country'].nunique()} countries, "
          f"{YEAR_MIN}-{YEAR_MAX}, {len(df)} rows")
    print(f"  covered world share: {share.min():.4f}-{share.max():.4f} "
          f"(remainder -> OTHER_WORLD)")
    print(f"  countries with energy data: {with_energy.min()}-{with_energy.max()}")
