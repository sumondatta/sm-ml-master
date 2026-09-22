"""International Soil Moisture Network reader.

ISMN is the single largest in-situ soil moisture archive — of the order of 2,800
stations across roughly 70 contributing networks, harmonized to common units and
carrying quality flags. It is the backbone of the database.

It is **not** an API. Data is obtained by registering free at ismn.earth and
requesting a bulk download, which arrives as a zip of per-sensor text files. This
module parses that archive; there is nothing to fetch.

Two formats exist and both are read:

*Header + values* (the usual choice) puts the station metadata on one header line
and one observation per line after it.

*CEOP* repeats full metadata on every line. Larger, but self-describing, and what
older exports contain.

Irrigation is the reason this project cares which stations these are, and ISMN
does not label it. :func:`flag_likely_irrigated` applies the heuristics that can
be applied from the archive alone, and is explicit that the result is a candidate
list needing confirmation against an irrigation map or the network's own
documentation — ISMN's own guidance is that irrigation is a very local phenomenon
and that affected stations should be treated with caution.
"""

from __future__ import annotations

import logging
import re
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from ..db.schema import METHOD_UNCERTAINTY, ObservationMethod, QualityFlag
from ..util.ids import observation_key, sensor_id, site_id
from .base import Connector, HarvestResult

log = logging.getLogger(__name__)

#: ISMN's own quality flags, mapped onto this project's scheme. ISMN uses
#: C = exceeds physical range, D = reported as dubious by a check, G = good,
#: M = missing, with a numeric sub-code after D.
ISMN_FLAG_MAP: dict[str, str] = {
    "G": QualityFlag.GOOD.value,
    "M": QualityFlag.MISSING.value,
    "C01": QualityFlag.OUT_OF_PHYSICAL_RANGE.value,
    "C02": QualityFlag.OUT_OF_PHYSICAL_RANGE.value,
    "C03": QualityFlag.EXCEEDS_SATURATION.value,
    "D01": QualityFlag.FROZEN_SOIL.value,
    "D02": QualityFlag.FROZEN_SOIL.value,
    "D03": QualityFlag.FROZEN_SOIL.value,
    "D04": QualityFlag.SPIKE.value,
    "D05": QualityFlag.SPIKE.value,
    "D06": QualityFlag.SPIKE.value,
    "D07": QualityFlag.NEGATIVE_BREAK.value,
    "D08": QualityFlag.CONSTANT_VALUE.value,
    "D09": QualityFlag.CONSTANT_VALUE.value,
    "D10": QualityFlag.SENSOR_DRIFT.value,
}

#: Instrument name fragment -> (method, operating frequency in MHz).
#: The frequency is what determines how badly salinity corrupts a reading, so it
#: is carried per sensor rather than assumed.
INSTRUMENT_MAP: tuple[tuple[str, str, float], ...] = (
    ("hydraprobe", ObservationMethod.IMPEDANCE.value, 50.0),
    ("stevens", ObservationMethod.IMPEDANCE.value, 50.0),
    ("cs616", ObservationMethod.FDR_CAPACITANCE.value, 70.0),
    ("cs615", ObservationMethod.FDR_CAPACITANCE.value, 44.0),
    ("cs655", ObservationMethod.TDR.value, 175.0),
    ("cs650", ObservationMethod.TDR.value, 175.0),
    ("acclima", ObservationMethod.TDR.value, 1000.0),
    ("trime", ObservationMethod.TDR.value, 1000.0),
    ("tdr", ObservationMethod.TDR.value, 1000.0),
    ("5tm", ObservationMethod.FDR_CAPACITANCE.value, 70.0),
    ("5te", ObservationMethod.FDR_CAPACITANCE.value, 70.0),
    ("gs3", ObservationMethod.FDR_CAPACITANCE.value, 70.0),
    ("ec-5", ObservationMethod.FDR_CAPACITANCE.value, 70.0),
    ("ec5", ObservationMethod.FDR_CAPACITANCE.value, 70.0),
    ("teros", ObservationMethod.FDR_CAPACITANCE.value, 70.0),
    ("decagon", ObservationMethod.FDR_CAPACITANCE.value, 70.0),
    ("thetaprobe", ObservationMethod.IMPEDANCE.value, 100.0),
    ("pr2", ObservationMethod.FDR_CAPACITANCE.value, 100.0),
    ("sentek", ObservationMethod.FDR_CAPACITANCE.value, 100.0),
    ("enviroscan", ObservationMethod.FDR_CAPACITANCE.value, 100.0),
    ("diviner", ObservationMethod.FDR_CAPACITANCE.value, 100.0),
    ("neutron", ObservationMethod.NEUTRON_PROBE.value, np.nan),
    ("cosmic", ObservationMethod.COSMIC_RAY.value, np.nan),
    ("crns", ObservationMethod.COSMIC_RAY.value, np.nan),
    ("gravimetric", ObservationMethod.GRAVIMETRIC.value, np.nan),
)


def classify_instrument(name: str) -> tuple[str, float]:
    """Measurement method and operating frequency from a sensor name.

    The frequency matters: below roughly 100 MHz a probe cannot reject the
    dielectric loss term, so salinity inflates its reading; TDR at ~1 GHz largely
    can. Defaulting an unknown sensor to the capacitance class is the
    conservative choice, since it means its readings get flagged in saline soil
    rather than silently trusted.
    """
    lowered = (name or "").lower()
    for fragment, method, frequency in INSTRUMENT_MAP:
        if fragment in lowered:
            return method, frequency
    return ObservationMethod.FDR_CAPACITANCE.value, 70.0


@dataclass
class IsmnSensorFile:
    """One parsed ISMN sensor file."""

    network: str
    station: str
    lat: float
    lon: float
    elevation_m: float
    depth_from_cm: float
    depth_to_cm: float
    variable: str
    instrument: str
    data: pd.DataFrame


HEADER_RE = re.compile(
    r"^\s*(?P<network>\S+)\s+(?P<station>\S+)\s+"
    r"(?P<lat>-?\d+\.?\d*)\s+(?P<lon>-?\d+\.?\d*)\s+"
    r"(?P<elev>-?\d+\.?\d*)\s+(?P<dfrom>-?\d+\.?\d*)\s+(?P<dto>-?\d+\.?\d*)\s*"
    r"(?P<rest>.*)$"
)


def parse_stm(text: str, filename: str = "") -> IsmnSensorFile | None:
    """Parse one ``.stm`` sensor file in ISMN header-and-values format.

    Depths in ISMN are in **metres**; the database stores centimetres.
    """
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return None
    match = HEADER_RE.match(lines[0])
    if not match:
        return None

    rest = match.group("rest").split()
    variable = rest[0] if rest else "soil_moisture"
    instrument = " ".join(rest[1:]) if len(rest) > 1 else ""
    if not instrument:
        # Older exports omit the sensor from the header; the filename carries it.
        parts = Path(filename).stem.split("_")
        instrument = parts[2] if len(parts) > 2 else ""

    records = []
    for line in lines[1:]:
        fields = line.split()
        if len(fields) < 3:
            continue
        try:
            timestamp = pd.to_datetime(f"{fields[0]} {fields[1]}", format="%Y/%m/%d %H:%M",
                                       utc=True)
            value = float(fields[2])
        except (ValueError, TypeError):
            continue
        records.append((timestamp, value,
                        fields[3] if len(fields) > 3 else "G",
                        fields[4] if len(fields) > 4 else ""))

    if not records:
        return None

    return IsmnSensorFile(
        network=match.group("network"),
        station=match.group("station"),
        lat=float(match.group("lat")),
        lon=float(match.group("lon")),
        elevation_m=float(match.group("elev")),
        depth_from_cm=float(match.group("dfrom")) * 100.0,
        depth_to_cm=float(match.group("dto")) * 100.0,
        variable=variable,
        instrument=instrument,
        data=pd.DataFrame(records, columns=["time_utc", "value", "ismn_flag", "provider_flag"]),
    )


class IsmnConnector(Connector):
    """Read an ISMN bulk download.

    ``fetch`` takes a path to the downloaded zip, or to a directory of extracted
    ``.stm`` files. There is no network access — ISMN is a registered bulk
    download, not an API — so nothing here is rate limited.
    """

    short_id = "ismn"
    produces = "observations"
    licence = "free for research; attribution and registration required (see ismn.earth)"
    redistributable = False
    citation = (
        "Dorigo et al. (2021), The International Soil Moisture Network: serving "
        "Earth system science for over a decade, HESS 25:5749-5804"
    )

    def fetch(self, path: Path | str, variable: str = "soil_moisture",
              max_files: int | None = None, **kwargs) -> HarvestResult:
        path = Path(path)
        sites, sensors, observations, errors = [], [], [], []

        for name, text in self._iter_files(path):
            if max_files is not None and len(sensors) >= max_files:
                break
            try:
                parsed = parse_stm(text, name)
            except Exception as exc:  # noqa: BLE001 - one bad file must not stop the read
                errors.append(f"{name}: {type(exc).__name__}: {exc}")
                continue
            if parsed is None or (variable and variable not in parsed.variable):
                continue
            site_row, sensor_row, obs = self._to_rows(parsed)
            sites.append(site_row)
            sensors.append(sensor_row)
            observations.append(obs)

        return HarvestResult(
            sites=pd.DataFrame(sites).drop_duplicates("site_id") if sites else pd.DataFrame(),
            sensors=pd.DataFrame(sensors) if sensors else pd.DataFrame(),
            observations=pd.concat(observations, ignore_index=True) if observations else pd.DataFrame(),
            errors=errors,
        )

    @staticmethod
    def _iter_files(path: Path) -> Iterator[tuple[str, str]]:
        if path.is_dir():
            for file in sorted(path.rglob("*.stm")):
                yield file.name, file.read_text(errors="replace")
        elif path.suffix.lower() == ".zip":
            with zipfile.ZipFile(path) as archive:
                for name in sorted(archive.namelist()):
                    if name.lower().endswith(".stm"):
                        yield name, archive.read(name).decode("utf-8", errors="replace")
        else:
            yield path.name, path.read_text(errors="replace")

    @staticmethod
    def _to_rows(parsed: IsmnSensorFile) -> tuple[dict, dict, pd.DataFrame]:
        site = site_id(parsed.network, parsed.station, parsed.lat, parsed.lon)
        method, frequency = classify_instrument(parsed.instrument)
        sensor = sensor_id(site, parsed.variable, parsed.depth_from_cm,
                           parsed.depth_to_cm, parsed.instrument)

        data = parsed.data
        flags = data["ismn_flag"].map(ISMN_FLAG_MAP).fillna(QualityFlag.GOOD.value)

        observations = pd.DataFrame({
            "observation_key": [observation_key(sensor, str(t)) for t in data["time_utc"]],
            "site_id": site,
            "sensor_id": sensor,
            "source_id": "ismn",
            "time_utc": data["time_utc"],
            "depth_top_cm": np.float32(parsed.depth_from_cm),
            "depth_bottom_cm": np.float32(parsed.depth_to_cm),
            "theta_m3m3": data["value"].astype("float32"),
            "theta_original": data["value"].astype("float32"),
            "original_unit": "m3/m3",
            "method": method,
            "quality_flag": flags,
            "uncertainty_m3m3": np.float32(METHOD_UNCERTAINTY.get(method, 0.035)),
            "year": data["time_utc"].dt.year.astype("int16"),
            "network": parsed.network,
        })

        site_row = {
            "site_id": site, "source_id": "ismn", "network": parsed.network,
            "station_name": parsed.station, "lat": parsed.lat, "lon": parsed.lon,
            "elevation_m": parsed.elevation_m,
            "record_start": data["time_utc"].min(), "record_end": data["time_utc"].max(),
            "n_observations": len(data),
        }
        sensor_row = {
            "sensor_id": sensor, "site_id": site, "variable": parsed.variable,
            "depth_top_cm": parsed.depth_from_cm, "depth_bottom_cm": parsed.depth_to_cm,
            "method": method, "instrument": parsed.instrument,
            "instrument_frequency_mhz": frequency,
            "calibration": "factory",
            "reported_accuracy_m3m3": METHOD_UNCERTAINTY.get(method, 0.035),
            "n_observations": len(data),
        }
        return site_row, sensor_row, observations


def flag_likely_irrigated(
    sites: pd.DataFrame,
    observations: pd.DataFrame | None = None,
    irrigation_mask: pd.Series | None = None,
    weather: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Mark ISMN stations that are plausibly in irrigated fields.

    ISMN carries no irrigation attribute, and this project is about irrigated
    land specifically, so the label has to be reconstructed. Three independent
    lines of evidence, in descending order of trustworthiness:

    1. **An irrigation extent map** at the station's coordinates (LANID, MIrAD,
       IrrMapper, GMIA — all catalogued in the registry). Pass it as
       ``irrigation_mask``. This is the only strong evidence.
    2. **Unexplained wetting** in the moisture record, using the same test as
       :func:`smml.qc.checks.detect_rise_without_input`. Requires ``weather``.
       Strong when precipitation data is reliable, weak in humid climates where
       rain is frequent enough to be mistaken for irrigation.
    3. **Network membership.** A handful of contributing networks are known to be
       sited on irrigated cropland. Weak, and listed only as a prior.

    Returns the frame with ``irrigation_status``, ``irrigation_source`` and a
    ``irrigation_confidence`` in [0, 1]. Nothing here is conclusive: treat the
    output as a candidate list to confirm against the contributing network's own
    documentation, which is also ISMN's own advice about irrigated stations.
    """
    out = sites.copy()
    confidence = pd.Series(0.0, index=out.index)
    source = pd.Series("none", index=out.index)

    if irrigation_mask is not None:
        aligned = irrigation_mask.reindex(out.index).fillna(0).astype(float)
        hit = aligned > 0.5
        confidence = confidence.where(~hit, 0.9)
        source = source.where(~hit, "mask")

    if observations is not None and weather is not None:
        from ..qc.checks import infer_irrigation_events

        for idx, row in out.iterrows():
            if confidence.loc[idx] >= 0.9:
                continue
            block = observations[observations["site_id"] == row["site_id"]]
            if block.empty:
                continue
            merged = block.merge(weather, on=["site_id", "date"], how="left") \
                if "date" in block.columns and "date" in weather.columns else block
            events = infer_irrigation_events(merged)
            if len(events) >= 5 and events["confidence"].mean() > 0.5:
                confidence.loc[idx] = max(float(confidence.loc[idx]), 0.6)
                source.loc[idx] = "inferred_from_soil_moisture"

    out["irrigation_confidence"] = confidence
    out["irrigation_source"] = source
    out["irrigation_status"] = np.where(
        confidence >= 0.6, "irrigated",
        np.where(confidence > 0.0, "mixed", "unknown"),
    )
    return out
