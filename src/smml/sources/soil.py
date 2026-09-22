"""Soil property connectors.

Texture is the pivot of this whole project — it is what the model needs, what
determines how much a dielectric sensor is lying, and what almost every study
reports too coarsely to use directly. Two complementary sources are implemented:

:class:`SoilGridsConnector`
    Global, 250 m, free, six standard depth intervals. The only option outside
    the United States and the default everywhere.
:class:`SoilDataAccessConnector`
    USDA SSURGO/gNATSGO via Soil Data Access. Far more detailed than SoilGrids
    in the US — real horizon data from surveyed pedons rather than a global
    model — and, critically for this project, it carries measured **electrical
    conductivity and SAR**, which no global product does.

Both normalize onto the same standard depth intervals so a site can be described
identically regardless of which answered.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

from ..physics.water import STANDARD_LAYERS_CM, saxton_rawls, usda_texture_class
from .base import HarvestResult, PointQueryConnector

log = logging.getLogger(__name__)


class SoilGridsConnector(PointQueryConnector):
    """ISRIC SoilGrids 2.0 point query.

    Three things about this API cause silent errors and are handled explicitly:

    * **Values are stored as integers** and must be divided by a per-property
      factor. The factor is read from each response's ``unit_measure.d_factor``
      rather than hard-coded, because ISRIC has changed it between releases.
    * **Sand, silt and clay do not sum to 100.** They come from independent
      quantile regression forests. They are renormalized here, since every
      downstream texture calculation assumes a closed composition.
    * **The fair-use limit is about five calls a minute** and the service is
      labelled beta with a history of multi-week outages. Past roughly a
      thousand points the cloud-optimized GeoTIFFs are the right access route,
      not this API; :meth:`fetch_many` will work but will take days.
    """

    short_id = "soilgrids_rest"
    produces = "sites"
    licence = "CC-BY-4.0"
    redistributable = True
    citation = (
        "Poggio et al. (2021), SoilGrids 2.0: producing soil information for "
        "the globe with quantified spatial uncertainty, SOIL 7:217-240"
    )

    BASE_URL = "https://rest.isric.org/soilgrids/v2.0/properties/query"
    PROPERTIES = ("clay", "sand", "silt", "bdod", "soc", "cec", "phh2o", "cfvo",
                  "nitrogen", "wv0033", "wv1500")
    DEPTH_LABELS = ("0-5cm", "5-15cm", "15-30cm", "30-60cm", "60-100cm", "100-200cm")

    def fetch_point(
        self,
        lat: float,
        lon: float,
        site_id: str | None = None,
        properties: tuple[str, ...] | None = None,
        depths: tuple[str, ...] | None = None,
        value: str = "mean",
        **kwargs: Any,
    ) -> HarvestResult:
        params: list[tuple[str, Any]] = [
            ("lon", round(float(lon), 6)),
            ("lat", round(float(lat), 6)),
            ("value", value),
        ]
        for prop in properties or self.PROPERTIES:
            params.append(("property", prop))
        for depth in depths or self.DEPTH_LABELS:
            params.append(("depth", depth))

        payload = self.session.get_json(self.BASE_URL, params=params)
        frame = self.parse(payload, lat, lon, site_id)
        return HarvestResult(sites=frame)

    @classmethod
    def parse(
        cls, payload: dict, lat: float, lon: float, site_id: str | None = None
    ) -> pd.DataFrame:
        """Turn a SoilGrids response into one row per standard depth layer."""
        layers = payload.get("properties", {}).get("layers", [])
        if not layers:
            return pd.DataFrame()

        records: dict[str, dict[str, float]] = {}
        for layer in layers:
            name = layer.get("name")
            factor = float(layer.get("unit_measure", {}).get("d_factor", 1) or 1)
            for depth in layer.get("depths", []):
                label = depth.get("label")
                raw = (depth.get("values") or {}).get("mean")
                if raw is None:
                    continue
                records.setdefault(label, {})[name] = float(raw) / factor

        if not records:
            return pd.DataFrame()

        rows = []
        for label, values in records.items():
            top, bottom = cls._parse_depth_label(label)
            sand, silt, clay = (values.get(k) for k in ("sand", "silt", "clay"))
            # Independent models per fraction: renormalize to a closed composition.
            if None not in (sand, silt, clay) and (sand + silt + clay) > 0:
                total = sand + silt + clay
                sand, silt, clay = (100.0 * v / total for v in (sand, silt, clay))
            rows.append({
                "site_id": site_id or f"sg_{lat:.4f}_{lon:.4f}",
                "lat": lat, "lon": lon,
                "depth_top_cm": top, "depth_bottom_cm": bottom,
                "sand_pct_grid": sand, "silt_pct_grid": silt, "clay_pct_grid": clay,
                "bulk_density_grid_g_cm3": values.get("bdod"),
                # SoilGrids reports soil organic carbon in g/kg; organic matter
                # is conventionally SOC / 0.58, and g/kg -> % is another /10.
                "om_pct_grid": (values.get("soc") / 5.8) if values.get("soc") is not None else None,
                "cec_grid": values.get("cec"),
                "coarse_fragments_grid_pct": values.get("cfvo"),
                "ph": values.get("phh2o"),
                # wv0033 / wv1500 arrive as volume percent; the database is m3/m3.
                "field_capacity_m3m3": (values["wv0033"] / 100.0) if "wv0033" in values else None,
                "wilting_point_m3m3": (values["wv1500"] / 100.0) if "wv1500" in values else None,
                "soil_property_source": "soilgrids",
            })

        frame = pd.DataFrame(rows).sort_values("depth_top_cm").reset_index(drop=True)
        return _add_derived(frame, sand_col="sand_pct_grid", clay_col="clay_pct_grid",
                            om_col="om_pct_grid")

    @staticmethod
    def _parse_depth_label(label: str) -> tuple[float, float]:
        cleaned = label.replace("cm", "")
        top, _, bottom = cleaned.partition("-")
        return float(top), float(bottom)


class SoilDataAccessConnector(PointQueryConnector):
    """USDA-NRCS Soil Data Access — SSURGO / STATSGO2 / gNATSGO tabular queries.

    The only implemented source carrying **measured salinity** (``ec_r``, the
    saturation-extract EC, and ``sar_r``), which makes it the one that can
    populate the salinity flags for US sites from data rather than inference.

    Two aggregation steps are unavoidable and both are done here, because
    getting them wrong is the standard way SSURGO is misused:

    1. A map unit contains several *components* with different soils. Properties
       are aggregated as a component-percentage weighted mean, so a minor
       inclusion cannot dominate the answer.
    2. Components are described by genetic *horizons* at irregular depths. These
       are depth-weighted onto the project's standard intervals.

    Unit conversions that routinely trip people up are applied explicitly:
    ``ksat_r`` is micrometres per second, not cm/hr; ``wthirdbar_r`` and
    ``wfifteenbar_r`` are volumetric percent, not fractions.
    """

    short_id = "usda_sda"
    produces = "sites"
    licence = "public domain (USDA-NRCS)"
    redistributable = True
    citation = "Soil Survey Staff, USDA-NRCS, Soil Data Access"

    BASE_URL = "https://SDMDataAccess.sc.egov.usda.gov/Tabular/post.rest"

    QUERY_TEMPLATE = """
SELECT
    p.lat, p.lon, m.mukey, c.cokey, c.comppct_r, c.compname,
    h.hzdept_r, h.hzdepb_r,
    h.sandtotal_r, h.silttotal_r, h.claytotal_r, h.om_r,
    h.dbthirdbar_r, h.ksat_r, h.awc_r,
    h.wthirdbar_r, h.wfifteenbar_r,
    h.ec_r, h.sar_r, h.caco3_r, h.gypsum_r, h.cec7_r, h.ph1to1h2o_r
FROM ({points}) AS p
CROSS APPLY SDA_Get_Mukey_from_intersection_with_WktWgs84(p.wkt) AS m(mukey)
INNER JOIN component AS c ON c.mukey = m.mukey
INNER JOIN chorizon  AS h ON h.cokey = c.cokey
WHERE c.comppct_r IS NOT NULL AND h.hzdept_r IS NOT NULL
"""

    def fetch_point(self, lat: float, lon: float, site_id: str | None = None, **kwargs: Any):
        points = pd.DataFrame([{"lat": lat, "lon": lon, "site_id": site_id or f"sda_{lat:.4f}_{lon:.4f}"}])
        return self.fetch_batch(points)

    def fetch_batch(
        self,
        points: pd.DataFrame,
        lat_col: str = "lat",
        lon_col: str = "lon",
        id_col: str = "site_id",
        chunk_size: int = 200,
    ) -> HarvestResult:
        """Query many points per request.

        Soil Data Access caps a response at 100,000 records and 32 MB, and a
        single point can return dozens of horizon rows, so the point list is
        chunked. Batching is not an optimization here — point-at-a-time querying
        of a few thousand sites takes hours and is a poor use of a shared public
        service.
        """
        total = HarvestResult()
        for start in range(0, len(points), chunk_size):
            chunk = points.iloc[start : start + chunk_size]
            values = ", ".join(
                f"('{row[id_col]}', {float(row[lat_col])}, {float(row[lon_col])}, "
                f"'point({float(row[lon_col])} {float(row[lat_col])})')"
                for _, row in chunk.iterrows()
            )
            inner = f"SELECT * FROM (VALUES {values}) AS t(site_id, lat, lon, wkt)"
            query = self.QUERY_TEMPLATE.format(points=inner)
            payload = self.session.request(
                "POST", self.BASE_URL,
                json_body={"query": query, "format": "JSON+COLUMNNAME"},
            )
            import json as _json

            parsed = _json.loads(payload)
            total = total + HarvestResult(sites=self.parse(parsed, chunk, id_col))
        return total

    @classmethod
    def parse(cls, payload: dict, points: pd.DataFrame, id_col: str = "site_id") -> pd.DataFrame:
        table = payload.get("Table")
        if not table or len(table) < 2:
            return pd.DataFrame()
        frame = pd.DataFrame(table[1:], columns=table[0])
        numeric = [c for c in frame.columns if c not in ("compname", "mukey", "cokey")]
        for col in numeric:
            frame[col] = pd.to_numeric(frame[col], errors="coerce")

        rows = []
        for (lat, lon), group in frame.groupby(["lat", "lon"]):
            match = points[
                (points["lat"].round(6) == round(float(lat), 6))
                & (points["lon"].round(6) == round(float(lon), 6))
            ]
            site_id = match[id_col].iloc[0] if len(match) else f"sda_{lat:.4f}_{lon:.4f}"
            for top, bottom in STANDARD_LAYERS_CM:
                rows.append(cls._aggregate_layer(group, site_id, lat, lon, top, bottom))
        result = pd.DataFrame([r for r in rows if r is not None])
        if result.empty:
            return result
        return _add_derived(result, sand_col="sand_pct", clay_col="clay_pct", om_col="om_pct")

    @staticmethod
    def _aggregate_layer(group, site_id, lat, lon, top, bottom) -> dict | None:
        """Component-weighted, depth-weighted aggregation onto one standard layer."""
        overlap = (
            np.minimum(group["hzdepb_r"], bottom) - np.maximum(group["hzdept_r"], top)
        ).clip(lower=0)
        weight = overlap * group["comppct_r"].fillna(0)
        if weight.sum() <= 0:
            return None

        def wmean(column: str, scale: float = 1.0) -> float | None:
            values = group[column]
            ok = values.notna() & (weight > 0)
            if not ok.any():
                return None
            return float((values[ok] * weight[ok]).sum() / weight[ok].sum() * scale)

        return {
            "site_id": site_id, "lat": float(lat), "lon": float(lon),
            "depth_top_cm": float(top), "depth_bottom_cm": float(bottom),
            "sand_pct": wmean("sandtotal_r"),
            "silt_pct": wmean("silttotal_r"),
            "clay_pct": wmean("claytotal_r"),
            "om_pct": wmean("om_r"),
            "bulk_density_g_cm3": wmean("dbthirdbar_r"),
            # ksat_r is micrometres per second. To mm/h: 1e-3 mm/um * 3600 s/h.
            "ksat_mm_h": wmean("ksat_r", scale=3.6),
            # wthirdbar_r / wfifteenbar_r are volumetric PERCENT.
            "field_capacity_m3m3": wmean("wthirdbar_r", scale=0.01),
            "wilting_point_m3m3": wmean("wfifteenbar_r", scale=0.01),
            # NULL ec_r means "never measured", not "not saline"; it stays NULL.
            "ec_bulk_ds_m": wmean("ec_r"),
            "ece_ds_m": wmean("ec_r"),
            "ph": wmean("ph1to1h2o_r"),
            "soil_property_source": "ssurgo",
        }


def _add_derived(
    frame: pd.DataFrame, sand_col: str, clay_col: str, om_col: str | None = None
) -> pd.DataFrame:
    """Fill texture class and any missing hydraulic properties by pedotransfer.

    A measured value always wins; Saxton-Rawls only fills gaps. The source of
    each property stays recorded so that a model can be restricted to measured
    inputs if that turns out to matter.
    """
    out = frame.copy()
    if sand_col not in out or clay_col not in out:
        return out
    sand = out[sand_col].to_numpy(dtype=float)
    clay = out[clay_col].to_numpy(dtype=float)
    om = out[om_col].fillna(2.0).to_numpy(dtype=float) if om_col and om_col in out else np.full(len(out), 2.0)

    out["texture_class"] = usda_texture_class(sand, clay)
    ptf = saxton_rawls(sand, clay, om)
    for column, key in (
        ("wilting_point_m3m3", "wilting_point_m3m3"),
        ("field_capacity_m3m3", "field_capacity_m3m3"),
        ("porosity_m3m3", "porosity_m3m3"),
        ("ksat_mm_h", "ksat_mm_h"),
    ):
        estimate = pd.Series(ptf[key], index=out.index)
        out[column] = out[column].fillna(estimate) if column in out else estimate
    if "salinity_class" not in out and "ece_ds_m" in out:
        from ..physics.dielectric import salinity_class

        out["salinity_class"] = salinity_class(out["ece_ds_m"].to_numpy(dtype=float))
    return out


SOIL_CONNECTORS = {
    "soilgrids_rest": SoilGridsConnector,
    "usda_sda": SoilDataAccessConnector,
}
