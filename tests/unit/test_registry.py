"""Registry integrity tests.

The registry is data, not code, so nothing type-checks it. These assert the
invariants the rest of the project relies on: that identifiers are unique and
usable as Python names, that every entry declares how confident it is, and that
the irrigation classification — which is the axis this whole project is
organized around — is consistent with the prose it was derived from.
"""

from __future__ import annotations

import re

import pytest

from smml import registry

VALID_CATEGORIES = {
    "in_situ_network", "soil_property", "weather_forcing",
    "irrigation_extent", "remote_sensing", "repository", "literature_api",
}
IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")


def test_registry_is_populated():
    summary = registry.summary()
    assert summary["n_sources"] > 150
    assert summary["n_studies"] > 80
    assert summary["n_techniques"] > 20


def test_source_ids_are_unique():
    ids = [s["short_id"] for s in registry.sources()]
    duplicates = {i for i in ids if ids.count(i) > 1}
    assert not duplicates, duplicates


def test_source_ids_are_valid_python_identifiers():
    """They are used as module names and as dict keys throughout."""
    bad = [s["short_id"] for s in registry.sources() if not IDENTIFIER.match(s["short_id"])]
    assert not bad, bad


def test_every_source_declares_a_known_category():
    bad = [(s["short_id"], s.get("category")) for s in registry.sources()
           if s.get("category") not in VALID_CATEGORIES]
    assert not bad, bad


def test_every_source_declares_its_confidence():
    """A `recalled` endpoint has to be verifiable as such before anyone relies on it."""
    bad = [s["short_id"] for s in registry.sources()
           if s.get("confidence") not in {"confirmed", "recalled", "uncertain"}]
    assert not bad, bad


def test_every_source_declares_a_priority():
    bad = [s["short_id"] for s in registry.sources() if s.get("priority") not in (1, 2, 3)]
    assert not bad, bad


def test_no_source_has_a_placeholder_url():
    """A fabricated endpoint is worse than an absent one."""
    bad = [
        s["short_id"] for s in registry.sources()
        if str(s.get("base_url", "")).strip().lower() in
        {"", "n/a", "todo", "example.com", "http://example.com"}
    ]
    assert not bad, bad


def test_lookup_by_id_works_and_raises_on_a_typo():
    assert registry.source("nasa_power")["category"] == "weather_forcing"
    with pytest.raises(KeyError):
        registry.source("no_such_source")


def test_filtering_by_category_and_priority():
    soils = registry.sources(category="soil_property", max_priority=1)
    assert soils
    assert all(s["category"] == "soil_property" and s["priority"] == 1 for s in soils)


# --------------------------------------------------------------------------
# Networks and irrigation — the axis the project turns on
# --------------------------------------------------------------------------


def test_networks_are_catalogued():
    assert len(registry.networks()) > 50


def test_irrigated_and_rainfed_sets_are_disjoint_and_non_empty():
    irrigated = {s["short_id"] for s in registry.networks(irrigated=True)}
    rainfed = {s["short_id"] for s in registry.networks(irrigated=False)}
    assert irrigated and rainfed
    assert not (irrigated & rainfed)


def test_the_obvious_irrigation_networks_are_classified_as_irrigated():
    """CIMIS and AZMET exist to schedule irrigation; if they are not in this set
    the classifier has regressed."""
    irrigated = {s["short_id"] for s in registry.networks(irrigated=True)}
    assert {"cimis", "azmet", "scan"} <= irrigated


def test_networks_sited_away_from_agriculture_are_not_marked_irrigated():
    """SNOTEL is alpine headwaters and USCRN is deliberately sited on unmanaged
    ground; both mention irrigation in their notes and neither is irrigated."""
    rainfed = {s["short_id"] for s in registry.networks(irrigated=False)}
    assert {"snotel", "uscrn", "neon"} <= rainfed


def test_every_network_carries_an_irrigation_verdict():
    bad = [s["short_id"] for s in registry.networks()
           if s.get("irrigated_stations") not in {"yes", "no", "unknown"}]
    assert not bad, bad


def test_repositories_are_not_filed_as_networks():
    """Zenodo and PANGAEA host data; they do not measure it."""
    network_ids = {s["short_id"] for s in registry.networks()}
    assert not ({"zenodo", "dryad", "pangaea", "hydroshare", "ornl_daac"} & network_ids)


# --------------------------------------------------------------------------
# Studies
# --------------------------------------------------------------------------


def test_studies_split_into_open_data_and_figure_only():
    open_data = registry.studies(with_open_data=True)
    figure_only = registry.studies(figure_only=True)
    assert len(open_data) > 20
    assert len(figure_only) > 20


def test_every_study_states_its_data_availability():
    bad = [s.get("citation", "?")[:40] for s in registry.studies()
           if not str(s.get("data_availability", "")).strip()]
    assert not bad, bad


def test_techniques_carry_an_implementation_recipe():
    """A technique entry without a `how` is a note, not something to code from."""
    bad = [t["name"] for t in registry.techniques(max_priority=1)
           if len(str(t.get("how", ""))) < 200]
    assert not bad, bad
