"""Physics correctness tests.

Where an independent implementation of the same published standard exists it is
used as the oracle (``refet`` for FAO-56/ASCE reference ET). Elsewhere the tests
assert the invariants that must hold for the harmonization to be trustworthy:
round-trip consistency, monotonicity, and exact zero response where a correction
must not fire.
"""

from __future__ import annotations

import numpy as np
import pytest

from smml.physics import agromet as am
from smml.physics import dielectric as di
from smml.physics import water as wa

# --------------------------------------------------------------------------
# Dielectric
# --------------------------------------------------------------------------


def test_topp_matches_published_coefficients():
    # Topp (1980) reports theta ~ 0.29 at an apparent permittivity of 16.
    assert di.topp(16.0) == pytest.approx(0.291, abs=0.002)


def test_topp_inverse_round_trips():
    eps = np.linspace(3.0, 60.0, 200)
    assert np.allclose(di.topp_inverse(di.topp(eps)), eps, atol=1e-5)


def test_topp_is_monotone_in_permittivity():
    eps = np.linspace(1.0, 80.0, 500)
    assert np.all(np.diff(di.topp(eps)) > 0)


def test_clay_bias_is_exactly_zero_without_clay():
    """The flag must isolate the clay effect, not the offset between two models."""
    assert di.clay_bias(0.30, 0.0, 0.45) == pytest.approx(0.0, abs=1e-12)


def test_clay_bias_increases_with_clay():
    bias = di.clay_bias(0.30, [0, 10, 20, 30, 40, 50], 0.45)
    assert np.all(np.diff(bias) > 0)
    # Direction: ignoring bound water makes a dielectric sensor read low.
    assert np.all(bias[1:] > 0)


def test_bound_water_never_exceeds_total_water():
    """A dry clay cannot hold more bound water than it holds water at all."""
    theta = float(di.crim_bound_water(eps=3.0, porosity=0.45, clay_pct=60.0))
    potential = di.BOUND_WATER_PER_CLAY * 60.0
    assert 0.0 <= theta <= 0.45
    # Dry enough that the clay-imposed potential cannot be met: the solution must
    # land in the fully-bound regime, where all the water present is bound water.
    assert theta < potential


def test_four_phase_mixing_law_is_solved_exactly():
    """Substituting the solution back into the mixing law must leave no residual."""
    alpha, eps_w, eps_b, eps_s = 0.5, di.EPS_WATER_20C, di.EPS_BOUND_WATER, di.EPS_SOLID_MINERAL
    n = 0.45
    for eps in (3.0, 5.0, 8.0, 12.0, 16.0):
        for clay in (0.0, 20.0, 40.0, 60.0):
            theta = float(di.crim_bound_water(eps, n, clay))
            bound = min(di.BOUND_WATER_PER_CLAY * clay, theta)
            free = theta - bound
            rhs = (
                free * eps_w**alpha + bound * eps_b**alpha
                + (n - theta) * di.EPS_AIR**alpha + (1.0 - n) * eps_s**alpha
            )
            assert eps**alpha == pytest.approx(rhs, abs=1e-9), f"eps={eps} clay={clay}"


def test_bound_water_solution_is_continuous_across_its_two_regimes():
    """The fully-bound and partially-bound branches must meet without a step."""
    eps = np.linspace(1.5, 20.0, 5000)
    for clay in (20.0, 60.0):
        theta = di.crim_bound_water(eps, 0.45, clay)
        finite = theta[np.isfinite(theta)]
        # A jump between branches would dwarf the local slope; the true slope is
        # bounded well below 0.01 per grid step here.
        assert np.max(np.abs(np.diff(finite))) < 0.01
        assert np.all(np.diff(finite) >= -1e-12)  # monotone increasing in permittivity


def test_crim_reduces_to_three_phase_without_clay():
    eps, n = 20.0, 0.45
    assert di.crim_bound_water(eps, n, 0.0) == pytest.approx(float(di.crim(eps, n)), abs=1e-9)


def test_ec_temperature_correction_is_identity_at_reference():
    assert di.ec_temperature_correction(1.23, 25.0) == pytest.approx(1.23)


def test_ec_temperature_correction_direction():
    """A warm sample reads high, so normalizing to 25 C must reduce it."""
    assert di.ec_temperature_correction(1.0, 35.0) < 1.0
    assert di.ec_temperature_correction(1.0, 15.0) > 1.0


def test_hilhorst_is_nan_in_dry_soil():
    """The relation is numerically unusable as bulk permittivity approaches the offset."""
    assert np.isnan(di.hilhorst_pore_ec(0.5, 4.5, 4.1))


def test_salinity_classes_match_usda_handbook_60():
    labels = di.salinity_class([0.5, 3.0, 6.0, 12.0, 30.0])
    assert list(labels) == [
        "non_saline", "slightly_saline", "moderately_saline",
        "strongly_saline", "very_strongly_saline",
    ]


def test_salinity_risk_is_low_for_high_frequency_sensors():
    """TDR rejects the loss term; low-frequency capacitance does not."""
    tdr = di.salinity_bias_risk(8.0, 1000.0)
    fdr = di.salinity_bias_risk(8.0, 50.0)
    assert tdr < 0.01
    assert fdr > 0.8


# --------------------------------------------------------------------------
# Water
# --------------------------------------------------------------------------


def test_gravimetric_volumetric_round_trip():
    w = np.array([0.05, 0.15, 0.25])
    rb = np.array([1.2, 1.35, 1.55])
    assert np.allclose(wa.volumetric_to_gravimetric(wa.gravimetric_to_volumetric(w, rb), rb), w)


def test_porosity_bulk_density_round_trip():
    rb = np.array([1.1, 1.35, 1.6])
    assert np.allclose(wa.bulk_density_from_porosity(wa.porosity_from_bulk_density(rb)), rb)


@pytest.mark.parametrize(
    ("sand", "clay", "expected"),
    [
        (90, 3, "sand"), (80, 8, "loamy_sand"), (65, 10, "sandy_loam"),
        (40, 18, "loam"), (10, 5, "silt"), (20, 15, "silt_loam"),
        (60, 28, "sandy_clay_loam"), (33, 33, "clay_loam"),
        (10, 33, "silty_clay_loam"), (50, 40, "sandy_clay"),
        (10, 45, "silty_clay"), (20, 55, "clay"),
    ],
)
def test_usda_texture_triangle(sand, clay, expected):
    assert str(wa.usda_texture_class(sand, clay)) == expected


def test_saxton_rawls_orders_water_contents_correctly():
    r = wa.saxton_rawls([90, 40, 20], [3, 18, 45], [1.5, 2.0, 2.5])
    assert np.all(r["wilting_point_m3m3"] < r["field_capacity_m3m3"])
    assert np.all(r["field_capacity_m3m3"] < r["saturation_m3m3"])
    # Sand drains fastest, clay slowest.
    assert r["ksat_mm_h"][0] > r["ksat_mm_h"][1] > r["ksat_mm_h"][2]
    # Clay holds more water at wilting point than sand.
    assert r["wilting_point_m3m3"][2] > r["wilting_point_m3m3"][0]


def test_van_genuchten_round_trip():
    tr, ts, a, n = 0.061, 0.399, 10**-1.954, 10**0.168
    for h in (10.0, 100.0, 330.0, 15000.0):
        theta = wa.van_genuchten_theta(h, tr, ts, a, n)
        assert wa.van_genuchten_head(theta, tr, ts, a, n) == pytest.approx(h, rel=1e-6)


def test_van_genuchten_is_monotone_decreasing_in_suction():
    h = np.logspace(0, 4.5, 200)
    theta = wa.van_genuchten_theta(h, 0.061, 0.399, 10**-1.954, 10**0.168)
    assert np.all(np.diff(theta) < 0)


def test_mualem_conductivity_is_ksat_at_saturation():
    ks = 12.05
    k = wa.mualem_conductivity(0.399, 0.061, 0.399, 10**0.168, ks)
    assert k == pytest.approx(ks, rel=1e-6)


def test_layer_overlap_weights_partition_an_integrating_sensor():
    """A 0-30 cm sensor must distribute exactly once across the standard layers."""
    total = sum(
        float(wa.layer_overlap_weights(0.0, 30.0, top, bot))
        for top, bot in wa.STANDARD_LAYERS_CM
    )
    assert total == pytest.approx(1.0)


def test_layer_overlap_weights_place_a_point_sensor_in_one_layer():
    hits = [
        float(wa.layer_overlap_weights(10.0, 10.0, top, bot))
        for top, bot in wa.STANDARD_LAYERS_CM
    ]
    assert sum(hits) == pytest.approx(1.0)
    assert hits.count(1.0) == 1


def test_profile_storage_respects_root_depth():
    theta = np.full(len(wa.STANDARD_LAYERS_CM), 0.25)
    assert wa.profile_storage_mm(theta, max_depth_cm=100) == pytest.approx(0.25 * 100 * 10)
    assert wa.profile_storage_mm(theta) == pytest.approx(0.25 * 200 * 10)


def test_exponential_filter_damps_a_step():
    t = np.arange(60.0)
    x = np.where(t < 30, 0.15, 0.35)
    swi = wa.exponential_filter_swi(x, t, t_characteristic_days=20.0)
    assert swi[29] == pytest.approx(0.15, abs=1e-6)      # nothing to respond to yet
    assert 0.15 < swi[35] < 0.35                          # partial response
    assert swi[-1] > swi[35]                              # still converging upward


# --------------------------------------------------------------------------
# Agromet — validated against the independent `refet` implementation of ASCE/FAO-56
# --------------------------------------------------------------------------

ET0_CASES = [
    ("bangkok",    34.8, 25.6, 22.65, 3.23, 2.0, 13.73, 2.0, 105),
    ("davis",      35.0, 15.0, 30.00, 1.20, 2.2, 38.50, 18.0, 196),
    ("lubbock",    34.0, 19.0, 28.00, 1.50, 3.5, 33.60, 990.0, 166),
    ("wageningen", 13.0, 3.0, 13.00, 0.80, 2.5, 51.97, 7.0, 105),
    ("cairo",      37.0, 23.0, 26.00, 1.90, 2.0, 30.05, 20.0, 227),
    ("fargo",      22.0, 8.0, 22.00, 1.00, 4.0, 46.90, 274.0, 135),
]


def _dewpoint_from_ea(ea: float) -> float:
    z = np.log(ea / 0.6108)
    return float(z * 237.3 / (17.27 - z))


@pytest.mark.parametrize(("name", "tmax", "tmin", "rs", "ea", "u2", "lat", "elev", "doy"), ET0_CASES)
def test_et0_matches_independent_implementation(name, tmax, tmin, rs, ea, u2, lat, elev, doy):
    refet = pytest.importorskip("refet")
    mine = float(np.atleast_1d(am.et0_penman_monteith(
        tmax_c=tmax, tmin_c=tmin, rs_mj_m2_day=rs, wind_2m_ms=u2,
        lat_deg=lat, elevation_m=elev, doy=doy, tdew_c=_dewpoint_from_ea(ea),
    ))[0])
    ref = float(np.atleast_1d(refet.Daily(
        tmin=np.array([tmin]), tmax=np.array([tmax]), ea=np.array([ea]), rs=np.array([rs]),
        uz=np.array([u2]), zw=2.0, elev=np.array([elev]), lat=np.array([lat]),
        doy=np.array([doy]), method="asce",
    ).eto())[0])
    assert mine == pytest.approx(ref, rel=0.005)


def test_vapour_pressure_routes_are_ordered_as_fao_expects():
    """RHmean (eq. 19) biases ea high / VPD low relative to RHmax-RHmin (eq. 17)."""
    ea_pair = am.actual_vapour_pressure(34.8, 25.6, rh_max_pct=85, rh_min_pct=66)
    ea_mean = am.actual_vapour_pressure(34.8, 25.6, rh_mean_pct=75.5)
    assert float(ea_pair) == pytest.approx(3.23, abs=0.01)
    assert float(ea_mean) > float(ea_pair)


def test_actual_vapour_pressure_requires_some_humidity_input():
    with pytest.raises(ValueError):
        am.actual_vapour_pressure(20.0, 10.0)


def test_extraterrestrial_radiation_matches_fao_table():
    # FAO-56 Annex 2 Table 2.6: lat 13.73 N, 15 April -> Ra ~ 38.1 MJ m-2 d-1
    assert float(am.extraterrestrial_radiation(13.73, 105)) == pytest.approx(38.06, abs=0.2)


def test_hargreaves_tracks_penman_monteith_within_the_expected_spread():
    hs = float(am.et0_hargreaves(35.0, 15.0, 38.5, 196))
    pm = float(am.et0_penman_monteith(tmax_c=35.0, tmin_c=15.0, rs_mj_m2_day=30.0, wind_2m_ms=2.2,
                                      lat_deg=38.5, elevation_m=18.0, doy=196, tdew_c=9.8))
    assert 0.6 * pm < hs < 1.4 * pm


def test_kc_curve_follows_the_four_stage_shape():
    p = am.CROP_PARAMS["maize"]
    kc = am.kc_curve([0, 25, 65, 110, 140, 200], p["l_ini"], p["l_dev"], p["l_mid"],
                     p["l_late"], p["kc_ini"], p["kc_mid"], p["kc_end"])
    assert kc[0] == pytest.approx(p["kc_ini"])
    assert kc[1] == pytest.approx(p["kc_ini"])          # end of initial stage
    assert kc[2] == pytest.approx(p["kc_mid"])          # mid-season plateau
    assert p["kc_end"] <= kc[4] <= p["kc_mid"]          # late-season decline
    assert kc[5] == pytest.approx(0.15)                 # bare soil after harvest


def test_root_depth_saturates_at_the_crop_maximum():
    p = am.CROP_PARAMS["maize"]
    total = p["l_ini"] + p["l_dev"] + p["l_mid"] + p["l_late"]
    d = am.root_depth_cm([0, 50, 140], p["root_max_cm"], total)
    assert d[0] == pytest.approx(20.0)
    assert d[2] == pytest.approx(p["root_max_cm"])
    assert d[0] < d[1] < d[2]
