"""Route evidence matching for Stage A Sprint 4."""

from __future__ import annotations

import logging
import re

from stage_a.evidence.scoring import bucket_from_token_overlap

logger = logging.getLogger(__name__)

_WHITESPACE_RE = re.compile(r"\s+")

_ROUTE_FAMILIES = {
    "oral": "enteral",
    "po": "enteral",
    "sublingual": "enteral",
    "buccal": "enteral",
    "intravenous": "parenteral",
    "iv": "parenteral",
    "intramuscular": "parenteral",
    "im": "parenteral",
    "subcutaneous": "parenteral",
    "sc": "parenteral",
    "inhalation": "respiratory",
    "intranasal": "respiratory",
    "nasal": "respiratory",
    "topical": "topical",
    "transdermal": "topical",
    "ophthalmic": "ophthalmic_otic",
    "otic": "ophthalmic_otic",
    "rectal": "mucosal",
    "vaginal": "mucosal",
}


def _route_family(route: str) -> str | None:
    for token in route.split(" "):
        family = _ROUTE_FAMILIES.get(token)
        if family:
            return family
    return None


def _normalize_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text or text == "nan":
        return None
    return _WHITESPACE_RE.sub(" ", text)


def route_match(drugA_rxnorm, drugB_rxnorm) -> float:
    """Compare route values and return a deterministic bucket score."""
    route_a = _normalize_text((drugA_rxnorm or {}).get("route"))
    route_b = _normalize_text((drugB_rxnorm or {}).get("route"))

    insufficient_data = route_a is None or route_b is None
    if insufficient_data:
        logger.info("route_match: insufficient_data because route is missing.")

    route_match.last_result = {"insufficient_data": insufficient_data}

    if insufficient_data:
        return 0.0

    if route_a == route_b:
        return 1.0

    if route_a in route_b or route_b in route_a:
        return 0.75

    family_a = _route_family(route_a)
    family_b = _route_family(route_b)
    if family_a and family_b and family_a == family_b:
        return 0.5

    return bucket_from_token_overlap(route_a, route_b)


route_match.last_result = {"insufficient_data": False}
