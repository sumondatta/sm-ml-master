"""A multi-layer soil water balance for generating physically-consistent synthetic fields.

Why a simulator lives in a data-harvesting project: the harvest is slow, gated by
network access and by what other people chose to publish, but the modelling and
tuning code has to be correct *before* it is pointed at real data. This module
produces multi-depth soil moisture series that obey conservation of mass, respond
to weather and irrigation with the right lags, and carry realistic sensor
artefacts — so the full pipeline (features, spatiotemporal cross-validation,
hyperparameter search, evaluation) can be exercised and falsified end to end.

It is deliberately a *tipping-bucket cascade* rather than a Richards solver. The
cascade reproduces the behaviour that matters for a learning model — fast
wetting, slow asymmetric drydown, depth-increasing lag and damping, capped
infiltration, deep percolation — at a cost that allows thousands of site-years,
and without pretending to a physical fidelity that the harvested data could not
resolve anyway.

The generated fields are *not* a substitute for real observations and are never
mixed into the harvested database. They exist to test code.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .agromet import CROP_PARAMS, et0_penman_monteith, kc_curve, root_depth_cm
from .dielectric import BOUND_WATER_PER_CLAY, clay_bias, salinity_bias_risk
from .water import (
    STANDARD_LAYERS_CM,
    degree_of_saturation,
    saxton_rawls,
    usda_texture_class,
)


@dataclass
class SiteSpec:
    """Everything static about one synthetic field."""

    site_id: str
    lat: float
    lon: float
    elevation_m: float
    sand_pct: float
    clay_pct: float
    om_pct: float = 2.0
    ece_ds_m: float = 0.5
    crop: str = "maize"
    irrigation_method: str = "center_pivot"
    sensor_frequency_mhz: float = 70.0
    sensor_noise_sd: float = 0.008
    sensor_bias: float = 0.0
    planting_doy: int = 120
    # Climate character, used to drive the stochastic weather generator.
    mean_annual_temp_c: float = 14.0
    temp_amplitude_c: float = 12.0
    annual_precip_mm: float = 550.0
    wet_day_fraction: float = 0.22
    aridity: float = 1.0

    @property
    def silt_pct(self) -> float:
        return max(0.0, 100.0 - self.sand_pct - self.clay_pct)


@dataclass
class SoilColumn:
    """Layer geometry and hydraulic properties derived from texture."""

    layers_cm: tuple[tuple[float, float], ...] = STANDARD_LAYERS_CM
    theta_sat: np.ndarray = field(default_factory=lambda: np.array([]))
    theta_fc: np.ndarray = field(default_factory=lambda: np.array([]))
    theta_wp: np.ndarray = field(default_factory=lambda: np.array([]))
    ksat_mm_day: np.ndarray = field(default_factory=lambda: np.array([]))
    thickness_mm: np.ndarray = field(default_factory=lambda: np.array([]))

    @classmethod
    def from_texture(
        cls,
        sand_pct: float,
        clay_pct: float,
        om_pct: float = 2.0,
        layers_cm: tuple[tuple[float, float], ...] = STANDARD_LAYERS_CM,
        rng: np.random.Generator | None = None,
    ) -> SoilColumn:
        """Build a layered column, letting texture drift with depth.

        Real profiles are not uniform: clay usually increases and organic matter
        decreases downward. Imposing that drift matters, because a model trained
        on columns with depth-invariant properties learns a depth signal that
        does not exist in the field.
        """
        rng = rng or np.random.default_rng(0)
        n = len(layers_cm)
        mid = np.array([(t + b) / 2 for t, b in layers_cm])
        clay_prof = np.clip(clay_pct * (1.0 + 0.004 * (mid - mid[0])), 1.0, 70.0)
        sand_prof = np.clip(sand_pct * (1.0 - 0.002 * (mid - mid[0])), 1.0, 95.0)
        over = (clay_prof + sand_prof) > 98.0
        sand_prof = np.where(over, 98.0 - clay_prof, sand_prof)
        om_prof = np.clip(om_pct * np.exp(-mid / 60.0), 0.05, 12.0)

        sr = saxton_rawls(sand_prof, clay_prof, om_prof)
        jitter = 1.0 + rng.normal(0.0, 0.03, n)  # layer-to-layer heterogeneity
        return cls(
            layers_cm=layers_cm,
            theta_sat=np.clip(sr["saturation_m3m3"] * jitter, 0.25, 0.70),
            theta_fc=np.clip(sr["field_capacity_m3m3"] * jitter, 0.08, 0.55),
            theta_wp=np.clip(sr["wilting_point_m3m3"] * jitter, 0.02, 0.40),
            ksat_mm_day=np.clip(sr["ksat_mm_h"] * 24.0, 1.0, 5000.0),
            thickness_mm=np.array([(b - t) * 10.0 for t, b in layers_cm]),
        )


# --------------------------------------------------------------------------
# Weather
# --------------------------------------------------------------------------


def generate_weather(
    spec: SiteSpec,
    start: str,
    days: int,
    rng: np.random.Generator,
) -> pd.DataFrame:
    """Stochastic daily weather with seasonality and persistence.

    Precipitation follows a two-state Markov chain (wet days cluster, which is
    what makes drydowns long enough to be interesting) with gamma-distributed
    depths. Temperature and radiation are seasonal sinusoids with AR(1) noise so
    that consecutive days are correlated, as they are in reality.
    """
    dates = pd.date_range(start, periods=days, freq="D")
    doy = dates.dayofyear.to_numpy()
    seasonal = np.sin(2 * np.pi * (doy - 105) / 365.25)
    if spec.lat < 0:
        seasonal = -seasonal

    tmean = spec.mean_annual_temp_c + spec.temp_amplitude_c * seasonal
    ar = np.zeros(days)
    for i in range(1, days):
        ar[i] = 0.7 * ar[i - 1] + rng.normal(0, 2.2)
    tmean = tmean + ar
    dtr = np.clip(11.0 + 3.0 * seasonal + rng.normal(0, 1.5, days), 4.0, 22.0)
    tmax, tmin = tmean + dtr / 2, tmean - dtr / 2

    # Two-state Markov precipitation occurrence.
    p_wet = np.clip(spec.wet_day_fraction * (1.0 + 0.45 * seasonal), 0.02, 0.8)
    p_ww, p_dw = np.clip(p_wet * 2.1, 0, 0.9), np.clip(p_wet * 0.6, 0, 0.9)
    wet = np.zeros(days, dtype=bool)
    for i in range(days):
        p = p_ww[i] if (i and wet[i - 1]) else p_dw[i]
        wet[i] = rng.random() < p
    mean_depth = spec.annual_precip_mm / max(wet.sum(), 1) * (days / 365.25)
    precip = np.where(wet, rng.gamma(0.7, max(mean_depth, 1.0) / 0.7, days), 0.0)
    precip = np.round(np.clip(precip, 0, 200), 2)

    rh = np.clip(72.0 - 22.0 * seasonal * spec.aridity + rng.normal(0, 7, days), 12, 99)
    rh = np.where(wet, np.clip(rh + 12, 12, 99), rh)
    wind = np.clip(rng.gamma(4.0, 0.6, days), 0.4, 12.0)

    # Solar radiation as a clear-sky fraction of extraterrestrial radiation.
    from .agromet import extraterrestrial_radiation

    ra = extraterrestrial_radiation(spec.lat, doy)
    clearness = np.clip(rng.normal(0.62, 0.10, days), 0.16, 0.78)
    clearness = np.where(wet, clearness * 0.62, clearness)
    rs = ra * clearness

    et0 = et0_penman_monteith(
        tmax_c=tmax, tmin_c=tmin, rs_mj_m2_day=rs, wind_2m_ms=wind,
        lat_deg=spec.lat, elevation_m=spec.elevation_m, doy=doy, rh_mean_pct=rh,
    )

    return pd.DataFrame({
        "date": dates,
        "doy": doy,
        "precip_mm": precip,
        "tmax_c": np.round(tmax, 2),
        "tmin_c": np.round(tmin, 2),
        "tmean_c": np.round(tmean, 2),
        "rh_mean_pct": np.round(rh, 1),
        "wind_2m_ms": np.round(wind, 2),
        "srad_mj_m2": np.round(rs, 2),
        "et0_mm": np.round(et0, 3),
    })


# --------------------------------------------------------------------------
# Irrigation
# --------------------------------------------------------------------------

#: Application characteristics by method. ``efficiency`` is the fraction of
#: applied water reaching the soil; ``wetted_fraction`` is how much of the
#: surface is wetted (drip wets a strip, a pivot wets everything); ``depth_mm``
#: is the typical single application.
IRRIGATION_METHODS: dict[str, dict[str, float]] = {
    "center_pivot":     {"efficiency": 0.85, "wetted_fraction": 1.00, "depth_mm": 25.0, "min_interval_d": 3},
    "sprinkler":        {"efficiency": 0.75, "wetted_fraction": 1.00, "depth_mm": 30.0, "min_interval_d": 5},
    "furrow":           {"efficiency": 0.60, "wetted_fraction": 0.70, "depth_mm": 75.0, "min_interval_d": 10},
    "flood":            {"efficiency": 0.55, "wetted_fraction": 1.00, "depth_mm": 90.0, "min_interval_d": 12},
    "drip":             {"efficiency": 0.92, "wetted_fraction": 0.40, "depth_mm": 12.0, "min_interval_d": 2},
    "subsurface_drip":  {"efficiency": 0.95, "wetted_fraction": 0.35, "depth_mm": 12.0, "min_interval_d": 2},
    "rainfed":          {"efficiency": 0.00, "wetted_fraction": 0.00, "depth_mm": 0.0,  "min_interval_d": 9999},
}


#: NRCS runoff curve numbers for straight-row cultivated cropland in good
#: hydrologic condition, by hydrologic soil group, at average antecedent
#: moisture (AMC II). NEH-4 Table 9-1.
CURVE_NUMBER_ROW_CROP: dict[str, float] = {"A": 67.0, "B": 78.0, "C": 85.0, "D": 89.0}


def hydrologic_soil_group(ksat_mm_day: float) -> str:
    """NRCS hydrologic soil group from saturated conductivity.

    Thresholds are the NRCS class limits (40, 10 and 1 micrometres per second)
    converted to mm/day.
    """
    if ksat_mm_day > 40e-3 * 86400:      # > 3456 mm/day
        return "A"
    if ksat_mm_day > 10e-3 * 86400:      # > 864
        return "B"
    if ksat_mm_day > 1e-3 * 86400:       # > 86.4
        return "C"
    return "D"


def scs_runoff_mm(rain_mm: float, cn_ii: float, wetness: float,
                  initial_abstraction_ratio: float = 0.2) -> float:
    """SCS Curve Number storm runoff, mm.

        S = 25400 / CN - 254,   Ia = lambda S
        Q = (P - Ia)^2 / (P - Ia + S)   for P > Ia,  else 0

    ``wetness`` in [0, 1] is the relative available-water content of the top
    30 cm and slides the curve number between its AMC I (dry) and AMC III (wet)
    conversions,

        CN_I   = 4.2 CN_II / (10 - 0.058 CN_II)
        CN_III = 23  CN_II / (10 + 0.13  CN_II)

    which is what makes runoff depend on antecedent conditions rather than on
    rainfall alone — the coupling that matters when the aim is to reproduce a
    soil moisture time series rather than a flood peak.
    """
    if rain_mm <= 0.0:
        return 0.0
    cn_i = 4.2 * cn_ii / (10.0 - 0.058 * cn_ii)
    cn_iii = 23.0 * cn_ii / (10.0 + 0.13 * cn_ii)
    cn = cn_i + (cn_iii - cn_i) * float(np.clip(wetness, 0.0, 1.0))
    cn = float(np.clip(cn, 30.0, 98.0))
    s_ret = 25400.0 / cn - 254.0
    ia = initial_abstraction_ratio * s_ret
    if rain_mm <= ia:
        return 0.0
    return float((rain_mm - ia) ** 2 / (rain_mm - ia + s_ret))


@dataclass
class IrrigationPolicy:
    """How the grower decides to irrigate.

    ``deficit_fraction`` below 1 gives deficit irrigation — the field is
    deliberately kept drier than full replacement, which is common in
    water-limited regions and produces a visibly different soil moisture
    signature that a model must be able to represent.
    """

    method: str = "center_pivot"
    trigger_depletion: float = 0.50   # irrigate at this fraction of available water depleted
    deficit_fraction: float = 1.0     # 1.0 = full replacement, 0.6 = 60 % deficit
    root_zone_cm: float = 60.0
    season_only: bool = True
    scheduling_noise: float = 0.15    # growers do not follow the rule exactly


# --------------------------------------------------------------------------
# The water balance
# --------------------------------------------------------------------------


def simulate_site(
    spec: SiteSpec,
    weather: pd.DataFrame,
    policy: IrrigationPolicy | None = None,
    rng: np.random.Generator | None = None,
    column: SoilColumn | None = None,
) -> pd.DataFrame:
    """Run the layered water balance and return a daily multi-depth record.

    Per day, in order: irrigation decision, infiltration limited by the surface
    layer's conductivity with the excess becoming runoff, cascade of drainage
    through the layers, then evaporation from the surface layer and transpiration
    distributed over the active root zone with a water-stress reduction.

    Returns one row per day with true water content per layer, the sensor-observed
    values (carrying clay and salinity bias plus noise), and the fluxes — so an
    evaluation can separate error the model could have avoided from error baked
    into the observation.
    """
    rng = rng or np.random.default_rng(0)
    policy = policy or IrrigationPolicy(method=spec.irrigation_method)
    col = column or SoilColumn.from_texture(spec.sand_pct, spec.clay_pct, spec.om_pct, rng=rng)
    meth = IRRIGATION_METHODS[policy.method]

    n_days = len(weather)
    n_lay = len(col.layers_cm)
    mid_depth = np.array([(t + b) / 2 for t, b in col.layers_cm])

    crop = CROP_PARAMS.get(spec.crop, CROP_PARAMS["maize"])
    season_len = crop["l_ini"] + crop["l_dev"] + crop["l_mid"] + crop["l_late"]
    hsg = hydrologic_soil_group(float(col.ksat_mm_day[0]))
    cn_ii = CURVE_NUMBER_ROW_CROP[hsg]

    # State: water depth (mm) per layer, started near field capacity.
    water = col.theta_fc * col.thickness_mm * float(rng.uniform(0.75, 0.95))
    w_fc = col.theta_fc * col.thickness_mm
    w_wp = col.theta_wp * col.thickness_mm
    w_sat = col.theta_sat * col.thickness_mm

    theta_out = np.zeros((n_days, n_lay))
    irr_out = np.zeros(n_days)
    runoff_out = np.zeros(n_days)
    drain_out = np.zeros(n_days)
    et_out = np.zeros(n_days)
    kc_out = np.zeros(n_days)
    rootd_out = np.zeros(n_days)
    days_since_irr = 999

    precip = weather["precip_mm"].to_numpy()
    et0 = weather["et0_mm"].to_numpy()
    doy = weather["doy"].to_numpy()

    for d in range(n_days):
        dap = (doy[d] - spec.planting_doy) % 365
        in_season = dap <= season_len
        kc = float(kc_curve(dap if in_season else -1, crop["l_ini"], crop["l_dev"],
                            crop["l_mid"], crop["l_late"], crop["kc_ini"],
                            crop["kc_mid"], crop["kc_end"]))
        rd = float(root_depth_cm(dap if in_season else -1, crop["root_max_cm"], season_len))
        kc_out[d], rootd_out[d] = kc, rd

        # --- irrigation decision ------------------------------------------
        irrigation = 0.0
        days_since_irr += 1
        if meth["depth_mm"] > 0 and (in_season or not policy.season_only):
            rz = mid_depth <= max(policy.root_zone_cm, 15.0)
            avail = np.sum(water[rz] - w_wp[rz])
            capacity = np.sum(w_fc[rz] - w_wp[rz])
            depletion = 1.0 - avail / max(capacity, 1e-6)
            trigger = policy.trigger_depletion * (1.0 + rng.normal(0, policy.scheduling_noise))
            if depletion > trigger and days_since_irr >= meth["min_interval_d"]:
                gross = meth["depth_mm"] * policy.deficit_fraction
                gross *= 1.0 + rng.normal(0, 0.10)
                irrigation = max(gross * meth["efficiency"], 0.0)
                days_since_irr = 0
        irr_out[d] = irrigation

        # --- infiltration and runoff --------------------------------------
        # Storm runoff by SCS Curve Number, with the retention parameter moved
        # continuously between its dry and wet limits by how wet the surface
        # zone already is. Comparing a daily rainfall total against a daily
        # conductivity instead would let any storm infiltrate entirely, since
        # rain does not in fact arrive evenly across 24 hours.
        #
        # Irrigation is excluded from the runoff calculation: a managed
        # application is metered below the infiltration rate on purpose, and the
        # losses that do occur are already carried by the method's efficiency.
        rz_surface = mid_depth <= 30.0
        wetness = float(np.clip(
            (water[rz_surface].sum() - w_wp[rz_surface].sum())
            / max(w_fc[rz_surface].sum() - w_wp[rz_surface].sum(), 1e-6),
            0.0, 1.0,
        ))
        runoff_rain = scs_runoff_mm(precip[d], cn_ii, wetness)
        infiltrated = (precip[d] - runoff_rain) + irrigation
        runoff_out[d] = runoff_rain

        # --- cascade ------------------------------------------------------
        water[0] += infiltrated
        drained_out_of_profile = 0.0
        for k in range(n_lay):
            if water[k] > w_sat[k]:                       # saturation excess moves down
                excess = water[k] - w_sat[k]
                water[k] = w_sat[k]
                if k + 1 < n_lay:
                    water[k + 1] += excess
                else:
                    drained_out_of_profile += excess
            if water[k] > w_fc[k]:                        # gravity drainage above field capacity
                surplus = water[k] - w_fc[k]
                rate = min(1.0, col.ksat_mm_day[k] / max(surplus, 1e-6))
                drain = surplus * min(0.55 * rate + 0.05, 1.0)
                water[k] -= drain
                if k + 1 < n_lay:
                    water[k + 1] += drain
                else:
                    drained_out_of_profile += drain
        drain_out[d] = drained_out_of_profile

        # --- evaporation and transpiration ---------------------------------
        etc = et0[d] * kc
        # Split by canopy cover, approximated from Kc against its mid-season value.
        cover = np.clip((kc - crop["kc_ini"]) / max(crop["kc_mid"] - crop["kc_ini"], 1e-6), 0.0, 1.0)
        e_pot = etc * (1.0 - cover) * 0.9
        t_pot = etc * cover

        # Soil evaporation, surface layer only, falling off sharply as it dries.
        avail0 = max(water[0] - 0.4 * w_wp[0], 0.0)
        rel0 = np.clip(avail0 / max(w_fc[0] - 0.4 * w_wp[0], 1e-6), 0.0, 1.0)
        evap = min(e_pot * rel0**1.6, avail0)
        water[0] -= evap

        # Transpiration over the active root zone, weighted toward the surface
        # (the classic 40/30/20/10 root water uptake distribution).
        active = mid_depth <= max(rd, 10.0)
        if active.any() and t_pot > 0:
            w_root = np.where(active, np.exp(-mid_depth / max(rd / 1.4, 10.0)), 0.0)
            w_root = w_root / w_root.sum()
            avail_l = np.maximum(water - w_wp, 0.0)
            cap_l = np.maximum(w_fc - w_wp, 1e-6)
            # FAO-56 water stress: uptake unrestricted until the depletion
            # fraction p is exceeded, then falls linearly to zero at wilting.
            p = crop["depletion_frac"]
            ks = np.clip((avail_l / cap_l) / max(1.0 - p, 1e-6), 0.0, 1.0)
            demand = t_pot * w_root * ks
            demand = np.minimum(demand, avail_l)
            water -= demand
            et_out[d] = evap + demand.sum()
        else:
            et_out[d] = evap

        water = np.clip(water, 0.15 * w_wp, w_sat)
        theta_out[d] = water / col.thickness_mm

    # --- assemble --------------------------------------------------------
    out = weather.copy()
    out["site_id"] = spec.site_id
    out["irrigation_mm"] = np.round(irr_out, 3)
    out["runoff_mm"] = np.round(runoff_out, 3)
    out["drainage_mm"] = np.round(drain_out, 3)
    out["et_actual_mm"] = np.round(et_out, 3)
    out["kc"] = np.round(kc_out, 3)
    out["root_depth_cm"] = np.round(rootd_out, 1)

    porosity = col.theta_sat
    for i, (top, bot) in enumerate(col.layers_cm):
        tag = f"{int(top)}_{int(bot)}"
        true_theta = theta_out[:, i]
        out[f"theta_true_{tag}"] = np.round(true_theta, 5)
        out[f"theta_obs_{tag}"] = np.round(
            _apply_sensor_response(true_theta, spec, porosity[i], col, i, rng), 5
        )
        out[f"saturation_{tag}"] = np.round(degree_of_saturation(true_theta, porosity[i]), 5)

    return out


def _apply_sensor_response(
    true_theta: np.ndarray,
    spec: SiteSpec,
    porosity: float,
    col: SoilColumn,
    layer_index: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """Turn true water content into what a dielectric probe would report.

    Three artefacts are imposed, in the direction the physics dictates:

    * **clay** — bound water is invisible to the probe, so it reads *low* by
      :func:`~smml.physics.dielectric.clay_bias`;
    * **salinity** — pore-water salts inflate apparent permittivity on
      low-frequency sensors, so it reads *high*, scaled by
      :func:`~smml.physics.dielectric.salinity_bias_risk`;
    * **noise and offset** — white measurement noise plus a fixed per-site
      installation offset, which is the single largest obstacle to pooling
      stations in practice.

    A model trained on ``theta_obs`` and scored against ``theta_true`` therefore
    faces the same irreducible floor as one trained on the real database.
    """
    mid = (col.layers_cm[layer_index][0] + col.layers_cm[layer_index][1]) / 2
    clay_here = np.clip(spec.clay_pct * (1.0 + 0.004 * (mid - 2.5)), 1.0, 70.0)

    bias_clay = np.nan_to_num(clay_bias(true_theta, clay_here, porosity,
                                        bound_water_per_clay=BOUND_WATER_PER_CLAY))
    risk = float(np.nan_to_num(salinity_bias_risk(spec.ece_ds_m, spec.sensor_frequency_mhz)))
    # A fully salinity-affected low-frequency reading overestimates by roughly
    # 25 % of the water content; scale that by the computed risk.
    bias_salt = 0.25 * risk * true_theta

    obs = true_theta - bias_clay + bias_salt + spec.sensor_bias
    obs = obs + rng.normal(0.0, spec.sensor_noise_sd, size=true_theta.shape)
    return np.clip(obs, 0.0, porosity * 1.05)


# --------------------------------------------------------------------------
# Corpus generation
# --------------------------------------------------------------------------

#: Climate archetypes spanning the range the harvested corpus will contain,
#: from humid temperate to hyper-arid. Used to sample synthetic sites so that
#: leave-region-out cross-validation has genuinely distinct regions to hold out.
CLIMATE_ARCHETYPES: dict[str, dict[str, float]] = {
    "humid_temperate":   {"mean_annual_temp_c": 11.0, "temp_amplitude_c": 11.0, "annual_precip_mm": 1000.0, "wet_day_fraction": 0.34, "aridity": 0.6},
    "subhumid":          {"mean_annual_temp_c": 13.5, "temp_amplitude_c": 12.0, "annual_precip_mm": 750.0,  "wet_day_fraction": 0.26, "aridity": 0.9},
    "semiarid_plains":   {"mean_annual_temp_c": 12.5, "temp_amplitude_c": 14.0, "annual_precip_mm": 460.0,  "wet_day_fraction": 0.18, "aridity": 1.3},
    "mediterranean":     {"mean_annual_temp_c": 16.5, "temp_amplitude_c": 9.0,  "annual_precip_mm": 420.0,  "wet_day_fraction": 0.16, "aridity": 1.5},
    "arid_irrigated":    {"mean_annual_temp_c": 19.0, "temp_amplitude_c": 12.0, "annual_precip_mm": 180.0,  "wet_day_fraction": 0.08, "aridity": 2.0},
    "hot_desert":        {"mean_annual_temp_c": 23.0, "temp_amplitude_c": 11.0, "annual_precip_mm": 90.0,   "wet_day_fraction": 0.05, "aridity": 2.4},
    "humid_subtropical": {"mean_annual_temp_c": 18.5, "temp_amplitude_c": 9.0,  "annual_precip_mm": 1250.0, "wet_day_fraction": 0.30, "aridity": 0.7},
    "continental_cold":  {"mean_annual_temp_c": 6.5,  "temp_amplitude_c": 17.0, "annual_precip_mm": 520.0,  "wet_day_fraction": 0.22, "aridity": 1.0},
}

#: Texture archetypes, chosen to populate distinct corners of the USDA triangle.
TEXTURE_ARCHETYPES: dict[str, tuple[float, float]] = {
    "sand": (90.0, 4.0),
    "loamy_sand": (82.0, 7.0),
    "sandy_loam": (65.0, 11.0),
    "loam": (42.0, 18.0),
    "silt_loam": (22.0, 15.0),
    "silty_clay_loam": (12.0, 33.0),
    "clay_loam": (33.0, 33.0),
    "clay": (20.0, 52.0),
}


def climate_texture_design(n_sites: int, rng: np.random.Generator) -> list[tuple[str, str]]:
    """A shuffled factorial assignment of climate x texture over ``n_sites``.

    Cycling the two lists at different strides looks like it spreads the design
    but does not: with eight climates and eight textures, the first 24 sites
    would land on only three textures. Enumerating the full grid and shuffling
    guarantees that even a small corpus spans the space, and that every
    combination appears before any repeats.
    """
    grid = [(c, t) for c in CLIMATE_ARCHETYPES for t in TEXTURE_ARCHETYPES]
    out: list[tuple[str, str]] = []
    while len(out) < n_sites:
        block = list(grid)
        rng.shuffle(block)
        out.extend(block)
    return out[:n_sites]


def sample_site(
    index: int,
    rng: np.random.Generator,
    climate_name: str | None = None,
    texture_name: str | None = None,
) -> tuple[SiteSpec, IrrigationPolicy]:
    """Draw one synthetic site: climate, texture, salinity, crop, sensor, policy."""
    if climate_name is None:
        climate_name = list(CLIMATE_ARCHETYPES)[index % len(CLIMATE_ARCHETYPES)]
    if texture_name is None:
        texture_name = list(TEXTURE_ARCHETYPES)[
            (index // len(CLIMATE_ARCHETYPES)) % len(TEXTURE_ARCHETYPES)
        ]
    climate = CLIMATE_ARCHETYPES[climate_name]
    sand, clay = TEXTURE_ARCHETYPES[texture_name]
    sand = float(np.clip(sand + rng.normal(0, 4), 2, 96))
    clay = float(np.clip(clay + rng.normal(0, 3), 1, 65))
    if sand + clay > 97:
        sand = 97 - clay

    method = str(rng.choice(
        ["center_pivot", "sprinkler", "furrow", "drip", "subsurface_drip", "flood", "rainfed"],
        p=[0.30, 0.13, 0.15, 0.12, 0.10, 0.10, 0.10],
    ))
    crop = str(rng.choice(list(CROP_PARAMS), p=None))

    # Salinity is higher in arid, irrigated, fine-textured settings — the
    # combination that also makes dielectric sensors least trustworthy, which is
    # precisely the interaction the model has to cope with.
    salinity_push = climate["aridity"] * (0.4 + clay / 120.0) * (0.3 if method == "rainfed" else 1.0)
    # Heavy right tail on purpose: salt-affected irrigated land is a minority of
    # sites but it is the minority this project exists to handle, so the corpus
    # has to contain enough of it to exercise (and to falsify) the correction.
    ece = float(np.clip(rng.lognormal(np.log(1.2 * salinity_push + 0.15), 1.05), 0.05, 30.0))

    # Sensor population, roughly matching what the public networks actually run.
    sensor_freq = float(rng.choice([50.0, 70.0, 100.0, 175.0, 800.0, 1000.0],
                                   p=[0.18, 0.24, 0.16, 0.14, 0.14, 0.14]))

    lat = float(rng.uniform(-40, 52))
    return (
        SiteSpec(
            site_id=f"syn_{climate_name}_{texture_name}_{index:04d}",
            lat=lat,
            lon=float(rng.uniform(-125, 145)),
            elevation_m=float(np.clip(rng.gamma(2.0, 260.0), 1, 2600)),
            sand_pct=sand,
            clay_pct=clay,
            om_pct=float(np.clip(rng.gamma(2.0, 1.0), 0.15, 7.0)),
            ece_ds_m=ece,
            crop=crop,
            irrigation_method=method,
            sensor_frequency_mhz=sensor_freq,
            sensor_noise_sd=float(np.clip(rng.gamma(2.0, 0.005), 0.001, 0.035)),
            sensor_bias=float(rng.normal(0.0, 0.022)),
            planting_doy=int(np.clip(rng.normal(120 if lat >= 0 else 300, 22), 1, 365)),
            **climate,
        ),
        IrrigationPolicy(
            method=method,
            trigger_depletion=float(np.clip(rng.normal(0.50, 0.12), 0.20, 0.80)),
            deficit_fraction=float(np.clip(rng.normal(0.92, 0.18), 0.40, 1.15)),
            root_zone_cm=float(rng.choice([30.0, 45.0, 60.0, 90.0])),
        ),
    )


def generate_corpus(
    n_sites: int = 60,
    years: int = 4,
    start: str = "2016-01-01",
    seed: int = 20240501,
) -> tuple["pd.DataFrame", "pd.DataFrame"]:
    """Generate a synthetic multi-site corpus in the harmonized long format.

    Returns ``(observations, sites)``: a long table with one row per site-day-layer
    and a site table of static attributes. The long shape matches what the
    harvested database produces, so downstream feature building, cross-validation
    and tuning code is exercised against exactly the schema it will meet in
    production.
    """
    rng = np.random.default_rng(seed)
    obs_frames: list[pd.DataFrame] = []
    site_rows: list[dict] = []
    design = climate_texture_design(n_sites, rng)

    for i, (climate_name, texture_name) in enumerate(design):
        spec, policy = sample_site(i, rng, climate_name=climate_name, texture_name=texture_name)
        col = SoilColumn.from_texture(spec.sand_pct, spec.clay_pct, spec.om_pct, rng=rng)
        weather = generate_weather(spec, start, int(365.25 * years), rng)
        daily = simulate_site(spec, weather, policy=policy, rng=rng, column=col)

        sr = saxton_rawls(spec.sand_pct, spec.clay_pct, spec.om_pct)
        site_rows.append({
            "site_id": spec.site_id,
            "lat": spec.lat, "lon": spec.lon, "elevation_m": spec.elevation_m,
            "sand_pct": spec.sand_pct, "silt_pct": spec.silt_pct, "clay_pct": spec.clay_pct,
            "om_pct": spec.om_pct,
            "texture_class": str(usda_texture_class(spec.sand_pct, spec.clay_pct)),
            "ece_ds_m": spec.ece_ds_m,
            "crop": spec.crop,
            "irrigation_method": spec.irrigation_method,
            "is_irrigated": spec.irrigation_method != "rainfed",
            "sensor_frequency_mhz": spec.sensor_frequency_mhz,
            "sensor_noise_sd": spec.sensor_noise_sd,
            "sensor_bias": spec.sensor_bias,
            "planting_doy": spec.planting_doy,
            "climate": climate_name,
            "texture_archetype": texture_name,
            "mean_annual_temp_c": spec.mean_annual_temp_c,
            "annual_precip_mm": spec.annual_precip_mm,
            "aridity": spec.aridity,
            "trigger_depletion": policy.trigger_depletion,
            "deficit_fraction": policy.deficit_fraction,
            "wilting_point_m3m3": float(sr["wilting_point_m3m3"]),
            "field_capacity_m3m3": float(sr["field_capacity_m3m3"]),
            "porosity_m3m3": float(sr["porosity_m3m3"]),
            "ksat_mm_h": float(sr["ksat_mm_h"]),
        })

        # Melt the wide per-layer columns into the long observation format.
        keep = ["date", "doy", "site_id", "precip_mm", "tmax_c", "tmin_c", "tmean_c",
                "rh_mean_pct", "wind_2m_ms", "srad_mj_m2", "et0_mm", "irrigation_mm",
                "runoff_mm", "drainage_mm", "et_actual_mm", "kc", "root_depth_cm"]
        for j, (top, bot) in enumerate(col.layers_cm):
            tag = f"{int(top)}_{int(bot)}"
            frame = daily[keep].copy()
            frame["depth_top_cm"] = float(top)
            frame["depth_bottom_cm"] = float(bot)
            frame["depth_mid_cm"] = (top + bot) / 2.0
            frame["layer_index"] = j
            frame["theta_true_m3m3"] = daily[f"theta_true_{tag}"].to_numpy()
            frame["theta_obs_m3m3"] = daily[f"theta_obs_{tag}"].to_numpy()
            frame["saturation"] = daily[f"saturation_{tag}"].to_numpy()
            frame["layer_porosity_m3m3"] = float(col.theta_sat[j])
            frame["layer_fc_m3m3"] = float(col.theta_fc[j])
            frame["layer_wp_m3m3"] = float(col.theta_wp[j])
            obs_frames.append(frame)

    observations = pd.concat(obs_frames, ignore_index=True)
    observations = observations.sort_values(["site_id", "date", "depth_top_cm"]).reset_index(drop=True)
    return observations, pd.DataFrame(site_rows)
