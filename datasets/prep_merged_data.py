"""
Merged prep table for the combined run (1820-2025): Malanima + OWID.

Builds merged_population_energy_1820_2025.csv in the layout of
country_populationshare_energypercapita.csv (prep_data.py), so the
cartogram pipeline can solve it as a separate run
(`worldcarto.cli --dataset merged ...`, configs/datasets/merged.yaml):

    Country, Macroarea, Year, Population, Energy_consumption,
    World_population, World_share, Per_capita_energy_consumption,
    Source_population, Source_energy

Inputs (both already in the pipeline layout, same country names):
- country_populationshare_energypercapita.csv  (prep_data.py)
  Malanima, WEC World Energy Consumption 1820-2020 (2022 revision)
- owid_population_energy_1965_2025.csv  (prep_owid_data.py)
  OWID: UN WPP 2024 population, primary energy per person

Rules:
- 1820-1964: Malanima rows unchanged.
- 1965-2025: OWID rows (population, world population, world share and
  energy) replace Malanima. World_population is then the OWID "World"
  row; the pipeline's OTHER_WORLD remainder follows from it.
- Energy gap fill: where OWID has no per-capita value but Malanima has
  one (20 countries 1965-1979, whose OWID series starts in 1980), the
  Malanima per-capita value is kept, so these countries do not turn
  grey for 15 years. Energy_consumption is recomputed from it with the
  OWID population. Source_energy marks every such value.
- Source_population / Source_energy ("malanima" | "owid" | ""): origin
  of each value (the pipeline ignores extra columns).

Discrepancy check (written to merged_discrepancies.csv, summary
printed): per country over the overlap 1965-2020, the ratio
OWID / Malanima of population and per-capita energy, plus the step at
the source change (1964 Malanima -> first OWID year). Systematically
lower OWID energy values are expected: Malanima includes traditional
biomass (firewood, fodder), OWID primary energy (Energy Institute,
EIA) only commercial energy.

Run:  ../.venv/bin/python prep_merged_data.py   (from this directory)
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent
MALANIMA_CSV = BASE / "country_populationshare_energypercapita.csv"
OWID_CSV = BASE / "owid_population_energy_1965_2025.csv"
OUT_CSV = BASE / "merged_population_energy_1820_2025.csv"
REPORT_CSV = BASE / "merged_discrepancies.csv"

SWITCH_YEAR = 1965           # first year taken from OWID
OVERLAP_END = 2020           # last Malanima year
KWH_PER_MTOE = 1.163e10      # 1 Mtoe = 11.63 TWh (as in prep_data.py)

COLUMNS = [
    "Country", "Macroarea", "Year", "Population",
    "Energy_consumption", "World_population", "World_share",
    "Per_capita_energy_consumption", "Source_population", "Source_energy",
]
PC = "Per_capita_energy_consumption"


def read(path: Path) -> pd.DataFrame:
    # "NAm" etc. must not become NaN (cf. prep_data.py); round_trip
    # keeps the Malanima rows byte-identical, so the pipeline computes
    # the same targets (and reuses solved frames, see PIPELINE.md)
    return pd.read_csv(path, keep_default_na=False, na_values=[""],
                       float_precision="round_trip")


def merge(mal: pd.DataFrame, owid: pd.DataFrame) -> pd.DataFrame:
    early = mal[mal["Year"] < SWITCH_YEAR].copy()
    early["Source_population"] = "malanima"
    early["Source_energy"] = np.where(early[PC].notna(), "malanima", "")

    late = owid[owid["Year"] >= SWITCH_YEAR].copy()
    late["Source_population"] = "owid"
    late["Source_energy"] = np.where(late[PC].notna(), "owid", "")

    # Gap fill from Malanima (per-capita value, OWID population)
    mal_pc = mal.set_index(["Country", "Year"])[PC]
    key = pd.MultiIndex.from_frame(late[["Country", "Year"]])
    fill = pd.Series(mal_pc.reindex(key).to_numpy(), index=late.index)
    gap = late[PC].isna() & fill.notna()
    late.loc[gap, PC] = fill[gap]
    late.loc[gap, "Energy_consumption"] = (
        fill[gap] * late.loc[gap, "Population"] / KWH_PER_MTOE)
    late.loc[gap, "Source_energy"] = "malanima"

    # Countries without own map entity (small states) exist only in
    # Malanima; after the switch the pipeline covers them through the
    # OWID world remainder (OTHER_WORLD).
    df = pd.concat([early, late], ignore_index=True)
    return (df[COLUMNS]
            .sort_values(["Country", "Year"], kind="stable")
            .reset_index(drop=True))


def discrepancies(mal: pd.DataFrame, owid: pd.DataFrame) -> pd.DataFrame:
    """Per-country OWID/Malanima ratios over the overlap years."""
    j = mal.merge(owid, on=["Country", "Year"], suffixes=("_m", "_o"))
    j = j[j["Year"].between(SWITCH_YEAR, OVERLAP_END)]
    j["pop_ratio"] = j["Population_o"] / j["Population_m"]
    j["pc_ratio"] = j[f"{PC}_o"] / j[f"{PC}_m"]

    rows = []
    for country, g in j.groupby("Country"):
        e = g.dropna(subset=["pc_ratio"])
        first = e.iloc[0] if len(e) else None
        rows.append({
            "Country": country,
            "Macroarea": g["Macroarea_m"].iloc[0],
            "pop_ratio_median": g["pop_ratio"].median(),
            "pop_ratio_min": g["pop_ratio"].min(),
            "pop_ratio_max": g["pop_ratio"].max(),
            "energy_overlap_years": len(e),
            "pc_ratio_median": e["pc_ratio"].median() if len(e) else np.nan,
            "pc_ratio_min": e["pc_ratio"].min() if len(e) else np.nan,
            "pc_ratio_max": e["pc_ratio"].max() if len(e) else np.nan,
            "first_owid_energy_year":
                int(first["Year"]) if first is not None else np.nan,
            # step at the source change: first OWID value / Malanima
            # value of the same year (= the jump in the merged series)
            "pc_ratio_at_switch":
                first["pc_ratio"] if first is not None else np.nan,
            "pc_malanima_2020": g.loc[g["Year"] == OVERLAP_END,
                                      f"{PC}_m"].squeeze() if (
                g["Year"] == OVERLAP_END).any() else np.nan,
            "pc_owid_2020": g.loc[g["Year"] == OVERLAP_END,
                                  f"{PC}_o"].squeeze() if (
                g["Year"] == OVERLAP_END).any() else np.nan,
        })
    return pd.DataFrame(rows).sort_values("pc_ratio_median",
                                          na_position="last")


def world_summary(mal: pd.DataFrame, owid: pd.DataFrame) -> pd.DataFrame:
    """World population and covered (mapped) population share per year."""
    def per_year(df):
        g = df.groupby("Year")
        return pd.DataFrame({"world": g["World_population"].first(),
                             "countries": g["Population"].sum()})
    m, o = per_year(mal), per_year(owid)
    years = [SWITCH_YEAR - 1, SWITCH_YEAR, 1990, OVERLAP_END]
    return pd.DataFrame({
        "world_malanima": m["world"], "world_owid": o["world"],
        "world_ratio": o["world"] / m["world"],
    }).loc[[y for y in years if y in m.index]]


if __name__ == "__main__":
    mal, owid = read(MALANIMA_CSV), read(OWID_CSV)
    df = merge(mal, owid)
    df.to_csv(OUT_CSV, index=False)

    n_fill = int(((df["Year"] >= SWITCH_YEAR)
                  & (df["Source_energy"] == "malanima")).sum())
    print(f"{OUT_CSV.name}: {df['Year'].min()}-{df['Year'].max()}, "
          f"{len(df)} rows; Malanima < {SWITCH_YEAR}, OWID from "
          f"{SWITCH_YEAR}; {n_fill} OWID-year energy gaps filled from "
          f"Malanima")

    rep = discrepancies(mal, owid)
    rep.to_csv(REPORT_CSV, index=False, float_format="%.4f")
    print(f"\n{REPORT_CSV.name}: {len(rep)} countries in the overlap "
          f"{SWITCH_YEAR}-{OVERLAP_END}")

    print("\nWorld population OWID / Malanima:")
    print(world_summary(mal, owid).to_string(float_format="%.4f"))

    off = rep[(rep["pop_ratio_min"] < 0.98) | (rep["pop_ratio_max"] > 1.02)]
    print(f"\nPopulation: median ratio {rep['pop_ratio_median'].median():.4f}"
          f"; countries deviating > 2% in some year: {len(off)}")
    if len(off):
        print(off[["Country", "pop_ratio_min", "pop_ratio_max"]]
              .to_string(index=False, float_format="%.3f"))

    e = rep.dropna(subset=["pc_ratio_median"])
    print(f"\nEnergy per capita ({len(e)} countries with both series): "
          f"OWID / Malanima median {e['pc_ratio_median'].median():.2f}, "
          f"IQR {e['pc_ratio_median'].quantile(.25):.2f}-"
          f"{e['pc_ratio_median'].quantile(.75):.2f}")
    print("Largest steps at the source change (first OWID year):")
    steps = pd.concat([e.nsmallest(10, "pc_ratio_at_switch"),
                       e.nlargest(3, "pc_ratio_at_switch")])
    steps["first_owid_energy_year"] = steps["first_owid_energy_year"] \
        .astype(int)
    print(steps[["Country", "first_owid_energy_year", "pc_ratio_at_switch",
                 "pc_ratio_median"]].to_string(index=False,
                                               float_format="%.2f"))
