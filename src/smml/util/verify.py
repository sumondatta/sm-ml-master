"""Probing catalogued endpoints to find out which are actually alive.

Ninety-one of the registry's source entries are ``recalled`` — their endpoints
came from model knowledge rather than from a verified response — and none of the
connectors has ever contacted a live server. Some fraction of those URLs have
moved, changed platform, or never existed in quite that form.

Rather than guess which, probe them all and write a report. The report is
designed to be handed back for repair: it records the exact URL tried, the
status, the redirect target where there was one, and a first guess at the
category of failure, so a fix can be made without a second round of
investigation.

Probing is deliberately gentle. A HEAD request, falling back to a ranged GET for
servers that reject HEAD, with the same per-host rate limiting the harvest uses.
Nothing here downloads a payload.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

import pandas as pd
import requests

from .http import PoliteSession, limiter_for

log = logging.getLogger(__name__)


class Status:
    ALIVE = "alive"
    REDIRECTED = "redirected"
    NOT_FOUND = "not_found"
    FORBIDDEN = "forbidden"
    AUTH_REQUIRED = "auth_required"
    RATE_LIMITED = "rate_limited"
    SERVER_ERROR = "server_error"
    UNREACHABLE = "unreachable"
    BLOCKED_BY_POLICY = "blocked_by_egress_policy"
    SKIPPED = "skipped"


#: What each HTTP status most likely means for a catalogued endpoint, and
#: whether the registry entry needs changing.
STATUS_MEANING: dict[str, tuple[str, bool]] = {
    Status.ALIVE: ("reachable and answering at this exact path; the connector can be "
                   "pointed at it as recorded", False),
    Status.REDIRECTED: ("moved; update base_url to the redirect target", True),
    Status.NOT_FOUND: ("endpoint does not exist at this path; the service may have "
                       "restructured its API", True),
    Status.FORBIDDEN: ("reachable but refusing; often needs a key, a User-Agent, or "
                       "is blocking automated access", False),
    Status.AUTH_REQUIRED: ("needs credentials; check the auth field is right", False),
    Status.RATE_LIMITED: ("reachable but throttling; raise this host's interval", False),
    Status.SERVER_ERROR: ("server-side failure; retry later before concluding anything", False),
    Status.UNREACHABLE: ("no response; the host may be gone, or the network may be "
                         "restricted here", True),
    Status.BLOCKED_BY_POLICY: ("blocked by this environment's egress policy, not by the "
                               "service; says nothing about whether the endpoint works", False),
}


@dataclass
class ProbeResult:
    short_id: str
    url: str
    status: str
    http_code: int | None = None
    final_url: str | None = None
    elapsed_ms: int | None = None
    detail: str = ""
    needs_fix: bool = False
    category: str = ""
    confidence: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def as_row(self) -> dict:
        meaning, _ = STATUS_MEANING.get(self.status, ("", False))
        return {
            "short_id": self.short_id,
            "status": self.status,
            "http_code": self.http_code,
            "needs_fix": self.needs_fix,
            "url": self.url,
            "final_url": self.final_url or "",
            "elapsed_ms": self.elapsed_ms,
            "category": self.category,
            "registry_confidence": self.confidence,
            "meaning": meaning,
            "detail": self.detail[:200],
        }


def probe(
    url: str,
    short_id: str = "",
    timeout_s: float = 20.0,
    session: requests.Session | None = None,
) -> ProbeResult:
    """Check one endpoint without downloading it."""
    if not url or url.strip().lower() in {"unknown", "n/a", ""}:
        return ProbeResult(short_id, url, Status.SKIPPED, detail="no URL recorded")

    session = session or requests.Session()
    session.headers.setdefault(
        "User-Agent", "smml/0.1 endpoint-check (soil moisture research harvester)"
    )
    limiter_for(url).wait()
    started = time.monotonic()

    def finish(response) -> ProbeResult:
        elapsed = int((time.monotonic() - started) * 1000)
        code = response.status_code
        final = response.url if response.url != url else None
        if code in (200, 201, 202, 204, 206):
            status = Status.REDIRECTED if final else Status.ALIVE
        elif code in (301, 302, 303, 307, 308):
            status = Status.REDIRECTED
        elif code == 404 or code == 410:
            status = Status.NOT_FOUND
        elif code in (401, 402):
            status = Status.AUTH_REQUIRED
        elif code == 403:
            status = Status.FORBIDDEN
        elif code == 429:
            status = Status.RATE_LIMITED
        elif code >= 500:
            status = Status.SERVER_ERROR
        else:
            status = Status.ALIVE
        _, needs_fix = STATUS_MEANING.get(status, ("", False))
        return ProbeResult(short_id, url, status, http_code=code, final_url=final,
                           elapsed_ms=elapsed, needs_fix=needs_fix,
                           detail=f"HTTP {code}")

    try:
        response = session.head(url, timeout=timeout_s, allow_redirects=True)
        if response.status_code in (403, 405, 501):
            # Plenty of APIs refuse HEAD; ask for one byte instead.
            response = session.get(url, timeout=timeout_s, allow_redirects=True,
                                   headers={"Range": "bytes=0-256"}, stream=True)
            response.close()
        return finish(response)
    except requests.exceptions.SSLError as exc:
        return ProbeResult(short_id, url, Status.UNREACHABLE, detail=f"TLS: {exc}"[:200])
    except requests.exceptions.ProxyError as exc:
        return ProbeResult(short_id, url, Status.BLOCKED_BY_POLICY,
                           detail=f"proxy refused: {exc}"[:200])
    except requests.RequestException as exc:
        message = str(exc)
        status = (Status.BLOCKED_BY_POLICY
                  if "403" in message and "CONNECT" in message else Status.UNREACHABLE)
        _, needs_fix = STATUS_MEANING.get(status, ("", False))
        return ProbeResult(short_id, url, status, needs_fix=needs_fix,
                           detail=f"{type(exc).__name__}: {message}"[:200])


def verify_registry(
    category: str | None = None,
    max_priority: int | None = None,
    recalled_only: bool = False,
    limit: int | None = None,
    timeout_s: float = 20.0,
) -> pd.DataFrame:
    """Probe every catalogued source and report which need fixing.

    ``recalled_only`` restricts to the entries that were never corroborated by a
    search, which is where the failures will concentrate and is the sensible
    place to start.
    """
    from .. import registry

    sources = registry.sources(category=category, max_priority=max_priority)
    if recalled_only:
        sources = [s for s in sources if s.get("confidence") != "confirmed"]
    if limit:
        sources = sources[:limit]

    session = requests.Session()
    rows = []
    for source in sources:
        result = probe(source.get("base_url", ""), short_id=source.get("short_id", ""),
                       timeout_s=timeout_s, session=session)
        result.category = source.get("category", "")
        result.confidence = source.get("confidence", "")
        rows.append(result.as_row())
        log.info("%-32s %s", result.short_id, result.status)
    return pd.DataFrame(rows)


def verify_repositories(timeout_s: float = 25.0) -> pd.DataFrame:
    """Probe the OAI-PMH seed repositories with a real protocol request.

    A bare URL check is not enough for OAI: many repositories answer at the path
    but do not speak the protocol there. This issues ``verb=Identify``, which is
    the protocol's own liveness check, and reports the repository name it gets
    back — the fastest way to confirm a base URL is the right one.
    """
    from ..litmine.repositories import SEED_REPOSITORIES, OaiHarvester

    harvester = OaiHarvester(PoliteSession(use_cache=False))
    rows = []
    for repository in SEED_REPOSITORIES:
        started = time.monotonic()
        try:
            identity = harvester.identify(repository.oai_url)
            rows.append({
                "short_id": repository.short_id,
                "status": Status.ALIVE if identity else Status.NOT_FOUND,
                "reported_name": identity.get("name", ""),
                "earliest_record": identity.get("earliest", ""),
                "oai_url": repository.oai_url,
                "platform": repository.platform,
                "elapsed_ms": int((time.monotonic() - started) * 1000),
                "detail": "" if identity else "responded but not as an OAI endpoint",
            })
        except Exception as exc:
            rows.append({
                "short_id": repository.short_id, "status": Status.UNREACHABLE,
                "reported_name": "", "earliest_record": "",
                "oai_url": repository.oai_url, "platform": repository.platform,
                "elapsed_ms": int((time.monotonic() - started) * 1000),
                "detail": f"{type(exc).__name__}: {exc}"[:200],
            })
    return pd.DataFrame(rows)


def summarize(report: pd.DataFrame) -> pd.DataFrame:
    """Counts by status, with what each one means."""
    if report.empty:
        return pd.DataFrame()
    counts = report["status"].value_counts().reset_index()
    counts.columns = ["status", "n"]
    counts["meaning"] = counts["status"].map(lambda s: STATUS_MEANING.get(s, ("", False))[0])
    counts["pct"] = (100 * counts["n"] / len(report)).round(1)
    return counts
