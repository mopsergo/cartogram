# Primary energy use per person - Data package

This data package contains the data that powers the chart ["Primary energy use per person"](https://ourworldindata.org/grapher/energy-mix?v=1&csvType=full&useColumnShortNames=false&metric=per_capita&source=total) on the Our World in Data website. It was downloaded on October 12, 2026.

### Active Filters

A filtered subset of the full data was downloaded. The following filters were applied:

## CSV structure

Each row is an observation for an entity (usually a country or region) at a timepoint.

- "Entity" — the name of the entity, e.g. "United States".
- "Code" — our internal entity code. For most countries this is the [ISO alpha-3](https://en.wikipedia.org/wiki/ISO_3166-1_alpha-3) code, e.g. "USA"; historical and other non-standard entities get a custom code.
- "Year" or "Day" — the timepoint. Annual data has a "Year" column holding an integer year; otherwise a "Day" column holds a date string in the form "YYYY-MM-DD".
- The final column is the data column — the time series that powers the chart. Downloaded with the "full data" option it corresponds to the time series below; with "only selected data visible in the chart" it is transformed depending on the chart type, so the correspondence may be less direct.


## Metadata.json structure

The .metadata.json file contains metadata about the data package. The "charts" key contains information to recreate the chart, like the title, subtitle etc. The "columns" key contains information about each of the columns in the csv, like the unit, timespan covered, citation for the data etc.

## How we process data at Our World in Data

Our World in Data is almost never the original producer of the data - almost all of the data we use has been compiled by others. If you want to re-use data, it is your responsibility to ensure that you adhere to the sources' license and to credit them correctly. Please note that a single time series may have more than one source - e.g. when we stitch together data from different time periods by different producers or when we calculate per capita metrics using population data from a second source.

Preparing this data involves several processing steps. Depending on the data, this can include standardizing country names and world region definitions, converting units, calculating derived indicators such as per capita measures, as well as adding or adapting metadata such as the name or the description given to an indicator.
[Read about our data pipeline](https://docs.owid.io/projects/etl/).

## Detailed information about the data


### Total energy supply per capita
Measured in kilowatt-hours of total energy supply per person.
Last updated: June 30, 2026  
Next expected update: June 2027  
Date range: 1800–2025  
Unit: kilowatt-hours per person  
Source: Energy Institute – Statistical Review of World Energy (2026); Smil (2017); U.S. Energy Information Administration (2026); Population based on various sources (2024) – with major processing by Our World in Data  

#### How to cite this data

Energy Institute – Statistical Review of World Energy (2026) and other sources – with major processing by Our World in Data

#### How this data is described by its producers
In this review, energy supply comprises commercially-traded fuels, including modern renewables used to generate electricity. Energy from non-fossil fuel combustible electricity generation is accounted for on their input heat requirements and non-combustible renewables on the energy content of their gross electrical output. See https://www.energyinst.org/statistical-review for more details on this methodology.

#### Notes on our processing step for this indicator
- Total energy supply is extended with total energy consumption from the U.S. Energy Information Administration (EIA), to cover countries and years for which the Statistical Review does not report a total. Where both sources report a value, we use the Statistical Review.
- For the World, data before 1965 (going back to 1800) comes from Vaclav Smil's historical estimates (2017).


## Sources

These are the sources behind the data in this package. Each time series above names the ones it draws on in its citation.

### Energy Institute – Statistical Review of World Energy

The Energy Institute Statistical Review of World Energy analyses data on world energy markets from the prior year.

Producer: Energy Institute  
Published: 2026-06-30  
Retrieved on: 2026-07-02  
Retrieved from: https://www.energyinst.org/statistical-review/  
License: © Energy Institute 2026 (https://www.energyinst.org/terms)  

Citation: Energy Institute – Statistical Review of World Energy (2026).

### Smil – Energy Transitions: Global and National Perspectives

Producer: Smil  
Published: 2017-01-01  
Retrieved on: 2023-12-12  
Retrieved from: https://vaclavsmil.com/book/energy-transitions-global-and-national-perspectives-second-expanded-and-updated-edition/  
License: CC BY 4.0 (https://vaclavsmil.com/book/energy-transitions-global-and-national-perspectives-second-expanded-and-updated-edition/)  

Citation: Energy Transitions: Global and National Perspectives, 2nd edition, Appendix A, Vaclav Smil (2017).

### U.S. Energy Information Administration – International Energy Data

Producer: U.S. Energy Information Administration  
Published: 2026-05-05  
Retrieved on: 2026-05-05  
Retrieved from: https://www.eia.gov/opendata/bulkfiles.php  
Direct download: https://api.eia.gov/bulk/INTL.zip  
License: Public domain (https://www.eia.gov/about/copyrights_reuse.php)  

Citation: U.S. Energy Information Administration (EIA) – International Energy Data (2026).

### Various sources – Population

Our World in Data builds and maintains a long-run dataset on population by country, region, and for the world, based on various sources.

You can find more information on these sources and how our time series is constructed on this page: https://ourworldindata.org/population-sources

Producer: Various sources  
Published: 2024-07-15  
Retrieved on: 2026-03-31  
Retrieved from: https://ourworldindata.org/population-sources  
License: CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/)  

Citation: The long-run data on population is based on various sources, described on this page: https://ourworldindata.org/population-sources

    