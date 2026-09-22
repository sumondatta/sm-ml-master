"""Connector parsing tests, against recorded response shapes.

The environment these connectors were written in had no outbound access to any
of these hosts, so nothing here has touched a live server. What *is* tested is
the part that actually goes wrong in practice: unit conversion and response
parsing. Every fixture is built to the shape documented for its service and
deliberately includes the traps — NASA POWER's -999 fill value, SoilGrids'
integer storage with a per-property divisor and fractions that do not sum to
100, SSURGO's multiple components per map unit with irregular horizons and a
null salinity.

A connector that parses these correctly can still fail against the live API if
an endpoint has moved. It cannot, however, silently record a -999 mm rainfall
day or a hydraulic conductivity wrong by a factor of 3600, which is the class of
error that survives a smoke test and corrupts a database.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from smml.sources.soil import SoilDataAccessConnector, SoilGridsConnector
from smml.sources.weather import (
    DaymetConnector,
    NasaPowerConnector,
    OpenMeteoConnector,
)

FIXTURES = Path(__file__).parent.parent / "fixtures"


def load_json(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


# --------------------------------------------------------------------------
# NASA POWER
# --------------------------------------------------------------------------


@pytest.fixture
def power_frame() -> pd.DataFrame:
    connector = NasaPowerConnector.__new__(NasaPowerConnector)
    return connector._parse(load_json("nasa_power_point.json"), 37.0, -100.5, "test_site")


def test_power_parses_every_day(power_frame):
    assert len(power_frame) == 84
    assert power_frame["site_id"].eq("test_site").all()
    assert power_frame["source_id"].eq("nasa_power").all()


def test_power_fill_value_becomes_missing_not_a_number(power_frame):
    """-999 left in place would be a -999 mm rainfall day, and nothing downstream
    would notice until the water balance went negative."""
    assert power_frame["precip_mm"].isna().sum() == 2
    assert (power_frame["precip_mm"].dropna() >= 0).all()
    assert power_frame["precip_mm"].min(skipna=True) > -1


def test_power_produces_reference_et(power_frame):
    assert power_frame["et0_mm"].notna().all()
    assert (power_frame["et0_mm"] >= 0).all()
    assert power_frame["et0_mm"].max() < 20
    # Radiation, wind and dewpoint are all present, so the accurate method applies.
    assert power_frame["et0_method"].eq("fao56_penman_monteith").all()


def test_power_output_matches_the_weather_schema(power_frame):
    from smml.db.schema import WEATHER_SCHEMA

    declared = {f.name for f in WEATHER_SCHEMA}
    assert set(power_frame.columns) <= declared
    for required in ("site_id", "date", "source_id", "year"):
        assert required in power_frame.columns
    assert power_frame["year"].dtype == np.int16


# --------------------------------------------------------------------------
# SoilGrids
# --------------------------------------------------------------------------


@pytest.fixture
def soilgrids_frame() -> pd.DataFrame:
    return SoilGridsConnector.parse(load_json("soilgrids_point.json"), 37.0, -100.5, "sg_site")


def test_soilgrids_returns_the_six_standard_layers(soilgrids_frame):
    assert len(soilgrids_frame) == 6
    assert list(soilgrids_frame["depth_top_cm"]) == [0, 5, 15, 30, 60, 100]
    assert list(soilgrids_frame["depth_bottom_cm"]) == [5, 15, 30, 60, 100, 200]


def test_soilgrids_applies_the_per_property_divisor(soilgrids_frame):
    """Stored integers divided by d_factor read from the response, not hard-coded."""
    # clay 221 g/kg with d_factor 10 -> 22.1 %, then renormalized to close at 100.
    assert 20.0 < soilgrids_frame["clay_pct_grid"].iloc[0] < 24.0
    # bdod 132 cg/cm3 with d_factor 100 -> 1.32 kg/dm3.
    assert soilgrids_frame["bulk_density_grid_g_cm3"].iloc[0] == pytest.approx(1.32)
    # phh2o 68 with d_factor 10 -> 6.8.
    assert soilgrids_frame["ph"].iloc[0] == pytest.approx(6.8)


def test_soilgrids_texture_fractions_are_renormalized_to_one_hundred(soilgrids_frame):
    """The three fractions come from independent models and do not close."""
    total = (
        soilgrids_frame["sand_pct_grid"]
        + soilgrids_frame["silt_pct_grid"]
        + soilgrids_frame["clay_pct_grid"]
    )
    assert np.allclose(total, 100.0, atol=1e-6)


def test_soilgrids_water_contents_are_volumetric_fractions(soilgrids_frame):
    """wv0033 arrives as 0.1 volume percent; the database stores m3/m3."""
    fc = soilgrids_frame["field_capacity_m3m3"]
    wp = soilgrids_frame["wilting_point_m3m3"]
    assert fc.between(0.05, 0.60).all(), fc.tolist()
    assert wp.between(0.02, 0.45).all()
    assert (fc > wp).all()


def test_soilgrids_converts_organic_carbon_to_organic_matter(soilgrids_frame):
    # soc 168 dg/kg -> 16.8 g/kg -> 1.68 % C -> /0.58 -> ~2.9 % OM.
    assert soilgrids_frame["om_pct_grid"].iloc[0] == pytest.approx(2.9, abs=0.05)


def test_soilgrids_adds_texture_class_and_hydraulics(soilgrids_frame):
    assert soilgrids_frame["texture_class"].notna().all()
    assert set(soilgrids_frame["texture_class"]) <= {
        "sand", "loamy_sand", "sandy_loam", "loam", "silt", "silt_loam",
        "sandy_clay_loam", "clay_loam", "silty_clay_loam", "sandy_clay",
        "silty_clay", "clay", "unknown",
    }
    assert soilgrids_frame["porosity_m3m3"].notna().all()


def test_soilgrids_handles_an_empty_response():
    assert SoilGridsConnector.parse({"properties": {"layers": []}}, 0.0, 0.0).empty


# --------------------------------------------------------------------------
# USDA Soil Data Access
# --------------------------------------------------------------------------


@pytest.fixture
def sda_frame() -> pd.DataFrame:
    points = pd.DataFrame([{"site_id": "sda_site", "lat": 37.0, "lon": -100.5}])
    return SoilDataAccessConnector.parse(load_json("usda_sda_response.json"), points)


def test_sda_aggregates_onto_the_standard_layers(sda_frame):
    assert len(sda_frame) == 6
    assert list(sda_frame["depth_top_cm"]) == [0, 5, 15, 30, 60, 100]
    assert sda_frame["site_id"].eq("sda_site").all()


def test_sda_weights_components_by_their_percentage(sda_frame):
    """70 % Ulysses at 30 % sand, 30 % Richfield at 22 % sand -> 27.6 %."""
    assert sda_frame["sand_pct"].iloc[0] == pytest.approx(0.7 * 30.0 + 0.3 * 22.0, abs=0.01)
    assert sda_frame["clay_pct"].iloc[0] == pytest.approx(0.7 * 26.0 + 0.3 * 34.0, abs=0.01)


def test_sda_converts_conductivity_from_micrometres_per_second(sda_frame):
    """ksat_r is um/s. 9.17 um/s is 33 mm/h; read as cm/hr it would be 9 mm/h."""
    assert sda_frame["ksat_mm_h"].iloc[0] == pytest.approx(9.17 * 3.6, rel=1e-3)


def test_sda_converts_water_contents_from_percent(sda_frame):
    """wthirdbar_r is volumetric percent, not a fraction."""
    assert sda_frame["field_capacity_m3m3"].iloc[0] == pytest.approx(0.285, abs=1e-3)
    assert sda_frame["wilting_point_m3m3"].iloc[0] == pytest.approx(0.142, abs=1e-3)


def test_sda_null_salinity_is_not_read_as_zero(sda_frame):
    """A null ec_r means never measured. Treating it as 0 would mark a soil
    non-saline on no evidence, and the salinity flags depend on this."""
    # Only the 70 % component reports EC; the weighted mean must be that
    # component's value, not diluted toward zero by the component with no data.
    assert sda_frame["ece_ds_m"].iloc[0] == pytest.approx(1.8, abs=1e-6)


def test_sda_assigns_a_salinity_class(sda_frame):
    assert "salinity_class" in sda_frame.columns
    assert sda_frame["salinity_class"].iloc[0] == "non_saline"


def test_sda_handles_an_empty_response():
    points = pd.DataFrame([{"site_id": "x", "lat": 0.0, "lon": 0.0}])
    assert SoilDataAccessConnector.parse({"Table": []}, points).empty


# --------------------------------------------------------------------------
# Daymet
# --------------------------------------------------------------------------


@pytest.fixture
def daymet_frame() -> pd.DataFrame:
    connector = DaymetConnector.__new__(DaymetConnector)
    return connector._parse((FIXTURES / "daymet_point.csv").read_text(), 37.0, -100.5, "dm_site")


def test_daymet_skips_the_header_block(daymet_frame):
    assert len(daymet_frame) == 90
    assert daymet_frame["date"].iloc[0].isoformat() == "2020-01-01"


def test_daymet_converts_radiation_to_a_daily_total(daymet_frame):
    """srad is a daylight-average W/m2; FAO-56 needs MJ/m2/day, via day length."""
    assert daymet_frame["srad_mj_m2"].between(1, 45).all()


def test_daymet_derives_dewpoint_from_vapour_pressure(daymet_frame):
    assert daymet_frame["tdew_c"].notna().all()
    assert daymet_frame["tdew_c"].between(-40, 40).all()


def test_daymet_falls_back_to_hargreaves_without_wind(daymet_frame):
    """Daymet carries no wind, so Penman-Monteith cannot be applied."""
    assert daymet_frame["et0_method"].eq("hargreaves_samani").all()
    assert daymet_frame["et0_mm"].between(0, 20).all()


# --------------------------------------------------------------------------
# Open-Meteo
# --------------------------------------------------------------------------


@pytest.fixture
def open_meteo_frame() -> pd.DataFrame:
    connector = OpenMeteoConnector.__new__(OpenMeteoConnector)
    return connector._parse(load_json("open_meteo_point.json"), 37.0, -100.5, "om_site")


def test_open_meteo_parses_the_daily_block(open_meteo_frame):
    assert len(open_meteo_frame) == 90
    assert open_meteo_frame["source_id"].eq("open_meteo").all()


def test_open_meteo_converts_wind_from_ten_metres_to_two(open_meteo_frame):
    """FAO-56 log profile: u2 = u10 * 4.87 / ln(67.8*10 - 5.42) ~ 0.748 u10."""
    raw = load_json("open_meteo_point.json")["daily"]["wind_speed_10m_max"]
    expected = np.asarray(raw) * (4.87 / np.log(67.8 * 10 - 5.42))
    assert np.allclose(open_meteo_frame["wind_2m_ms"].to_numpy(), expected)
    assert (open_meteo_frame["wind_2m_ms"] < np.asarray(raw)).all()


def test_open_meteo_prefers_the_supplied_reference_et(open_meteo_frame):
    assert open_meteo_frame["et0_method"].eq("open_meteo_fao56").all()


# --------------------------------------------------------------------------
# Cross-connector
# --------------------------------------------------------------------------


def test_all_weather_connectors_agree_on_their_columns(power_frame, daymet_frame, open_meteo_frame):
    """Sites must be able to draw weather from whichever source answered."""
    core = {"site_id", "date", "source_id", "precip_mm", "tmax_c", "tmin_c",
            "et0_mm", "et0_method", "year"}
    for frame in (power_frame, daymet_frame, open_meteo_frame):
        assert core <= set(frame.columns)


def test_connectors_declare_a_licence():
    """Whether harvested rows may be redistributed is a per-source question that
    can only sensibly be recorded at ingest."""
    for connector in (NasaPowerConnector, DaymetConnector, OpenMeteoConnector,
                      SoilGridsConnector, SoilDataAccessConnector):
        assert connector.licence and connector.licence != "unknown"
        assert isinstance(connector.redistributable, bool)
        assert connector.citation


def test_connectors_resolve_their_registry_entry():
    from smml.util.http import PoliteSession

    session = PoliteSession(offline=True)
    for cls in (NasaPowerConnector, DaymetConnector, OpenMeteoConnector, SoilGridsConnector):
        entry = cls(session=session).registry_entry
        assert entry, f"{cls.short_id} is not in the registry"
        assert entry.get("base_url")
