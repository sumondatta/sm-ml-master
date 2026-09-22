"""Deterministic identifiers.

Every id in the database is a pure function of the thing it names, so that
re-running the harvest produces byte-identical keys and ingestion is idempotent.
No counters, no UUID4, no timestamps.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata

# ~11 m at the equator. Fine enough to separate distinct plots within a field
# station, coarse enough that the same station reported by two networks with
# slightly different rounding still collides into one id.
COORD_DECIMALS = 4


def _h(*parts: object, n: int = 16) -> str:
    payload = "\x1f".join("" if p is None else str(p) for p in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:n]


def slugify(value: str, maxlen: int = 48) -> str:
    """ASCII, lowercase, underscore-separated. Stable across platforms."""
    value = unicodedata.normalize("NFKD", str(value))
    value = value.encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").lower()
    value = re.sub(r"_+", "_", value)
    return value[:maxlen] or "na"


def snap_coord(value: float, decimals: int = COORD_DECIMALS) -> float:
    """Round a coordinate to the grid used for identity comparisons."""
    return round(float(value) + 0.0, decimals)


def site_id(network: str, station: str, lat: float, lon: float) -> str:
    """Identity of a measurement location.

    Includes the coordinates, not just the station name, because station names
    are reused across networks and are sometimes renamed mid-record while the
    coordinates stay put.
    """
    return f"{slugify(network, 24)}__{slugify(station, 32)}__{_h(snap_coord(lat), snap_coord(lon), n=8)}"


def sensor_id(site: str, variable: str, depth_top_cm: float, depth_bottom_cm: float, instrument: str = "") -> str:
    """Identity of one sensor: a site, a variable, a depth interval, an instrument."""
    return f"{site}__{slugify(variable, 16)}__{depth_top_cm:g}_{depth_bottom_cm:g}__{_h(slugify(instrument), n=6)}"


def source_id(name: str, version: str = "") -> str:
    return f"{slugify(name, 32)}{('@' + slugify(version, 16)) if version else ''}"


def study_id(doi: str | None, title: str | None = None) -> str:
    """Identity of a literature item. DOI when present, else a title hash."""
    if doi:
        return "doi:" + doi.strip().lower().removeprefix("https://doi.org/").removeprefix("doi:")
    return "ttl:" + _h(slugify(title or "", 200), n=16)


def series_id(study: str, figure: str, panel: str, label: str) -> str:
    """Identity of one digitized curve inside one figure panel."""
    return f"{_h(study, n=10)}__{slugify(figure, 12)}__{slugify(panel, 8)}__{slugify(label, 24)}"


def observation_key(sensor: str, timestamp_utc: str) -> str:
    """Primary key of a fact row — used to drop duplicate re-ingests."""
    return _h(sensor, timestamp_utc, n=20)


def file_fingerprint(path_or_bytes) -> str:
    """SHA-256 of a downloaded artifact, for the content-addressed raw cache."""
    h = hashlib.sha256()
    if isinstance(path_or_bytes, (bytes, bytearray)):
        h.update(path_or_bytes)
    else:
        with open(path_or_bytes, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
    return h.hexdigest()
