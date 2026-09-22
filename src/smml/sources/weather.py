"""Weather forcing connectors.

Every site in the database needs a daily weather record covering its
observations, and the sites are scattered across every continent. That rules out
national networks as the primary source and leaves the global reanalysis and
interpolation products. Three are implemented, in the order they should be tried:

:class:`NasaPowerConnector`
    Global, free, no registration, back to 1981, and returns exactly the
    variables FAO-56 needs. The default.
:class:`DaymetConnector`
    1 km gridded North America, considerably better than a reanalysis at
    capturing local precipitation, but the continent only.
:class:`OpenMeteoConnector`
    ERA5/ERA5-Land served through a fast API with no key and generous limits.
    The fallback when POWER is throttling, and the quickest way to backfill.

All three return the same schema, so a site's weather can come from whichever is
available without the modelling code caring — except that ``source_id`` records
which, because mixing products within one site's record introduces steps that
look like real events.
"""

from __future__ import annotations

import io
import logging
from typing import Any

import numpy as np
import pandas as pd

from ..physics.agromet import et0_hargreaves, et0_penman_monteith
from .base import HarvestResult, PointQueryConnector

log = logging.getLogger(__name__)


class NasaPowerConnector(PointQueryConnector):
    """NASA POWER daily point API.

    Notes that matter in practice, from the service's own documentation:

    * ``PRECTOTCORR`` is the bias-corrected precipitation and is the one to use;
      ``PRECTOT`` is deprecated and differs materially.
    * At most 20 parameters per daily request.
    * 30 unique queries per 60 seconds per IP, then HTTP 429. The session's rate
      limiter is configured for this.
    * Radiation comes as MJ/m2/day for daily requests, which is already the unit
      FAO-56 wants.
    """

    short_id = "nasa_power"
    produces = "weather"
    licence = "public domain (NASA)"
    redistributable = True
    citation = (
        "NASA Langley Research Center (LaRC) POWER Project, "
        "https://power.larc.nasa.gov/"
    )

    BASE_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
    PARAMETERS = (
        "T2M", "T2M_MAX", "T2M_MIN", "T2MDEW", "PRECTOTCORR",
        "RH2M", "WS2M", "ALLSKY_SFC_SW_DWN", "PS",
    )
    FILL = -999.0

    def fetch_point(
        self,
        lat: float,
        lon: float,
        start: str = "19810101",
        end: str = "20241231",
        site_id: str | None = None,
        community: str = "AG",
        **kwargs: Any,
    ) -> HarvestResult:
        params = {
            "parameters": ",".join(self.PARAMETERS),
            "community": community,
            "longitude": round(float(lon), 4),
            "latitude": round(float(lat), 4),
            "start": start.replace("-", ""),
            "end": end.replace("-", ""),
            "format": "JSON",
        }
        payload = self.session.get_json(self.BASE_URL, params=params)
        frame = self._parse(payload, lat, lon, site_id)
        return HarvestResult(weather=frame)

    def _parse(self, payload: dict, lat: float, lon: float, site_id: str | None) -> pd.DataFrame:
        records = payload.get("properties", {}).get("parameter", {})
        if not records:
            return pd.DataFrame()

        frame = pd.DataFrame(records)
        frame.index = pd.to_datetime(frame.index, format="%Y%m%d")
        frame = frame.sort_index()
        # POWER uses -999 as the fill value; left in place it would silently
        # become a -999 mm rainfall day.
        frame = frame.replace(self.FILL, np.nan)

        elevation = float(
            payload.get("geometry", {}).get("coordinates", [0, 0, 0])[2]
            if len(payload.get("geometry", {}).get("coordinates", [])) > 2 else 0.0
        )

        out = pd.DataFrame({
            "site_id": site_id or f"power_{lat:.4f}_{lon:.4f}",
            "date": frame.index.date,
            "source_id": self.short_id,
            "precip_mm": frame.get("PRECTOTCORR"),
            "tmax_c": frame.get("T2M_MAX"),
            "tmin_c": frame.get("T2M_MIN"),
            "tmean_c": frame.get("T2M"),
            "tdew_c": frame.get("T2MDEW"),
            "rh_mean_pct": frame.get("RH2M"),
            "wind_2m_ms": frame.get("WS2M"),
            "srad_mj_m2": frame.get("ALLSKY_SFC_SW_DWN"),
        }).reset_index(drop=True)

        out["et0_mm"], out["et0_method"] = _compute_et0(out, lat, elevation)
        out["year"] = pd.to_datetime(out["date"]).dt.year.astype("int16")
        return out


class DaymetConnector(PointQueryConnector):
    """Daymet v4 single-pixel extraction, 1 km daily, North America 1980-present.

    Returns CSV with a header block that has to be skipped. Daymet uses a
    365-day year and omits 31 December in leap years, which is a real gap that
    must not be interpolated over silently — it is left as a missing date.
    """

    short_id = "daymet_v4"
    produces = "weather"
    licence = "public domain (ORNL DAAC)"
    redistributable = True
    citation = "Thornton et al., Daymet Version 4 R1, ORNL DAAC"

    BASE_URL = "https://daymet.ornl.gov/single-pixel/api/data"
    VARIABLES = ("tmax", "tmin", "prcp", "srad", "vp", "dayl", "swe")

    def fetch_point(
        self,
        lat: float,
        lon: float,
        start: str = "1980-01-01",
        end: str = "2024-12-31",
        site_id: str | None = None,
        **kwargs: Any,
    ) -> HarvestResult:
        params = {
            "lat": round(float(lat), 5),
            "lon": round(float(lon), 5),
            "vars": ",".join(self.VARIABLES),
            "start": start,
            "end": end,
        }
        text = self.session.get_text(self.BASE_URL, params=params)
        return HarvestResult(weather=self._parse(text, lat, lon, site_id))

    def _parse(self, text: str, lat: float, lon: float, site_id: str | None) -> pd.DataFrame:
        lines = text.splitlines()
        header = next((i for i, line in enumerate(lines) if line.startswith("year,")), None)
        if header is None:
            return pd.DataFrame()
        elevation = 0.0
        for line in lines[:header]:
            if "elevation" in line.lower():
                digits = "".join(c for c in line if c.isdigit() or c == ".")
                elevation = float(digits) if digits else 0.0
        frame = pd.read_csv(io.StringIO("\n".join(lines[header:])))
        frame.columns = [c.split(" ")[0].strip() for c in frame.columns]

        dates = pd.to_datetime(frame["year"].astype(int).astype(str), format="%Y") + pd.to_timedelta(
            frame["yday"].astype(int) - 1, unit="D"
        )
        # Daymet reports radiation as a daylight-average W/m2; converting to the
        # daily total MJ/m2 that FAO-56 expects needs the day length in seconds.
        srad_mj = frame["srad"] * frame["dayl"] / 1e6

        out = pd.DataFrame({
            "site_id": site_id or f"daymet_{lat:.4f}_{lon:.4f}",
            "date": dates.dt.date,
            "source_id": self.short_id,
            "precip_mm": frame["prcp"],
            "tmax_c": frame["tmax"],
            "tmin_c": frame["tmin"],
            "tmean_c": (frame["tmax"] + frame["tmin"]) / 2.0,
            "srad_mj_m2": srad_mj,
            "snow_mm": frame.get("swe"),
        })
        # Daymet gives vapour pressure in Pa; convert to a dewpoint so the ET0
        # routine can use its most accurate humidity path.
        if "vp" in frame.columns:
            ea_kpa = frame["vp"] / 1000.0
            with np.errstate(invalid="ignore", divide="ignore"):
                z = np.log(np.maximum(ea_kpa, 1e-6) / 0.6108)
                out["tdew_c"] = z * 237.3 / (17.27 - z)
        out["wind_2m_ms"] = np.nan  # Daymet has no wind; ET0 falls back below.
        out["et0_mm"], out["et0_method"] = _compute_et0(out, lat, elevation)
        out["year"] = pd.to_datetime(out["date"]).dt.year.astype("int16")
        return out


class OpenMeteoConnector(PointQueryConnector):
    """Open-Meteo historical archive: ERA5 / ERA5-Land, global, no key.

    The pragmatic default when NASA POWER is throttling or when a quick global
    backfill is wanted. Serves JSON, accepts a date range in one request, and
    provides its own FAO-56 reference ET, which is used when present in
    preference to recomputing.
    """

    short_id = "open_meteo"
    produces = "weather"
    licence = "CC-BY-4.0 (Open-Meteo); underlying ERA5 is Copernicus licensed"
    redistributable = True
    citation = "Zippenfenig, P. (2023). Open-Meteo.com Weather API"

    BASE_URL = "https://archive-api.open-meteo.com/v1/archive"
    DAILY_VARIABLES = (
        "temperature_2m_max", "temperature_2m_min", "temperature_2m_mean",
        "precipitation_sum", "shortwave_radiation_sum",
        "wind_speed_10m_max", "et0_fao_evapotranspiration",
        "dew_point_2m_mean", "relative_humidity_2m_mean",
    )

    def fetch_point(
        self,
        lat: float,
        lon: float,
        start: str = "1981-01-01",
        end: str = "2024-12-31",
        site_id: str | None = None,
        **kwargs: Any,
    ) -> HarvestResult:
        params = {
            "latitude": round(float(lat), 4),
            "longitude": round(float(lon), 4),
            "start_date": start,
            "end_date": end,
            "daily": ",".join(self.DAILY_VARIABLES),
            "timezone": "UTC",
        }
        payload = self.session.get_json(self.BASE_URL, params=params)
        return HarvestResult(weather=self._parse(payload, lat, lon, site_id))

    def _parse(self, payload: dict, lat: float, lon: float, site_id: str | None) -> pd.DataFrame:
        daily = payload.get("daily", {})
        if not daily:
            return pd.DataFrame()
        frame = pd.DataFrame(daily)
        elevation = float(payload.get("elevation", 0.0) or 0.0)

        # 10 m wind to 2 m by the FAO-56 logarithmic profile.
        wind10 = frame.get("wind_speed_10m_max")
        wind2 = wind10 * (4.87 / np.log(67.8 * 10 - 5.42)) if wind10 is not None else np.nan

        out = pd.DataFrame({
            "site_id": site_id or f"openmeteo_{lat:.4f}_{lon:.4f}",
            "date": pd.to_datetime(frame["time"]).dt.date,
            "source_id": self.short_id,
            "precip_mm": frame.get("precipitation_sum"),
            "tmax_c": frame.get("temperature_2m_max"),
            "tmin_c": frame.get("temperature_2m_min"),
            "tmean_c": frame.get("temperature_2m_mean"),
            "tdew_c": frame.get("dew_point_2m_mean"),
            "rh_mean_pct": frame.get("relative_humidity_2m_mean"),
            "wind_2m_ms": wind2,
            "srad_mj_m2": frame.get("shortwave_radiation_sum"),
        })
        supplied = frame.get("et0_fao_evapotranspiration")
        if supplied is not None and supplied.notna().any():
            out["et0_mm"] = supplied
            out["et0_method"] = "open_meteo_fao56"
        else:
            out["et0_mm"], out["et0_method"] = _compute_et0(out, lat, elevation)
        out["year"] = pd.to_datetime(out["date"]).dt.year.astype("int16")
        return out


def _compute_et0(frame: pd.DataFrame, lat: float, elevation_m: float) -> tuple[pd.Series, pd.Series]:
    """Reference ET by the best method the available columns support.

    Penman-Monteith where radiation, wind and a humidity measure are all present;
    Hargreaves-Samani on temperature alone otherwise. Which one was used is
    returned alongside, because the two are not interchangeable — Hargreaves can
    differ from Penman-Monteith by 20 % in windy or humid conditions — and a
    model trained across a mixture needs to know.
    """
    doy = pd.to_datetime(frame["date"]).dt.dayofyear.to_numpy()
    tmax = frame["tmax_c"].to_numpy(dtype=float)
    tmin = frame["tmin_c"].to_numpy(dtype=float)

    has_radiation = "srad_mj_m2" in frame and frame["srad_mj_m2"].notna().any()
    has_wind = "wind_2m_ms" in frame and frame["wind_2m_ms"].notna().any()
    humidity: dict[str, Any] = {}
    if "tdew_c" in frame and frame["tdew_c"].notna().any():
        humidity = {"tdew_c": frame["tdew_c"].to_numpy(dtype=float)}
    elif "rh_mean_pct" in frame and frame["rh_mean_pct"].notna().any():
        humidity = {"rh_mean_pct": frame["rh_mean_pct"].to_numpy(dtype=float)}

    if has_radiation and has_wind and humidity:
        et0 = et0_penman_monteith(
            tmax_c=tmax, tmin_c=tmin,
            rs_mj_m2_day=frame["srad_mj_m2"].to_numpy(dtype=float),
            wind_2m_ms=frame["wind_2m_ms"].to_numpy(dtype=float),
            lat_deg=lat, elevation_m=elevation_m, doy=doy, **humidity,
        )
        method = "fao56_penman_monteith"
    else:
        et0 = et0_hargreaves(tmax, tmin, lat, doy)
        method = "hargreaves_samani"
    return pd.Series(et0, index=frame.index), pd.Series(method, index=frame.index)


WEATHER_CONNECTORS = {
    "nasa_power": NasaPowerConnector,
    "daymet_v4": DaymetConnector,
    "open_meteo": OpenMeteoConnector,
}
