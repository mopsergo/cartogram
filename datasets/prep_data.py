"""
Country-level prep table: world population share + per-capita energy, 1820-2020.

Builds country_populationshare_energypercapita.csv from
TableP2_population_per_country_annual.csv (population, thousands, 195
countries) and TableA13_energy_consumption_per_country_annual.csv
(energy, Mtoe; only ~68 countries have values, the rest stay empty).

One row per country and year:

    Country, Macroarea, Year, Population, Energy_consumption,
    World_population, World_share, Per_capita_energy_consumption

- Population: absolute persons (Population_000 x 1000)
- Energy_consumption: Mtoe, as in the source
- World_population: the TOTAL row of TableP2, in absolute persons.
  Since the country table now covers all 195 countries, TOTAL is the
  world population. The Table_A1P1 "World" rows (used while only 72
  countries were tracked, cf. world_share_implementation.md) come from
  a different population series: they lie up to 0.7% BELOW the sum of
  the 195 countries in 38 years, which would make the remainder
  negative. TOTAL is checked against the country sum.
- World_share: Population / World_population, as a fraction of 1
  (e.g. Algeria 2020: 43.851/7795.482 Mio. = 0.005625 = 0.5625%).
- No OTHER_WORLD rows: with World_population = sum of all countries
  the remainder is zero. The cartogram pipeline builds its OTHER_WORLD
  entity itself from the small states without own map geometry
  (entities.yaml), see worldcarto.ingest.ensure_other_world.
- Per_capita_energy_consumption: kWh per capita, as in percapita.py
  (1 Mtoe = 11.63 TWh = 1.163e10 kWh)
- Macroarea: the source files spell regions out ("Western Europe");
  they are mapped to the short codes the pipeline uses (WE, EE, NAm,
  LA, O, As, ME, Af). "NAm" is used instead of "NA" because the latter
  is in pandas' default NA list and would silently become NaN on a
  plain pd.read_csv().

Run:  python3 prep_data.py   (from this directory)  -> writes the CSV
next to the sources and prints a short sanity summary.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parent
POP_CSV = BASE / "TableP2_population_per_country_annual.csv"
ENERGY_CSV = BASE / "TableA13_energy_consumption_per_country_annual.csv"
OUT_CSV = BASE / "country_populationshare_energypercapita.csv"

KWH_PER_MTOE = 1.163e10      # 1 Mtoe = 11.63 TWh (as in percapita.py)
TOTAL = "TOTAL"              # sum-of-countries rows in the country tables

MACROAREA_CODES = {
    "Western Europe": "WE", "Eastern Europe": "EE", "North America": "NAm",
    "Latin America": "LA", "Oceania": "O", "Asia": "As",
    "Middle East": "ME", "Africa": "Af",
}

COLUMNS = [
    "Country", "Macroarea", "Year", "Population",
    "Energy_consumption", "World_population", "World_share",
    "Per_capita_energy_consumption",
]


def prep() -> pd.DataFrame:
    """Merge population + energy per country/year, add world share."""
    pop = pd.read_csv(POP_CSV)
    energy = pd.read_csv(ENERGY_CSV)

    # --- Phase 1: world population per year (thousands) = TOTAL row,
    # which must equal the sum of all countries.
    world_pop_000 = pop.loc[pop["Country"] == TOTAL].set_index("Year")["Population_000"]
    if world_pop_000.index.duplicated().any():
        raise ValueError(f"{POP_CSV.name}: duplicate {TOTAL!r} rows per year")
    country_sum = pop.loc[pop["Country"] != TOTAL].groupby("Year")["Population_000"].sum()
    max_dev = ((country_sum / world_pop_000) - 1.0).abs().max()
    if max_dev > 1e-6:
        raise ValueError(f"{TOTAL} deviates from the country sum by {max_dev:.2e}")

    # Countries only; keep country-years present in both tables (inner join).
    df = pd.merge(
        pop.loc[pop["Country"] != TOTAL,
                ["Country", "Macroarea", "Year", "Population_000"]],
        energy.loc[energy["Country"] != TOTAL,
                   ["Country", "Year", "Energy_consumption_Mtoe"]],
        on=["Country", "Year"],
        how="inner",
    )

    # Coverage check: every country-year should exist in both sources.
    n_pop = int((pop["Country"] != TOTAL).sum())
    if len(df) != n_pop:
        print(f"[prep] WARNUNG: {n_pop - len(df)} country-years missing in {ENERGY_CSV.name}")

    unknown = sorted(set(df["Macroarea"].dropna()) - set(MACROAREA_CODES))
    if unknown:
        raise ValueError(f"unknown macroareas: {unknown}")
    df["Macroarea"] = df["Macroarea"].map(MACROAREA_CODES)

    df["Population"] = df["Population_000"] * 1000.0
    df["Energy_consumption"] = df["Energy_consumption_Mtoe"]

    # --- Phase 2: world_share = country population / world population
    # (both in thousands -> the ratio is the same), fraction of 1.
    world_pop = df["Year"].map(world_pop_000)
    df["World_population"] = world_pop * 1000.0
    df["World_share"] = (df["Population_000"] / world_pop).round(8)
    # kWh per capita: Mtoe -> kWh, divided by persons (NaN without energy).
    df["Per_capita_energy_consumption"] = (
        df["Energy_consumption_Mtoe"] * KWH_PER_MTOE / df["Population"]
    ).round(1)

    out = (df[COLUMNS]
           .sort_values(["Country", "Year"], kind="stable")
           .reset_index(drop=True))

    # --- Validierung: country shares ≈ 1.0 per year.
    max_err = (out.groupby("Year")["World_share"].sum() - 1.0).abs().max()
    if max_err > 1e-5:
        print(f"[prep] WARNUNG: World_share sum deviates from 1.0 by {max_err:.2e}")

    out.to_csv(OUT_CSV, index=False)
    return out


if __name__ == "__main__":
    t = prep()

    years = sorted(t["Year"].unique())
    last = years[-1]
    with_energy = t.loc[t["Energy_consumption"].notna(), "Country"].nunique()
    share_last = t.loc[t["Year"] == last, "World_share"].sum()
    top = t.loc[t["Year"] == last].nlargest(3, "World_share")
    print(f"[prep] {len(t)} rows, {t['Country'].nunique()} countries "
          f"({with_energy} with energy data), {years[0]}-{last} -> {OUT_CSV.name}")
    print(f"[prep] World_share sum {last}: {share_last:.6f}")
    for _, r in top.iterrows():
        print(f"    {r['Country']}: {r['World_share']:.2%}, "
              f"{r['Per_capita_energy_consumption']:,.0f} kWh/Kopf")
    a = t[(t["Country"] == "Austria") & (t["Year"] == 1820)].iloc[0]
    print(f"[prep] check Austria 1820: pop={a['Population']:,.0f}, "
          f"world_share={a['World_share']:.4%} of {a['World_population']:,.0f}, "
          f"{a['Per_capita_energy_consumption']} kWh/Kopf")
