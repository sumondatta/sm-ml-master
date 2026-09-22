"""Dielectric soil moisture physics: permittivity, texture bias and salinity.

Most of the world's in-situ soil moisture record is produced by dielectric
sensors, and almost none of it is directly comparable across sites. Two effects
dominate the incomparability, and both are handled here:

**Clay.** The standard Topp (1980) calibration was fitted on four mineral soils
with low specific surface area. In fine-textured soils a large fraction of the
water is held on clay surfaces as *bound water*, whose relative permittivity is
closer to that of ice (~3-6) than of free water (~80). Topp therefore
*underestimates* water content in clay-rich soils, and the error grows with clay
fraction and with water content. Reported biases reach 0.05-0.10 m3/m3 in
smectitic clays.

**Salinity.** Pore water salts raise the imaginary part of the permittivity.
Low-frequency capacitance/FDR sensors (<100 MHz) cannot separate the real and
imaginary parts, so they read the *apparent* permittivity and report water
content that is biased high — severely so above roughly 2-4 dS/m pore-water EC.
TDR and high-frequency (>200 MHz) sensors are far more robust because the loss
term contributes less at high frequency.

Everything in this module is vectorized over NumPy arrays and returns NaN rather
than raising where an input is outside the physically meaningful domain, so that
it can be applied column-wise to a heterogeneous database.

References for the coefficients are given per function. Where a relation is
empirical the fitting soils are stated, because applying it outside that domain
is exactly the error this module exists to quantify.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import ArrayLike, NDArray

# Relative permittivity of the phases at ~20 C, 50 MHz-1 GHz.
EPS_AIR = 1.0
EPS_WATER_20C = 80.1
EPS_SOLID_MINERAL = 4.7   # quartz-dominated mineral matrix; 4-5 is the usual range
EPS_BOUND_WATER = 3.2     # water in the first few molecular layers on clay surfaces
EPS_ICE = 3.2

# Bound water volume per percent clay (m3/m3 / %). See crim_bound_water.
BOUND_WATER_PER_CLAY = 0.002

# Salinity classes by saturation-extract EC (dS/m at 25 C), USDA Handbook 60.
SALINITY_CLASSES: tuple[tuple[str, float, float], ...] = (
    ("non_saline", 0.0, 2.0),
    ("slightly_saline", 2.0, 4.0),
    ("moderately_saline", 4.0, 8.0),
    ("strongly_saline", 8.0, 16.0),
    ("very_strongly_saline", 16.0, np.inf),
)


def _arr(x: ArrayLike) -> NDArray[np.float64]:
    return np.asarray(x, dtype=float)


# --------------------------------------------------------------------------
# Permittivity -> volumetric water content
# --------------------------------------------------------------------------


def topp(eps: ArrayLike) -> NDArray[np.float64]:
    """Topp, Davis & Annan (1980) universal calibration.

    theta = -5.3e-2 + 2.92e-2 eps - 5.5e-4 eps^2 + 4.3e-6 eps^3

    Fitted on four mineral soils (sandy loam to clay) with clay < ~40 % and low
    organic matter. Accuracy ~0.013 m3/m3 within that domain; biased low in
    high-surface-area soils and in organic soils.
    """
    e = _arr(eps)
    theta = -5.3e-2 + 2.92e-2 * e - 5.5e-4 * e**2 + 4.3e-6 * e**3
    return np.where((e >= 1.0) & (e <= 100.0), theta, np.nan)


def topp_inverse(theta: ArrayLike) -> NDArray[np.float64]:
    """Apparent permittivity implied by Topp for a given water content.

    Solved numerically by monotone inversion on [1, 100]; the Topp cubic is
    monotone increasing over that interval so the root is unique.
    """
    th = _arr(theta)
    grid_eps = np.linspace(1.0, 100.0, 20001)
    grid_theta = topp(grid_eps)
    out = np.interp(th, grid_theta, grid_eps, left=np.nan, right=np.nan)
    return np.where(np.isfinite(th), out, np.nan)


def ledieu(eps: ArrayLike) -> NDArray[np.float64]:
    """Ledieu et al. (1986) linear square-root ("refractive index") relation.

    theta = 0.1138 sqrt(eps) - 0.1758
    """
    e = _arr(eps)
    return np.where(e >= 1.0, 0.1138 * np.sqrt(e) - 0.1758, np.nan)


def malicki(eps: ArrayLike, bulk_density: ArrayLike) -> NDArray[np.float64]:
    """Malicki, Plagge & Roth (1996) — bulk-density-aware.

    theta = (sqrt(eps) - 0.819 - 0.168 rho_b - 0.159 rho_b^2) / (7.17 + 1.18 rho_b)

    Removes most of the density-related scatter that Topp absorbs into its
    coefficients, so it transfers better between compacted and loose soils.
    """
    e, rb = _arr(eps), _arr(bulk_density)
    num = np.sqrt(e) - 0.819 - 0.168 * rb - 0.159 * rb**2
    den = 7.17 + 1.18 * rb
    return np.where((e >= 1.0) & (rb > 0.2) & (rb < 2.2), num / den, np.nan)


def crim(
    eps: ArrayLike,
    porosity: ArrayLike,
    eps_solid: float = EPS_SOLID_MINERAL,
    eps_water: float = EPS_WATER_20C,
    alpha: float = 0.5,
) -> NDArray[np.float64]:
    """Complex refractive index model (CRIM), inverted for water content.

    eps^a = theta eps_w^a + (n - theta) eps_air^a + (1 - n) eps_s^a

    with ``alpha = 0.5`` the usual isotropic-mixture exponent. Unlike the
    empirical fits above this is a physically-grounded volumetric mixing law, so
    it extrapolates more safely — but it needs porosity, and it still assumes
    all water behaves as free water (see :func:`crim_bound_water`).
    """
    e, n = _arr(eps), _arr(porosity)
    num = e**alpha - (n * EPS_AIR**alpha) - ((1.0 - n) * eps_solid**alpha)
    den = eps_water**alpha - EPS_AIR**alpha
    theta = num / den
    return np.where((e >= 1.0) & (n > 0.0) & (n < 1.0), theta, np.nan)


def crim_bound_water(
    eps: ArrayLike,
    porosity: ArrayLike,
    clay_pct: ArrayLike,
    eps_solid: float = EPS_SOLID_MINERAL,
    eps_water: float = EPS_WATER_20C,
    eps_bound: float = EPS_BOUND_WATER,
    alpha: float = 0.5,
    bound_water_per_clay: float = BOUND_WATER_PER_CLAY,
) -> NDArray[np.float64]:
    """Four-phase CRIM treating clay-bound water as a separate low-permittivity phase.

    This is the correction for the clay bias. The four-phase mixing law is

        eps^a = th_f eps_w^a + th_b eps_b^a + (n - th_f - th_b) eps_air^a + (1 - n) eps_s^a

    with total water ``th = th_f + th_b`` and bound water limited both by the
    clay content and by how much water is present at all:

        th_b = min(P, th),   P = bound_water_per_clay * clay_pct

    That cap is what makes the system implicit — the bound fraction depends on the
    total the model is solving for. It is solved exactly rather than iteratively,
    because the two regimes are each linear in ``th``:

    *Unsaturated-bound regime* (``th > P``): bound water is at its clay-imposed
    potential and the rest is free, so ``th`` follows directly from the mixing law.

    *Fully-bound regime* (``th <= P``): every water molecule is bound, the free
    term vanishes, and the mixing law collapses to

        th = [n + (1 - n) eps_s^a - eps^a] / (1 - eps_b^a)

    The branches agree where they meet, so the result is continuous in both
    permittivity and clay content. (An earlier fixed-point formulation of this
    converged far too slowly to be usable — the map contracts by only about 0.9
    per pass in dry clay — which is why the closed form is used.)

    The default ``bound_water_per_clay`` of 0.002 m3/m3 per percent clay gives
    ~0.08 m3/m3 of bound water at 40 % clay, in the range reported for
    illitic/mixed mineralogy. Use ~0.003 for smectitic soils and ~0.001 for
    kaolinitic ones. It is the single tuning knob and should be fitted per soil
    wherever gravimetric calibration samples exist.
    """
    e, n, clay = np.broadcast_arrays(_arr(eps), _arr(porosity), _arr(clay_pct))
    ea, eba, esa = EPS_AIR**alpha, eps_bound**alpha, eps_solid**alpha
    den = eps_water**alpha - ea
    solid = (1.0 - n) * esa
    potential = np.clip(bound_water_per_clay * clay, 0.0, n)

    with np.errstate(invalid="ignore", divide="ignore"):
        # Regime 1: bound water saturated at its potential, remainder free.
        th_unsat = (e**alpha - potential * eba - (n - potential) * ea - solid) / den + potential
        # Regime 2: all water bound, no free water.
        th_full = (n * ea + solid - e**alpha) / (ea - eba)

    theta = np.where(th_unsat > potential, th_unsat, th_full)
    valid = (e >= 1.0) & (n > 0.0) & (n < 1.0) & (clay >= 0.0) & (clay <= 100.0)
    return np.where(valid, np.clip(theta, 0.0, n), np.nan)


def clay_bias(
    theta_apparent: ArrayLike,
    clay_pct: ArrayLike,
    porosity: ArrayLike,
    bound_water_per_clay: float = BOUND_WATER_PER_CLAY,
) -> NDArray[np.float64]:
    """Water content underestimated (m3/m3) because bound water was ignored.

    Positive means the sensor's factory calibration reads *low* by that amount.

    The comparison is made between the four-phase model at the site's clay
    content and the *same* four-phase model at zero clay, both driven by the same
    apparent permittivity. Differencing against Topp instead would confound the
    clay effect with the unrelated offset between two different calibration
    families, which is not what this is for — at zero clay this returns exactly
    zero, by construction.
    """
    eps = topp_inverse(_arr(theta_apparent))
    with_clay = crim_bound_water(
        eps, porosity, clay_pct, bound_water_per_clay=bound_water_per_clay
    )
    without_clay = crim_bound_water(eps, porosity, 0.0, bound_water_per_clay=bound_water_per_clay)
    return with_clay - without_clay


def correct_for_clay(
    theta_apparent: ArrayLike,
    clay_pct: ArrayLike,
    porosity: ArrayLike,
    bound_water_per_clay: float = BOUND_WATER_PER_CLAY,
) -> NDArray[np.float64]:
    """Apply :func:`clay_bias` to an apparent (factory-calibration) water content.

    Kept separate from the flag so that a pipeline can record the bias without
    silently altering the observation — which is the default in this project,
    because a correction applied to data whose sensor calibration is unknown can
    easily be worse than no correction. Corrected values are written to their own
    column alongside the original.

    The correction is largest in *relative* terms in dry fine-textured soil,
    where almost all the water is bound and therefore nearly invisible to the
    sensor. That is real physics, but it is also where the linear bound-water
    assumption is least tested, so treat corrected values below about
    0.10 m3/m3 in soils over 35 % clay as indicative only.
    """
    th = _arr(theta_apparent)
    return th + clay_bias(th, clay_pct, porosity, bound_water_per_clay=bound_water_per_clay)


# --------------------------------------------------------------------------
# Salinity
# --------------------------------------------------------------------------


def ec_temperature_correction(ec: ArrayLike, temp_c: ArrayLike, ref_c: float = 25.0) -> NDArray[np.float64]:
    """Normalize electrical conductivity to a reference temperature.

    EC_ref = EC_t / (1 + 0.019 (T - T_ref))

    The 1.9 %/C coefficient is the standard linear approximation for dilute
    soil solutions between roughly 5 and 40 C.
    """
    e, t = _arr(ec), _arr(temp_c)
    return np.where(np.isfinite(e) & np.isfinite(t), e / (1.0 + 0.019 * (t - ref_c)), np.nan)


def hilhorst_pore_ec(
    bulk_ec: ArrayLike,
    eps_bulk: ArrayLike,
    eps_offset: ArrayLike = 4.1,
    bulk_ec_offset: float = 0.0,
) -> NDArray[np.float64]:
    """Hilhorst (2000) pore-water EC from bulk EC and bulk permittivity.

        EC_pore = eps_water * (EC_bulk - EC_bulk,0) / (eps_bulk - eps_sigma0)

    ``eps_sigma0`` is the real permittivity at which bulk EC extrapolates to
    zero; 4.1 is the widely used default for mineral soils, but it is genuinely
    soil-specific (reported 1.9-14) and is the dominant source of error here.
    Returns NaN where the denominator is small, because the relation is
    numerically unusable in dry soil.
    """
    ecb, e, e0 = _arr(bulk_ec), _arr(eps_bulk), _arr(eps_offset)
    den = e - e0
    out = EPS_WATER_20C * (ecb - bulk_ec_offset) / den
    return np.where((den > 1.0) & (ecb >= 0.0), out, np.nan)


def ece_from_pore_ec(
    pore_ec: ArrayLike,
    theta: ArrayLike,
    porosity: ArrayLike,
    saturation_water_fraction: float = 1.0,
) -> NDArray[np.float64]:
    """Saturation-extract EC (ECe) from pore-water EC by dilution scaling.

        ECe ~= EC_pore * theta / theta_saturated_paste

    A mass-balance dilution argument: the saturated paste holds more water than
    the field soil, so the same salt mass gives a proportionally lower EC. Crude
    — it ignores mineral dissolution/precipitation and cation exchange — but it
    is the standard field approximation and is good to roughly a factor of 1.5.
    """
    pec, th, n = _arr(pore_ec), _arr(theta), _arr(porosity)
    th_sat = n * saturation_water_fraction
    return np.where((th_sat > 0) & (th >= 0), pec * th / th_sat, np.nan)


def salinity_class(ece: ArrayLike) -> NDArray[np.str_]:
    """USDA salinity class label from saturation-extract EC (dS/m)."""
    e = _arr(ece)
    out = np.full(e.shape, "unknown", dtype=object)
    for name, lo, hi in SALINITY_CLASSES:
        out = np.where(np.isfinite(e) & (e >= lo) & (e < hi), name, out)
    return out.astype(str)


def salinity_bias_risk(
    ece: ArrayLike,
    sensor_frequency_mhz: ArrayLike,
) -> NDArray[np.float64]:
    """Dimensionless 0-1 risk that a reading is salinity-biased.

    Combines how saline the soil is with how vulnerable the sensor is. The
    frequency term is a logistic centred at 150 MHz: below ~50 MHz (older
    capacitance probes) the sensor cannot reject the loss term at all; above
    ~500 MHz (TDR) it largely can.

    This is the flag to carry into the database and into the model as a feature,
    and the one to filter on when building a clean training subset.
    """
    e = _arr(ece)
    f = _arr(sensor_frequency_mhz)
    salt_term = np.clip((e - 1.0) / 7.0, 0.0, 1.0)          # 0 at 1 dS/m, 1 at 8
    freq_term = 1.0 / (1.0 + np.exp((f - 150.0) / 60.0))     # 1 at low f, 0 at high f
    risk = salt_term * freq_term
    return np.where(np.isfinite(e) & np.isfinite(f), risk, np.nan)


def temperature_correction_permittivity(
    eps: ArrayLike, temp_c: ArrayLike, ref_c: float = 20.0
) -> NDArray[np.float64]:
    """Adjust apparent permittivity to a reference soil temperature.

    Free water permittivity falls about 0.36 % per C over 0-40 C. The soil
    mixture inherits a fraction of that scaled by the water-filled volume, which
    is approximated here through the water term of the mixture. Small (a few
    tenths of a percent per C) but systematic, and it aliases directly onto the
    diurnal cycle, so it matters for sub-daily modelling.
    """
    e, t = _arr(eps), _arr(temp_c)
    eps_w_t = EPS_WATER_20C * (1.0 - 0.0036 * (t - 20.0))
    eps_w_ref = EPS_WATER_20C * (1.0 - 0.0036 * (ref_c - 20.0))
    # Scale only the part of eps above the dry-soil floor.
    dry_floor = EPS_SOLID_MINERAL
    scaled = dry_floor + (e - dry_floor) * (eps_w_ref / eps_w_t)
    return np.where((e >= 1.0) & np.isfinite(t), scaled, np.nan)
