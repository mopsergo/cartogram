"""Tests: Ingest + Validierung (Plan §2, §5.1)."""
from __future__ import annotations

import numpy as np
import pytest

from worldcarto.schema import ValidationError, validate_year_shares


def test_canonical_schema(canonical, cfg, registry):
    cols = {"entity_id", "country_name", "macroarea", "year", "population",
            "energy_consumption", "world_population", "world_share",
            "per_capita_energy_consumption", "is_other_world"}
    assert cols <= set(canonical.columns)
    assert not canonical.duplicated(subset=["entity_id", "year"]).any()
    assert int(canonical["year"].min()) == cfg.year_min
    assert int(canonical["year"].max()) == cfg.year_max


def test_all_entities_resolved(canonical, registry):
    have = set(canonical["entity_id"])
    for e in registry:
        if e.source_names:
            assert e.id in have, f"{e.id} fehlt im kanonischen DataFrame"


def test_shares_sum_to_one(canonical):
    sums = canonical.groupby("year")["world_share"].sum()
    assert ((sums - 1.0).abs() < 1e-5).all()


def test_other_world_matches_remainder(canonical, cfg):
    ow = cfg.other_world_id
    for year, g in canonical.groupby("year"):
        represented = g.loc[g["entity_id"] != ow, "world_share"].sum()
        ow_share = g.loc[g["entity_id"] == ow, "world_share"].iloc[0]
        assert abs(ow_share - (1.0 - represented)) < 1e-5, year


def test_israel_passive_before_1950(canonical, registry):
    isr = registry.index_of("ISR")
    rows = canonical[canonical["entity_id"] == "ISR"]
    assert rows["year"].min() == 1950
    targets, passive = _targets(canonical, registry, 1900)
    assert passive[isr]
    targets_50, passive_50 = _targets(canonical, registry, 1950)
    assert not passive_50[isr]
    assert targets_50[isr] > 0


def _targets(canonical, registry, year):
    from worldcarto.ingest import targets_for_year
    return targets_for_year(canonical, registry, year)


def test_targets_complete(canonical, registry):
    for year in (1820, 1900, 1950, 2000, 2020):
        targets, passive = _targets(canonical, registry, year)
        assert abs(targets[~passive].sum() - 1.0) < 1e-5


def test_validation_catches_bad_share():
    import pandas as pd
    from worldcarto.schema import RAW_COLUMNS, validate_raw
    df = pd.DataFrame({
        "Country": ["A", "A"], "Macroarea": ["WE", "WE"],
        "Year": [1820, 1821], "Population": [100.0, 110.0],
        "Energy_consumption": [1.0, np.nan], "World_population": [1000.0, 1000.0],
        "World_share": [0.1, 0.111],  # zweiter falsch
        "Per_capita_energy_consumption": [10.0, 10.0],
    })
    with pytest.raises(ValidationError):
        validate_raw(df[RAW_COLUMNS], 1820, 1821, share_tolerance=1e-9)


def test_remainder_check():
    import pandas as pd
    df = pd.DataFrame({
        "Country": ["A", "OTHER_WORLD"], "Year": [1820, 1820],
        "World_share": [0.4, 0.5],  # remainder wäre 0.6
    })
    with pytest.raises(ValidationError):
        validate_year_shares(df, "OTHER_WORLD", remainder_tolerance=1e-6)
