"""The source registry: what exists, where it lives, and how to get it.

Three YAML catalogues compiled from a literature and data-landscape survey:

``sources.yaml``
    Every dataset that can contribute to the database — in-situ networks, soil
    property grids, weather forcings, irrigation extent maps, remote sensing
    products and data repositories — with its access method, endpoint, licence,
    variables, resolution and known quirks.
``techniques.yaml``
    Implementation recipes for the parts of the pipeline that are methods rather
    than data: literature discovery APIs, PDF parsing, figure digitization.
``studies.yaml``
    Specific published studies reporting soil moisture in irrigated fields,
    tagged by whether the data is archived openly, tabulated, or recoverable only
    from figures.

The registry is deliberately data rather than code. New sources appear
constantly, the list will outlive any particular connector, and a catalogue that
a domain expert can edit without touching Python is far more likely to stay
current.

Every entry carries a ``confidence`` field. ``confirmed`` means a search result
corroborated it; ``recalled`` means it comes from model knowledge and the
endpoint should be checked before relying on it. Nothing here has been verified
against a live server, because the environment this was assembled in had no
outbound access to these hosts — treat ``base_url`` as a strong starting point,
not a guarantee.
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Any

import yaml

REGISTRY_DIR = Path(__file__).parent


@functools.cache
def _load(name: str) -> dict[str, Any]:
    path = REGISTRY_DIR / f"{name}.yaml"
    if not path.exists():
        return {}
    with path.open() as fh:
        return yaml.safe_load(fh) or {}


def sources(
    category: str | None = None,
    max_priority: int | None = None,
    access_method: str | None = None,
    min_confidence: str | None = None,
) -> list[dict[str, Any]]:
    """Catalogued data sources, optionally filtered.

    ``category`` is one of ``in_situ_network``, ``soil_property``,
    ``weather_forcing``, ``irrigation_extent``, ``remote_sensing``,
    ``repository``, ``literature_api``.
    """
    items = list(_load("sources").get("sources", []))
    if category:
        items = [s for s in items if s.get("category") == category]
    if max_priority is not None:
        items = [s for s in items if s.get("priority", 9) <= max_priority]
    if access_method:
        items = [s for s in items if access_method.lower() in str(s.get("access_method", "")).lower()]
    if min_confidence == "confirmed":
        items = [s for s in items if s.get("confidence") == "confirmed"]
    return items


def source(short_id: str) -> dict[str, Any]:
    """One source by its identifier."""
    for item in _load("sources").get("sources", []):
        if item.get("short_id") == short_id:
            return item
    raise KeyError(f"unknown source {short_id!r}")


def networks(irrigated: bool | None = None, in_ismn: bool | None = None) -> list[dict[str, Any]]:
    """In-situ soil moisture networks, optionally filtered by irrigation.

    ``irrigated=True`` returns the networks known to have stations on irrigated
    cropland — the ones this project is built around. ``irrigated=False`` returns
    those explicitly sited away from irrigation, which are the rainfed controls a
    model needs in order to learn what irrigation does.

    The classification is derived from each entry's ``irrigated_relevance`` note
    and is deliberately conservative: a network whose siting is not clearly
    stated is left ``unknown`` rather than guessed at. Confirm any of them
    against an irrigation extent map before treating the label as fact.
    """
    items = sources(category="in_situ_network")
    if irrigated is True:
        items = [s for s in items if s.get("irrigated_stations") == "yes"]
    elif irrigated is False:
        items = [s for s in items if s.get("irrigated_stations") == "no"]
    if in_ismn is not None:
        want = "yes" if in_ismn else "no"
        items = [s for s in items if str(s.get("in_ismn", "")).lower().startswith(want)]
    return items


def techniques(max_priority: int | None = None) -> list[dict[str, Any]]:
    items = list(_load("techniques").get("techniques", []))
    if max_priority is not None:
        items = [t for t in items if t.get("priority", 9) <= max_priority]
    return items


def studies(
    with_open_data: bool | None = None,
    figure_only: bool | None = None,
    irrigation_method: str | None = None,
) -> list[dict[str, Any]]:
    """Catalogued published studies.

    ``figure_only`` selects the studies whose numbers exist only as plotted
    lines — the ones the digitization pipeline is for.
    """
    items = list(_load("studies").get("studies", []))
    if with_open_data is not None:
        def has_repo(s: dict) -> bool:
            text = str(s.get("data_availability", "")).lower()
            return any(k in text for k in ("repositor", "zenodo", "dryad", "figshare",
                                           "hydroshare", "pangaea", "open data", "ag data"))
        items = [s for s in items if has_repo(s) == with_open_data]
    if figure_only is not None:
        def fig(s: dict) -> bool:
            return "figure" in str(s.get("data_availability", "")).lower()
        items = [s for s in items if fig(s) == figure_only]
    if irrigation_method:
        items = [s for s in items
                 if irrigation_method.lower() in str(s.get("irrigation_method", "")).lower()]
    return items


def summary() -> dict[str, Any]:
    """Counts by category, priority and confidence — a quick look at coverage."""
    from collections import Counter

    src = sources()
    return {
        "n_sources": len(src),
        "by_category": dict(Counter(s.get("category", "?") for s in src)),
        "by_priority": dict(Counter(s.get("priority", 9) for s in src)),
        "by_confidence": dict(Counter(s.get("confidence", "?") for s in src)),
        "n_techniques": len(techniques()),
        "n_studies": len(studies()),
        "n_studies_open_data": len(studies(with_open_data=True)),
        "n_studies_figure_only": len(studies(figure_only=True)),
        "n_networks": len(networks()),
        "n_networks_irrigated": len(networks(irrigated=True)),
        "n_networks_rainfed_control": len(networks(irrigated=False)),
    }
