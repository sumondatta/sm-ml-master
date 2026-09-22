"""Connector interface.

A connector turns one external service into rows matching a table in
:mod:`smml.db.schema`. Everything else about the harvest — caching, rate
limiting, retry, idempotent writes — is handled by the infrastructure, so a
connector is only responsible for the part that is specific to its source:
constructing requests, parsing the response, and converting units.

Three rules hold across all of them.

**Return the schema's units.** Volumetric water content in m3/m3, precipitation
in mm, depth in cm, time in UTC. A connector that returns a source's native
units pushes the conversion onto every downstream consumer and it will
eventually be done twice or not at all.

**Never silently drop a record.** A value that fails parsing is returned with a
quality flag, not discarded. The QC layer decides what to do with it.

**Declare the licence.** ``licence`` and ``redistributable`` are required,
because whether the harvested rows may be republished is a per-source question
with genuinely different answers, and the only workable time to record it is at
ingest.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from ..util.http import PoliteSession

log = logging.getLogger(__name__)


@dataclass
class HarvestResult:
    """What one connector call produced."""

    sites: pd.DataFrame = field(default_factory=pd.DataFrame)
    sensors: pd.DataFrame = field(default_factory=pd.DataFrame)
    observations: pd.DataFrame = field(default_factory=pd.DataFrame)
    weather: pd.DataFrame = field(default_factory=pd.DataFrame)
    irrigation: pd.DataFrame = field(default_factory=pd.DataFrame)
    errors: list[str] = field(default_factory=list)

    def __add__(self, other: HarvestResult) -> HarvestResult:
        def cat(a: pd.DataFrame, b: pd.DataFrame) -> pd.DataFrame:
            frames = [f for f in (a, b) if not f.empty]
            return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

        return HarvestResult(
            sites=cat(self.sites, other.sites),
            sensors=cat(self.sensors, other.sensors),
            observations=cat(self.observations, other.observations),
            weather=cat(self.weather, other.weather),
            irrigation=cat(self.irrigation, other.irrigation),
            errors=self.errors + other.errors,
        )

    def summary(self) -> dict[str, int]:
        return {
            "sites": len(self.sites),
            "sensors": len(self.sensors),
            "observations": len(self.observations),
            "weather": len(self.weather),
            "irrigation": len(self.irrigation),
            "errors": len(self.errors),
        }


class Connector(ABC):
    """One external data source."""

    #: Identifier matching the entry in :mod:`smml.registry`.
    short_id: str = "base"
    #: Which schema table this connector populates.
    produces: str = "observations"
    #: SPDX-style licence identifier or a short description. Required.
    licence: str = "unknown"
    #: Whether the harvested rows may be redistributed, as opposed to used locally.
    redistributable: bool = False
    #: Citation to propagate into the sources table.
    citation: str = ""

    def __init__(self, session: PoliteSession | None = None, **options: Any) -> None:
        self.session = session or PoliteSession()
        self.options = options

    @property
    def registry_entry(self) -> dict[str, Any]:
        """The catalogue entry for this source, if one exists."""
        from .. import registry

        try:
            return registry.source(self.short_id)
        except KeyError:
            return {}

    @abstractmethod
    def fetch(self, **kwargs: Any) -> HarvestResult:
        """Retrieve and parse. Implementations document their own arguments."""

    def source_row(self, **extra: Any) -> dict[str, Any]:
        """The row describing this source for the sources dimension table."""
        entry = self.registry_entry
        row = {
            "source_id": self.short_id,
            "name": entry.get("name", self.short_id),
            "category": entry.get("category"),
            "url": entry.get("base_url"),
            "licence": self.licence,
            "redistributable": self.redistributable,
            "citation": self.citation,
            "version": entry.get("version", ""),
        }
        row.update(extra)
        return row


class PointQueryConnector(Connector):
    """A connector that answers one coordinate at a time.

    Most soil and weather services work this way. Harvesting thousands of sites
    then means thousands of requests, which the caching layer makes survivable
    across re-runs but which still has to be paced; :meth:`fetch_many` does the
    pacing and, crucially, keeps going when an individual point fails rather than
    losing the whole batch to one bad coordinate.
    """

    @abstractmethod
    def fetch_point(self, lat: float, lon: float, **kwargs: Any) -> HarvestResult:
        ...

    def fetch(self, **kwargs: Any) -> HarvestResult:
        return self.fetch_point(**kwargs)

    def fetch_many(
        self,
        points: pd.DataFrame,
        lat_col: str = "lat",
        lon_col: str = "lon",
        id_col: str | None = "site_id",
        progress: bool = True,
        **kwargs: Any,
    ) -> HarvestResult:
        """Query a table of coordinates, accumulating results and errors."""
        total = HarvestResult()
        iterator = points.itertuples(index=False)
        if progress:
            try:
                from tqdm import tqdm

                iterator = tqdm(iterator, total=len(points), desc=self.short_id)
            except ImportError:
                pass

        for row in iterator:
            lat = getattr(row, lat_col)
            lon = getattr(row, lon_col)
            identifier = getattr(row, id_col) if id_col and hasattr(row, id_col) else None
            try:
                result = self.fetch_point(lat=lat, lon=lon, site_id=identifier, **kwargs)
            except Exception as exc:  # noqa: BLE001 - one bad point must not end the harvest
                message = f"{self.short_id} {identifier or (lat, lon)}: {type(exc).__name__}: {exc}"
                log.warning(message)
                total.errors.append(message)
                continue
            total = total + result
        return total
