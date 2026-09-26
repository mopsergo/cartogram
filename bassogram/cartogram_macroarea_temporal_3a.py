from pathlib import Path
import json
import math
import sys

import numpy as np
import pandas as pd
import geopandas as gpd
import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import matplotlib as mpl
from matplotlib.collections import PatchCollection
from matplotlib.patches import Rectangle, Polygon as MplPolygon, Patch
import matplotlib.patheffects as pe

from shapely.affinity import scale, translate
from shapely.geometry import Point, LineString
from shapely.ops import unary_union

# shapely 1.x vs 2.x: Polygon.exterior.coords, unchanged either way.


# ============================================================
# PATH RESOLUTION (works from any working directory)
# ============================================================
#
# Every input/output path below is repo-root-relative
# (datasets/…, natural_earth/…, cartogram_macroarea/…). This script
# itself lives in bassogram/, one level below the repo root, so
# launching it with a different working directory (PyCharm's Run
# button defaults to the script's own folder; `cd bassogram &&
# python …` does the same) used to break every lookup: no local
# datasets were found, the Natural Earth loader fell back to an
# S3 download that failed, and the run died with an unrelated-
# looking network traceback. repo_path() instead resolves a
# repo-relative path against the CWD, the CWD's parents, the
# script's own folder, and its parents (the repo root is the
# script folder's parent), returning the first existing match —
# and the plain CWD-relative path when nothing exists, so a
# genuinely missing file still reports the same path as before.
# REPO_BASE is the base directory that owns the datasets;
# OUTPUT_DIR is anchored to it so the on-disk tile cache
# (.gpkg + _clusters.json, keyed by BASE_TAG) is shared and
# reused no matter where the script is launched from.

SCRIPT_DIR = Path(__file__).resolve().parent


def repo_path(relative):
    """Resolve `relative` (a repo-root-relative path) from any
    working directory; see the comment block above."""
    for base in (Path.cwd(), *Path.cwd().parents, SCRIPT_DIR, *SCRIPT_DIR.parents):
        candidate = base / relative
        if candidate.exists():
            return candidate
    return Path.cwd() / relative


def _find_repo_base(marker):
    """The base directory that contains `marker` (a repo-relative
    path), searched from the CWD and from the script's location.
    Falls back to the CWD, so behaviour matches the old CWD-relative
    code when the marker isn't found anywhere."""
    for base in (Path.cwd(), *Path.cwd().parents, SCRIPT_DIR, *SCRIPT_DIR.parents):
        if (base / marker).is_file():
            return base
    return Path.cwd()


# ============================================================
# MACRO-AREA + COUNTRY CARTOGRAM — WEC, ANIMATED OVER TIME
# ============================================================
#
# Builds on the temporally-coherent macroarea cartogram:
#
#   - Geometry / neighbor relationships / TILE_SIZE / colorbar
#     scale are all fixed once, outside the year loop.
#   - Each year's force-directed layout is warm-started from the
#     previous year's resting positions, so macroareas keep
#     roughly the same position across frames instead of being
#     re-solved from scratch every year.
#
# COUNTRY LAYER (toggle with 4th CLI arg = "countries"):
#
#   Countries are NOT given their own independent force-directed
#   layout. Instead, once a macroarea's own tiles are placed for
#   the year, those exact tiles are PARTITIONED among the
#   countries that belong to that macroarea:
#
#     - each country's share of that macroarea's tile count is
#       proportional to its own datasets value this year (population
#       or per-capita energy, matching area_var);
#     - tiles are handed to their nearest country by true
#       geographic position (a capacity-constrained nearest-
#       neighbor assignment), so the partition still looks
#       spatially sensible rather than random.
#
#   Because a country's tiles are always a *subset* of its
#   macroarea's own already-placed tiles, countries can never end
#   up outside their macroarea's shape — containment is exact by
#   construction, not an approximation enforced by extra forces.
#
#   When the country layer is on, the macroarea layer itself is not
#   drawn at all (no fill, no outline) — the country tiles, which
#   exactly fill their macroarea's tile footprint, are what's
#   visible. An earlier version drew a macroarea coastline (the true
#   Natural Earth polygon, affine-transformed to the tile cluster's
#   scale/position) as a dividing outline; that was dropped on
#   feedback that it read as clutter rather than a helpful boundary.
#   The helper that computes it (transform_true_macro_geometry) is
#   kept, since macro_scale_factor is still used by the country
#   partition step below, but its output is no longer drawn.
#
#   Countries are distinguished from each other by: their own tile
#   fill color (see country_norm below), a visible dark tile edge
#   (distinct from the thin white edge used elsewhere), and — when
#   SHOW_COUNTRY_LABELS is on — a text label. Labels are their own
#   switch (5th CLI arg "nolabels" turns them off) because in a
#   small macroarea with a dozen countries, a name on every tile
#   cluster becomes unreadable regardless of font tuning; with
#   labels off, color + tile boundaries + the country legend/colorbar
#   still make each country identifiable without the clutter. When
#   labels are on, only countries whose tile cluster is large enough
#   to hold text legibly get one, to keep the smallest slivers from
#   piling up illegible labels on top of each other.
#
#   Countries are also colored on their OWN scale (country_norm),
#   scanned independently across the country-level datasets, rather than
#   the macro-level `norm`: a single country is almost always a much
#   smaller share of a metric than an 8-way macroarea aggregate, so
#   sharing one scale left nearly every country the same washed-out
#   color at the bottom of the colormap.
#
#   A static background layer draws the true, un-transformed Natural
#   Earth countries as a light reference map under everything else,
#   in both modes — the fixed geography the cartogram is distorting
#   away from.
#
#   With the country layer off, the macroarea layer is filled as
#   before, with no background/coastline changes.
#
# Command line:
#
#   python cartogram_macroarea_1b_temporal.py 1000000 1200 population countries
#
# Arguments:
#   1. PEOPLE_PER_TILE
#   2. N_ITERATIONS   (macroarea layer only — the country layer
#                       needs no optimization of its own)
#   3. "population" or "energy"
#   4. optional: "countries" to also build+draw the country layer
#      (default: off, i.e. same behaviour as before)
#   5. optional: "nolabels" to suppress country name labels while
#      keeping the country tile layer on (default: labels on)
#
# ============================================================


# ============================================================
# SETTINGS
# ============================================================

YEAR_START = 2000
YEAR_END = 2020
YEAR_STEP = 1

TABLE_A1P1_FILE = repo_path(
    Path("datasets/Table_A1P1_energy_population_percapita.csv")
)

# Annual (linearly-interpolated) per-country tables, matching the
# resolution of TABLE_A1P1_FILE. See TableA13_energy_consumption_
# per_country_annual.csv / TableP2_population_per_country_annual.csv.
TABLE_A13_FILE = repo_path(
    Path("datasets/TableA13_energy_consumption_per_country_annual.csv")
)
TABLE_P2_FILE = repo_path(
    Path("datasets/TableP2_population_per_country_annual.csv")
)

NATURAL_EARTH_URL = (
    "https://naturalearth.s3.amazonaws.com/"
    "110m_cultural/ne_110m_admin_0_countries.zip"
)

# Local copy of the same 110m Natural Earth countries (shipped with
# the repo) — preferred over the download whenever it exists.
NATURAL_EARTH_LOCAL = repo_path(
    Path("datasets/ne_110m_admin_0_countries.geojson")
)

# Anchored to REPO_BASE rather than the CWD, so a run launched from
# bassogram/ writes to (and finds the existing tile cache in) the
# same cartogram_macroarea/ folder a run from the repo root does.
REPO_BASE = _find_repo_base(
    Path("datasets/Table_A1P1_energy_population_percapita.csv")
)
OUTPUT_DIR = REPO_BASE / "cartogram_macroarea"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

if len(sys.argv) < 4:
    print(
        "Usage: python bassogram/cartogram_macroarea_temporal_3a.py "
        "PEOPLE_PER_TILE N_ITERATIONS {population|energy} "
        "[countries] [nolabels]\n"
        "  e.g. python bassogram/cartogram_macroarea_temporal_3a.py "
        "1000000 1200 population countries"
    )
    sys.exit(1)

PEOPLE_PER_TILE = int(sys.argv[1])
N_ITERATIONS = int(sys.argv[2])
area_var = sys.argv[3].strip().lower()

if area_var not in {"population", "energy"}:
    raise ValueError(
        "Third argument must be 'population' or 'energy'."
    )

SHOW_COUNTRIES = (
    len(sys.argv) > 4 and sys.argv[4].strip().lower() == "countries"
)

# Country-name labels are their own switch, independent of
# SHOW_COUNTRIES: the country TILES (colors + outlines) are what
# make countries identifiable, and labels are a legibility aid on
# top of that which gets crowded fast in small, many-country
# macroareas (e.g. Latin America, Western Europe). 5th CLI arg
# "nolabels" turns the text off while keeping the tile layer on.
SHOW_COUNTRY_LABELS = not (
    len(sys.argv) > 5 and sys.argv[5].strip().lower() == "nolabels"
)


if area_var == "population":
    value_column = "Population"
    value_label = "Population"
    # macro_size_column decides how many tiles each MACROAREA gets
    # (value_column keeps deciding the within-macro COUNTRY split,
    # further down). Population is already extensive/summable at a
    # roughly stable scale year to year, so both are the same column
    # here.
    macro_size_column = "Population"
    colorbar_varname = "Per_capita_energy_consumption"
    colorbar_varname_cb = "Energy consumption per capita (toe)"
else:
    value_column = "Per_capita_energy_consumption"
    # Per-capita energy consumption is intensive, and its absolute
    # value has grown roughly 40x from 1820 to today — sizing
    # macroareas directly off of it (as a raw threshold-per-tile)
    # made every early year's map minuscule next to a recent one,
    # even though the *relative* split between macroareas is what a
    # cartogram should actually show. macro_size_column instead uses
    # each macroarea's SHARE of that year's world total energy
    # consumption (see Energy_share_of_world below): shares always
    # sum to ~1,000,000 ppm regardless of the era, so the overall
    # map size stays comparable across the whole animation, while
    # each macroarea's footprint still tracks its true changing
    # share of world energy use. value_column (per-capita, unchanged)
    # still decides each country's split of its own macro's tiles,
    # since that's a same-year, same-macro comparison the secular
    # trend doesn't affect.
    value_label = "Global energy consumption\nshare (ppm)"
    macro_size_column = "Energy_share_of_world"
    colorbar_varname = "Population_Fraction"
    colorbar_varname_cb = "Population share (%)"


# ------------------------------------------------------------
# Optimization parameters — macroarea layer only. The country
# layer has no optimization of its own: see the module docstring.
# ------------------------------------------------------------

OVERLAP_STRENGTH = 0.3
NEIGHBOR_STRENGTH = 0.8
ANCHOR_STRENGTH = 0.9
DAMPING = 0.80

# NOTE on N_ITERATIONS with warm-starting:
# the very first year (YEAR_START) still starts cold, from the
# geometric anchor, and needs the full iteration count. Every
# later year starts from the previous year's resting state, so it
# will often visibly converge (see the "movement" printout) in far
# fewer iterations than YEAR_START does.


# ============================================================
# WEC MACROAREAS
# ============================================================

MACROAREAS = [
    "Western Europe",
    "Eastern Europe",
    "North America",
    "Latin America",
    "Oceania",
    "Asia",
    "Middle East",
    "Africa",
]

MACROAREA_ABBR = {
    "Western Europe": "WE",
    "Eastern Europe": "EE",
    "North America": "NA",
    "Latin America": "LA",
    "Oceania": "OC",
    "Asia": "AS",
    "Middle East": "ME",
    "Africa": "AF",
}

# NOTE: country->macroarea assignment is derived below directly from
# COUNTRY_TO_ISO3 + MACROAREA_CODES (see macro_for_country), not from
# the "Macroarea" column in the Table A.13 / P.2 CSV files. That
# column stores short codes like "NA" (North America), "EE", etc.,
# and the annual (interpolated) versions of those two files were
# generated by a pipeline that at some point read "NA" as pandas'
# missing-value marker rather than the literal string — so on disk,
# Canada's and USA's "Macroarea" cells are genuinely blank, not just
# misread. Rather than depend on that column (or re-fix the CSV),
# every country's macroarea is computed here from the same two dicts
# already used to build the macroarea geometries, which is both more
# robust and guaranteed self-consistent with them.


# ============================================================
# COUNTRY -> WEC MACROAREA  (ISO alpha-3, Natural Earth ADM0_A3)
# ============================================================
# Used only to build macroarea *shapes* from Natural Earth.

MACROAREA_CODES = {
    # Western Europe
    "AUT": "Western Europe", "BEL": "Western Europe",
    "CHE": "Western Europe", "DEU": "Western Europe",
    "DNK": "Western Europe", "ESP": "Western Europe",
    "FIN": "Western Europe", "FRA": "Western Europe",
    "GBR": "Western Europe", "GRC": "Western Europe",
    "IRL": "Western Europe", "ISL": "Western Europe",
    "ITA": "Western Europe", "LUX": "Western Europe",
    "NLD": "Western Europe", "NOR": "Western Europe",
    "PRT": "Western Europe", "SWE": "Western Europe",

    # Eastern Europe
    "ALB": "Eastern Europe", "BGR": "Eastern Europe",
    "BIH": "Eastern Europe", "BLR": "Eastern Europe",
    "CZE": "Eastern Europe", "EST": "Eastern Europe",
    "HRV": "Eastern Europe", "HUN": "Eastern Europe",
    "LTU": "Eastern Europe", "LVA": "Eastern Europe",
    "MDA": "Eastern Europe", "MKD": "Eastern Europe",
    "MNE": "Eastern Europe", "POL": "Eastern Europe",
    "ROU": "Eastern Europe", "RUS": "Eastern Europe",
    "SRB": "Eastern Europe", "SVK": "Eastern Europe",
    "SVN": "Eastern Europe", "UKR": "Eastern Europe",

    # North America
    "CAN": "North America",
    "USA": "North America",

    # Latin America
    "ARG": "Latin America", "BOL": "Latin America",
    "BRA": "Latin America", "CHL": "Latin America",
    "COL": "Latin America", "CRI": "Latin America",
    "CUB": "Latin America", "DOM": "Latin America",
    "ECU": "Latin America", "SLV": "Latin America",
    "GTM": "Latin America", "HTI": "Latin America",
    "HND": "Latin America", "JAM": "Latin America",
    "MEX": "Latin America", "NIC": "Latin America",
    "PAN": "Latin America", "PRY": "Latin America",
    "PER": "Latin America", "URY": "Latin America",
    "VEN": "Latin America",

    # Oceania
    "AUS": "Oceania", "NZL": "Oceania",
    "PNG": "Oceania", "FJI": "Oceania",
    "SLB": "Oceania", "VUT": "Oceania",
    "WSM": "Oceania", "TON": "Oceania",

    # Asia
    "AFG": "Asia", "ARM": "Asia", "AZE": "Asia",
    "BGD": "Asia", "BTN": "Asia", "BRN": "Asia",
    "CHN": "Asia", "GEO": "Asia", "IND": "Asia",
    "IDN": "Asia", "JPN": "Asia", "KAZ": "Asia",
    "KGZ": "Asia", "KHM": "Asia", "KOR": "Asia",
    "LAO": "Asia", "LKA": "Asia", "MNG": "Asia",
    "MMR": "Asia", "MYS": "Asia", "NPL": "Asia",
    "PAK": "Asia", "PHL": "Asia", "PRK": "Asia",
    "SGP": "Asia", "THA": "Asia", "TJK": "Asia",
    "TKM": "Asia", "TWN": "Asia", "UZB": "Asia",
    "VNM": "Asia",

    # Middle East
    "BHR": "Middle East", "CYP": "Middle East",
    "IRN": "Middle East", "IRQ": "Middle East",
    "ISR": "Middle East", "JOR": "Middle East",
    "KWT": "Middle East", "LBN": "Middle East",
    "OMN": "Middle East", "QAT": "Middle East",
    "SAU": "Middle East", "SYR": "Middle East",
    "TUR": "Middle East", "ARE": "Middle East",
    "YEM": "Middle East",

    # Africa
    "DZA": "Africa", "AGO": "Africa", "BEN": "Africa",
    "BWA": "Africa", "BFA": "Africa", "BDI": "Africa",
    "CMR": "Africa", "CPV": "Africa", "CAF": "Africa",
    "TCD": "Africa", "COM": "Africa", "COG": "Africa",
    "COD": "Africa", "CIV": "Africa", "DJI": "Africa",
    "EGY": "Africa", "GNQ": "Africa", "ERI": "Africa",
    "SWZ": "Africa", "ETH": "Africa", "GAB": "Africa",
    "GMB": "Africa", "GHA": "Africa", "GIN": "Africa",
    "GNB": "Africa", "KEN": "Africa", "LSO": "Africa",
    "LBR": "Africa", "LBY": "Africa", "MDG": "Africa",
    "MWI": "Africa", "MLI": "Africa", "MRT": "Africa",
    "MUS": "Africa", "MAR": "Africa", "MOZ": "Africa",
    "NAM": "Africa", "NER": "Africa", "NGA": "Africa",
    "RWA": "Africa", "STP": "Africa", "SEN": "Africa",
    "SYC": "Africa", "SLE": "Africa", "SOM": "Africa",
    "ZAF": "Africa", "SSD": "Africa", "SDN": "Africa",
    "TZA": "Africa", "TGO": "Africa", "TUN": "Africa",
    "UGA": "Africa", "ZMB": "Africa", "ZWE": "Africa",
}

# Optional per-country macroarea override, applied on top of
# MACROAREA_CODES for both the map geometry and country_macro.
#
# MACROAREA_CODES itself matches the WEC SOURCE DATA's own regional
# convention, not a guess — e.g. Mexico is filed under Latin America
# ("LA") in that convention (confirmed directly in the raw per-country
# CSVs: Table A.13 / Table P.2 both carry "Mexico,LA,..." on disk), so
# North America there means USA + Canada only. That's a property of
# the dataset, not a bug in this script. To show a country under a
# different macroarea anyway for this visualization (without touching
# the source CSVs), add it here, e.g.:
#   MACROAREA_OVERRIDE = {"MEX": "North America"}
MACROAREA_OVERRIDE = {}

EFFECTIVE_MACROAREA_CODES = {**MACROAREA_CODES, **MACROAREA_OVERRIDE}


# ============================================================
# WEC COUNTRY NAME -> ISO3 CODE(S) + ABBREVIATION
# ============================================================
#
# The 72 countries in Table A.13 / P.2 are matched to Natural
# Earth's ADM0_A3 codes so we can get a *true geographic reference
# point* (centroid) for each — this is what the nearest-country
# tile assignment uses, not for building separate country shapes.
#
# A handful of WEC entries are historical aggregates that don't
# correspond to a single modern country. For those, the reference
# geometry is the union of the present-day successor states:
#   - "Czechoslovakia" -> Czech Republic + Slovakia
#   - "Yugoslavia"      -> Serbia, Croatia, Bosnia, Montenegro,
#                          North Macedonia, Slovenia
#   - "F. USSR"         -> the 15 former Soviet republics
#   - "Eritrea & Ethiopia" -> Eritrea + Ethiopia
#
# Abbreviations are the ISO3 code itself for ordinary countries;
# aggregates get a short conventional tag instead.
# ============================================================

COUNTRY_TO_ISO3 = {
    "Austria": "AUT", "Belgium": "BEL", "Denmark": "DNK",
    "Finland": "FIN", "France": "FRA", "Germany": "DEU",
    "Greece": "GRC", "Ireland": "IRL", "Italy": "ITA",
    "Netherlands": "NLD", "Norway": "NOR", "Portugal": "PRT",
    "Spain": "ESP", "Sweden": "SWE", "Switzerland": "CHE",
    "UK": "GBR",

    "Bulgaria": "BGR",
    "Czechoslovakia": ["CZE", "SVK"],
    "Hungary": "HUN", "Poland": "POL", "Romania": "ROU",
    "Yugoslavia": ["SRB", "HRV", "BIH", "MNE", "MKD", "SVN"],
    "F. USSR": [
        "RUS", "UKR", "BLR", "EST", "LVA", "LTU", "MDA",
        "GEO", "ARM", "AZE", "KAZ", "UZB", "TKM", "TJK", "KGZ",
    ],

    "Canada": "CAN", "USA": "USA",

    "Argentina": "ARG", "Bolivia": "BOL", "Brazil": "BRA",
    "Chile": "CHL", "Colombia": "COL", "Costa Rica": "CRI",
    "Cuba": "CUB", "Dominican Rep.": "DOM", "Ecuador": "ECU",
    "El Salvador": "SLV", "Guatemala": "GTM", "Haïti": "HTI",
    "Honduras": "HND", "Mexico": "MEX", "Nicaragua": "NIC",
    "Panama": "PAN", "Paraguay": "PRY", "Peru": "PER",
    "Uruguay": "URY", "Venezuela": "VEN",

    "Australia": "AUS", "N. Zealand": "NZL",

    "China": "CHN", "India": "IND", "Indonesia": "IDN",
    "Japan": "JPN", "Malaysia": "MYS", "Philippines": "PHL",
    "Thailand": "THA",

    "Iran": "IRN", "Iraq": "IRQ", "Israel": "ISR",
    "S. Arabia": "SAU", "Syria": "SYR", "Turkey": "TUR",

    "Algeria": "DZA", "Congo R.D.": "COD", "Egypt": "EGY",
    "Eritrea & Ethiopia": ["ERI", "ETH"], "Libya": "LBY",
    "Malawi": "MWI", "Morocco": "MAR", "Nigeria": "NGA",
    "South Africa": "ZAF", "Tunisia": "TUN", "Zambia": "ZMB",
    "Zimbabwe": "ZWE",
}

COUNTRY_ABBR_OVERRIDE = {
    "Czechoslovakia": "CSK",
    "Yugoslavia": "YUG",
    "F. USSR": "USSR",
    "Eritrea & Ethiopia": "ERI+ETH",
}


def country_abbr(name):
    if name in COUNTRY_ABBR_OVERRIDE:
        return COUNTRY_ABBR_OVERRIDE[name]
    codes = COUNTRY_TO_ISO3[name]
    return codes if isinstance(codes, str) else codes[0]


def macro_for_country(name):
    """Full macroarea name for a WEC country, via its first ISO3 code
    (an aggregate's constituent codes always share one macroarea)."""
    codes = COUNTRY_TO_ISO3[name]
    first_code = codes if isinstance(codes, str) else codes[0]
    return EFFECTIVE_MACROAREA_CODES.get(first_code)


# {country name: full macroarea name}, computed once — always
# available regardless of SHOW_COUNTRIES, since it's pure dict
# lookups with no file I/O.
country_macro = {name: macro_for_country(name) for name in COUNTRY_TO_ISO3}
_unmapped = sorted(c for c, m in country_macro.items() if m is None)
if _unmapped:
    print(f"  [country layer] could not resolve a macroarea for: {_unmapped}")

# REST-OF-MACROAREA entries -----------------------------------------
#
# COUNTRY_TO_ISO3 only tracks a subset of a macroarea's countries
# (the ones the WEC country-level tables carry individually). A
# macroarea's own tile COUNT is driven by its macro-level total
# (all countries in the region, tracked or not), so partitioning
# its tiles only among the tracked countries would silently give
# them 100% of the area — overstating each one's share and hiding
# the untracked remainder entirely. A synthetic "Rest of <macro>"
# entry is added per macroarea to absorb that gap: each year, its
# value is set to (macro total − sum of tracked countries' values),
# clipped at 0, so it only appears when there's an actual gap to
# show, sized to match it. One entry per macroarea, added here to
# country_macro (so it's picked up by the same "which countries
# belong to this macro" lookup as real countries) and given a
# geographic reference point below (the macro's own true centroid,
# since there's no more specific location for "the rest").
REST_PREFIX = "Rest of "
for _macro in MACROAREAS:
    country_macro[REST_PREFIX + _macro] = _macro


# ============================================================
# 1. LOAD GEOMETRY + BUILD MACROAREA SHAPES (ONCE)
# ============================================================

print("Loading Natural Earth...")

NE_SHP_FILE = repo_path(
    Path("natural_earth/ne_110m_admin_0_countries.shp")
)

if NE_SHP_FILE.is_file():
    world = gpd.read_file(NE_SHP_FILE)
elif NATURAL_EARTH_LOCAL.is_file():
    world = gpd.read_file(NATURAL_EARTH_LOCAL)
else:
    # No local copy found anywhere (see repo_path) — the download
    # is the last resort. A failure here used to surface as a raw
    # urllib traceback that read like a network bug, when the real
    # problem was simply that no datasets/ folder was in scope — so
    # wrap it with a message that says what belongs where.
    try:
        world = gpd.read_file(NATURAL_EARTH_URL)
    except Exception as exc:
        raise RuntimeError(
            "Could not load Natural Earth countries: no local copy "
            f"found (expected {repo_path(Path('datasets/ne_110m_admin_0_countries.geojson'))}) "
            f"and downloading {NATURAL_EARTH_URL} failed ({exc}). "
            "Place ne_110m_admin_0_countries.geojson in the repo's "
            "datasets/ folder and re-run."
        ) from exc

world = world.rename(columns={"ADM0_A3": "Code"})
world["Code"] = world["Code"].astype(str).str.strip()
world["Macroarea"] = world["Code"].map(EFFECTIVE_MACROAREA_CODES)

world = world[world["Macroarea"].isin(MACROAREAS)].copy()

print(f"Natural Earth countries assigned to macroareas: {len(world)}")

world = world.to_crs("EPSG:6933")
world["geometry"] = world.geometry.buffer(0)

# --- macroarea shapes -----------------------------------------

macro_geom_records = []
for macro in MACROAREAS:
    subset = world[world["Macroarea"] == macro]
    if subset.empty:
        raise ValueError(f"No Natural Earth countries assigned to {macro}")
    macro_geom_records.append(
        {"Macroarea": macro, "geometry": unary_union(subset.geometry.tolist())}
    )

macroareas_geo = gpd.GeoDataFrame(macro_geom_records, crs=world.crs)
total_world_area = macroareas_geo.geometry.area.sum()

# --- country reference points (true geographic centroid), only
#     needed if SHOW_COUNTRIES ---------------------------------

def get_country_geometry(codes):
    if isinstance(codes, str):
        codes = [codes]
    geoms = world[world["Code"].isin(codes)].geometry.tolist()
    return unary_union(geoms) if geoms else None


country_ref_points = {}   # {country: (x, y) true centroid, EPSG:6933}
# (country_macro is already built above, from COUNTRY_TO_ISO3 +
# MACROAREA_CODES — not reset here.)

if SHOW_COUNTRIES:
    for name, codes in COUNTRY_TO_ISO3.items():
        geom = get_country_geometry(codes)
        if geom is None or geom.is_empty:
            print(f"  [country layer] skipping {name!r}: no matching geometry in Natural Earth")
            continue
        c = geom.centroid
        country_ref_points[name] = (c.x, c.y)

    # "Rest of <macro>" reference points: the macro's own true
    # centroid (no more specific location is available for
    # countries this dataset doesn't track individually).
    for _, _geo_row in macroareas_geo.iterrows():
        _macro_name = _geo_row["Macroarea"]
        _c = _geo_row["geometry"].centroid
        country_ref_points[REST_PREFIX + _macro_name] = (_c.x, _c.y)

# --- fixed camera ------------------------------------------------

WORLD_MINX, WORLD_MINY, WORLD_MAXX, WORLD_MAXY = macroareas_geo.total_bounds
_world_w = WORLD_MAXX - WORLD_MINX
_world_h = WORLD_MAXY - WORLD_MINY
BOUNDS_MARGIN = 0.35

FIXED_XLIM = (
    WORLD_MINX - _world_w * BOUNDS_MARGIN,
    WORLD_MAXX + _world_w * BOUNDS_MARGIN,
)
FIXED_YLIM = (
    WORLD_MINY - _world_h * BOUNDS_MARGIN,
    WORLD_MAXY + _world_h * BOUNDS_MARGIN,
)

# --- fixed macroarea neighbor relationships -----------------------

neighbor_pairs = []
for i in range(len(macroareas_geo)):
    geom_i = macroareas_geo.geometry.iloc[i]
    name_i = macroareas_geo.Macroarea.iloc[i]
    for j in range(i + 1, len(macroareas_geo)):
        geom_j = macroareas_geo.geometry.iloc[j]
        name_j = macroareas_geo.Macroarea.iloc[j]
        if geom_i.touches(geom_j):
            neighbor_pairs.append((name_i, name_j))

print()
print("Macroarea neighbor pairs:")
for a, b in neighbor_pairs:
    print(f"  {a} <-> {b}")


# ============================================================
# 2. LOAD WEC TABLES ONCE
# ============================================================

wec_full = pd.read_csv(TABLE_A1P1_FILE)
wec_full["Year"] = pd.to_numeric(wec_full["Year"], errors="coerce")

years = list(range(YEAR_START, YEAR_END + 1, YEAR_STEP))


def load_year_wec(year):
    """Per-year macroarea table: filtering + unit conversion."""
    df = wec_full[
        (wec_full["Year"] == year) & (wec_full["Column"].isin(MACROAREAS))
    ].copy()

    if len(df) != len(MACROAREAS):
        missing = sorted(set(MACROAREAS) - set(df["Column"]))
        raise ValueError(f"Missing macroareas in Table A1P1 for {year}: {missing}")

    df["Energy_consumption_Mtoe"] = pd.to_numeric(
        df["Energy_consumption_Mtoe"], errors="coerce"
    )
    df["Population_000"] = pd.to_numeric(df["Population_000"], errors="coerce")
    df["Population"] = df["Population_000"] * 1000
    df["Per_capita_energy_consumption"] = (
        df["Per_capita_energy_consumption"] * 1_000_000_000
    )
    # Each macroarea's share of the (8-macroarea) world population
    # this year, in percent.
    df["Population_Fraction"] = df["Population"] / df["Population"].sum() * 100

    # Each macroarea's share of the WORLD's total energy consumption
    # this year (not just the 8 tracked macroareas' own sum), in
    # parts per million — an extensive, always-normalized quantity
    # that stays on the same 0-1,000,000 scale in 1820 and in 2020
    # alike, unlike the secular growth in Per_capita_energy_
    # consumption itself. Used only to SIZE macroareas (see
    # macro_size_column above); relies on world_series, built right
    # after this function, but not called until later in the module.
    world_total_energy = world_series.loc[year, "Energy_consumption_Mtoe"]
    df["Energy_share_of_world"] = (
        df["Energy_consumption_Mtoe"] / world_total_energy * 1_000_000
    )

    return df


# World totals, for the two timeline panels.
world_series = wec_full[wec_full["Column"] == "World"].copy()
world_series["Energy_consumption_Mtoe"] = pd.to_numeric(
    world_series["Energy_consumption_Mtoe"], errors="coerce"
)
world_series["Population_000"] = pd.to_numeric(
    world_series["Population_000"], errors="coerce"
)
world_series = world_series.set_index("Year").sort_index()


# --- country tables (only needed if SHOW_COUNTRIES) ---------------
#
# Only the numeric columns are read from these two files — the
# "Macroarea" text column is not: see the note above country_macro.

if SHOW_COUNTRIES:
    a13_full = pd.read_csv(TABLE_A13_FILE)
    p2_full = pd.read_csv(TABLE_P2_FILE)

    country_wec_full = pd.merge(
        a13_full[["Country", "Year", "Energy_consumption_Mtoe"]],
        p2_full[["Country", "Year", "Population_000"]],
        on=["Country", "Year"],
        how="inner",
    )
    country_wec_full = country_wec_full[country_wec_full["Country"] != "TOTAL"]

    _unmatched = sorted(set(country_wec_full["Country"]) - set(country_macro))
    if _unmatched:
        print(f"  [country layer] no macroarea mapping for countries found in the datasets: {_unmatched}")

    def load_year_country_wec(year):
        df = country_wec_full[country_wec_full["Year"] == year].copy()
        df["Population"] = df["Population_000"] * 1000
        with np.errstate(divide="ignore", invalid="ignore"):
            df["Per_capita_energy_consumption"] = (
                df["Energy_consumption_Mtoe"] / df["Population_000"]
            ) * 1_000_000_000
        df["Population_Fraction"] = (
            df["Population"] / df["Population"].sum() * 100
        )
        return df.set_index("Country")


# ============================================================
# 3. FIX TILE_SIZE, COLORBAR SCALE, AND PANEL AXIS RANGES
# ============================================================

print()
print("Scanning the full year range to fix stable scales...")

max_total_tiles = 0.0
colorbar_min = math.inf
colorbar_max = -math.inf

energy_share_min = math.inf
energy_share_max = -math.inf
pop_share_min = math.inf
pop_share_max = -math.inf

for y in years:
    df_y = load_year_wec(y)
    total_tiles_y = df_y[macro_size_column].sum() / PEOPLE_PER_TILE
    max_total_tiles = max(max_total_tiles, total_tiles_y)

    cb_vals = df_y[colorbar_varname]
    colorbar_min = min(colorbar_min, cb_vals.min())
    colorbar_max = max(colorbar_max, cb_vals.max())

    pce = df_y["Per_capita_energy_consumption"]
    pce_share = pce / pce.sum() * 100
    energy_share_min = min(energy_share_min, pce_share.min())
    energy_share_max = max(energy_share_max, pce_share.max())

    pop_share_min = min(pop_share_min, df_y["Population_Fraction"].min())
    pop_share_max = max(pop_share_max, df_y["Population_Fraction"].max())

TILE_SIZE = math.sqrt(total_world_area / max_total_tiles * 0.65)
MAX_STEP = TILE_SIZE * 2.0
BOUNDARY_CLOSE_DIST = TILE_SIZE * 0.6  # see tile_set_outline() above

print(f"Fixed tile size: {TILE_SIZE:,.0f} projected units")
print(f"Fixed colorbar range ({colorbar_varname}): {colorbar_min:,.3f} - {colorbar_max:,.3f}")

cmap = plt.get_cmap("plasma_r")
norm = mpl.colors.Normalize(vmin=colorbar_min, vmax=colorbar_max)

# Countries need their OWN color scale. A single country is almost
# always a much smaller share of a metric than a whole 8-way
# macroarea aggregate, so sharing `norm` (fixed from macro-level
# min/max) squashed nearly every country into the bottom sliver of
# the colormap — that low contrast, not just crowded labels, is why
# countries were hard to tell apart. country_norm is scanned
# independently from the country-level datasets across the full year
# range, so the full colormap range is actually used to tell
# countries apart from each other.
country_norm = None
if SHOW_COUNTRIES:
    country_colorbar_min = math.inf
    country_colorbar_max = -math.inf
    for y in years:
        cb_vals = load_year_country_wec(y)[colorbar_varname]
        cb_vals = cb_vals[np.isfinite(cb_vals)]
        if len(cb_vals) == 0:
            continue
        country_colorbar_min = min(country_colorbar_min, cb_vals.min())
        country_colorbar_max = max(country_colorbar_max, cb_vals.max())
    country_norm = mpl.colors.Normalize(vmin=country_colorbar_min, vmax=country_colorbar_max)
    print(
        f"Fixed country-level colorbar range ({colorbar_varname}): "
        f"{country_colorbar_min:,.3f} - {country_colorbar_max:,.3f}"
    )

LINE_YEAR_MIN, LINE_YEAR_MAX = years[0], years[-1]
ENERGY_TIMELINE_YMAX = world_series["Energy_consumption_Mtoe"].max() * 1.05
POPULATION_TIMELINE_YMAX = world_series["Population_000"].max() * 1.05


# ============================================================
# 4. TILE GENERATION + MACROAREA LAYOUT OPTIMIZATION
# ============================================================

def make_area_tiles(geometry, n_tiles, tile_size):
    if geometry.is_empty:
        return []

    target_area = n_tiles * tile_size * tile_size
    current_area = geometry.area

    if current_area <= 0:
        return []

    scale_factor = math.sqrt(target_area / current_area)
    centroid = geometry.centroid

    scaled = scale(geometry, xfact=scale_factor, yfact=scale_factor, origin=centroid)

    minx, miny, maxx, maxy = scaled.bounds

    xs = np.arange(minx + tile_size / 2, maxx, tile_size)
    ys = np.arange(miny + tile_size / 2, maxy, tile_size)

    candidates = []
    for y in ys:
        for x in xs:
            if scaled.contains(Point(x, y)):
                candidates.append((x, y))

    if len(candidates) > n_tiles:
        cx, cy = centroid.x, centroid.y
        candidates.sort(key=lambda p: (p[0] - cx) ** 2 + (p[1] - cy) ** 2)
        candidates = candidates[:n_tiles]

    return [
        (x, y, x - tile_size / 2, y - tile_size / 2, x + tile_size / 2, y + tile_size / 2)
        for x, y in candidates
    ]


def get_bounds(row):
    dx = row["x"] - row["anchor_x"]
    dy = row["y"] - row["anchor_y"]
    return (row["minx"] + dx, row["miny"] + dy, row["maxx"] + dx, row["maxy"] + dy)


def desired_neighbor_distance(row_i, row_j):
    width_i = row_i["maxx"] - row_i["minx"]
    height_i = row_i["maxy"] - row_i["miny"]
    width_j = row_j["maxx"] - row_j["minx"]
    height_j = row_j["maxy"] - row_j["miny"]
    return 0.5 * max(width_i + width_j, height_i + height_j)


def project_overlaps(clusters, max_sweeps=10):
    """Position-based overlap elimination (hard constraint).

    Pure forces can never end a deep bounding-box overlap: the
    overlap push goes to zero AT contact while the anchor spring
    does not, so any static force balance keeps a residual overlap,
    and the bang-bang nature of the push (constant while overlap
    persists, zero once gone) makes the dynamics orbit that balance
    point instead of settling (years 2004-2010 etc. never
    converged). So after each force step the overlaps are resolved
    directly: every intersecting pair of bounding boxes is translated
    apart along its minimal-translation axis — deepest overlap
    first, each side weighted by the other cluster's tile count, so
    big clusters move less than small ones — repeating until no
    boxes intersect. The caller then derives each cluster's velocity
    from its actual position change, so the projection feeds back
    into the dynamics rather than being undone by them next step.
    The result is a resting state with zero overlap no matter how
    the force constants are tuned; clusters simply sit slightly
    displaced from their geographic anchors to make room, which is
    the honest cartogram answer when scaled shapes don't fit the
    true geographic arrangement.
    """
    n = len(clusters)

    def scan():
        found = []
        for i in range(n):
            minxi, minyi, maxxi, maxyi = get_bounds(clusters.iloc[i])
            for j in range(i + 1, n):
                minxj, minyj, maxxj, maxyj = get_bounds(clusters.iloc[j])
                ox = min(maxxi, maxxj) - max(minxi, minxj)
                oy = min(maxyi, maxyj) - max(minyi, minyj)
                if ox > 0 and oy > 0:
                    found.append((min(ox, oy), i, j, ox, oy))
        return found

    for _ in range(max_sweeps):
        pairs = scan()
        if not pairs:
            return
        # Deepest first; Gauss-Seidel: bounds are re-measured before
        # each shift, since earlier shifts in this sweep may have
        # already changed the picture for later pairs.
        pairs.sort(key=lambda p: -p[0])
        for _, i, j, _, _ in pairs:
            minxi, minyi, maxxi, maxyi = get_bounds(clusters.iloc[i])
            minxj, minyj, maxxj, maxyj = get_bounds(clusters.iloc[j])
            ox = min(maxxi, maxxj) - max(minxi, minxj)
            oy = min(maxyi, maxyj) - max(minyi, minyj)
            if ox <= 0 or oy <= 0:
                continue

            mi = float(clusters.at[i, "n_tiles"])
            mj = float(clusters.at[j, "n_tiles"])
            mtot = mi + mj
            pen = min(ox, oy)

            if ox <= oy:
                s = 1.0 if clusters.at[j, "x"] >= clusters.at[i, "x"] else -1.0
                clusters.at[i, "x"] -= s * pen * (mj / mtot)
                clusters.at[j, "x"] += s * pen * (mi / mtot)
            else:
                s = 1.0 if clusters.at[j, "y"] >= clusters.at[i, "y"] else -1.0
                clusters.at[i, "y"] -= s * pen * (mj / mtot)
                clusters.at[j, "y"] += s * pen * (mi / mtot)


def allocate_tile_counts(values, people_per_tile):
    """Floor + largest-remainder allocation of tile counts, so the
    sum matches round(total_value / people_per_tile) exactly."""
    n_tiles_float = values / people_per_tile
    n_tiles = np.floor(n_tiles_float).astype(int)
    n_tiles = n_tiles.clip(lower=1)

    target_tiles = round(values.sum() / people_per_tile)
    current_tiles = int(n_tiles.sum())
    remaining = target_tiles - current_tiles

    remainder = n_tiles_float - np.floor(n_tiles_float)

    if remaining > 0:
        idx = remainder.sort_values(ascending=False).index[:remaining]
        n_tiles.loc[idx] += 1
    elif remaining < 0:
        eligible = n_tiles[n_tiles > 1]
        idx = remainder.loc[eligible.index].sort_values().index[: abs(remaining)]
        n_tiles.loc[idx] -= 1

    return n_tiles, target_tiles


def allocate_shares(values, total):
    """Floor + largest-remainder split of an exact integer `total`
    across `values`' proportional shares. Unlike allocate_tile_counts,
    entries CAN receive 0 — used to partition a macroarea's fixed
    tile budget across its countries."""
    if total <= 0 or values.sum() <= 0:
        return pd.Series(0, index=values.index)

    shares = values / values.sum() * total
    counts = np.floor(shares).astype(int)
    remainder = shares - counts

    diff = total - int(counts.sum())
    if diff > 0:
        idx = remainder.sort_values(ascending=False).index[:diff]
        counts.loc[idx] += 1
    # diff < 0 cannot happen: sum(floor(x_i)) <= sum(x_i) = total always.

    return counts


def build_initial_clusters(entities, id_col, tile_size, prev_pos):
    """entities: GeoDataFrame with [id_col, 'geometry', 'WEC_value', 'n_tiles'].
    Builds the undisplaced tile layout for each entity and sets the
    optimizer's starting (x, y) to the warm-started previous position
    if available, else to this entity's own natural centroid."""
    records = []

    for _, row in entities.iterrows():
        name = row[id_col]
        n_tiles = int(row["n_tiles"])

        tiles = make_area_tiles(row.geometry, n_tiles, tile_size)
        if not tiles:
            raise ValueError(f"No tiles generated for {name}")

        geometries = [
            gpd.GeoSeries.from_wkt(
                [
                    f"POLYGON (({xmin} {ymin}, {xmax} {ymin}, "
                    f"{xmax} {ymax}, {xmin} {ymax}, {xmin} {ymin}))"
                ]
            ).iloc[0]
            for _, _, xmin, ymin, xmax, ymax in tiles
        ]

        cluster_geometry = unary_union(geometries)
        centroid = cluster_geometry.centroid
        minx, miny, maxx, maxy = cluster_geometry.bounds

        start_x, start_y = prev_pos.get(name, (centroid.x, centroid.y))

        records.append(
            {
                id_col: name,
                "WEC_value": row["WEC_value"],
                "n_tiles": len(geometries),
                "anchor_x": centroid.x,
                "anchor_y": centroid.y,
                "x": start_x,
                "y": start_y,
                "geometry": cluster_geometry,
                "minx": minx,
                "miny": miny,
                "maxx": maxx,
                "maxy": maxy,
                "tiles": geometries,
            }
        )

    return gpd.GeoDataFrame(records, crs=entities.crs)


def optimize_clusters(
    clusters, id_col, neighbor_pairs, n_iterations,
    overlap_strength, neighbor_strength, anchor_strength, damping, max_step,
    verbose=False,
):
    """Runs the force-directed layout in place on clusters['x'/'y']."""
    cluster_index = {name: i for i, name in enumerate(clusters[id_col])}
    velocity = np.zeros((len(clusters), 2), dtype=float)

    for iteration in range(n_iterations):
        forces = np.zeros_like(velocity)
        n = len(clusters)

        # A. Anchor force
        for i, row in clusters.iterrows():
            forces[i, 0] += anchor_strength * (row["anchor_x"] - row["x"])
            forces[i, 1] += anchor_strength * (row["anchor_y"] - row["y"])

        # B. Overlap repulsion
        for i in range(n):
            row_i = clusters.iloc[i]
            minxi, minyi, maxxi, maxyi = get_bounds(row_i)

            for j in range(i + 1, n):
                row_j = clusters.iloc[j]
                minxj, minyj, maxxj, maxyj = get_bounds(row_j)

                overlap_x = min(maxxi, maxxj) - max(minxi, minxj)
                overlap_y = min(maxyi, maxyj) - max(minyi, minyj)

                if overlap_x <= 0 or overlap_y <= 0:
                    continue

                # B. Overlap repulsion — minimal translation vector.
                #
                # Push direction: the MTV between the two bounding
                # boxes (along whichever axis the overlap is
                # SHALLOWER), not the center-to-center vector. For
                # elongated clusters (e.g. Eastern Europe / F. USSR
                # vs Asia) the center-to-center push could point
                # along an axis whose overlap it does not reduce at
                # all, so the anchor force dragged the pair straight
                # back into the same overlap every iteration — a
                # permanent limit cycle (see the movement printout:
                # years 2009+ never converged, and EE/Asia tiles
                # overlapped every year). Pushing along the MTV always
                # reduces the overlap exactly, so the force field now
                # has a fixed point at bounding-box contact instead
                # of a cycle through it.
                if overlap_x <= overlap_y:
                    s = 1.0 if row_j["x"] >= row_i["x"] else -1.0
                    ux, uy = s, 0.0
                    push = overlap_x * overlap_strength
                else:
                    s = 1.0 if row_j["y"] >= row_i["y"] else -1.0
                    ux, uy = 0.0, s
                    push = overlap_y * overlap_strength

                forces[i, 0] -= ux * push
                forces[i, 1] -= uy * push
                forces[j, 0] += ux * push
                forces[j, 1] += uy * push

        # C. Neighbor attraction
        for name_i, name_j in neighbor_pairs:
            i, j = cluster_index[name_i], cluster_index[name_j]
            row_i, row_j = clusters.iloc[i], clusters.iloc[j]

            dx = row_j["x"] - row_i["x"]
            dy = row_j["y"] - row_i["y"]
            distance = math.hypot(dx, dy)

            if distance < 1e-9:
                continue

            desired = desired_neighbor_distance(row_i, row_j)
            gap = distance - desired

            if gap <= 0:
                continue

            ux, uy = dx / distance, dy / distance
            attraction = gap * neighbor_strength

            forces[i, 0] += ux * attraction
            forces[i, 1] += uy * attraction
            forces[j, 0] -= ux * attraction
            forces[j, 1] -= uy * attraction

        # D. Velocity + damping
        velocity = velocity * damping + forces

        # E. Apply the capped force step ...
        pos_start = clusters[["x", "y"]].to_numpy(dtype=float)
        for i in range(n):
            vx, vy = velocity[i, 0], velocity[i, 1]
            speed = math.hypot(vx, vy)

            if speed > max_step:
                factor = max_step / speed
                vx *= factor
                vy *= factor
                velocity[i, 0], velocity[i, 1] = vx, vy

            clusters.at[i, "x"] += vx
            clusters.at[i, "y"] += vy

        # F. ... then project remaining overlaps away (hard
        # constraint — see project_overlaps) and derive the velocity
        # from the ACTUAL position change, so the projection feeds
        # back into the dynamics instead of being undone by them on
        # the next step. The cap is re-applied so a large projection
        # shift on a cold start doesn't convert into a huge coast.
        project_overlaps(clusters)
        pos_end = clusters[["x", "y"]].to_numpy(dtype=float)
        velocity = pos_end - pos_start

        speeds = np.hypot(velocity[:, 0], velocity[:, 1])
        too_fast = speeds > max_step
        if too_fast.any():
            velocity[too_fast] *= (max_step / speeds[too_fast])[:, None]
        movement = float(speeds.sum())

        if verbose and (iteration % 25 == 0 or iteration == n_iterations - 1):
            print(f"    iter {iteration:4d} | movement = {movement:,.0f}")

    return clusters


def finalize_tiles(clusters, id_col, extra_cols):
    records = []
    for _, row in clusters.iterrows():
        dx = row["x"] - row["anchor_x"]
        dy = row["y"] - row["anchor_y"]

        for tile_number, tile in enumerate(row["tiles"]):
            rec = {
                id_col: row[id_col],
                "n_tiles": row["n_tiles"],
                "tile": tile_number,
                # Undisplaced center, kept for the country partition
                # step below (nearest-country assignment needs a
                # position in the same frame as country_ref_points,
                # mapped through this macroarea's own scale/anchor).
                "undisplaced_x": tile.centroid.x,
                "undisplaced_y": tile.centroid.y,
                "geometry": translate(tile, xoff=dx, yoff=dy),
            }
            for col in extra_cols:
                rec[col] = row[col]
            records.append(rec)

    return gpd.GeoDataFrame(records, crs=clusters.crs)


# ============================================================
# 3a. SOLID OUTLINE FROM A SET OF TILES (macro or country border)
# ============================================================
#
# A plain unary_union of a tile set's own squares traces every
# tile's own edge, including any small sampling gaps between rows —
# exactly the "barcode" fragmentation the macroarea coastline hit
# before (see the module docstring). Buffering out by a bit more
# than half a tile width and then back in by the same amount closes
# any such gaps first, so the boundary below always comes out as
# one clean outline regardless of how the tiles were sampled.
#
# join_style="mitre" keeps that buffer's corners square instead of
# rounding them off — shapely's default (round) turns every square
# tile's corner into a little arc, which is what made these borders
# look soft/rounded instead of the blocky, edgy tile-grid outline
# that actually matches what's rendered.
# ============================================================

def tile_set_outline(geoms, close_dist):
    if not geoms:
        return None
    merged = unary_union(list(geoms))
    if merged.is_empty:
        return None
    return merged.buffer(close_dist, join_style="mitre").buffer(
        -close_dist, join_style="mitre"
    )


def draw_outline(ax, geom, color, linewidth, zorder):
    if geom is None or geom.is_empty:
        return
    parts = geom.geoms if hasattr(geom, "geoms") else [geom]
    for part in parts:
        if part.is_empty or part.geom_type != "Polygon":
            continue
        xs, ys = part.exterior.xy
        ax.add_patch(
            MplPolygon(
                list(zip(xs, ys)), closed=True,
                facecolor="none", edgecolor=color,
                linewidth=linewidth, zorder=zorder,
            )
        )
        for interior in part.interiors:
            ixs, iys = interior.xy
            ax.add_patch(
                MplPolygon(
                    list(zip(ixs, iys)), closed=True,
                    facecolor="none", edgecolor=color,
                    linewidth=linewidth * 0.8, zorder=zorder,
                )
            )


# ============================================================
# 3b. CALLOUT LABELS: A RING OF LABELS AROUND A MACROAREA, EACH
#     CONNECTED BY AN ARROW TO ITS OWN COUNTRY'S TILES
# ============================================================
#
# A country whose tile cluster is too small to hold readable inline
# text (a sliver, or a single tile) still needs to be identifiable —
# an arrow from a label placed OUTSIDE the crowded cluster solves
# that unambiguously, the same way a pie chart calls out thin
# slices. Labels are laid out on one evenly-spaced ring around the
# macroarea's own bounding box, in the same rotational ORDER as each
# country's true direction from the macro's center (so leader lines
# radiate outward without needlessly crossing each other), but at
# forced-even angular spacing — not their true angle — since real
# positions are often bunched together in exactly the crowded cases
# this exists for, and cramming labels at their true (nearby) angles
# would just recreate the overlap this is meant to fix.
# ============================================================

def reach_in_direction(geom, cx, cy, theta, search_len):
    """How far the macro's own tile shape extends from (cx, cy) along
    the exact ray at angle theta, found by intersecting that ray with
    the shape itself (not its bounding box or an isotropic estimate).
    Exact for any silhouette — elongated, multi-island, or with a
    hole — because it only measures the direction actually used, so
    it can't overshoot in a direction the shape doesn't reach, nor
    undershoot in one where it reaches unusually far. Returns 0.0 if
    the ray never touches the shape (e.g. center sits outside every
    part of a disconnected macro), signalling the caller to fall back
    to an isotropic radius instead."""
    far_x = cx + search_len * math.cos(theta)
    far_y = cy + search_len * math.sin(theta)
    ray = LineString([(cx, cy), (far_x, far_y)])
    inter = geom.intersection(ray)
    if inter.is_empty:
        return 0.0
    coords = []
    gt = inter.geom_type
    if gt in ("LineString", "LinearRing"):
        coords = list(inter.coords)
    elif gt == "Point":
        coords = [(inter.x, inter.y)]
    elif gt in ("MultiLineString", "MultiPoint", "GeometryCollection"):
        for part in inter.geoms:
            if hasattr(part, "coords"):
                coords.extend(list(part.coords))
    if not coords:
        return 0.0
    return max(math.hypot(x - cx, y - cy) for x, y in coords)


def place_callout_labels(ax, center, macro_radius, items, tile_size, geom=None, color="seagreen"):
    """items: list of (label_text, is_rest, (x, y) attachment point).
    center: (x, y) — the macro's actual tile centroid (not its
    bounding-box center, which can sit far from the tiles themselves
    for an L-shaped or multi-island macro). macro_radius: the true
    farthest reach of the macro's tiles from that centroid — used as
    a fallback only (see below). geom: the macro's own tile-union
    geometry; when given, each label's distance from center is based
    on how far the shape ACTUALLY extends along that label's own
    placement direction (via reach_in_direction), not one isotropic
    guess applied at every angle alike. That isotropic guess was
    still overshooting for an elongated/bent macro (e.g. a callout
    for a small notch near one end of a long, curved landmass landing
    far past the shape's far end, well outside where that direction
    actually reaches) — a single number can't be both "far enough" for
    the long axis and "close enough" for the short one."""
    if not items:
        return
    cx, cy = center
    n = len(items)

    def angle_of(pt):
        return math.atan2(pt[1] - cy, pt[0] - cx)

    ordered = sorted(items, key=lambda it: angle_of(it[2]))
    start_angle = angle_of(ordered[0][2])
    # Upper bound for the ray-cast search: comfortably past the
    # farthest the shape could possibly reach in any direction.
    search_len = macro_radius * 3 + tile_size * 20
    # Modest, mostly-constant clearance beyond the shape's true edge
    # in that exact direction — no longer compensating for an
    # isotropic estimate's error margin, just leaving room for the
    # arrowhead and label text itself.
    clearance = tile_size * (2.0 + 0.5 * n)

    for i, (text, is_rest, (px, py)) in enumerate(ordered):
        theta = start_angle + 2 * math.pi * i / n
        reach = reach_in_direction(geom, cx, cy, theta, search_len) if geom is not None else 0.0
        if reach <= 0.0:
            reach = macro_radius  # fallback: center outside the shape in this direction
        base_r = reach + clearance
        lx = cx + base_r * math.cos(theta)
        ly = cy + base_r * math.sin(theta)
        ax.annotate(
            text, xy=(px, py), xytext=(lx, ly),
            ha="center", va="center", fontsize=8, fontweight="bold",
            fontstyle=("italic" if is_rest else "normal"),
            color="black", zorder=27, annotation_clip=False,
            path_effects=[
                pe.withStroke(linewidth=2.2, foreground="white", alpha=0.95)
            ],
            arrowprops=dict(
                arrowstyle="-|>", color=color, lw=0.8,
                shrinkA=1, shrinkB=1, mutation_scale=7,
            ),
        )


# ============================================================
# 4a. MAP A MACROAREA'S TRUE GEOMETRY THROUGH ITS TILE TRANSFORM
# ============================================================
#
# The tile cluster for a macroarea is built by scaling its TRUE
# Natural Earth geometry up (or down) around its own centroid to
# hit the target tile area, then translating the whole cluster by
# (dx, dy) to its optimized position. macro_scale_factor recomputes
# that same scale factor from n_tiles (rather than threading it out
# of make_area_tiles), and transform_true_macro_geometry applies the
# identical scale+translate to the macroarea's one clean true
# polygon — giving a smooth "coastline" for that macroarea at its
# cartogram position, with none of the fragility of re-deriving an
# outline from a union of many small tiles (see the module docstring
# under "coastline outline" for why that approach broke down).
# ============================================================

def macro_scale_factor(macro_name, macro_row):
    true_geom = macro_geom_by_name[macro_name]
    target_area = macro_row["n_tiles"] * TILE_SIZE * TILE_SIZE
    return math.sqrt(target_area / true_geom.area)


def transform_true_macro_geometry(macro_name, macro_row):
    true_geom = macro_geom_by_name[macro_name]
    true_centroid = true_geom.centroid
    scale_factor = macro_scale_factor(macro_name, macro_row)
    scaled = scale(true_geom, xfact=scale_factor, yfact=scale_factor, origin=true_centroid)
    dx = macro_row["x"] - macro_row["anchor_x"]
    dy = macro_row["y"] - macro_row["anchor_y"]
    return translate(scaled, xoff=dx, yoff=dy)


# ============================================================
# 4b. PARTITION A MACROAREA'S OWN TILES AMONG ITS COUNTRIES
# ============================================================
#
# Countries never get their own tile geometry: they simply claim a
# subset of the macroarea's already-placed, already-optimized
# tiles. This makes containment exact (a subset of a shape is
# always inside it) and needs no extra force-directed layout.
# ============================================================

def partition_macro_tiles_to_countries(
    macro_name, macro_row, macro_tiles, countries_in_macro, country_values,
    forced_quota=None,
):
    """
    macro_row: the row from `clusters` for this macroarea (has
        anchor_x/anchor_y = true-geometry-derived centroid, and the
        scale factor implied by n_tiles/TILE_SIZE vs macro's true
        area — recomputed here to map country true centroids into
        the same "undisplaced" coordinate frame as macro_tiles'
        undisplaced_x/y).
    macro_tiles: this macroarea's rows from `tiles` (already has
        undisplaced_x/y and final geometry).
    countries_in_macro: list of country names assigned to this
        macroarea.
    country_values: {country: WEC_value this year}, used only to
        set each FREE country's *share* of the tile budget left
        after forced_quota entries are taken out.
    forced_quota: optional {country: int tile count}, for entries
        whose tile count is fixed directly rather than derived from
        country_values — used for the "Rest of <macro>" entry, whose
        share is population-coverage-based (extensive) regardless of
        which metric (population or per-capita energy — the latter
        is intensive and doesn't have a meaningful "total accounted
        for" to size Rest from) this macro's own tiles are sized by.

    Returns: {country: [row indices into macro_tiles]}.
    """
    k = len(macro_tiles)
    countries_in_macro = [c for c in countries_in_macro if c in country_ref_points]

    if k == 0 or not countries_in_macro:
        return {}

    # Map country true centroids into the macro's undisplaced/scaled
    # tile-coordinate frame, using the exact scale factor make_area_
    # tiles used for this macroarea this year.
    true_geom = macro_geom_by_name[macro_name]
    true_centroid = true_geom.centroid
    scale_factor = macro_scale_factor(macro_name, macro_row)

    ref_xy = np.array(
        [
            (
                true_centroid.x + (country_ref_points[c][0] - true_centroid.x) * scale_factor,
                true_centroid.y + (country_ref_points[c][1] - true_centroid.y) * scale_factor,
            )
            for c in countries_in_macro
        ]
    )

    forced_quota = {
        c: int(v) for c, v in (forced_quota or {}).items() if c in countries_in_macro
    }
    forced_total = min(sum(forced_quota.values()), k)
    free_budget = k - forced_total

    free_countries = [c for c in countries_in_macro if c not in forced_quota]
    free_values = pd.Series(
        [max(country_values.get(c, 0.0), 0.0) for c in free_countries],
        index=free_countries,
    )
    free_quotas = allocate_shares(free_values, free_budget)

    quotas = pd.Series(0, index=countries_in_macro)
    for c, v in forced_quota.items():
        quotas[c] = v
    for c in free_countries:
        quotas[c] = int(free_quotas[c])

    tile_xy = macro_tiles[["undisplaced_x", "undisplaced_y"]].to_numpy()
    tile_indices = macro_tiles.index.to_numpy()

    # Distance from every tile to every country's reference point.
    dists = np.sqrt(
        ((tile_xy[:, None, :] - ref_xy[None, :, :]) ** 2).sum(axis=2)
    )  # shape (k, m)

    order = np.argsort(dists, axis=None)
    tile_i, country_j = np.unravel_index(order, dists.shape)

    remaining = {c: int(quotas[c]) for c in countries_in_macro}
    assigned_tile = np.full(k, -1, dtype=int)

    filled = 0
    for ti, cj in zip(tile_i, country_j):
        if filled == k:
            break
        if assigned_tile[ti] != -1:
            continue
        cname = countries_in_macro[cj]
        if remaining[cname] <= 0:
            continue
        assigned_tile[ti] = cj
        remaining[cname] -= 1
        filled += 1

    # Any tiles left unassigned (can happen only if some country had
    # 0 quota everywhere nearby) go to the nearest country with any
    # quota left; if truly none remains (shouldn't happen, quotas
    # sum to k), they fall back to the single nearest country.
    leftover = np.where(assigned_tile == -1)[0]
    for ti in leftover:
        candidates = [c for c in countries_in_macro if remaining[c] > 0]
        if not candidates:
            candidates = countries_in_macro
        d = {c: dists[ti, countries_in_macro.index(c)] for c in candidates}
        cname = min(d, key=d.get)
        cj = countries_in_macro.index(cname)
        assigned_tile[ti] = cj
        remaining[cname] = max(remaining[cname] - 1, 0)

    result = {c: [] for c in countries_in_macro}
    for local_i, cj in enumerate(assigned_tile):
        result[countries_in_macro[cj]].append(tile_indices[local_i])

    return result


# ============================================================
# 5. PERSISTENT STATE ACROSS YEARS
# ============================================================

prev_pos = {}  # {macroarea: (x, y)}

macro_geom_by_name = dict(zip(macroareas_geo["Macroarea"], macroareas_geo["geometry"]))

# ============================================================
# 5a. ON-DISK CACHE: SKIP RE-OPTIMIZING A YEAR ALREADY SAVED
# ============================================================
#
# The force-directed layout (build_initial_clusters/optimize_
# clusters) and the country partition are the expensive parts of a
# run; everything after that (plotting) is cheap and is exactly what
# gets iterated on and re-run repeatedly while tuning colors, labels,
# borders, etc. BASE_TAG identifies the geometry-affecting settings
# only (not SHOW_COUNTRIES or SHOW_COUNTRY_LABELS, which change what
# gets drawn but not the tiles/partition themselves), so a cached
# macroarea .gpkg from a countries-off run is still reused by a
# later countries-on run of the same core parameters, and toggling
# "nolabels" never invalidates anything.
#
# Each cached macroarea .gpkg has a companion "<...>_clusters.json"
# sidecar carrying the small per-macro (x, y, anchor_x, anchor_y,
# n_tiles) values that would otherwise only exist as the optimizer's
# in-memory output — needed to warm-start the NEXT year and to place
# macro labels — without which the tiles alone aren't quite enough
# to resume from. If a .gpkg exists without its sidecar (or vice
# versa), that's treated as a cache miss and both are recomputed and
# rewritten, so a partial/interrupted cache can't leave stale state.
# ============================================================

# The repulsion/projection algorithm version is part of the cache
# key: it changes the resulting geometry, so a cache written by an
# older version (center-to-center push, no overlap projection) must
# not be reused by the current one (MTV push + position-based
# overlap projection), and vice versa.
BASE_TAG = (
    f"{area_var}_"
    f"people{PEOPLE_PER_TILE}_"
    f"iter{N_ITERATIONS}_"
    f"overlap{str(OVERLAP_STRENGTH).replace('.', 'p')}_"
    f"neighbor{str(NEIGHBOR_STRENGTH).replace('.', 'p')}_"
    f"anchor{str(ANCHOR_STRENGTH).replace('.', 'p')}_"
    f"damping{str(DAMPING).replace('.', 'p')}_"
    f"mtvproj"
)


def cluster_meta_path(gpkg_path):
    return gpkg_path.with_name(gpkg_path.stem + "_clusters.json")


def save_cluster_meta(gpkg_path, clusters):
    records = clusters[
        ["Macroarea", "x", "y", "anchor_x", "anchor_y", "n_tiles"]
    ].to_dict(orient="records")
    with open(cluster_meta_path(gpkg_path), "w") as f:
        json.dump(records, f)


def load_cluster_meta(gpkg_path):
    with open(cluster_meta_path(gpkg_path)) as f:
        records = json.load(f)
    return pd.DataFrame(records)


# ============================================================
# 6. LOOP YEARS
# ============================================================

for YEAR in years:
    print()
    print(f"=== YEAR {YEAR} ===")

    # --------------------------------------------------------
    # Macroarea layer
    # --------------------------------------------------------

    wec = load_year_wec(YEAR)
    colorbar_var = wec.set_index("Column")[colorbar_varname].to_dict()

    print(
        wec[["Column", "Energy_consumption_Mtoe", "Population_000"]].to_string(
            index=False
        )
    )

    # tag/gpkg_file/country_gpkg_file only ever depend on geometry-
    # affecting settings (BASE_TAG), not on SHOW_COUNTRIES or
    # SHOW_COUNTRY_LABELS — a macroarea .gpkg from a countries-off
    # run is exactly reusable by a countries-on run of the same core
    # parameters, and vice versa. Only the PNG filename (tag) reflects
    # those rendering-only toggles, since it's the one thing that
    # actually differs on disk between them.
    gpkg_file = OUTPUT_DIR / f"macroarea_cartogram_{YEAR}_{BASE_TAG}.gpkg"
    country_gpkg_file = OUTPUT_DIR / f"country_cartogram_{YEAR}_{BASE_TAG}.gpkg"

    tag = BASE_TAG
    if SHOW_COUNTRIES:
        tag += "_withcountries"
        if not SHOW_COUNTRY_LABELS:
            tag += "_nolabels"

    if gpkg_file.exists() and cluster_meta_path(gpkg_file).exists():
        print(f"Using cached macroarea layer: {gpkg_file}")
        tiles = gpd.read_file(gpkg_file)
        clusters = load_cluster_meta(gpkg_file)

        # Recover each tile's "undisplaced" (pre-translate) position
        # exactly: finalize_tiles built the saved geometry as
        # translate(undisplaced_tile, dx=x-anchor_x, dy=y-anchor_y),
        # and that's an exact, invertible affine shift — no
        # approximation needed even though the optimizer itself
        # didn't run this time.
        dx = (clusters.set_index("Macroarea")["x"]
              - clusters.set_index("Macroarea")["anchor_x"])
        dy = (clusters.set_index("Macroarea")["y"]
              - clusters.set_index("Macroarea")["anchor_y"])
        tiles["undisplaced_x"] = tiles.geometry.centroid.x - tiles["Macroarea"].map(dx)
        tiles["undisplaced_y"] = tiles.geometry.centroid.y - tiles["Macroarea"].map(dy)
    else:
        macroareas = macroareas_geo.copy()
        macroareas["WEC_value"] = macroareas["Macroarea"].map(
            dict(zip(wec["Column"], wec[macro_size_column]))
        )
        n_tiles, target_tiles = allocate_tile_counts(
            macroareas.set_index("Macroarea")["WEC_value"], PEOPLE_PER_TILE
        )
        macroareas["n_tiles"] = macroareas["Macroarea"].map(n_tiles)

        print(f"Total target tiles (macroareas): {target_tiles:,}")

        clusters = build_initial_clusters(macroareas, "Macroarea", TILE_SIZE, prev_pos)
        print("Optimizing macroarea layout...")
        clusters = optimize_clusters(
            clusters, "Macroarea", neighbor_pairs, N_ITERATIONS,
            OVERLAP_STRENGTH, NEIGHBOR_STRENGTH, ANCHOR_STRENGTH, DAMPING, MAX_STEP,
            verbose=True,
        )

        tiles = finalize_tiles(clusters, "Macroarea", ["WEC_value"])
        print(f"Final macroarea tiles: {len(tiles):,}")

        save_cluster_meta(gpkg_file, clusters)
        tiles.drop(columns=["undisplaced_x", "undisplaced_y"]).to_file(
            gpkg_file, layer=f"macroarea_cartogram_{YEAR}", driver="GPKG"
        )
        print(f"Saved: {gpkg_file}")

    for _, row in clusters.iterrows():
        prev_pos[row["Macroarea"]] = (row["x"], row["y"])

    # --------------------------------------------------------
    # Country layer: partition each macroarea's own tiles
    # --------------------------------------------------------

    country_tiles = None

    if SHOW_COUNTRIES:
        # Needed either way: cheap to (re)compute, and the PLOT step
        # below reads df_cy directly for each country's datasets color
        # regardless of whether the tile PARTITION was cached.
        df_cy = load_year_country_wec(YEAR)

    if SHOW_COUNTRIES and country_gpkg_file.exists():
        print(f"Using cached country layer: {country_gpkg_file}")
        country_tiles = gpd.read_file(country_gpkg_file)

    elif SHOW_COUNTRIES:
        macro_population = wec.set_index("Column")["Population_000"] * 1000

        country_records = []
        for _, macro_row in clusters.iterrows():
            macro_name = macro_row["Macroarea"]
            macro_tiles = tiles[tiles["Macroarea"] == macro_name]

            countries_in_macro = [
                c for c, m in country_macro.items() if m == macro_name
            ]
            country_values = {
                c: df_cy.loc[c, value_column]
                for c in countries_in_macro
                if c in df_cy.index
            }

            # "Rest of <macro>" gets a tile quota sized by POPULATION
            # coverage specifically (always extensive/summable, and
            # always available regardless of area_var) rather than
            # value_column: value_column is "Per_capita_energy_
            # consumption" in energy mode, which is intensive — the
            # sum of several countries' per-capita values has no
            # "share of the macro accounted for" meaning to size a
            # gap from. The rest of the macro's tile budget (after
            # Rest's forced share) is still split among tracked
            # countries by value_column as before, so the on-screen
            # metric (color, relative country size) is unaffected —
            # only the fact that some tiles go to an unlabeled-country
            # "Rest" bucket is new.
            rest_name = REST_PREFIX + macro_name
            macro_pop = macro_population.get(macro_name)
            tracked_pop = sum(
                df_cy.loc[c, "Population"]
                for c in countries_in_macro
                if c in df_cy.index
            )
            forced_quota = {}
            if macro_pop and macro_pop > 0:
                rest_pop_fraction = max(1.0 - tracked_pop / macro_pop, 0.0)
                n_rest_tiles = round(rest_pop_fraction * macro_row["n_tiles"])
                if n_rest_tiles > 0:
                    forced_quota[rest_name] = n_rest_tiles

            assignment = partition_macro_tiles_to_countries(
                macro_name, macro_row, macro_tiles, countries_in_macro, country_values,
                forced_quota=forced_quota,
            )

            for country, tile_idx in assignment.items():
                for idx in tile_idx:
                    trow = macro_tiles.loc[idx]
                    country_records.append(
                        {
                            "Country": country,
                            "Macroarea": macro_name,
                            "geometry": trow["geometry"],
                        }
                    )

        country_tiles = gpd.GeoDataFrame(country_records, crs=tiles.crs)
        print(f"Final country tiles: {len(country_tiles):,}")

        if len(country_tiles) > 0:
            country_tiles.to_file(
                country_gpkg_file, layer=f"country_cartogram_{YEAR}", driver="GPKG"
            )
            print(f"Saved: {country_gpkg_file}")

    # --------------------------------------------------------
    # PLOT
    # --------------------------------------------------------

    png_file = OUTPUT_DIR / f"macroarea_cartogram_{YEAR}_{tag}.png"

    fig = plt.figure(figsize=(20, 12), facecolor="white")

    # ax_map is narrower than before (0.90 instead of 0.96 wide) to
    # leave a real, fixed-position strip on the right for the
    # colorbar (cbar_ax below) — fig.colorbar(..., ax=ax_map) doesn't
    # actually reserve space from a manually add_axes'd axes, so it
    # was just being drawn immediately to the right of ax_map's own
    # box, past x=0.98, and getting clipped by the figure edge.
    ax_map = fig.add_axes([0.02, 0.02, 0.90, 0.96])
    ax_tl = fig.add_axes([0.045, 0.72, 0.20, 0.22])
    ax_tr = fig.add_axes([0.775, 0.72, 0.20, 0.22])
    ax_bl = fig.add_axes([0.045, 0.045, 0.24, 0.17])
    ax_br = fig.add_axes([0.735, 0.045, 0.24, 0.17])
    cbar_ax = fig.add_axes([0.935, 0.35, 0.014, 0.3])

    macro_colors = {
        macroarea: cmap(norm(val)) for macroarea, val in colorbar_var.items()
    }

    # --- background: true, un-transformed Natural Earth geometry as
    # a fixed geographic reference, under everything else, in both
    # modes. ---
    world.plot(
        ax=ax_map, facecolor="#eef0f2", edgecolor="#c7cbd1",
        linewidth=0.35, zorder=1,
    )

    # --- macroarea tiles: always filled, plain white grid lines (the
    # same treatment used everywhere else — tile edges are not meant
    # to be a visual signal; boundaries below are). When the country
    # layer is on, country tiles (drawn next, at a higher zorder)
    # cover this completely since they're an exact partition of the
    # same tile set — this is just the fallback color if a tile is
    # ever left unassigned. ---
    patches, colors = [], []
    for _, row in tiles.iterrows():
        minx, miny, maxx, maxy = row.geometry.bounds
        patches.append(Rectangle((minx, miny), maxx - minx, maxy - miny))
        colors.append(macro_colors[row["Macroarea"]])

    collection = PatchCollection(
        patches, facecolor=colors, edgecolor="white", linewidth=0.15,
        antialiased=True, zorder=5,
    )
    ax_map.add_collection(collection)

    # --- map: country tiles, filling the macroarea outlines ---
    #
    # Colored on their OWN scale (country_norm), not the macro-level
    # `norm` — see the note by country_norm's definition for why
    # sharing one scale between 8 macroareas and 72 countries left
    # almost every country the same washed-out color. Tile-to-tile
    # edges are plain white again — a dark per-tile edge, at the
    # tile counts a real run has, just ink-blotted the whole map into
    # a muddy, uniform texture instead of helping. What actually
    # marks out one country from the next is the solid black BORDER
    # traced around each country's whole tile cluster below.
    #
    # "Rest of <macro>" tiles (the untracked-country remainder — see
    # REST_PREFIX) get a fixed neutral gray instead of a datasets color,
    # since there's no per-country value behind them.

    REST_FILL = "#c9c9c9"
    has_rest = False

    # --- macroarea bounding boxes/outlines, from their own tiles (no
    # geometry transform needed — this hugs exactly what's rendered).
    # Computed here (before country tiles/labels) since the callout-
    # label layout below needs each macro's bounds to lay its ring
    # of labels around; drawn on top of everything else in the map
    # so the border reads clearly against either a solid macro fill
    # or a busy country patchwork underneath. ---
    macro_tile_bounds = {}  # macro name -> (minx, miny, maxx, maxy) of its own tiles
    # macro name -> {"center": (x, y) tile centroid, "radius": equal-
    # area circle radius}, used for callout-label placement below —
    # deliberately NOT the bounding box, which blows up for an
    # elongated or multi-island macro (see place_callout_labels).
    macro_tile_stats = {}
    for macro_name, grp in tiles.groupby("Macroarea"):
        macro_geom = unary_union(grp.geometry.tolist())
        macro_tile_bounds[macro_name] = macro_geom.bounds
        macro_centroid = macro_geom.centroid
        ccx, ccy = macro_centroid.x, macro_centroid.y
        # The true farthest point of the shape from its own centroid
        # — NOT half the bounding box (which overshoots badly for a
        # diagonal or skewed shape) and NOT an equal-area circle
        # (which undershoots for an elongated one, so a callout for
        # a country at the tip of a long thin macro still ends up
        # placed well past the edge of the map). This is exact for
        # any shape, so callouts stay close to the actual tiles
        # regardless of how irregular the macro's silhouette is.
        max_reach = 0.0
        parts = macro_geom.geoms if hasattr(macro_geom, "geoms") else [macro_geom]
        for part in parts:
            if part.is_empty:
                continue
            for x, y in part.exterior.coords:
                max_reach = max(max_reach, math.hypot(x - ccx, y - ccy))
        macro_tile_stats[macro_name] = {"center": (ccx, ccy), "radius": max_reach, "geom": macro_geom}
        outline = tile_set_outline(grp.geometry.tolist(), BOUNDARY_CLOSE_DIST)
        draw_outline(ax_map, outline, color="black", linewidth=1.6, zorder=16)

    if SHOW_COUNTRIES and country_tiles is not None and len(country_tiles) > 0:
        country_colors = {
            name: cmap(country_norm(val))
            for name, val in df_cy[colorbar_varname].items()
        }

        # Rest tiles are drawn as their OWN collection, not folded
        # into the datasets-colored one: a flat gray fill sitting at the
        # pale end of a yellow-heavy colormap reads as just another
        # low-value country at a glance (this is exactly what made
        # "Rest" unidentifiable in Oceania — a gray patch next to
        # pale-yellow Australia doesn't visually register as a
        # different KIND of thing, just another low number). A hatch
        # pattern is a categorical signal no point on a continuous
        # color scale can produce by accident, so it stays legible
        # regardless of which countries happen to be near the low
        # end of the datasets range that year.
        c_patches, c_colors = [], []
        rest_patches = []
        for _, row in country_tiles.iterrows():
            minx, miny, maxx, maxy = row.geometry.bounds
            rect = Rectangle((minx, miny), maxx - minx, maxy - miny)
            if row["Country"].startswith(REST_PREFIX):
                rest_patches.append(rect)
            else:
                c_patches.append(rect)
                c_colors.append(country_colors.get(row["Country"], REST_FILL))

        c_collection = PatchCollection(
            c_patches, facecolor=c_colors, edgecolor="white", linewidth=0.15,
            antialiased=True, zorder=10,
        )
        ax_map.add_collection(c_collection)

        has_rest = len(rest_patches) > 0
        if has_rest:
            rest_collection = PatchCollection(
                rest_patches, facecolor=REST_FILL, edgecolor="#777777",
                linewidth=0.15, hatch="///", antialiased=True, zorder=10,
            )
            ax_map.add_collection(rest_collection)

        # --- seagreen border around each COUNTRY's own tile cluster
        # (tile_set_outline closes any grid-sampling gaps first, so
        # this stays one clean line at any scale). This is what
        # actually separates same-macro countries visually — color
        # alone, especially between two similarly-valued countries,
        # wasn't enough. Green (rather than the macroarea's own
        # black) also keeps the two border levels visually distinct
        # from each other. ---
        for country, grp in country_tiles.groupby("Country"):
            outline = tile_set_outline(grp.geometry.tolist(), BOUNDARY_CLOSE_DIST)
            draw_outline(ax_map, outline, color="seagreen", linewidth=0.9, zorder=13)

        # Country labels are gated on SHOW_COUNTRY_LABELS (5th CLI
        # arg "nolabels" turns this whole block off, keeping the
        # colored/outlined tiles above).
        #
        # An absolute size floor alone (a country's OWN tile cluster
        # big enough to hold text) isn't enough to decide "inline or
        # callout": a real macroarea like Western Europe has a dozen-
        # plus countries that each individually clear that floor, but
        # are packed close enough together that their inline labels
        # still collide with each other — that's exactly the crowding
        # this was meant to fix, and it doesn't show up in any single
        # country's own size. So after the size floor, candidates are
        # placed inline GREEDILY, largest first: a candidate is only
        # actually drawn inline if its label position isn't too close
        # to an already-accepted inline label in the SAME macro
        # (checked against both labels' estimated on-map footprint,
        # which scales with their font size); everything else —
        # whether too small on its own, or simply too close to a
        # bigger neighbor that got there first — becomes a callout.
        if SHOW_COUNTRY_LABELS:
            MIN_TILES_FOR_LABEL = 2
            MIN_BBOX_FOR_LABEL = TILE_SIZE * 2.2  # in map units (either dimension)
            # How far apart (in TILE_SIZE units per unit of fontsize)
            # two inline labels need to be to not visually collide.
            CLEARANCE_PER_FONTSIZE = 0.34
            CLEARANCE_BASE = 1.6

            candidates_by_macro = {}  # macro name -> [candidate dict, ...]

            for country, grp in country_tiles.groupby("Country"):
                n_country_tiles = len(grp)
                geom = unary_union(grp.geometry.tolist())
                minx, miny, maxx, maxy = geom.bounds
                bbox_extent = max(maxx - minx, maxy - miny)
                is_rest = country.startswith(REST_PREFIX)
                label_text = "Rest" if is_rest else country_abbr(country)
                label_point = geom.centroid
                macro_name = grp["Macroarea"].iloc[0]
                fontsize = max(6.0, min(13.0, 5.5 + 1.3 * math.sqrt(n_country_tiles)))
                clearance = TILE_SIZE * (CLEARANCE_BASE + CLEARANCE_PER_FONTSIZE * fontsize)
                eligible = n_country_tiles >= MIN_TILES_FOR_LABEL and bbox_extent >= MIN_BBOX_FOR_LABEL

                candidates_by_macro.setdefault(macro_name, []).append(
                    {
                        "text": label_text, "is_rest": is_rest,
                        "point": (label_point.x, label_point.y),
                        "fontsize": fontsize, "clearance": clearance,
                        "n_tiles": n_country_tiles, "eligible": eligible,
                    }
                )

            for macro_name, candidates in candidates_by_macro.items():
                candidates.sort(key=lambda c: c["n_tiles"], reverse=True)
                accepted = []  # [(x, y, clearance), ...]
                callout_items = []

                for c in candidates:
                    px, py = c["point"]
                    too_close = any(
                        math.hypot(px - ax_, py - ay_) < (c["clearance"] + a_clear) * 0.6
                        for ax_, ay_, a_clear in accepted
                    )
                    if c["eligible"] and not too_close:
                        accepted.append((px, py, c["clearance"]))
                        ax_map.text(
                            px, py, c["text"],
                            ha="center", va="center", fontsize=c["fontsize"],
                            fontweight="bold",
                            fontstyle=("italic" if c["is_rest"] else "normal"),
                            color="black", zorder=25,
                            path_effects=[
                                pe.withStroke(linewidth=2.4, foreground="white", alpha=0.9)
                            ],
                        )
                    else:
                        callout_items.append((c["text"], c["is_rest"], c["point"]))

                if callout_items and macro_name in macro_tile_stats:
                    stats = macro_tile_stats[macro_name]
                    place_callout_labels(
                        ax_map, stats["center"], stats["radius"],
                        callout_items, TILE_SIZE, geom=stats["geom"],
                    )

    # --- macroarea labels ---
    #
    # Centered on the tile cluster as before when countries are off.
    # When countries are on, moved to just above the tile cluster
    # instead: centering on top of the (now more crowded) country
    # tiles/labels is what made macro names collide with country
    # labels underneath (e.g. "Latin America" sitting on top of a
    # dozen small country tags).

    for _, row in clusters.iterrows():
        macro_name = row["Macroarea"]
        if SHOW_COUNTRIES and macro_name in macro_tile_bounds:
            minx, miny, maxx, maxy = macro_tile_bounds[macro_name]
            label_x, label_y = (minx + maxx) / 2, maxy + TILE_SIZE * 3
            va = "bottom"
        else:
            label_x, label_y = row["x"], row["y"]
            va = "center"

        ax_map.text(
            label_x, label_y, macro_name,
            ha="center", va=va, fontsize=12, fontweight="bold",
            bbox=dict(boxstyle="round,pad=0.3", facecolor="white", edgecolor="black", alpha=0.85),
            zorder=20,
        )

    if SHOW_COUNTRIES:
        sm = mpl.cm.ScalarMappable(cmap=cmap, norm=country_norm)
        cb_label = colorbar_varname_cb + "\n(per-country scale)"
    else:
        sm = mpl.cm.ScalarMappable(cmap=cmap, norm=norm)
        cb_label = colorbar_varname_cb
    sm.set_array([])
    cbar = fig.colorbar(sm, cax=cbar_ax, orientation="vertical")
    cbar.set_label(cb_label, fontsize=14)
    cbar.ax.tick_params(labelsize=10)

    settings_text = (
        "WEC cartogram\n"
        "────────────────────────\n"
        f"Year: {YEAR}\n"
        f"{value_label} per tile: {PEOPLE_PER_TILE:,}\n"
        f"Iterations: {N_ITERATIONS}\n"
        f"Countries layer: {'on' if SHOW_COUNTRIES else 'off'}"
        + (
            f"\nCountry labels: {'on' if SHOW_COUNTRY_LABELS else 'off'}"
            if SHOW_COUNTRIES else ""
        )
    )
    ax_map.text(
        0.015, 0.5, settings_text, transform=ax_map.transAxes,
        ha="left", va="center", fontsize=11, family="monospace",
        bbox=dict(boxstyle="round,pad=0.5", facecolor="white", edgecolor="black", alpha=0.90),
        zorder=100,
    )

    # --- "Rest of <macro>" legend swatch — only drawn for a frame
    # that actually has a Rest region, so there's nothing to explain
    # when there isn't one. A hatch pattern alone can still read as
    # "just a texture" without this key spelling out what it means;
    # the gray hatch here is drawn with the exact same style as the
    # map tiles, so it's an unambiguous match to point at. ---
    if SHOW_COUNTRIES and has_rest:
        legend_patch = Patch(
            facecolor=REST_FILL, edgecolor="#777777", hatch="///",
            label="Rest of macroarea\n(countries not tracked\nindividually in WEC datasets)",
        )
        ax_map.legend(
            handles=[legend_patch], loc="upper left",
            bbox_to_anchor=(0.015, 0.33), fontsize=9, frameon=True,
            facecolor="white", edgecolor="black", framealpha=0.90,
        ).set_zorder(100)

    ax_map.set_xlim(*FIXED_XLIM)
    ax_map.set_ylim(*FIXED_YLIM)
    ax_map.set_axis_off()

    # --- top-left: per-capita energy share by macroarea (%) ---

    pce = wec.set_index("Column")["Per_capita_energy_consumption"]
    pce_share = (pce / pce.sum() * 100).reindex(MACROAREAS)

    ax_tl.set_facecolor("white")
    ax_tl.patch.set_alpha(0.85)
    bar_colors = [macro_colors[m] for m in MACROAREAS]
    ax_tl.bar(
        [MACROAREA_ABBR[m] for m in MACROAREAS], pce_share.values, color=bar_colors,
        edgecolor="black", linewidth=0.4,
    )
    ax_tl.set_ylim(0, energy_share_max * 1.1)
    ax_tl.set_ylabel("Per-capita energy\nshare (%)", fontsize=8)
    ax_tl.tick_params(axis="both", labelsize=7)
    ax_tl.set_title("Per-capita energy consumption share", fontsize=9)

    # --- top-right: population share by macroarea (%) ---

    pop_share = wec.set_index("Column")["Population_Fraction"].reindex(MACROAREAS)

    ax_tr.set_facecolor("white")
    ax_tr.patch.set_alpha(0.85)
    ax_tr.bar(
        [MACROAREA_ABBR[m] for m in MACROAREAS], pop_share.values, color=bar_colors,
        edgecolor="black", linewidth=0.4,
    )
    ax_tr.set_ylim(0, pop_share_max * 1.1)
    ax_tr.set_ylabel("Population\nshare (%)", fontsize=8)
    ax_tr.tick_params(axis="both", labelsize=7)
    ax_tr.set_title("Population share", fontsize=9)

    # --- bottom-left: world energy consumption timeline ---

    energy_upto = world_series.loc[LINE_YEAR_MIN:YEAR, "Energy_consumption_Mtoe"]

    ax_bl.set_facecolor("white")
    ax_bl.patch.set_alpha(0.85)
    ax_bl.plot(energy_upto.index, energy_upto.values, color="firebrick", linewidth=1.6)
    ax_bl.scatter([YEAR], [energy_upto.iloc[-1]], color="firebrick", s=18, zorder=5)
    ax_bl.set_xlim(LINE_YEAR_MIN, LINE_YEAR_MAX)
    ax_bl.set_ylim(0, ENERGY_TIMELINE_YMAX)
    ax_bl.set_ylabel("World energy\n(Mtoe)", fontsize=8)
    ax_bl.tick_params(axis="both", labelsize=7)
    ax_bl.set_title("Total energy consumption", fontsize=9)

    # --- bottom-right: world population timeline ---

    pop_upto = world_series.loc[LINE_YEAR_MIN:YEAR, "Population_000"]

    ax_br.set_facecolor("white")
    ax_br.patch.set_alpha(0.85)
    ax_br.plot(pop_upto.index, pop_upto.values, color="steelblue", linewidth=1.6)
    ax_br.scatter([YEAR], [pop_upto.iloc[-1]], color="steelblue", s=18, zorder=5)
    ax_br.set_xlim(LINE_YEAR_MIN, LINE_YEAR_MAX)
    ax_br.set_ylim(0, POPULATION_TIMELINE_YMAX)
    ax_br.set_ylabel("World population\n(000)", fontsize=8)
    ax_br.tick_params(axis="both", labelsize=7)
    ax_br.set_title("Total population", fontsize=9)

    fig.savefig(png_file, dpi=300, facecolor="white")
    plt.close(fig)

    print(f"Saved: {png_file}")

print()
print("Done. To stitch the PNG sequence into a video, e.g.:")
print(
    "  ffmpeg -framerate 12 -pattern_type glob "
    f"-i '{OUTPUT_DIR}/macroarea_cartogram_*.png' "
    f"-vf scale=1920:-2 -pix_fmt yuv420p {OUTPUT_DIR}/animation.mp4"
)
