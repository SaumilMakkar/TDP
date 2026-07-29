"""Dosage form evidence matching for Stage A Sprint 4."""

from __future__ import annotations

import logging
import re

from stage_a.evidence.scoring import bucket_from_token_overlap

logger = logging.getLogger(__name__)

_WHITESPACE_RE = re.compile(r"\s+")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9\s]")


def _normalize_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text or text == "nan":
        return None
    text = _NON_ALNUM_RE.sub(" ", text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    if not text:
        return None
    return text


def _canonical_form(value: object) -> str | None:
    normalized = _normalize_text(value)
    if normalized is None:
        return None
    return normalized


def _has_reference_row(drug: object) -> bool:
    return getattr(drug, "rxnorm_ref", None) is not None


def _forms_match(left: str, right: str) -> bool:
    if left == right:
        return True
    if left in right or right in left:
        return True
    left_tokens = set(left.split(" "))
    right_tokens = set(right.split(" "))
    return bool(left_tokens & right_tokens)


_FORM_FAMILIES = {
    "tablet": "oral_solid",
    "capsule": "oral_solid",
    "caplet": "oral_solid",
    "solution": "liquid",
    "suspension": "liquid",
    "syrup": "liquid",
    "elixir": "liquid",
    "cream": "topical_semisolid",
    "ointment": "topical_semisolid",
    "gel": "topical_semisolid",
    "lotion": "topical_semisolid",
    "patch": "transdermal",
    "spray": "spray",
}


def _form_family(value: str) -> str | None:
    tokens = value.split(" ")
    for token in tokens:
        family = _FORM_FAMILIES.get(token)
        if family:
            return family
    return None


def form_match(drugA, drugB, drugA_rxnorm=None, drugB_rxnorm=None) -> float:
    """
    Compare dosage forms with RxNorm preferred and CSV fallback.

    Return a deterministic bucket score. Detailed status is recorded on form_match.last_result.
    """
    used_fallback_csv = False
    insufficient_data = False

    if _has_reference_row(drugA) and _has_reference_row(drugB):
        source = "rxnorm"
        left = _canonical_form((drugA_rxnorm or {}).get("dose_form"))
        right = _canonical_form((drugB_rxnorm or {}).get("dose_form"))
    else:
        used_fallback_csv = True
        source = "csv"
        logger.info("form_match: using CSV dosage_form fallback because rxnorm_ref is missing.")
        left = _canonical_form(getattr(drugA, "dosage_form", None))
        right = _canonical_form(getattr(drugB, "dosage_form", None))

    if left is None or right is None:
        insufficient_data = True
        logger.info("form_match: insufficient_data because dosage form is missing after normalization.")
        score = 0.0
    else:
        if left == right:
            score = 1.0
        elif left in right or right in left:
            score = 0.75
        else:
            left_family = _form_family(left)
            right_family = _form_family(right)
            if left_family and right_family and left_family == right_family:
                score = 0.5
            elif _forms_match(left, right):
                score = 0.25
            else:
                score = bucket_from_token_overlap(left, right)

    form_match.last_result = {
        "insufficient_data": insufficient_data,
        "source": source,
        "used_fallback_csv": used_fallback_csv,
    }

    return score


form_match.last_result = {
    "insufficient_data": False,
    "source": "rxnorm",
    "used_fallback_csv": False,
}
