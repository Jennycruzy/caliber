"""Kalshi weather-series -> physical station registry.

Coordinates are the official NWS/GHCND station locations Kalshi's resolution
rule actually names (verified live via NOAA NCDC station pages,
docs/VERIFICATION_LEDGER.md §1). Getting the wrong point on the map is the
single easiest way to answer the wrong question — this table exists so that
mistake can't happen silently.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Station:
    name: str
    lat: float
    lon: float
    ghcnd_id: str
    source: str


# Verified 2026-07-08 against NOAA NCDC GHCND station detail pages.
STATIONS: dict[str, Station] = {
    "KXHIGHNY": Station(
        name="NY City Central Park, NY US",
        lat=40.7667,
        lon=-73.9667,
        ghcnd_id="GHCND:USW00094728",
        source="https://www.ncdc.noaa.gov/cdo-web/datasets/GHCND/stations/GHCND:USW00094728/detail",
    ),
    "KXHIGHCHI": Station(
        name="Chicago Midway Airport, IL US",
        lat=41.79,
        lon=-87.74,
        ghcnd_id="GHCND:USW00014819",
        source="https://www.ncdc.noaa.gov/cdo-web/datasets/GHCND/stations/GHCND:USW00014819/detail",
    ),
}


def station_for_series(series_ticker: str) -> Station:
    if series_ticker not in STATIONS:
        raise KeyError(
            f"No verified station coordinates for series '{series_ticker}'. "
            "Add and verify one in weather_stations.py before using this series "
            "— never guess a station's lat/lon."
        )
    return STATIONS[series_ticker]
