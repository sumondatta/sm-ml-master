"""Agrometeorology: reference evapotranspiration and crop water demand.

FAO-56 (Allen et al. 1998) throughout, because that is what the agronomic
literature this project harvests reports against, and because its inputs are
exactly what the free global weather products supply.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import ArrayLike, NDArray

SOLAR_CONSTANT = 0.0820  # MJ m-2 min-1
STEFAN_BOLTZMANN = 4.903e-9  # MJ K-4 m-2 day-1


def _arr(x: ArrayLike) -> NDArray[np.float64]:
    return np.asarray(x, dtype=float)


def saturation_vapour_pressure(temp_c: ArrayLike) -> NDArray[np.float64]:
    """FAO-56 eq. 11, kPa."""
    t = _arr(temp_c)
    return 0.6108 * np.exp(17.27 * t / (t + 237.3))


def slope_vapour_pressure_curve(temp_c: ArrayLike) -> NDArray[np.float64]:
    """FAO-56 eq. 13, kPa/C."""
    t = _arr(temp_c)
    return 4098.0 * saturation_vapour_pressure(t) / (t + 237.3) ** 2


def psychrometric_constant(elevation_m: ArrayLike) -> NDArray[np.float64]:
    """FAO-56 eqs. 7-8, kPa/C."""
    z = _arr(elevation_m)
    p = 101.3 * ((293.0 - 0.0065 * z) / 293.0) ** 5.26
    return 0.000665 * p


def extraterrestrial_radiation(lat_deg: ArrayLike, doy: ArrayLike) -> NDArray[np.float64]:
    """FAO-56 eq. 21, MJ m-2 day-1."""
    phi = np.deg2rad(_arr(lat_deg))
    j = _arr(doy)
    dr = 1.0 + 0.033 * np.cos(2.0 * np.pi * j / 365.0)
    delta = 0.409 * np.sin(2.0 * np.pi * j / 365.0 - 1.39)
    x = np.clip(-np.tan(phi) * np.tan(delta), -1.0, 1.0)
    ws = np.arccos(x)
    return (
        24.0 * 60.0 / np.pi * SOLAR_CONSTANT * dr
        * (ws * np.sin(phi) * np.sin(delta) + np.cos(phi) * np.cos(delta) * np.sin(ws))
    )


def actual_vapour_pressure(
    tmax_c: ArrayLike,
    tmin_c: ArrayLike,
    rh_mean_pct: ArrayLike | None = None,
    rh_max_pct: ArrayLike | None = None,
    rh_min_pct: ArrayLike | None = None,
    tdew_c: ArrayLike | None = None,
) -> NDArray[np.float64]:
    """Actual vapour pressure (kPa), by the most accurate route the inputs allow.

    FAO-56 ranks these, best first:

    1. dewpoint (eq. 14),  ea = e0(Tdew)
    2. RHmax and RHmin (eq. 17),  ea = [e0(Tmin) RHmax + e0(Tmax) RHmin] / 200
    3. RHmean (eq. 19),  ea = RHmean/100 * [e0(Tmax) + e0(Tmin)] / 2

    Route 3 biases ET0 low by roughly 5-7 % relative to route 2 in humid
    climates, because the daily mean of a nonlinear function is not the function
    of the daily mean. Weather products differ in what they supply — gridMET has
    rmin/rmax, NASA POWER has RH2M and T2MDEW — so all three routes are kept and
    the caller passes whatever it has.
    """
    tmax, tmin = _arr(tmax_c), _arr(tmin_c)
    if tdew_c is not None:
        return saturation_vapour_pressure(tdew_c)
    if rh_max_pct is not None and rh_min_pct is not None:
        return (
            saturation_vapour_pressure(tmin) * np.clip(_arr(rh_max_pct), 1.0, 100.0)
            + saturation_vapour_pressure(tmax) * np.clip(_arr(rh_min_pct), 1.0, 100.0)
        ) / 200.0
    if rh_mean_pct is not None:
        es = (saturation_vapour_pressure(tmax) + saturation_vapour_pressure(tmin)) / 2.0
        return es * np.clip(_arr(rh_mean_pct), 1.0, 100.0) / 100.0
    raise ValueError("need one of tdew_c, (rh_max_pct, rh_min_pct), or rh_mean_pct")


def et0_penman_monteith(
    tmax_c: ArrayLike,
    tmin_c: ArrayLike,
    rs_mj_m2_day: ArrayLike,
    wind_2m_ms: ArrayLike,
    lat_deg: ArrayLike,
    elevation_m: ArrayLike,
    doy: ArrayLike,
    rh_mean_pct: ArrayLike | None = None,
    rh_max_pct: ArrayLike | None = None,
    rh_min_pct: ArrayLike | None = None,
    tdew_c: ArrayLike | None = None,
) -> NDArray[np.float64]:
    """FAO-56 reference evapotranspiration for a short grass surface, mm/day.

        ET0 = [0.408 D (Rn - G) + g 900/(T+273) u2 (es - ea)] / [D + g (1 + 0.34 u2)]

    Daily ``G`` is taken as zero, as FAO-56 recommends for daily time steps.
    Humidity is supplied as dewpoint, as an RHmax/RHmin pair, or as RHmean; see
    :func:`actual_vapour_pressure`.
    """
    tmax, tmin = _arr(tmax_c), _arr(tmin_c)
    rs, u2 = _arr(rs_mj_m2_day), _arr(wind_2m_ms)
    tmean = (tmax + tmin) / 2.0

    delta = slope_vapour_pressure_curve(tmean)
    gamma = psychrometric_constant(elevation_m)
    es = (saturation_vapour_pressure(tmax) + saturation_vapour_pressure(tmin)) / 2.0
    ea = actual_vapour_pressure(tmax, tmin, rh_mean_pct, rh_max_pct, rh_min_pct, tdew_c)
    vpd = np.maximum(es - ea, 0.0)

    ra = extraterrestrial_radiation(lat_deg, doy)
    rso = (0.75 + 2e-5 * _arr(elevation_m)) * ra
    rns = (1.0 - 0.23) * rs
    rel = np.clip(np.where(rso > 0, rs / rso, 1.0), 0.3, 1.0)
    rnl = (
        STEFAN_BOLTZMANN
        * ((tmax + 273.16) ** 4 + (tmin + 273.16) ** 4) / 2.0
        * (0.34 - 0.14 * np.sqrt(np.maximum(ea, 0.0)))
        * (1.35 * rel - 0.35)
    )
    rn = rns - rnl

    num = 0.408 * delta * rn + gamma * 900.0 / (tmean + 273.0) * u2 * vpd
    den = delta + gamma * (1.0 + 0.34 * u2)
    return np.maximum(num / den, 0.0)


def et0_hargreaves(
    tmax_c: ArrayLike, tmin_c: ArrayLike, lat_deg: ArrayLike, doy: ArrayLike
) -> NDArray[np.float64]:
    """Hargreaves-Samani ET0, mm/day — the fallback when only temperature exists.

        ET0 = 0.0023 (Tmean + 17.8) (Tmax - Tmin)^0.5 Ra / 2.45

    Needed because a large share of the harvested literature reports temperature
    and nothing else.
    """
    tmax, tmin = _arr(tmax_c), _arr(tmin_c)
    tmean = (tmax + tmin) / 2.0
    ra = extraterrestrial_radiation(lat_deg, doy)
    trange = np.maximum(tmax - tmin, 0.0)
    return np.maximum(0.0023 * (tmean + 17.8) * np.sqrt(trange) * ra / 2.45, 0.0)


def kc_curve(
    days_after_planting: ArrayLike,
    l_ini: int,
    l_dev: int,
    l_mid: int,
    l_late: int,
    kc_ini: float,
    kc_mid: float,
    kc_end: float,
) -> NDArray[np.float64]:
    """FAO-56 four-stage crop coefficient curve."""
    d = _arr(days_after_planting)
    t1, t2, t3, t4 = l_ini, l_ini + l_dev, l_ini + l_dev + l_mid, l_ini + l_dev + l_mid + l_late
    kc = np.full(d.shape, kc_end, dtype=float)
    kc = np.where(d <= t1, kc_ini, kc)
    kc = np.where((d > t1) & (d <= t2), kc_ini + (kc_mid - kc_ini) * (d - t1) / max(l_dev, 1), kc)
    kc = np.where((d > t2) & (d <= t3), kc_mid, kc)
    kc = np.where((d > t3) & (d <= t4), kc_mid + (kc_end - kc_mid) * (d - t3) / max(l_late, 1), kc)
    kc = np.where((d < 0) | (d > t4), 0.15, kc)  # bare soil outside the season
    return kc


#: FAO-56 Table 11/12 stage lengths (days) and crop coefficients, for the crops
#: that dominate the irrigated soil moisture literature.
CROP_PARAMS: dict[str, dict[str, float]] = {
    "maize":     {"l_ini": 25, "l_dev": 40, "l_mid": 45, "l_late": 30, "kc_ini": 0.30, "kc_mid": 1.20, "kc_end": 0.50, "root_max_cm": 140, "depletion_frac": 0.55},
    "cotton":    {"l_ini": 30, "l_dev": 50, "l_mid": 60, "l_late": 55, "kc_ini": 0.35, "kc_mid": 1.18, "kc_end": 0.60, "root_max_cm": 150, "depletion_frac": 0.65},
    "soybean":   {"l_ini": 20, "l_dev": 35, "l_mid": 60, "l_late": 25, "kc_ini": 0.40, "kc_mid": 1.15, "kc_end": 0.50, "root_max_cm": 130, "depletion_frac": 0.50},
    "wheat":     {"l_ini": 30, "l_dev": 140, "l_mid": 40, "l_late": 30, "kc_ini": 0.40, "kc_mid": 1.15, "kc_end": 0.40, "root_max_cm": 150, "depletion_frac": 0.55},
    "alfalfa":   {"l_ini": 10, "l_dev": 30, "l_mid": 25, "l_late": 10, "kc_ini": 0.40, "kc_mid": 1.20, "kc_end": 1.15, "root_max_cm": 200, "depletion_frac": 0.55},
    "potato":    {"l_ini": 25, "l_dev": 30, "l_mid": 45, "l_late": 30, "kc_ini": 0.50, "kc_mid": 1.15, "kc_end": 0.75, "root_max_cm": 60,  "depletion_frac": 0.35},
    "rice":      {"l_ini": 30, "l_dev": 30, "l_mid": 60, "l_late": 30, "kc_ini": 1.05, "kc_mid": 1.20, "kc_end": 0.90, "root_max_cm": 60,  "depletion_frac": 0.20},
    "sorghum":   {"l_ini": 20, "l_dev": 35, "l_mid": 40, "l_late": 30, "kc_ini": 0.30, "kc_mid": 1.10, "kc_end": 0.55, "root_max_cm": 150, "depletion_frac": 0.55},
    "sugarbeet": {"l_ini": 30, "l_dev": 45, "l_mid": 90, "l_late": 15, "kc_ini": 0.35, "kc_mid": 1.20, "kc_end": 0.70, "root_max_cm": 120, "depletion_frac": 0.55},
    "grape":     {"l_ini": 20, "l_dev": 50, "l_mid": 75, "l_late": 60, "kc_ini": 0.30, "kc_mid": 0.85, "kc_end": 0.45, "root_max_cm": 180, "depletion_frac": 0.45},
}


def root_depth_cm(days_after_planting: ArrayLike, root_max_cm: float, l_total: float,
                  root_initial_cm: float = 20.0) -> NDArray[np.float64]:
    """Root front advance — linear to maximum at 70 % of the season, then constant."""
    d = _arr(days_after_planting)
    frac = np.clip(d / max(0.7 * l_total, 1.0), 0.0, 1.0)
    depth = root_initial_cm + (root_max_cm - root_initial_cm) * frac
    return np.where(d < 0, 0.0, depth)
