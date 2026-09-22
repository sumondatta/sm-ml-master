"""Tests for grey-literature discovery: triage, repositories, multilingual terms."""

from __future__ import annotations

import pandas as pd
import pytest

from smml.litmine.multilingual import (
    SKIP_LANGUAGES,
    TERMS,
    agrovoc_sparql_query,
    ascii_fold,
    build_query,
    normalize,
    normalize_arabic,
    normalize_persian,
    normalize_turkish,
    query_terms,
    variants,
)
from smml.litmine.repositories import (
    DATAVERSE_INSTANCES,
    SEED_REPOSITORIES,
    OaiHarvester,
)
from smml.litmine.triage import (
    GENRE_PRIOR,
    detect_genre,
    score_document,
    triage,
    yield_estimate,
)

# --------------------------------------------------------------------------
# Triage
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("PhD dissertation", "thesis_phd"),
        ("Doctoral thesis", "thesis_phd"),
        ("M.Sc. thesis", "thesis_msc"),
        ("thesis submitted to the faculty", "thesis_msc"),
        ("Kansas Agricultural Experiment Station Research Report", "experiment_station_report"),
        ("Field Day Report", "field_day_report"),
        ("IAEA-TECDOC-1137", "iaea_tecdoc"),
        ("A review of dielectric sensing", "review"),
        ("extension fact sheet", "extension_factsheet"),
        ("something else entirely", "unknown"),
    ],
)
def test_genre_detection(text, expected):
    assert detect_genre(text) == expected


def test_a_thesis_with_a_neutron_probe_and_an_appendix_scores_highest():
    result = score_document(
        "1", title="Soil water dynamics under subsurface drip irrigated cotton",
        abstract="Neutron probe access tubes were read at 15 cm increments to 180 cm. "
                 "Raw data are given in Appendix C.",
        genre_hint="PhD dissertation",
    )
    assert result.score > 0.9
    assert result.genre == "thesis_phd"
    assert "instrument" in result.signals


def test_a_modelling_paper_scores_low_despite_being_about_soil_moisture():
    """Relevance and data-bearing are different questions; this paper consumes data."""
    result = score_document(
        "2", title="Machine learning prediction of root zone soil moisture from SMAP",
        abstract="We train a random forest on satellite retrievals.",
        genre_hint="journal article",
    )
    assert result.score < 0.15
    assert result.signals.get("data_consumer", 0) < 0


def test_a_review_scores_near_zero():
    result = score_document("3", title="A review of soil moisture sensing technologies",
                            genre_hint="review")
    assert result.score < 0.05


def test_an_extension_factsheet_scores_near_zero():
    """Fact sheets give recommendations, not measurements."""
    result = score_document("4", title="Irrigation scheduling for Florida tomato",
                            genre_hint="extension fact sheet")
    assert result.score < 0.05


def test_full_text_evidence_raises_the_score():
    without = score_document("5", title="Deficit irrigation of maize",
                             genre_hint="journal article")
    with_text = score_document("5", title="Deficit irrigation of maize",
                               genre_hint="journal article",
                               full_text="Appendix B. Soil water content by depth, "
                                         "measured with a neutron probe at 15 cm increments.")
    assert with_text.score > without.score


def test_triage_orders_by_expected_yield():
    documents = pd.DataFrame([
        {"doi": "a", "title": "A review of soil moisture sensors", "abstract": "",
         "type": "review"},
        {"doi": "b", "title": "Profile soil water under furrow irrigation",
         "abstract": "Neutron probe readings at each depth are tabulated in the appendix.",
         "type": "PhD thesis"},
    ])
    ranked = triage(documents)
    assert list(ranked["doi"]) == ["b", "a"]
    assert ranked["table_probability"].is_monotonic_decreasing


def test_triage_on_an_empty_frame():
    assert triage(pd.DataFrame(columns=["doi", "title", "abstract", "type"])).empty


def test_yield_estimate_turns_ranking_into_a_stopping_rule():
    documents = pd.DataFrame([
        {"doi": str(i), "title": "Neutron probe profile appendix" if i < 5 else "A review",
         "abstract": "", "type": "PhD thesis" if i < 5 else "review"}
        for i in range(10)
    ])
    estimate = yield_estimate(triage(documents))
    assert not estimate.empty
    assert {"n_documents", "expected_values", "mean_probability"} <= set(estimate.columns)
    assert estimate["n_documents"].sum() == 10


def test_genre_priors_rank_theses_above_journal_articles():
    """Degree regulations force raw data into appendices that journals strip out."""
    assert GENRE_PRIOR["thesis_phd"] > GENRE_PRIOR["journal_article"]
    assert GENRE_PRIOR["experiment_station_report"] > GENRE_PRIOR["journal_article"]
    assert GENRE_PRIOR["review"] < 0.05


# --------------------------------------------------------------------------
# Multilingual
# --------------------------------------------------------------------------


def test_persian_arabic_character_folding():
    """Iranian databases store the same word both ways; without folding, exact
    matching returns a fraction of what exists."""
    assert normalize_persian("رطوبت خاك") == "رطوبت خاک"
    assert normalize_persian("آبياري") == "آبیاری"


def test_turkish_dotted_i():
    """str.lower() maps I to i; Turkish I lowercases to ı. The classic bug."""
    assert normalize_turkish("KISITLI") == "kısıtlı"
    assert "KISITLI".lower() != normalize_turkish("KISITLI")
    assert normalize_turkish("İRRİGASYON") == "irrigasyon"


def test_arabic_presentation_forms_are_flattened():
    """Scanned-PDF text layers are full of these and they never match otherwise."""
    presentation = "ﻟﺮﻲ"          # presentation forms
    assert normalize_arabic(presentation) != presentation
    assert normalize_arabic("أرض") == "ارض"


def test_ascii_folding():
    assert ascii_fold("yağmurlama") == "yagmurlama"
    assert ascii_fold("irrigação") == "irrigacao"
    assert ascii_fold("aspersión") == "aspersion"


def test_variants_cover_the_zwnj_family():
    """The same Persian compound appears with the joiner, without it, and spaced."""
    got = variants("آبیاری قطره‌ای", "fa")
    assert len(got) >= 3
    assert any("‌" in v for v in got)
    assert any("‌" not in v and " " in v for v in got)


def test_variants_include_an_ascii_form_for_turkish():
    got = variants("yağmurlama sulama", "tr")
    assert "yagmurlama sulama" in got


def test_portuguese_carries_both_orthographies():
    """umidade/humidade and irrigação/rega split on exactly the query words."""
    terms = query_terms("pt")
    joined = " ".join(terms)
    assert "umidade do solo" in joined
    assert "humidade do solo" in joined
    assert "rega" in joined


def test_japanese_carries_all_three_irrigation_orthographies():
    terms = set(TERMS["ja"]["irrigation"])
    assert {"灌漑", "潅漑", "かんがい"} <= terms


def test_chinese_carries_both_moisture_bases():
    terms = set(TERMS["zh"]["moisture"])
    assert "体积含水率" in terms and "质量含水率" in terms


def test_query_terms_refuses_the_languages_that_are_not_worth_targeting():
    """Indian agricultural research publishes in English; the effort belongs elsewhere."""
    assert "hi" in SKIP_LANGUAGES
    with pytest.raises(ValueError, match="deliberately not targeted"):
        query_terms("hi")


def test_query_terms_rejects_an_unknown_language():
    with pytest.raises(KeyError):
        query_terms("xx")


def test_build_query_pairs_moisture_with_irrigation():
    query = build_query("es")
    assert " AND " in query
    assert "humedad del suelo" in query
    assert "riego" in query


@pytest.mark.parametrize("language", sorted(TERMS))
def test_every_language_has_moisture_and_irrigation_terms(language):
    assert TERMS[language].get("moisture")
    assert TERMS[language].get("irrigation")
    assert query_terms(language)


def test_normalize_dispatches_by_language():
    assert normalize("رطوبت خاك", "fa") == "رطوبت خاک"
    assert normalize("KISITLI", "tr") == "kısıtlı"
    assert normalize("  humedad  ", "es") == "humedad"


def test_agrovoc_query_is_well_formed_sparql():
    query = agrovoc_sparql_query("soil water content")
    assert "PREFIX skos:" in query
    assert "skos:prefLabel" in query
    assert "soil water content" in query


# --------------------------------------------------------------------------
# Repositories
# --------------------------------------------------------------------------


def test_seed_repositories_are_well_formed():
    assert len(SEED_REPOSITORIES) >= 10
    ids = [r.short_id for r in SEED_REPOSITORIES]
    assert len(set(ids)) == len(ids)
    for repository in SEED_REPOSITORIES:
        assert repository.oai_url.startswith("http")
        assert repository.platform in {"digital_commons", "dspace", "eprints", "custom"}


def test_digital_commons_and_dspace_use_their_standard_oai_paths():
    """One harvester reaches the whole land-grant tier because of this."""
    for repository in SEED_REPOSITORIES:
        if repository.platform == "digital_commons":
            assert repository.oai_url.endswith("/do/oai/")
        elif repository.platform == "dspace":
            assert "/oai" in repository.oai_url


def test_the_land_grant_tier_is_represented():
    ids = {r.short_id for r in SEED_REPOSITORIES}
    assert {"newprairiepress", "oaktrust", "unl_digitalcommons"} <= ids


def test_cgiar_and_indian_repositories_are_represented():
    ids = {r.short_id for r in SEED_REPOSITORIES}
    assert "cgspace" in ids
    assert {"shodhganga", "krishikosh"} & ids


def test_dataverse_instances_include_icrisat():
    """Patancheru carries neutron-probe profiles at 15 cm increments to 180 cm."""
    ids = {i[0] for i in DATAVERSE_INSTANCES}
    assert "icrisat" in ids


def test_oai_record_parsing():
    from xml.etree import ElementTree

    xml = """<record xmlns="http://www.openarchives.org/OAI/2.0/">
      <header><identifier>oai:x:123</identifier></header>
      <metadata>
        <oai_dc:dc xmlns:oai_dc="http://www.openarchives.org/OAI/2.0/oai_dc/"
                   xmlns:dc="http://purl.org/dc/elements/1.1/">
          <dc:title>Soil water under drip irrigation</dc:title>
          <dc:creator>Datta, S.</dc:creator>
          <dc:date>2019-06-01</dc:date>
          <dc:type>Thesis</dc:type>
          <dc:description>Neutron probe profiles.</dc:description>
          <dc:identifier>https://example.org/item/123</dc:identifier>
        </oai_dc:dc>
      </metadata>
    </record>"""
    parsed = OaiHarvester._parse_record(ElementTree.fromstring(xml), "https://example.org/oai")
    assert parsed["title"] == "Soil water under drip irrigation"
    assert parsed["year"] == "2019"
    assert parsed["type"] == "Thesis"
    assert parsed["url"] == "https://example.org/item/123"


def test_deleted_oai_records_are_skipped():
    from xml.etree import ElementTree

    xml = """<record xmlns="http://www.openarchives.org/OAI/2.0/">
      <header status="deleted"><identifier>oai:x:9</identifier></header>
    </record>"""
    assert OaiHarvester._parse_record(ElementTree.fromstring(xml), "u") is None
