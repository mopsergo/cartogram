"""Kanonisches Datenschema + Minimalvalidierung (Plan §2, §5.1)."""
from __future__ import annotations

import pandas as pd

# Quelldatei-Spalten (bereinigtes CSV)
RAW_COLUMNS = [
    "Country",
    "Macroarea",
    "Year",
    "Population",
    "Energy_consumption",
    "World_population",
    "World_share",
    "Per_capita_energy_consumption",
]

# Kanonische Felder (Plan §5.1)
CANONICAL_COLUMNS = [
    "entity_id",
    "country_name",
    "macroarea",
    "year",
    "population",
    "energy_consumption",
    "world_population",
    "world_share",
    "per_capita_energy_consumption",
    "is_other_world",
]

OTHER_WORLD = "OTHER_WORLD"


class ValidationError(ValueError):
    """Sammelfehler der Minimalvalidierung mit allen Problemen auf einmal."""


def validate_raw(df: pd.DataFrame, year_min: int, year_max: int,
                 share_tolerance: float) -> None:
    """Minimalvalidierung vor dem Build (Plan §2).

    Wirft ValidationError mit allen gefundenen Problemen.
    """
    problems: list[str] = []

    missing = [c for c in RAW_COLUMNS if c not in df.columns]
    if missing:
        raise ValidationError(f"Fehlende Spalten: {missing}")

    if df.duplicated(subset=["Country", "Year"]).any():
        dup = df[df.duplicated(subset=["Country", "Year"])]
        problems.append(f"Doppelte (Country, Year)-Schlüssel: {len(dup)} Zeilen")

    years = df["Year"]
    if int(years.min()) != year_min:
        problems.append(f"Year.min() == {int(years.min())}, erwartet {year_min}")
    if int(years.max()) != year_max:
        problems.append(f"Year.max() == {int(years.max())}, erwartet {year_max}")

    if (df["Population"] < 0).any():
        problems.append("Negative Population vorhanden")

    energy = df["Energy_consumption"]
    if ((energy < 0) & energy.notna()).any():
        problems.append("Negative Energy_consumption vorhanden")

    if not (df["World_population"] > 0).all():
        problems.append("World_population <= 0 vorhanden")

    ok = (df["World_share"] - df["Population"] / df["World_population"]).abs()
    bad = ok > share_tolerance
    if bad.any():
        n = int(bad.sum())
        worst = ok.idxmax()
        problems.append(
            f"World_share != Population/World_population bei {n} Zeilen "
            f"(worst: {df.loc[worst, 'Country']} {df.loc[worst, 'Year']}, "
            f"Abweichung {ok.max():.2e})"
        )

    if problems:
        raise ValidationError("\n".join(f"- {p}" for p in problems))


def validate_year_shares(df: pd.DataFrame, other_world_id: str,
                         remainder_tolerance: float) -> dict[int, float]:
    """Je Jahr: represented_share / remainder_share prüfen (Plan §2).

    Falls OTHER_WORLD enthalten ist, muss dessen Anteil dem
    remainder_share entsprechen; andernfalls erzeugt die Pipeline die
    Entität (siehe ingest.ensure_other_world).
    """
    problems: list[str] = []
    remainders: dict[int, float] = {}

    for year, g in df.groupby("Year"):
        represented = g.loc[g["Country"] != other_world_id, "World_share"].sum()
        remainder = 1.0 - represented
        remainders[int(year)] = remainder

        if remainder < -remainder_tolerance:
            problems.append(
                f"{year}: represented_share {represented:.6f} > 1.0 "
                f"(remainder {remainder:.6f})"
            )
            continue

        ow = g.loc[g["Country"] == other_world_id]
        if not ow.empty:
            ow_share = float(ow["World_share"].iloc[0])
            if abs(ow_share - remainder) > remainder_tolerance:
                problems.append(
                    f"{year}: OTHER_WORLD-Anteil {ow_share:.8f} entspricht nicht "
                    f"dem remainder_share {remainder:.8f}"
                )

    if problems:
        raise ValidationError("\n".join(f"- {p}" for p in problems))
    return remainders
