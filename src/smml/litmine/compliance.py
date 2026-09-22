"""What may be fetched, kept, and republished.

Mass-harvesting publisher PDFs, extracting numbers from copyrighted figures, and
publishing the result openly raises three separate questions with three
different answers, and conflating them is how a database becomes unpublishable
after the work is done:

1. **May I fetch and keep a copy?** Text-and-data-mining law. Broadly permissive
   for non-commercial research with *lawful access*, and the copy may usually be
   retained for verification.
2. **May I extract the numbers?** Facts and measurements are generally not
   copyrightable; the expression of them — the figure, the table layout, the
   caption — is. Extraction for analysis is on much firmer ground than
   reproduction.
3. **May I redistribute what I extracted?** The hardest question, answered
   per-source, and the one that has to be recorded *at ingest* because it cannot
   be reconstructed later.

This module implements the policy, not the law. It gates the harvest so the
three questions get separate answers per item, and it makes the default the
conservative one. **None of this is legal advice.** The reasoning behind the
defaults is in ``docs/research/compliance-and-licensing.md``, which is itself
recalled rather than verified. Anything destined for publication needs a
conversation with a librarian or counsel, and the questions worth asking are
listed in :func:`counsel_checklist`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

import pandas as pd

log = logging.getLogger(__name__)


class Action(str, Enum):
    """The three questions, kept separate."""

    FETCH = "fetch"                # retrieve and cache a copy
    EXTRACT = "extract"            # derive numeric values from it
    REDISTRIBUTE = "redistribute"  # publish those values onward


class Verdict(str, Enum):
    ALLOW = "allow"
    ALLOW_WITH_ATTRIBUTION = "allow_with_attribution"
    #: Permitted for local analysis but not for republication.
    LOCAL_ONLY = "local_only"
    DENY = "deny"
    #: Cannot be decided from the metadata; a human has to look.
    REVIEW = "review"


#: Licence identifier prefix -> what each action is permitted.
#: Keys are matched case-insensitively against the start of the licence string,
#: so "cc-by-4.0" and "CC BY 4.0 International" both hit the ``cc-by`` entry.
LICENCE_POLICY: dict[str, dict[str, str]] = {
    "cc0":        {"fetch": Verdict.ALLOW.value, "extract": Verdict.ALLOW.value, "redistribute": Verdict.ALLOW.value},
    "public domain": {"fetch": Verdict.ALLOW.value, "extract": Verdict.ALLOW.value, "redistribute": Verdict.ALLOW.value},
    "cc-by-sa":   {"fetch": Verdict.ALLOW.value, "extract": Verdict.ALLOW.value,
                   "redistribute": Verdict.ALLOW_WITH_ATTRIBUTION.value},
    "cc-by-nc":   {"fetch": Verdict.ALLOW.value, "extract": Verdict.ALLOW.value,
                   "redistribute": Verdict.LOCAL_ONLY.value},
    "cc-by-nd":   {"fetch": Verdict.ALLOW.value, "extract": Verdict.ALLOW.value,
                   "redistribute": Verdict.LOCAL_ONLY.value},
    "cc-by":      {"fetch": Verdict.ALLOW.value, "extract": Verdict.ALLOW.value,
                   "redistribute": Verdict.ALLOW_WITH_ATTRIBUTION.value},
    "mit":        {"fetch": Verdict.ALLOW.value, "extract": Verdict.ALLOW.value, "redistribute": Verdict.ALLOW.value},
    "odbl":       {"fetch": Verdict.ALLOW.value, "extract": Verdict.ALLOW.value,
                   "redistribute": Verdict.ALLOW_WITH_ATTRIBUTION.value},
    "ogl":        {"fetch": Verdict.ALLOW.value, "extract": Verdict.ALLOW.value,
                   "redistribute": Verdict.ALLOW_WITH_ATTRIBUTION.value},
    # Open-access articles: the text is licensed, the underlying measurements are
    # facts. Extraction is on firm ground; republishing extracted values is a
    # judgement call that depends on how much of the original is reconstructed.
    "open access": {"fetch": Verdict.ALLOW.value, "extract": Verdict.ALLOW.value,
                    "redistribute": Verdict.REVIEW.value},
    # What most in-situ networks actually grant: use it freely for research,
    # credit us, do not hand it on as your own. Fetching and extraction are
    # unambiguous; republication is the network's call, not ours.
    "free for research": {"fetch": Verdict.ALLOW.value, "extract": Verdict.ALLOW.value,
                          "redistribute": Verdict.LOCAL_ONLY.value},
    "research use": {"fetch": Verdict.ALLOW.value, "extract": Verdict.ALLOW.value,
                     "redistribute": Verdict.LOCAL_ONLY.value},
    "attribution": {"fetch": Verdict.ALLOW.value, "extract": Verdict.ALLOW.value,
                    "redistribute": Verdict.ALLOW_WITH_ATTRIBUTION.value},
    # Subscription content with lawful access: TDM exceptions generally permit
    # fetching and extraction for research, and generally do not permit
    # republishing the source.
    "subscription": {"fetch": Verdict.ALLOW.value, "extract": Verdict.ALLOW.value,
                     "redistribute": Verdict.LOCAL_ONLY.value},
    "all rights reserved": {"fetch": Verdict.REVIEW.value, "extract": Verdict.REVIEW.value,
                            "redistribute": Verdict.DENY.value},
    "unknown":    {"fetch": Verdict.REVIEW.value, "extract": Verdict.REVIEW.value,
                   "redistribute": Verdict.DENY.value},
}

#: Sources that must never be fetched, whatever a licence field says.
#: Shadow libraries are not lawful access under any TDM exception, and using one
#: voids the exception for everything downstream of it.
FORBIDDEN_HOSTS: frozenset[str] = frozenset({
    "sci-hub", "libgen", "z-lib", "zlibrary", "booksc", "b-ok",
})


@dataclass
class ComplianceDecision:
    action: str
    verdict: str
    licence: str
    reason: str
    requires_attribution: bool = False

    @property
    def permitted(self) -> bool:
        return self.verdict in (Verdict.ALLOW.value, Verdict.ALLOW_WITH_ATTRIBUTION)


#: Rewrites applied before the policy lookup, longest first. Creative Commons
#: licences are written a dozen ways and the spelled-out forms have to be folded
#: onto the canonical identifiers before matching, or the generic "attribution"
#: class shadows the specific cc-by one.
LICENCE_SYNONYMS: tuple[tuple[str, str], ...] = (
    ("creative-commons-attribution-sharealike", "cc-by-sa"),
    ("creative-commons-attribution-noncommercial", "cc-by-nc"),
    ("creative-commons-attribution-noderiv", "cc-by-nd"),
    ("creative-commons-attribution", "cc-by"),
    ("creative-commons-zero", "cc0"),
    ("creative-commons", "cc"),
    ("cc-attribution-sharealike", "cc-by-sa"),
    ("cc-attribution-noncommercial", "cc-by-nc"),
    ("cc-attribution", "cc-by"),
    ("ccby-nc", "cc-by-nc"),
    ("ccbysa", "cc-by-sa"),
    ("ccby", "cc-by"),
    ("cc0", "cc0"),
    ("open-government-licence", "ogl"),
    ("open-database-license", "odbl"),
)


def normalize_licence(licence: str | None) -> str:
    """Reduce a free-text licence string to a policy key.

    Matching is by prefix first and only then by substring, and the more
    specific keys are tried before the general ones. Without that ordering the
    catch-all "attribution" class swallowed "Creative Commons Attribution 4.0",
    turning a cc-by source into a vaguer and more permissive class than it is.
    """
    if not licence:
        return "unknown"
    text = str(licence).strip().lower().replace("_", "-").replace(" ", "-")
    for pattern, canonical in LICENCE_SYNONYMS:
        if pattern in text:
            text = text.replace(pattern, canonical)
            break

    keys = sorted(LICENCE_POLICY, key=len, reverse=True)
    normalized = [(k, k.replace(" ", "-")) for k in keys]
    for key, pattern in normalized:          # prefix wins over substring
        if text.startswith(pattern):
            return key
    for key, pattern in normalized:
        if pattern in text:
            return key
    return "unknown"


def decide(action: str, licence: str | None, url: str | None = None) -> ComplianceDecision:
    """Whether one action on one item is permitted under the policy."""
    if url:
        lowered = str(url).lower()
        if any(host in lowered for host in FORBIDDEN_HOSTS):
            return ComplianceDecision(
                action=action, verdict=Verdict.DENY.value, licence=normalize_licence(licence),
                reason="shadow library: not lawful access under any TDM exception, "
                       "and using one voids the exception for everything derived from it",
            )
    key = normalize_licence(licence)
    verdict = LICENCE_POLICY[key][action]
    return ComplianceDecision(
        action=action, verdict=verdict, licence=key,
        reason=f"policy for licence class {key!r}",
        requires_attribution=verdict == Verdict.ALLOW_WITH_ATTRIBUTION.value,
    )


def gate(items: pd.DataFrame, action: str, licence_col: str = "licence",
         url_col: str = "url") -> pd.DataFrame:
    """Annotate a table with the verdict for one action, without dropping rows.

    Nothing is filtered out here. A denied item stays in the table with its
    verdict attached, because the fact that a study exists and cannot be used is
    itself worth recording — it belongs in the coverage accounting, and a licence
    can change.
    """
    out = items.copy()
    verdicts, reasons, attribution = [], [], []
    for _, row in out.iterrows():
        decision = decide(action, row.get(licence_col), row.get(url_col))
        verdicts.append(decision.verdict)
        reasons.append(decision.reason)
        attribution.append(decision.requires_attribution)
    out[f"{action}_verdict"] = verdicts
    out[f"{action}_reason"] = reasons
    if action == Action.REDISTRIBUTE:
        out["requires_attribution"] = attribution
    return out


def permitted(items: pd.DataFrame, action: str, **kwargs) -> pd.DataFrame:
    """The subset of items for which an action is permitted."""
    annotated = gate(items, action, **kwargs)
    column = f"{action}_verdict"
    return annotated[annotated[column].isin([Verdict.ALLOW.value, Verdict.ALLOW_WITH_ATTRIBUTION])]


def compliance_report(items: pd.DataFrame, **kwargs) -> pd.DataFrame:
    """Counts by verdict for all three actions — the thing to look at before publishing."""
    rows = []
    for action in (Action.FETCH, Action.EXTRACT, Action.REDISTRIBUTE):
        annotated = gate(items, action.value, **kwargs)
        counts = annotated[f"{action.value}_verdict"].value_counts()
        for verdict, n in counts.items():
            rows.append({"action": action.value, "verdict": verdict, "n": int(n),
                         "pct": round(100 * n / max(len(items), 1), 1)})
    return pd.DataFrame(rows)


def attribution_manifest(items: pd.DataFrame, licence_col: str = "licence",
                         citation_col: str = "citation") -> pd.DataFrame:
    """Every source that must be credited if the database is published.

    Generated from the data rather than maintained by hand, because an
    attribution list assembled at the end is always incomplete and a missing
    credit is the most common and most avoidable licence breach.
    """
    annotated = gate(items, Action.REDISTRIBUTE.value, licence_col=licence_col)
    needs = annotated[annotated.get("requires_attribution", False)]
    columns = [c for c in (citation_col, licence_col, "name", "url", "doi")
               if c in needs.columns]
    return needs[columns].drop_duplicates().reset_index(drop=True)


def counsel_checklist() -> list[str]:
    """Questions a lawyer or research librarian has to answer, not a search engine.

    Listed explicitly because the temptation is to treat the whole area as
    settled by a licence string, and it is not. Each of these changes what the
    project may publish.
    """
    return [
        "Which jurisdiction's law governs the copying — where the harvesting "
        "servers physically sit, or where the institution is?",
        "Does the institution qualify as a research organisation under the EU DSM "
        "Directive Article 3, and does that matter if the servers are elsewhere?",
        "Do any publisher subscription agreements contain TDM clauses, and are "
        "those clauses enforceable in the governing jurisdiction?",
        "Is the resulting database a 'substantial part' of any source database "
        "for sui generis database-right purposes?",
        "Are digitized values from a figure a reproduction of protected expression, "
        "or unprotectable facts, in the governing jurisdiction?",
        "What retention is permitted for verification, and for how long?",
        "Does publishing under a share-alike licence conflict with any "
        "non-commercial source already ingested?",
        "Do any contributing in-situ networks require prior notification or "
        "co-authorship as a condition of reuse?",
    ]
