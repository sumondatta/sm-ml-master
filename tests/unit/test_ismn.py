"""ISMN reader tests, against files written in the archive's documented format."""

from __future__ import annotations

import zipfile

import numpy as np
import pandas as pd
import pytest

from smml.db.schema import QualityFlag
from smml.sources.ismn import (
    IsmnConnector,
    classify_instrument,
    flag_likely_irrigated,
    parse_stm,
)

# Header: network station lat lon elevation depth_from depth_to variable sensor.
# Depths are in METRES in ISMN and centimetres in this database.
STM = """SCAN            2110-Adams-Ranch     34.25500  -105.41700   1620.00  0.05080  0.05080 soil_moisture Hydraprobe-II
2015/01/01 00:00 0.1520 G
2015/01/01 01:00 0.1518 G
2015/01/01 02:00 0.1515 G
2015/01/01 03:00 -0.9990 M
2015/01/01 04:00 0.9500 C01
2015/01/01 05:00 0.1502 D06
2015/01/01 06:00 0.1500 G
"""

STM_DEEP = """SCAN            2110-Adams-Ranch     34.25500  -105.41700   1620.00  0.50800  0.50800 soil_moisture Hydraprobe-II
2015/01/01 00:00 0.2210 G
2015/01/01 01:00 0.2209 G
2015/01/01 02:00 0.2208 G
"""


@pytest.fixture
def parsed():
    return parse_stm(STM, "SCAN_2110-Adams-Ranch_Hydraprobe-II_0.050800_0.050800_2015.stm")


def test_header_is_parsed(parsed):
    assert parsed.network == "SCAN"
    assert parsed.station == "2110-Adams-Ranch"
    assert parsed.lat == pytest.approx(34.255)
    assert parsed.lon == pytest.approx(-105.417)
    assert parsed.elevation_m == pytest.approx(1620.0)
    assert parsed.variable == "soil_moisture"
    assert parsed.instrument == "Hydraprobe-II"


def test_depths_are_converted_from_metres_to_centimetres(parsed):
    """ISMN reports depth in metres; storing 0.0508 as centimetres would put a
    5 cm sensor at half a millimetre."""
    assert parsed.depth_from_cm == pytest.approx(5.08)
    assert parsed.depth_to_cm == pytest.approx(5.08)


def test_all_observations_are_read(parsed):
    assert len(parsed.data) == 7
    assert parsed.data["time_utc"].dt.tz is not None


def test_parse_returns_none_on_a_file_without_a_header():
    assert parse_stm("not a header line\nnor this\n") is None


def test_parse_returns_none_on_an_empty_file():
    assert parse_stm("") is None


def test_malformed_rows_are_skipped_not_fatal():
    text = STM + "garbage line\n2015/01/01 07:00 notanumber G\n2015/01/01 08:00 0.1490 G\n"
    result = parse_stm(text)
    assert len(result.data) == 8  # the seven good rows plus the last valid one


@pytest.mark.parametrize(
    ("name", "method", "frequency"),
    [
        ("Hydraprobe II", "impedance", 50.0),
        ("CS616", "fdr_capacitance", 70.0),
        ("CS655", "tdr", 175.0),
        ("Acclima TDR-315", "tdr", 1000.0),
        ("Decagon 5TE", "fdr_capacitance", 70.0),
        ("Sentek EnviroSCAN", "fdr_capacitance", 100.0),
        ("neutron probe", "neutron_probe", None),
        ("CRNS", "cosmic_ray_neutron", None),
    ],
)
def test_instrument_classification(name, method, frequency):
    got_method, got_frequency = classify_instrument(name)
    assert got_method == method
    if frequency is None:
        assert np.isnan(got_frequency)
    else:
        assert got_frequency == frequency


def test_unknown_instrument_defaults_to_the_vulnerable_class():
    """Unknown sensors default to low-frequency capacitance, so they get flagged
    in saline soil rather than silently trusted."""
    method, frequency = classify_instrument("Mystery Probe 9000")
    assert method == "fdr_capacitance"
    assert frequency < 150


def _write_archive(tmp_path, as_zip: bool):
    if as_zip:
        path = tmp_path / "ismn.zip"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("SCAN/a_0.05.stm", STM)
            archive.writestr("SCAN/b_0.50.stm", STM_DEEP)
        return path
    directory = tmp_path / "extracted" / "SCAN"
    directory.mkdir(parents=True)
    (directory / "a_0.05.stm").write_text(STM)
    (directory / "b_0.50.stm").write_text(STM_DEEP)
    return directory.parent


@pytest.mark.parametrize("as_zip", [True, False])
def test_connector_reads_a_zip_or_a_directory(tmp_path, as_zip):
    result = IsmnConnector().fetch(_write_archive(tmp_path, as_zip))
    assert len(result.sites) == 1, "both sensors belong to one station"
    assert len(result.sensors) == 2
    assert len(result.observations) == 10
    assert not result.errors


def test_connector_output_matches_the_schema(tmp_path):
    from smml.db.schema import OBSERVATION_SCHEMA, SENSOR_SCHEMA, SITE_SCHEMA

    result = IsmnConnector().fetch(_write_archive(tmp_path, True))
    assert set(result.observations.columns) <= {f.name for f in OBSERVATION_SCHEMA}
    assert set(result.sensors.columns) <= {f.name for f in SENSOR_SCHEMA}
    assert set(result.sites.columns) <= {f.name for f in SITE_SCHEMA}


def test_connector_translates_ismn_quality_flags(tmp_path):
    result = IsmnConnector().fetch(_write_archive(tmp_path, True))
    flags = set(result.observations["quality_flag"])
    assert QualityFlag.MISSING.value in flags
    assert QualityFlag.OUT_OF_PHYSICAL_RANGE.value in flags
    assert QualityFlag.SPIKE.value in flags
    assert QualityFlag.GOOD.value in flags


def test_connector_assigns_the_sensor_frequency(tmp_path):
    """Needed downstream: it is what decides whether salinity corrupts a reading."""
    result = IsmnConnector().fetch(_write_archive(tmp_path, True))
    assert result.sensors["instrument_frequency_mhz"].eq(50.0).all()


def test_observation_keys_are_unique_and_stable(tmp_path):
    archive = _write_archive(tmp_path, True)
    first = IsmnConnector().fetch(archive).observations
    second = IsmnConnector().fetch(archive).observations
    assert first["observation_key"].is_unique
    assert list(first["observation_key"]) == list(second["observation_key"])


def test_two_depths_at_one_station_get_different_sensor_ids(tmp_path):
    result = IsmnConnector().fetch(_write_archive(tmp_path, True))
    assert result.sensors["sensor_id"].nunique() == 2
    assert result.sensors["site_id"].nunique() == 1
    assert sorted(result.sensors["depth_top_cm"].round(2)) == [5.08, 50.8]


def test_irrigation_flagging_trusts_a_mask_over_nothing():
    sites = pd.DataFrame({"site_id": ["a", "b"], "lat": [0.0, 1.0], "lon": [0.0, 1.0]})
    mask = pd.Series([1.0, 0.0])
    out = flag_likely_irrigated(sites, irrigation_mask=mask)
    assert out.loc[0, "irrigation_status"] == "irrigated"
    assert out.loc[0, "irrigation_source"] == "mask"
    assert out.loc[0, "irrigation_confidence"] == pytest.approx(0.9)
    assert out.loc[1, "irrigation_status"] == "unknown"


def test_irrigation_flagging_defaults_to_unknown():
    """ISMN carries no irrigation attribute; absent evidence the answer is unknown,
    not rainfed."""
    sites = pd.DataFrame({"site_id": ["a"], "lat": [0.0], "lon": [0.0]})
    out = flag_likely_irrigated(sites)
    assert out.loc[0, "irrigation_status"] == "unknown"
    assert out.loc[0, "irrigation_confidence"] == 0.0
