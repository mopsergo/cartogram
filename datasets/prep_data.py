"""
Country-level prep table: world population share + per-capita energy, 1820-2020.

Builds country_populationshare_energypercapita.csv from
TableP2_population_per_country_annual.csv (population, thousands),
TableA13_energy_consumption_per_country_annual.csv (energy, Mtoe) and
Table_A1P1_energy_population_percapita.csv (actual world population).

One row per country and year, plus one OTHER_WORLD row per year:

    Country, Macroarea, Year, Population, Energy_consumption,
    World_population, World_share, Per_capita_energy_consumption

- Population: absolute persons (Population_000 x 1000)
- Energy_consumption: Mtoe, as in the source
- World_population: actual world population of that year, in absolute
  persons, from the "World" rows of Table_A1P1 (cf.
  world_share_implementation.md). The TOTAL rows of the country tables
  are only the sum of the 72 tracked countries (~81-94% of the world
  population); normalizing against them (the old Popu_share) silently
  rescales the sample to 100% and loses the rest of the world.
- World_share: Population / World_population, as a fraction of 1
  (e.g. Algeria 2020: 43.851/7795.482 Mio. = 0.005625 = 0.5625%).
- OTHER_WORLD: World_population - sum of the tracked countries, per
  year, as an additional entity, so the cartogram solver receives the
  complete world population instead of renormalizing the sample. The
  country shares plus the OTHER_WORLD share sum to 1.0 for every
  year. Its energy columns stay empty: the Table_A1P1 world energy
  total is inconsistent with the TableA13 country sums (the remainder
  would be negative in 16 years), so no remainder energy exists.
- Per_capita_energy_consumption: kWh per capita, as in percapita.py
  (1 Mtoe = 11.63 TWh = 1.163e10 kWh)
- Canada/USA have an empty Macroarea in the source files; they are
  filled with "NAm" (North America, cf. Table_A1P1). "NAm" is used
  instead of "NA" because the latter is in pandas' default NA list
  and would silently become NaN on a plain pd.read_csv().

Run:  python3 prep_data.py   (from this directory)  -> writes the CSV
next to the sources and prints a short sanity summary.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parent
POP_CSV = BASE / "TableP2_population_per_country_annual.csv"
ENERGY_CSV = BASE / "TableA13_energy_consumption_per_country_annual.csv"
WORLD_CSV = BASE / "Table_A1P1_energy_population_percapita.csv"
OUT_CSV = BASE / "country_populationshare_energypercapita.csv"

KWH_PER_MTOE = 1.163e10      # 1 Mtoe = 11.63 TWh (as in percapita.py)
TOTAL = "TOTAL"              # sum-of-countries rows in the country tables
WORLD = "World"              # world-total rows in Table_A1P1
OTHER_WORLD = "OTHER_WORLD"  # remainder entity (world - tracked countries)

COLUMNS = [
    "Country", "Macroarea", "Year", "Population",
    "Energy_consumption", "World_population", "World_share",
    "Per_capita_energy_consumption",
]


def prep() -> pd.DataFrame:
    """Merge population + energy per country/year, add world share + OTHER_WORLD."""
    pop = pd.read_csv(POP_CSV)
    energy = pd.read_csv(ENERGY_CSV)
    world = pd.read_csv(WORLD_CSV)

    # --- Phase 1: actual world population per year (thousands).
    # Table_A1P1 "World" rows, NOT the TOTAL rows of the country tables:
    # the 72 tracked countries cover only ~81-94% of the world population.
    world_pop_000 = (world.loc[world["Column"] == WORLD]
                     .set_index("Year")["Population_000"])
    if world_pop_000.index.duplicated().any():
        raise ValueError(f"{WORLD_CSV.name}: duplicate {WORLD!r} rows per year")

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
        print(f"[prep] WARNUNG: {n_pop - len(df)} country-years without energy data")

    missing_years = sorted(set(df["Year"]) - set(world_pop_000.index))
    if missing_years:
        raise ValueError(f"no world population for years: {missing_years}")

    df["Population"] = df["Population_000"] * 1000.0
    df["Energy_consumption"] = df["Energy_consumption_Mtoe"]
    df["Macroarea"] = df["Macroarea"].fillna("NAm")

    # --- Phase 2: world_share = country population / actual world
    # population (both in thousands -> the ratio is the same), fraction of 1.
    world_pop = df["Year"].map(world_pop_000)
    df["World_population"] = world_pop * 1000.0
    df["World_share"] = (df["Population_000"] / world_pop).round(8)
    # kWh per capita: Mtoe -> kWh, divided by persons.
    df["Per_capita_energy_consumption"] = (
        df["Energy_consumption_Mtoe"] * KWH_PER_MTOE / df["Population"]
    ).round(1)

    countries = (df[COLUMNS]
                 .sort_values(["Country", "Year"], kind="stable")
                 .reset_index(drop=True))

    # --- Phase 3: OTHER_WORLD = world population - represented countries.
    # Models all regions not covered by the 72 WEC entities, so that the
    # solver receives the complete world population.
    represented = countries.groupby("Year")["Population"].sum()
    world_persons = world_pop_000 * 1000.0
    remainder = world_persons.loc[represented.index] - represented
    if (remainder < 0).any():
        bad = remainder.index[remainder < 0].tolist()
        raise ValueError(f"world population below represented countries in {bad}")
    other = pd.DataFrame({
        "Country": OTHER_WORLD,
        "Macroarea": "",  # spans all macroareas (world minus WEC geometries)
        "Year": remainder.index,
        "Population": remainder.to_numpy(),
        "World_population": world_persons.loc[remainder.index].to_numpy(),
        "World_share": (remainder / world_persons.loc[remainder.index]).round(8).to_numpy(),
    })
    # No remainder energy: the Table_A1P1 world energy total is not
    # consistent with the TableA13 country sums (negative in 16 years).
    other["Energy_consumption"] = float("nan")
    other["Per_capita_energy_consumption"] = float("nan")

    out = pd.concat([countries, other[COLUMNS]], ignore_index=True)

    # --- Validierung: country shares + OTHER_WORLD share ≈ 1.0 per year.
    max_err = (out.groupby("Year")["World_share"].sum() - 1.0).abs().max()
    if max_err > 1e-6:
        print(f"[prep] WARNUNG: World_share sum deviates from 1.0 by {max_err:.2e}")

    out.to_csv(OUT_CSV, index=False)
    return out


if __name__ == "__main__":
    t = prep()

    years = sorted(t["Year"].unique())
    countries = t.loc[t["Country"] != OTHER_WORLD]
    last = years[-1]
    share_last = t.loc[t["Year"] == last, "World_share"].sum()
    ow = t.loc[(t["Country"] == OTHER_WORLD) & (t["Year"] == last)].iloc[0]
    top = countries.loc[countries["Year"] == last].nlargest(3, "World_share")
    print(f"[prep] {len(countries)} country rows + "
          f"{(t['Country'] == OTHER_WORLD).sum()} OTHER_WORLD rows, "
          f"{countries['Country'].nunique()} countries, "
          f"{years[0]}-{last} -> {OUT_CSV.name}")
    print(f"[prep] World_share sum {last} (incl. OTHER_WORLD): {share_last:.6f}")
    print(f"[prep] OTHER_WORLD {last}: {ow['Population']:,.0f} people "
          f"({ow['World_share']:.1%} of world population)")
    for _, r in top.iterrows():
        print(f"    {r['Country']}: {r['World_share']:.2%}, "
              f"{r['Per_capita_energy_consumption']:,.0f} kWh/Kopf")
    a = countries[(countries["Country"] == "Austria") & (countries["Year"] == 1820)].iloc[0]
    print(f"[prep] check Austria 1820: pop={a['Population']:,.0f}, "
          f"world_share={a['World_share']:.4%} of {a['World_population']:,.0f}, "
          f"{a['Per_capita_energy_consumption']} kWh/Kopf")
