"""The harmonized database schema.

A star schema over partitioned Parquet, queried through DuckDB. The shape is
driven by what this particular corpus looks like: a few hundred thousand sites
at most, but potentially billions of observation rows, arriving from hundreds of
sources with wildly different fidelity, and needing to be filtered on provenance
and quality at every step.

Three conventions are load-bearing:

**Units are in the column names.** ``theta_m3m3``, ``precip_mm``,
``depth_top_cm``. A harmonized database assembled from sources that variously
report percent, fraction, millimetres and inches cannot afford ambiguity, and a
name is checked by every reader where a separate metadata table is not.

**Provenance travels with every row.** ``source_id`` and ``method`` are on the
fact table, not only on a dimension, because the first thing any analysis does is
exclude a source, an extraction method, or a quality tier — and that filter has
to be a partition prune or a column scan, not a join.

**The observed value and every correction are separate columns.** ``theta_m3m3``
is what the instrument reported after unit conversion and nothing else.
Corrections live alongside it. Nothing is ever silently overwritten, because a
correction applied on the basis of an estimated soil property can be worse than
no correction, and the only way to find out is to be able to compare.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import pyarrow as pa


class ObservationMethod(str, Enum):
    """How a soil moisture value came to exist. Drives uncertainty and QC."""

    GRAVIMETRIC = "gravimetric"
    NEUTRON_PROBE = "neutron_probe"
    TDR = "tdr"
    FDR_CAPACITANCE = "fdr_capacitance"
    IMPEDANCE = "impedance"
    HEAT_PULSE = "heat_pulse"
    COSMIC_RAY = "cosmic_ray_neutron"
    GPR = "ground_penetrating_radar"
    LYSIMETER = "lysimeter"
    TENSIOMETER_DERIVED = "tensiometer_derived"
    REMOTE_SENSING = "remote_sensing"
    MODEL_OUTPUT = "model_output"
    DIGITIZED_FIGURE = "digitized_figure"
    PUBLISHED_TABLE = "published_table"
    UNKNOWN = "unknown"


class QualityFlag(str, Enum):
    """Per-observation quality, following ISMN's scheme where it applies.

    ``GOOD`` means passed everything. The rest are reasons, and are kept rather
    than dropped: a record that fails a physical-range check against an
    *estimated* porosity may be perfectly valid data with a bad porosity
    estimate, and only the analyst downstream can decide.
    """

    GOOD = "G"
    MISSING = "M"
    OUT_OF_PHYSICAL_RANGE = "D01"       # below zero or above porosity
    EXCEEDS_SATURATION = "D02"
    SPIKE = "D03"
    NEGATIVE_BREAK = "D04"              # implausible drop
    CONSTANT_VALUE = "D05"              # flatlined sensor
    FROZEN_SOIL = "D06"                 # soil temperature below zero
    RISE_WITHOUT_WATER_INPUT = "D07"    # also the irrigation-detection signal
    SENSOR_DRIFT = "D08"
    STEP_CHANGE = "D09"                 # recalibration or reinstallation
    CROSS_DEPTH_INCONSISTENT = "D10"
    SALINITY_SUSPECT = "S01"            # high EC on a low-frequency sensor
    CLAY_SUSPECT = "S02"                # high clay, factory calibration
    DIGITIZATION_UNCERTAIN = "X01"
    SOURCE_UNVERIFIED = "X02"


class IrrigationStatus(str, Enum):
    IRRIGATED = "irrigated"
    RAINFED = "rainfed"
    MIXED = "mixed"
    UNKNOWN = "unknown"


# --------------------------------------------------------------------------
# Dimension: site
# --------------------------------------------------------------------------

SITE_SCHEMA = pa.schema([
    pa.field("site_id", pa.string(), nullable=False),
    pa.field("source_id", pa.string(), nullable=False),
    pa.field("network", pa.string()),
    pa.field("station_name", pa.string()),
    pa.field("lat", pa.float64(), nullable=False),
    pa.field("lon", pa.float64(), nullable=False),
    pa.field("elevation_m", pa.float32()),
    pa.field("country", pa.string()),
    pa.field("timezone", pa.string()),

    # Irrigation — the axis this project is organized around.
    pa.field("irrigation_status", pa.string()),
    pa.field("irrigation_method", pa.string()),
    pa.field("irrigation_source", pa.string(),
             metadata={b"doc": b"how the status was determined: reported | mask | inferred"}),
    pa.field("irrigation_mask_lanid", pa.float32()),
    pa.field("irrigation_mask_mirad", pa.float32()),
    pa.field("irrigation_mask_gmia", pa.float32()),

    # Soil, as reported by the study.
    pa.field("sand_pct", pa.float32()),
    pa.field("silt_pct", pa.float32()),
    pa.field("clay_pct", pa.float32()),
    pa.field("om_pct", pa.float32()),
    pa.field("bulk_density_g_cm3", pa.float32()),
    pa.field("texture_class", pa.string()),
    pa.field("ec_bulk_ds_m", pa.float32()),
    pa.field("ece_ds_m", pa.float32()),
    pa.field("salinity_class", pa.string()),
    pa.field("ph", pa.float32()),
    pa.field("soil_property_source", pa.string(),
             metadata={b"doc": b"reported | soilgrids | polaris | ssurgo | hwsd | estimated"}),

    # Soil, from a gridded product — kept separately so that a model can be
    # trained on globally available covariates only, which is what it will have
    # at prediction time anywhere outside an instrumented field.
    pa.field("sand_pct_grid", pa.float32()),
    pa.field("silt_pct_grid", pa.float32()),
    pa.field("clay_pct_grid", pa.float32()),
    pa.field("om_pct_grid", pa.float32()),
    pa.field("bulk_density_grid_g_cm3", pa.float32()),
    pa.field("cec_grid", pa.float32()),
    pa.field("coarse_fragments_grid_pct", pa.float32()),

    # Derived hydraulic properties.
    pa.field("wilting_point_m3m3", pa.float32()),
    pa.field("field_capacity_m3m3", pa.float32()),
    pa.field("porosity_m3m3", pa.float32()),
    pa.field("ksat_mm_h", pa.float32()),
    pa.field("vg_theta_r", pa.float32()),
    pa.field("vg_theta_s", pa.float32()),
    pa.field("vg_alpha_1cm", pa.float32()),
    pa.field("vg_n", pa.float32()),

    # Setting.
    pa.field("land_cover", pa.string()),
    pa.field("crop", pa.string()),
    pa.field("climate_zone", pa.string()),
    pa.field("mean_annual_precip_mm", pa.float32()),
    pa.field("mean_annual_temp_c", pa.float32()),
    pa.field("aridity_index", pa.float32()),
    pa.field("slope_pct", pa.float32()),
    pa.field("twi", pa.float32()),

    pa.field("record_start", pa.timestamp("s", tz="UTC")),
    pa.field("record_end", pa.timestamp("s", tz="UTC")),
    pa.field("n_observations", pa.int64()),
    pa.field("study_id", pa.string(), metadata={b"doc": b"DOI when the site came from a paper"}),
    pa.field("notes", pa.string()),
])


# --------------------------------------------------------------------------
# Dimension: sensor
# --------------------------------------------------------------------------

SENSOR_SCHEMA = pa.schema([
    pa.field("sensor_id", pa.string(), nullable=False),
    pa.field("site_id", pa.string(), nullable=False),
    pa.field("variable", pa.string(), nullable=False),
    pa.field("depth_top_cm", pa.float32(), nullable=False),
    pa.field("depth_bottom_cm", pa.float32(), nullable=False),
    pa.field("method", pa.string()),
    pa.field("instrument", pa.string()),
    pa.field("instrument_frequency_mhz", pa.float32(),
             metadata={b"doc": b"operating frequency; sets salinity vulnerability"}),
    pa.field("calibration", pa.string(),
             metadata={b"doc": b"factory | topp | soil_specific | unknown"}),
    pa.field("reported_accuracy_m3m3", pa.float32()),
    pa.field("install_date", pa.timestamp("s", tz="UTC")),
    pa.field("n_observations", pa.int64()),
])


# --------------------------------------------------------------------------
# Dimension: source
# --------------------------------------------------------------------------

SOURCE_SCHEMA = pa.schema([
    pa.field("source_id", pa.string(), nullable=False),
    pa.field("name", pa.string(), nullable=False),
    pa.field("category", pa.string()),
    pa.field("url", pa.string()),
    pa.field("licence", pa.string(), nullable=False,
             metadata={b"doc": b"required: governs whether the rows may be redistributed"}),
    pa.field("redistributable", pa.bool_()),
    pa.field("citation", pa.string()),
    pa.field("version", pa.string()),
    pa.field("accessed_at", pa.timestamp("s", tz="UTC")),
    pa.field("harvest_config_hash", pa.string()),
    pa.field("n_sites", pa.int64()),
    pa.field("n_observations", pa.int64()),
])


# --------------------------------------------------------------------------
# Fact: soil moisture observations
# --------------------------------------------------------------------------

OBSERVATION_SCHEMA = pa.schema([
    pa.field("observation_key", pa.string(), nullable=False),
    pa.field("site_id", pa.string(), nullable=False),
    pa.field("sensor_id", pa.string(), nullable=False),
    pa.field("source_id", pa.string(), nullable=False),
    pa.field("time_utc", pa.timestamp("s", tz="UTC"), nullable=False),
    pa.field("depth_top_cm", pa.float32(), nullable=False),
    pa.field("depth_bottom_cm", pa.float32(), nullable=False),

    # The observation as reported, converted to volumetric water content and
    # nothing more.
    pa.field("theta_m3m3", pa.float32(), nullable=False),
    pa.field("theta_original", pa.float32(),
             metadata={b"doc": b"value in the source's own units, before conversion"}),
    pa.field("original_unit", pa.string()),

    # Corrections, each additive to theta_m3m3 and each optional.
    pa.field("theta_clay_corrected_m3m3", pa.float32()),
    pa.field("theta_salinity_corrected_m3m3", pa.float32()),
    pa.field("clay_bias_m3m3", pa.float32()),
    pa.field("salinity_bias_risk", pa.float32()),

    # Transferable forms, precomputed because every model wants at least one.
    pa.field("saturation", pa.float32()),
    pa.field("plant_available_fraction", pa.float32()),
    pa.field("storage_mm", pa.float32()),

    pa.field("soil_temp_c", pa.float32()),
    pa.field("ec_bulk_ds_m", pa.float32()),

    pa.field("method", pa.string(), nullable=False),
    pa.field("quality_flag", pa.string(), nullable=False),
    pa.field("uncertainty_m3m3", pa.float32(),
             metadata={b"doc": b"1-sigma; larger for digitized and for suspect records"}),
    pa.field("is_interpolated", pa.bool_()),

    # Provenance for literature-derived rows.
    pa.field("study_id", pa.string()),
    pa.field("figure_ref", pa.string()),
    pa.field("extraction_method", pa.string()),

    # Partition keys, materialized as columns so a reader can filter without
    # relying on directory layout.
    pa.field("year", pa.int16(), nullable=False),
    pa.field("network", pa.string()),
])


# --------------------------------------------------------------------------
# Fact: daily weather
# --------------------------------------------------------------------------

WEATHER_SCHEMA = pa.schema([
    pa.field("site_id", pa.string(), nullable=False),
    pa.field("date", pa.date32(), nullable=False),
    pa.field("source_id", pa.string(), nullable=False),
    pa.field("precip_mm", pa.float32()),
    pa.field("tmax_c", pa.float32()),
    pa.field("tmin_c", pa.float32()),
    pa.field("tmean_c", pa.float32()),
    pa.field("tdew_c", pa.float32()),
    pa.field("rh_mean_pct", pa.float32()),
    pa.field("rh_max_pct", pa.float32()),
    pa.field("rh_min_pct", pa.float32()),
    pa.field("wind_2m_ms", pa.float32()),
    pa.field("srad_mj_m2", pa.float32()),
    pa.field("et0_mm", pa.float32()),
    pa.field("et0_method", pa.string()),
    pa.field("snow_mm", pa.float32()),
    pa.field("year", pa.int16(), nullable=False),
])


# --------------------------------------------------------------------------
# Fact: irrigation events
# --------------------------------------------------------------------------

IRRIGATION_SCHEMA = pa.schema([
    pa.field("site_id", pa.string(), nullable=False),
    pa.field("date", pa.date32(), nullable=False),
    pa.field("amount_mm", pa.float32()),
    pa.field("method", pa.string()),
    pa.field("evidence", pa.string(),
             metadata={b"doc": b"reported | inferred_from_soil_moisture | inferred_from_remote_sensing"}),
    pa.field("confidence", pa.float32()),
    pa.field("source_id", pa.string()),
    pa.field("year", pa.int16(), nullable=False),
])


# --------------------------------------------------------------------------
# Dimension: literature study
# --------------------------------------------------------------------------

STUDY_SCHEMA = pa.schema([
    pa.field("study_id", pa.string(), nullable=False),
    pa.field("doi", pa.string()),
    pa.field("title", pa.string()),
    pa.field("authors", pa.string()),
    pa.field("year", pa.int16()),
    pa.field("venue", pa.string()),
    pa.field("openalex_id", pa.string()),
    pa.field("oa_status", pa.string()),
    pa.field("pdf_path", pa.string()),
    pa.field("licence", pa.string()),
    pa.field("text_mining_allowed", pa.bool_()),
    pa.field("screened", pa.bool_()),
    pa.field("relevant", pa.bool_()),
    pa.field("screening_reason", pa.string()),
    pa.field("has_extractable_data", pa.bool_()),
    pa.field("data_location", pa.string(),
             metadata={b"doc": b"repository | table | figure | supplement | none"}),
    pa.field("n_figures_digitized", pa.int32()),
    pa.field("n_observations_extracted", pa.int64()),
])


# --------------------------------------------------------------------------
# Fact: digitized series (raw output of figure extraction, before harmonization)
# --------------------------------------------------------------------------

DIGITIZED_SERIES_SCHEMA = pa.schema([
    pa.field("series_id", pa.string(), nullable=False),
    pa.field("study_id", pa.string(), nullable=False),
    pa.field("figure_ref", pa.string()),
    pa.field("panel", pa.string()),
    pa.field("series_label", pa.string()),
    pa.field("x_values", pa.list_(pa.float64())),
    pa.field("y_values", pa.list_(pa.float64())),
    pa.field("x_variable", pa.string()),
    pa.field("y_variable", pa.string()),
    pa.field("x_unit", pa.string()),
    pa.field("y_unit", pa.string()),
    pa.field("depth_top_cm", pa.float32()),
    pa.field("depth_bottom_cm", pa.float32()),
    pa.field("extraction_method", pa.string(),
             metadata={b"doc": b"pdf_vector_paths | raster_colour_trace | raster_marker_detect | vlm | manual"}),
    pa.field("axis_calibration_rmse_px", pa.float32()),
    pa.field("y_uncertainty_data_units", pa.float32()),
    pa.field("n_points", pa.int32()),
    pa.field("validated", pa.bool_()),
    pa.field("validation_notes", pa.string()),
])


@dataclass(frozen=True)
class TableSpec:
    """One physical table: its schema, where it lives, how it is partitioned."""

    name: str
    schema: pa.Schema
    partition_cols: tuple[str, ...]
    primary_key: tuple[str, ...]


TABLES: dict[str, TableSpec] = {
    "sites": TableSpec("sites", SITE_SCHEMA, (), ("site_id",)),
    "sensors": TableSpec("sensors", SENSOR_SCHEMA, (), ("sensor_id",)),
    "sources": TableSpec("sources", SOURCE_SCHEMA, (), ("source_id",)),
    # Partitioned by network then year: the two filters essentially every query
    # applies, and the combination that keeps a partition to a workable size
    # without producing the tens of thousands of tiny files that a site-level
    # partition would.
    "observations": TableSpec("observations", OBSERVATION_SCHEMA, ("network", "year"),
                              ("observation_key",)),
    "weather": TableSpec("weather", WEATHER_SCHEMA, ("year",), ("site_id", "date", "source_id")),
    "irrigation": TableSpec("irrigation", IRRIGATION_SCHEMA, ("year",), ("site_id", "date")),
    "studies": TableSpec("studies", STUDY_SCHEMA, (), ("study_id",)),
    "digitized_series": TableSpec("digitized_series", DIGITIZED_SERIES_SCHEMA, (), ("series_id",)),
}


#: Uncertainty (1-sigma, m3/m3) assumed for each observation method when the
#: source reports none. These become sample weights during training: a value
#: digitized off a small figure should not carry the same weight as a
#: gravimetric sample.
METHOD_UNCERTAINTY: dict[str, float] = {
    ObservationMethod.GRAVIMETRIC: 0.010,
    ObservationMethod.LYSIMETER: 0.010,
    ObservationMethod.NEUTRON_PROBE: 0.015,
    ObservationMethod.TDR: 0.020,
    ObservationMethod.HEAT_PULSE: 0.025,
    ObservationMethod.IMPEDANCE: 0.030,
    ObservationMethod.FDR_CAPACITANCE: 0.035,
    ObservationMethod.COSMIC_RAY: 0.035,
    ObservationMethod.GPR: 0.040,
    ObservationMethod.TENSIOMETER_DERIVED: 0.045,
    ObservationMethod.PUBLISHED_TABLE: 0.020,
    ObservationMethod.DIGITIZED_FIGURE: 0.030,
    ObservationMethod.REMOTE_SENSING: 0.050,
    ObservationMethod.MODEL_OUTPUT: 0.060,
    ObservationMethod.UNKNOWN: 0.060,
}
