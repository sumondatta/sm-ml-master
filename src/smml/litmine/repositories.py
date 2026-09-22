"""Harvesting grey literature: theses, station reports, CGIAR and IAEA outputs.

The documents with the densest soil water tables are the ones the article
databases index worst. Theses live in university repositories, experiment
station field-day reports in land-grant Digital Commons instances, CGIAR trial
reports on CGSpace, and the Joint FAO/IAEA neutron-probe programme's national
datasets in INIS. None of that is in Crossref in any useful way.

What makes this tractable is that almost all of it speaks **OAI-PMH**. Digital
Commons exposes it at ``/do/oai/`` and DSpace at ``/oai/request``, universally,
so a single harvester reaches the entire land-grant tier and most of the world's
thesis repositories. Dataverse likewise gives every installation the same search
API. Two protocols cover most of the grey literature that matters.

The registry below is a seed, not a curated list. The scalable move is to pull
OpenDOAR or ROAR, filter to agriculture and environment subjects, and harvest
every OAI base URL they return — which turns "find the repositories" from a
research problem into a loop. :func:`repositories_from_opendoar` does that.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from xml.etree import ElementTree

import pandas as pd

from ..util.http import PoliteSession

log = logging.getLogger(__name__)

OAI_NS = {
    "oai": "http://www.openarchives.org/OAI/2.0/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "oai_dc": "http://www.openarchives.org/OAI/2.0/oai_dc/",
}


@dataclass(frozen=True)
class Repository:
    """One harvestable repository."""

    short_id: str
    name: str
    oai_url: str
    platform: str            # digital_commons | dspace | eprints | custom
    country: str = ""
    why: str = ""
    confidence: str = "recalled"


#: Seed repositories, chosen for irrigation and soil water density rather than
#: size. The land-grant entries are where US experiment station field-day
#: reports live, and those carry decades of neutron-probe profiles that were
#: never published anywhere a citation index would find them.
#:
#: Every URL here is *recalled*, not verified — the environment this was written
#: in could not reach any of them. Run ``smml literature verify-repositories``
#: before trusting one.
SEED_REPOSITORIES: tuple[Repository, ...] = (
    Repository("newprairiepress", "Kansas State — New Prairie Press",
               "https://newprairiepress.org/do/oai/", "digital_commons", "US",
               "Kansas Agricultural Experiment Station Research Reports; the Tribune and "
               "Garden City limited-irrigation series carry neutron-probe profiles"),
    Repository("krex", "Kansas State — K-REx",
               "https://krex.k-state.edu/oai/request", "dspace", "US",
               "Kansas State theses in agronomy and biological systems engineering"),
    Repository("oaktrust", "Texas A&M — OAKTrust",
               "https://oaktrust.library.tamu.edu/oai/request", "dspace", "US",
               "Texas High Plains theses; Bushland USDA-ARS neutron-probe profiles to 2.4 m"),
    Repository("unl_digitalcommons", "Nebraska — DigitalCommons@UNL",
               "https://digitalcommons.unl.edu/do/oai/", "digital_commons", "US",
               "Biological Systems Engineering theses; Nebraska Ag Water Management Network"),
    Repository("arizona_repository", "University of Arizona Repository",
               "https://repository.arizona.edu/oai", "dspace", "US",
               "Arizona Cotton Report and Forage & Grain Report series"),
    Repository("usu_digitalcommons", "Utah State — DigitalCommons",
               "https://digitalcommons.usu.edu/do/oai/", "digital_commons", "US",
               "Utah Water Research Laboratory reports"),
    Repository("escholarship", "University of California — eScholarship",
               "https://escholarship.org/oai", "custom", "US",
               "California SDI and drip in vegetables, almonds, processing tomato"),
    Repository("openprairie", "South Dakota State — Open PRAIRIE",
               "https://openprairie.sdstate.edu/do/oai/", "digital_commons", "US"),
    Repository("shareok", "Oklahoma State — SHAREOK",
               "https://shareok.org/oai/request", "dspace", "US"),
    Repository("iastate", "Iowa State — Digital Repository",
               "https://dr.lib.iastate.edu/oai/request", "dspace", "US",
               "Farm Progress Reports series"),
    Repository("wsu_rex", "Washington State — Research Exchange",
               "https://rex.libraries.wsu.edu/oai/request", "dspace", "US",
               "Columbia Basin irrigated potato and wheat"),
    Repository("ttu_ir", "Texas Tech — TTU DSpace",
               "https://ttu-ir.tdl.org/oai/request", "dspace", "US"),
    Repository("cgspace", "CGSpace (CGIAR)",
               "https://cgspace.cgiar.org/oai/request", "dspace", "international",
               "IWMI, ICARDA, ICRISAT, CIP working papers and trial reports — grey "
               "literature that carries raw trial data"),
    Repository("shodhganga", "Shodhganga (Indian ETDs)",
               "https://shodhganga.inflibnet.ac.in/oai/request", "dspace", "IN",
               "Indian agricultural theses; AICRP irrigation water management work"),
    Repository("krishikosh", "KrishiKosh (ICAR)",
               "https://krishikosh.egranth.ac.in/oai/request", "dspace", "IN",
               "ICAR institutional theses and station reports"),
)


# --------------------------------------------------------------------------
# OAI-PMH
# --------------------------------------------------------------------------


class OaiHarvester:
    """A generic OAI-PMH client.

    Handles resumption tokens, which is the entire protocol in practice: a
    repository returns a page and a token, and the harvest continues until the
    token stops coming back. Deleted records are skipped and malformed ones are
    counted rather than raising, because a single bad record in a repository of
    two hundred thousand must not end the harvest.
    """

    def __init__(self, session: PoliteSession | None = None):
        self.session = session or PoliteSession()

    def list_records(
        self,
        base_url: str,
        metadata_prefix: str = "oai_dc",
        set_spec: str | None = None,
        from_date: str | None = None,
        until_date: str | None = None,
        max_records: int = 50_000,
    ) -> pd.DataFrame:
        params: dict[str, Any] = {"verb": "ListRecords", "metadataPrefix": metadata_prefix}
        if set_spec:
            params["set"] = set_spec
        if from_date:
            params["from"] = from_date
        if until_date:
            params["until"] = until_date

        rows: list[dict] = []
        malformed = 0
        token: str | None = None

        while len(rows) < max_records:
            query = {"verb": "ListRecords", "resumptionToken": token} if token else params
            try:
                payload = self.session.get(base_url, params=query)
                root = ElementTree.fromstring(payload)
            except Exception as exc:
                log.warning("%s: %s", base_url, exc)
                break

            error = root.find("oai:error", OAI_NS)
            if error is not None:
                log.warning("%s returned OAI error %s: %s", base_url,
                            error.get("code"), (error.text or "").strip())
                break

            records = root.findall(".//oai:record", OAI_NS)
            if not records:
                break
            for record in records:
                try:
                    parsed = self._parse_record(record, base_url)
                except Exception:
                    malformed += 1
                    continue
                if parsed:
                    rows.append(parsed)

            token_element = root.find(".//oai:resumptionToken", OAI_NS)
            token = (token_element.text or "").strip() if token_element is not None else None
            if not token:
                break

        if malformed:
            log.info("%s: skipped %d malformed records", base_url, malformed)
        return pd.DataFrame(rows)

    @staticmethod
    def _parse_record(record, base_url: str) -> dict | None:
        header = record.find("oai:header", OAI_NS)
        if header is not None and header.get("status") == "deleted":
            return None
        identifier = header.findtext("oai:identifier", default="", namespaces=OAI_NS)

        metadata = record.find(".//oai_dc:dc", OAI_NS)
        if metadata is None:
            return None

        def gather(tag: str) -> list[str]:
            return [(e.text or "").strip() for e in metadata.findall(f"dc:{tag}", OAI_NS)
                    if (e.text or "").strip()]

        identifiers = gather("identifier")
        return {
            "oai_identifier": identifier,
            "title": "; ".join(gather("title")),
            "abstract": " ".join(gather("description"))[:4000],
            "authors": "; ".join(gather("creator")),
            "year": next((d[:4] for d in gather("date") if d[:4].isdigit()), None),
            "type": "; ".join(gather("type")),
            "subject": "; ".join(gather("subject"))[:1000],
            "language": "; ".join(gather("language")),
            "rights": "; ".join(gather("rights"))[:500],
            "url": next((i for i in identifiers if i.startswith("http")), ""),
            "doi": next((i for i in identifiers if "doi.org" in i or i.startswith("10.")), None),
            "repository": base_url,
        }

    def identify(self, base_url: str) -> dict[str, Any]:
        """The repository's own description — used to confirm it is reachable."""
        payload = self.session.get(base_url, params={"verb": "Identify"})
        root = ElementTree.fromstring(payload)
        identify = root.find(".//oai:Identify", OAI_NS)
        if identify is None:
            return {}
        return {
            "name": identify.findtext("oai:repositoryName", default="", namespaces=OAI_NS),
            "base_url": identify.findtext("oai:baseURL", default="", namespaces=OAI_NS),
            "protocol": identify.findtext("oai:protocolVersion", default="", namespaces=OAI_NS),
            "earliest": identify.findtext("oai:earliestDatestamp", default="",
                                          namespaces=OAI_NS),
        }


# --------------------------------------------------------------------------
# Dataverse
# --------------------------------------------------------------------------

#: Dataverse installations holding agricultural trial data. Every installation
#: exposes the same search API, so one client reaches all of them. ICRISAT is
#: the standout: the Patancheru long-term Vertisol watershed experiments carry
#: neutron-probe profiles at 15 cm increments to 180 cm across decades.
DATAVERSE_INSTANCES: tuple[tuple[str, str, str], ...] = (
    ("harvard", "https://dataverse.harvard.edu", "hosts CGIAR collections including IRRI and CIP"),
    ("cimmyt", "https://data.cimmyt.org", "CIMMYT maize and wheat trials"),
    ("icrisat", "http://dataverse.icrisat.org",
     "Patancheru long-term Vertisol watersheds: neutron-probe profiles at 15 cm "
     "increments to 180 cm over decades"),
    ("icarda_mel", "https://data.mel.cgiar.org",
     "ICARDA Tel Hadya supplemental-irrigation wheat trials, neutron probe to 180 cm"),
)


class DataverseClient:
    """Search any Dataverse installation. They all share one API."""

    def __init__(self, base_url: str, session: PoliteSession | None = None):
        self.base_url = base_url.rstrip("/")
        self.session = session or PoliteSession()

    def search(self, query: str = "soil moisture irrigation",
               max_records: int = 1000, per_page: int = 100) -> pd.DataFrame:
        rows: list[dict] = []
        start = 0
        while len(rows) < max_records:
            try:
                payload = self.session.get_json(
                    f"{self.base_url}/api/search",
                    params={"q": query, "type": "dataset",
                            "per_page": min(per_page, 1000), "start": start},
                )
            except Exception as exc:
                log.warning("%s: %s", self.base_url, exc)
                break
            items = (payload.get("data") or {}).get("items", [])
            if not items:
                break
            for item in items:
                rows.append({
                    "title": item.get("name"),
                    "doi": (item.get("global_id") or "").replace("doi:", "") or None,
                    "abstract": (item.get("description") or "")[:4000],
                    "authors": "; ".join(item.get("authors") or []),
                    "year": item.get("published_at", "")[:4] or None,
                    "url": item.get("url"),
                    "type": "dataset",
                    "repository": self.base_url,
                })
            start += len(items)
        return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# Registry discovery
# --------------------------------------------------------------------------


def repositories_from_opendoar(
    api_key: str,
    session: PoliteSession | None = None,
    subjects: tuple[str, ...] = ("Agriculture", "Environment", "Earth"),
) -> pd.DataFrame:
    """Pull OpenDOAR and filter to the subjects that carry soil water data.

    This is the move that makes the grey-literature tier tractable: rather than
    curating repositories by hand, take the ~6,000 in OpenDOAR with their subject
    classification and OAI base URLs, keep agriculture and environment, and
    harvest all of them. A free key is needed.
    """
    session = session or PoliteSession()
    payload = session.get_json(
        "https://v2.sherpa.ac.uk/cgi/retrieve",
        params={"item-type": "repository", "api-key": api_key, "format": "Json"},
    )
    rows = []
    for item in payload.get("items", []):
        subject_text = " ".join(
            str(s.get("subject", "")) for s in (item.get("repository_subject") or [])
        )
        if subjects and not any(s.lower() in subject_text.lower() for s in subjects):
            continue
        rows.append({
            "name": (item.get("name") or [{}])[0].get("name", ""),
            "oai_url": item.get("oai_url") or "",
            "country": ((item.get("organisation") or [{}])[0].get("country") or ""),
            "software": (item.get("software") or [{}])[0].get("name", ""),
            "subjects": subject_text[:300],
        })
    return pd.DataFrame(rows)


def harvest_seed_repositories(
    session: PoliteSession | None = None,
    max_records_each: int = 5000,
    only: tuple[str, ...] | None = None,
) -> pd.DataFrame:
    """Harvest the seed list, continuing past any repository that fails.

    A repository that has moved, changed platform or gone offline is recorded in
    the output rather than raising: the fact that a known source is unreachable
    is itself worth knowing, and roughly one in five of these URLs is expected to
    need correcting on first contact.
    """
    session = session or PoliteSession()
    harvester = OaiHarvester(session)
    frames, failures = [], []

    for repository in SEED_REPOSITORIES:
        if only and repository.short_id not in only:
            continue
        try:
            frame = harvester.list_records(repository.oai_url, max_records=max_records_each)
        except Exception as exc:
            failures.append({"short_id": repository.short_id, "error": str(exc)[:200]})
            continue
        if frame.empty:
            failures.append({"short_id": repository.short_id, "error": "no records returned"})
            continue
        frame["repository_id"] = repository.short_id
        frame["repository_name"] = repository.name
        frames.append(frame)

    if failures:
        log.warning("%d of %d repositories returned nothing", len(failures),
                    len(only or SEED_REPOSITORIES))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
