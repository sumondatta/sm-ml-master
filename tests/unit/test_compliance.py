"""Compliance policy tests.

The policy is deliberately conservative and these tests pin that down: unknown
means deny for redistribution, non-commercial means local-only, and a shadow
library is refused whatever licence is claimed for the item.
"""

from __future__ import annotations

import pandas as pd
import pytest

from smml.litmine.compliance import (
    Action,
    Verdict,
    attribution_manifest,
    compliance_report,
    counsel_checklist,
    decide,
    gate,
    normalize_licence,
    permitted,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("CC-BY-4.0", "cc-by"),
        ("CC BY 4.0 International", "cc-by"),
        ("Creative Commons Attribution 4.0", "cc-by"),
        ("cc-by-nc-4.0", "cc-by-nc"),
        ("CC-BY-SA-3.0", "cc-by-sa"),
        ("CC0 1.0", "cc0"),
        ("public domain (NASA)", "public domain"),
        ("All rights reserved", "all rights reserved"),
        ("", "unknown"),
        (None, "unknown"),
        ("some bespoke terms nobody has seen", "unknown"),
    ],
)
def test_licence_normalization(text, expected):
    assert normalize_licence(text) == expected


def test_non_commercial_permits_analysis_but_not_republication():
    assert decide(Action.EXTRACT.value, "CC-BY-NC-4.0").permitted
    assert decide(Action.REDISTRIBUTE.value, "CC-BY-NC-4.0").verdict == Verdict.LOCAL_ONLY.value


def test_attribution_licences_are_flagged_as_requiring_it():
    decision = decide(Action.REDISTRIBUTE.value, "CC-BY-4.0")
    assert decision.permitted
    assert decision.requires_attribution


def test_public_domain_is_unconditionally_allowed():
    for action in Action:
        assert decide(action.value, "public domain (NASA)").permitted


def test_unknown_licence_denies_republication():
    """A licence nobody recorded is not a licence to publish."""
    assert decide(Action.REDISTRIBUTE.value, None).verdict == Verdict.DENY.value
    assert decide(Action.REDISTRIBUTE.value, "").verdict == Verdict.DENY.value


def test_all_rights_reserved_denies_republication_and_flags_the_rest_for_review():
    assert decide(Action.REDISTRIBUTE.value, "All rights reserved").verdict == Verdict.DENY.value
    assert decide(Action.FETCH.value, "All rights reserved").verdict == Verdict.REVIEW.value


def test_research_use_licences_permit_fetch_and_extract():
    """What most in-situ networks actually grant."""
    licence = "free for research; attribution and registration required"
    assert decide(Action.FETCH.value, licence).permitted
    assert decide(Action.EXTRACT.value, licence).permitted
    assert decide(Action.REDISTRIBUTE.value, licence).verdict == Verdict.LOCAL_ONLY.value


@pytest.mark.parametrize("host", ["sci-hub.se", "libgen.rs", "z-lib.org"])
def test_shadow_libraries_are_refused_whatever_licence_is_claimed(host):
    """Not lawful access under any TDM exception, and using one voids the
    exception for everything derived from it."""
    for action in Action:
        decision = decide(action.value, "CC-BY-4.0", f"https://{host}/10.1/x")
        assert decision.verdict == Verdict.DENY.value
        assert not decision.permitted


def test_gate_annotates_without_dropping_rows():
    """A denied item still belongs in the coverage accounting, and a licence can change."""
    items = pd.DataFrame([{"licence": "CC-BY-4.0", "url": "https://a"},
                          {"licence": None, "url": "https://b"}])
    out = gate(items, Action.REDISTRIBUTE.value)
    assert len(out) == len(items)
    assert "redistribute_verdict" in out.columns
    assert "redistribute_reason" in out.columns


def test_permitted_filters_to_the_allowed_subset():
    items = pd.DataFrame([{"licence": "CC0", "url": "https://a"},
                          {"licence": "All rights reserved", "url": "https://b"}])
    assert len(permitted(items, Action.REDISTRIBUTE.value)) == 1


def test_report_covers_all_three_actions():
    items = pd.DataFrame([{"licence": "CC-BY-4.0", "url": "https://a"}])
    report = compliance_report(items)
    assert set(report["action"]) == {a.value for a in Action}
    assert report["verdict"].isin([v.value for v in Verdict]).all()


def test_verdicts_are_plain_strings_not_enum_reprs():
    """A str-Enum member stringifies as 'Verdict.ALLOW' under Python 3.11, which
    leaked into every report before the policy table stored values."""
    items = pd.DataFrame([{"licence": "CC-BY-4.0", "url": "https://a"}])
    verdicts = set(compliance_report(items)["verdict"])
    assert not any(v.startswith("Verdict.") for v in verdicts)


def test_attribution_manifest_lists_only_what_needs_crediting():
    items = pd.DataFrame([
        {"name": "a", "licence": "CC-BY-4.0", "citation": "A et al."},
        {"name": "b", "licence": "CC0", "citation": "B et al."},
        {"name": "c", "licence": "All rights reserved", "citation": "C et al."},
    ])
    manifest = attribution_manifest(items)
    assert list(manifest["name"]) == ["a"]


def test_counsel_checklist_is_not_empty():
    """The area is not settled by a licence string, and pretending otherwise is
    the failure mode this list exists to prevent."""
    questions = counsel_checklist()
    assert len(questions) >= 5
    assert all(q.endswith("?") for q in questions)


def test_the_registry_itself_passes_through_the_gate():
    """Every catalogued source must get a decidable verdict."""
    from smml import registry

    items = pd.DataFrame(registry.sources())
    out = gate(items, Action.REDISTRIBUTE.value)
    assert len(out) == len(items)
    assert out["redistribute_verdict"].isin([v.value for v in Verdict]).all()
