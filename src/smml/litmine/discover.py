"""Finding the literature and the datasets attached to it.

The corpus is assembled in three passes, in decreasing order of how good the
data is when you get it:

1. **Repositories.** DataCite, Zenodo, Dryad and the rest already hold the
   numbers, in machine-readable form, with a licence. Always search here first —
   a dataset found this way costs nothing to ingest and carries no digitization
   error. Roughly half the studies in the registry turn out to have one.
2. **Full text.** Europe PMC serves JATS XML for open-access articles, which
   contains tables as markup rather than as pictures of numbers. Its ``FIG:``
   query prefix searches figure captions specifically, which is the most direct
   way there is to find papers that plot soil moisture.
3. **Figures.** Whatever is left is a picture, and goes to
   :mod:`smml.litmine.digitize`.

Two current details that break older code and are handled here: **OpenAlex now
requires an API key** (since February 2026; the old ``mailto`` polite-pool
parameter is ignored), and **Zenodo caps search at 30 requests per minute** for
anonymous and authenticated callers alike.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from ..util.http import PoliteSession

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# Query construction
# --------------------------------------------------------------------------

#: Ways the literature refers to the measurement. OpenAlex does **not** support
#: wildcards, so every morphological variant has to be enumerated.
MOISTURE_TERMS = (
    "soil moisture", "soil water content", "volumetric water content",
    "soil water storage", "profile water content", "soil moisture content",
    "soil water depletion", "root zone soil moisture", "gravimetric water content",
)

IRRIGATION_TERMS = (
    "irrigation", "irrigated", "irrigating", "irrigate",
    "center pivot", "centre pivot", "drip irrigation", "subsurface drip",
    "sprinkler irrigation", "furrow irrigation", "flood irrigation",
    "deficit irrigation", "supplemental irrigation", "border irrigation",
    "variable rate irrigation", "irrigation scheduling",
)

DEPTH_TERMS = (
    "soil depth", "depth increments", "multi-depth", "soil profile",
    "0-30 cm", "root zone", "soil layers",
)

SENSOR_TERMS = (
    "neutron probe", "time domain reflectometry", "TDR", "frequency domain",
    "capacitance probe", "Sentek", "EnviroSCAN", "Diviner", "TEROS",
    "Hydra Probe", "CS616", "CS655", "cosmic ray neutron", "watermark sensor",
)

CROP_TERMS = (
    "maize", "corn", "cotton", "soybean", "wheat", "rice", "alfalfa", "potato",
    "sugar beet", "sorghum", "sunflower", "canola", "peanut", "sugarcane",
    "almond", "vineyard", "tomato", "onion",
)


def _or_block(terms: tuple[str, ...], quote: bool = True) -> str:
    joined = " OR ".join(f'"{t}"' if quote and " " in t else t for t in terms)
    return f"({joined})"


def openalex_query(
    include_crops: bool = False,
    include_sensors: bool = False,
) -> str:
    """A high-recall boolean query for OpenAlex.

    Boolean operators must be uppercase and wildcards are unsupported, hence the
    explicit variant lists. Kept broad on purpose: precision is cheap to recover
    with a screening pass, whereas a study missed at this stage is missed for
    good.
    """
    parts = [_or_block(MOISTURE_TERMS), _or_block(IRRIGATION_TERMS)]
    if include_crops:
        parts.append(_or_block(CROP_TERMS))
    if include_sensors:
        parts.append(_or_block(SENSOR_TERMS))
    return " AND ".join(parts)


def europepmc_query(figures_only: bool = False, open_access: bool = True) -> str:
    """A field-prefixed Europe PMC query.

    ``figures_only`` restricts to figure captions via the ``FIG:`` prefix, which
    finds exactly the papers whose soil moisture data is plotted rather than
    tabulated — the target of the digitization pipeline.
    """
    moisture = " OR ".join(
        f'{"FIG" if figures_only else "TITLE_ABS"}:"{t}"' for t in MOISTURE_TERMS
    )
    irrigation = " OR ".join(f'FULL_TEXT:"{t}"' for t in IRRIGATION_TERMS)
    clauses = [f"({moisture})", f"({irrigation})", "(PUB_YEAR:[1980 TO 2026])", "LANG:eng"]
    if open_access:
        clauses.append("OPEN_ACCESS:Y")
    return " AND ".join(clauses)


# --------------------------------------------------------------------------
# Clients
# --------------------------------------------------------------------------


@dataclass
class DiscoveryResult:
    """Works and datasets found by one search."""

    works: pd.DataFrame = field(default_factory=pd.DataFrame)
    datasets: pd.DataFrame = field(default_factory=pd.DataFrame)
    errors: list[str] = field(default_factory=list)

    def __add__(self, other: DiscoveryResult) -> DiscoveryResult:
        def cat(a, b):
            frames = [f for f in (a, b) if not f.empty]
            return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

        return DiscoveryResult(cat(self.works, other.works),
                               cat(self.datasets, other.datasets),
                               self.errors + other.errors)

    def deduplicate(self) -> DiscoveryResult:
        """Collapse to one row per DOI, keeping the most informative."""
        works = self.works
        if not works.empty and "doi" in works.columns:
            works = works.sort_values("n_fields", ascending=False) if "n_fields" in works else works
            has_doi = works[works["doi"].notna()].drop_duplicates("doi")
            no_doi = works[works["doi"].isna()].drop_duplicates("title")
            works = pd.concat([has_doi, no_doi], ignore_index=True)
        datasets = self.datasets
        if not datasets.empty and "doi" in datasets.columns:
            datasets = datasets.drop_duplicates("doi")
        return DiscoveryResult(works, datasets, self.errors)


class OpenAlexClient:
    """OpenAlex works search.

    Requires an API key as of February 2026 — anonymous access is capped at 100
    credits a day, which is a testing allowance rather than a harvest. A free
    registered key allows 100,000 a day. Set ``OPENALEX_API_KEY`` or pass one.
    """

    BASE_URL = "https://api.openalex.org/works"
    SELECT = (
        "id,doi,title,publication_year,type,cited_by_count,open_access,"
        "primary_location,authorships,language,locations"
    )

    def __init__(self, session: PoliteSession | None = None, api_key: str | None = None):
        self.session = session or PoliteSession()
        self.api_key = api_key or os.environ.get("OPENALEX_API_KEY")
        if not self.api_key:
            log.warning(
                "no OpenAlex API key; anonymous access is limited to ~100 credits/day. "
                "Register free at openalex.org/settings/api and set OPENALEX_API_KEY."
            )

    def search(
        self,
        query: str | None = None,
        from_year: int = 1980,
        to_year: int = 2026,
        open_access_only: bool = False,
        max_records: int = 10_000,
        per_page: int = 200,
    ) -> DiscoveryResult:
        query = query or openalex_query()
        filters = [
            f"title_and_abstract.search:{query}",
            f"publication_year:{from_year}-{to_year}",
            "type:article",
            "has_doi:true",
        ]
        if open_access_only:
            filters.append("open_access.is_oa:true")

        rows: list[dict] = []
        errors: list[str] = []
        cursor = "*"
        while len(rows) < max_records and cursor:
            params = {
                "filter": ",".join(filters),
                "per-page": min(per_page, 200),
                "cursor": cursor,
                "select": self.SELECT,
            }
            if self.api_key:
                params["api_key"] = self.api_key
            try:
                payload = self.session.get_json(self.BASE_URL, params=params)
            except Exception as exc:
                errors.append(f"openalex: {type(exc).__name__}: {exc}")
                break
            results = payload.get("results", [])
            if not results:
                break
            rows.extend(self._parse(item) for item in results)
            cursor = payload.get("meta", {}).get("next_cursor")
        return DiscoveryResult(works=pd.DataFrame(rows), errors=errors)

    @staticmethod
    def _parse(item: dict) -> dict:
        location = item.get("primary_location") or {}
        oa = item.get("open_access") or {}
        authors = [
            (a.get("author") or {}).get("display_name", "")
            for a in (item.get("authorships") or [])[:12]
        ]
        return {
            "openalex_id": item.get("id"),
            "doi": (item.get("doi") or "").replace("https://doi.org/", "") or None,
            "title": item.get("title"),
            "year": item.get("publication_year"),
            "venue": (location.get("source") or {}).get("display_name"),
            "authors": "; ".join(a for a in authors if a),
            "oa_status": oa.get("oa_status"),
            "pdf_url": oa.get("oa_url") or location.get("pdf_url"),
            "cited_by": item.get("cited_by_count"),
            "source": "openalex",
        }


class EuropePMCClient:
    """Europe PMC search, including figure-caption search and JATS full text."""

    BASE_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
    FULLTEXT_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"

    def __init__(self, session: PoliteSession | None = None):
        self.session = session or PoliteSession()

    def search(
        self,
        query: str | None = None,
        max_records: int = 10_000,
        page_size: int = 1000,
    ) -> DiscoveryResult:
        query = query or europepmc_query()
        rows: list[dict] = []
        errors: list[str] = []
        cursor = "*"
        while len(rows) < max_records:
            params = {
                "query": query, "resultType": "core", "format": "json",
                "pageSize": min(page_size, 1000), "cursorMark": cursor,
            }
            try:
                payload = self.session.get_json(self.BASE_URL, params=params)
            except Exception as exc:
                errors.append(f"europepmc: {type(exc).__name__}: {exc}")
                break
            results = (payload.get("resultList") or {}).get("result", [])
            if not results:
                break
            rows.extend(self._parse(item) for item in results)
            next_cursor = payload.get("nextCursorMark")
            if not next_cursor or next_cursor == cursor:
                break
            cursor = next_cursor
        return DiscoveryResult(works=pd.DataFrame(rows), errors=errors)

    @staticmethod
    def _parse(item: dict) -> dict:
        return {
            "doi": item.get("doi"),
            "title": item.get("title"),
            "year": int(item["pubYear"]) if str(item.get("pubYear", "")).isdigit() else None,
            "venue": item.get("journalTitle"),
            "authors": item.get("authorString"),
            "pmcid": item.get("pmcid"),
            "pmid": item.get("pmid"),
            "is_open_access": item.get("isOpenAccess") == "Y",
            "in_epmc": item.get("inEPMC") == "Y",
            "has_supplementary": item.get("hasSuppl") == "Y",
            "licence": item.get("license"),
            "source": "europepmc",
        }

    def full_text_xml(self, pmcid: str) -> str:
        """JATS XML for an open-access article.

        Worth preferring over the PDF wherever it exists: tables arrive as
        markup rather than as an image of numbers, and figure captions come with
        their graphic references already associated.
        """
        return self.session.get_text(self.FULLTEXT_URL.format(pmcid=pmcid))


class DataCiteClient:
    """DataCite dataset search — federates Zenodo, Dryad, Pangaea and the rest.

    Searched before the article databases because a dataset found here is the
    actual numbers, already machine-readable and already licensed. The
    ``relatedIdentifiers`` field links a dataset back to the paper it belongs to.
    """

    BASE_URL = "https://api.datacite.org/dois"

    def __init__(self, session: PoliteSession | None = None):
        self.session = session or PoliteSession()

    def search(
        self,
        query: str | None = None,
        max_records: int = 5000,
        page_size: int = 500,
    ) -> DiscoveryResult:
        query = query or (
            '(titles.title:("soil moisture" OR "soil water content" OR '
            '"volumetric water content") AND (descriptions.description:irrigation '
            "OR subjects.subject:irrigation))"
        )
        rows: list[dict] = []
        errors: list[str] = []
        cursor: str | None = "1"
        while len(rows) < max_records and cursor:
            params = {
                "query": query,
                "resource-type-id": "dataset",
                "page[size]": min(page_size, 1000),
                "page[cursor]": cursor,
            }
            try:
                payload = self.session.get_json(self.BASE_URL, params=params)
            except Exception as exc:
                errors.append(f"datacite: {type(exc).__name__}: {exc}")
                break
            data = payload.get("data", [])
            if not data:
                break
            rows.extend(self._parse(item) for item in data)
            next_link = (payload.get("links") or {}).get("next")
            cursor = _cursor_from(next_link) if next_link else None
        return DiscoveryResult(datasets=pd.DataFrame(rows), errors=errors)

    @staticmethod
    def _parse(item: dict) -> dict:
        attrs = item.get("attributes", {})
        titles = attrs.get("titles") or [{}]
        related = [
            r.get("relatedIdentifier")
            for r in (attrs.get("relatedIdentifiers") or [])
            if r.get("relatedIdentifierType") == "DOI"
            and r.get("relationType") in ("IsSupplementTo", "IsSourceOf", "IsCitedBy")
        ]
        rights = attrs.get("rightsList") or [{}]
        return {
            "doi": attrs.get("doi"),
            "title": titles[0].get("title"),
            "year": attrs.get("publicationYear"),
            "publisher": attrs.get("publisher"),
            "licence": rights[0].get("rightsIdentifier") or rights[0].get("rights"),
            "url": attrs.get("url"),
            "related_article_dois": "; ".join(d for d in related if d),
            "source": "datacite",
        }


class ZenodoClient:
    """Zenodo records search.

    Capped at 30 requests a minute since November 2025, for anonymous and
    authenticated callers alike; the session's limiter is set accordingly.
    """

    BASE_URL = "https://zenodo.org/api/records"

    def __init__(self, session: PoliteSession | None = None, token: str | None = None):
        self.session = session or PoliteSession()
        self.token = token or os.environ.get("ZENODO_TOKEN")

    def search(
        self, query: str = '"soil moisture" AND irrigation',
        max_records: int = 2000, page_size: int = 100,
    ) -> DiscoveryResult:
        rows: list[dict] = []
        errors: list[str] = []
        page = 1
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else None
        while len(rows) < max_records:
            params = {"q": query, "type": "dataset", "size": min(page_size, 100),
                      "page": page, "sort": "mostrecent"}
            try:
                payload = self.session.get_json(self.BASE_URL, params=params, headers=headers)
            except Exception as exc:
                errors.append(f"zenodo: {type(exc).__name__}: {exc}")
                break
            hits = (payload.get("hits") or {}).get("hits", [])
            if not hits:
                break
            rows.extend(self._parse(item) for item in hits)
            page += 1
        return DiscoveryResult(datasets=pd.DataFrame(rows), errors=errors)

    @staticmethod
    def _parse(item: dict) -> dict:
        meta = item.get("metadata", {})
        files = item.get("files", []) or []
        return {
            "doi": item.get("doi") or meta.get("doi"),
            "title": meta.get("title"),
            "year": (meta.get("publication_date") or "")[:4] or None,
            "publisher": "Zenodo",
            "licence": ((meta.get("license") or {}).get("id")
                        if isinstance(meta.get("license"), dict) else meta.get("license")),
            "url": (item.get("links") or {}).get("self_html"),
            "n_files": len(files),
            "file_urls": "; ".join((f.get("links") or {}).get("self", "") for f in files[:20]),
            "source": "zenodo",
        }


class UnpaywallClient:
    """Resolve a DOI to a legally downloadable full text.

    Consulted before any PDF is fetched. A paper behind a paywall is not
    downloaded: the text-and-data-mining position differs by publisher and by
    jurisdiction, and the open-access copy is both unambiguous and usually the
    same document.
    """

    BASE_URL = "https://api.unpaywall.org/v2/{doi}"

    def __init__(self, session: PoliteSession | None = None, email: str | None = None):
        self.session = session or PoliteSession()
        self.email = email or os.environ.get("UNPAYWALL_EMAIL")
        if not self.email:
            log.warning("Unpaywall requires an email address; set UNPAYWALL_EMAIL")

    def resolve(self, doi: str) -> dict[str, Any]:
        payload = self.session.get_json(
            self.BASE_URL.format(doi=doi.strip()), params={"email": self.email}
        )
        best = payload.get("best_oa_location") or {}
        return {
            "doi": doi,
            "is_oa": payload.get("is_oa", False),
            "oa_status": payload.get("oa_status"),
            "pdf_url": best.get("url_for_pdf"),
            "landing_url": best.get("url_for_landing_page"),
            "licence": best.get("license"),
            "host_type": best.get("host_type"),
            "text_mining_allowed": bool(best.get("license")) and "nd" not in str(best.get("license", "")),
        }


def _cursor_from(url: str) -> str | None:
    from urllib.parse import parse_qs, urlparse

    values = parse_qs(urlparse(url).query).get("page[cursor]")
    return values[0] if values else None


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------


def discover_all(
    session: PoliteSession | None = None,
    max_per_source: int = 2000,
    include_repositories: bool = True,
    include_articles: bool = True,
) -> DiscoveryResult:
    """Run every discovery channel and merge.

    Repositories first, deliberately. Every dataset found there is a study that
    does not need its figures digitized.
    """
    session = session or PoliteSession()
    total = DiscoveryResult()

    if include_repositories:
        for client in (DataCiteClient(session), ZenodoClient(session)):
            total = total + client.search(max_records=max_per_source)
    if include_articles:
        total = total + OpenAlexClient(session).search(max_records=max_per_source)
        total = total + EuropePMCClient(session).search(max_records=max_per_source)

    return total.deduplicate()


def screen_works(works: pd.DataFrame) -> pd.DataFrame:
    """Score and rank candidate papers before anything is downloaded.

    A broad query returns tens of thousands of hits and most are irrelevant.
    Ranking on title and venue costs nothing and puts the studies most likely to
    contain multi-depth irrigated soil moisture at the top, so a harvest that is
    interrupted has still collected the best of them.
    """
    if works.empty:
        return works
    out = works.copy()
    title = out["title"].fillna("").str.lower()
    venue = out.get("venue", pd.Series("", index=out.index)).fillna("").str.lower()

    score = pd.Series(0.0, index=out.index)
    score += title.str.contains("|".join(MOISTURE_TERMS), regex=True).astype(float) * 3
    score += title.str.contains("|".join(IRRIGATION_TERMS), regex=True).astype(float) * 3
    score += title.str.contains("|".join(DEPTH_TERMS), regex=True).astype(float) * 2
    score += title.str.contains("|".join(SENSOR_TERMS).lower(), regex=True).astype(float) * 1.5
    score += title.str.contains("|".join(CROP_TERMS), regex=True).astype(float) * 1
    high_yield_venues = (
        "agricultural water management|irrigation science|vadose zone|"
        "soil science society|water resources research|agronomy journal|"
        "field crops research|journal of hydrology|transactions of the asabe|"
        "computers and electronics in agriculture|agricultural and forest meteorology"
    )
    score += venue.str.contains(high_yield_venues, regex=True).astype(float) * 2
    # Downweight the modelling and remote-sensing literature: it discusses soil
    # moisture constantly but rarely publishes field measurements.
    score -= title.str.contains("review|meta-analysis|simulation only|satellite retrieval",
                                regex=True).astype(float) * 1.5

    out["relevance_score"] = score
    return out.sort_values("relevance_score", ascending=False).reset_index(drop=True)
