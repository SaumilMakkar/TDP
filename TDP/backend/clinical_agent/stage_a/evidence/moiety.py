"""Active moiety evidence matching for Stage A Sprint 4."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from stage_a.evidence.scoring import normalize_simple_text, soft_bucket_from_text_similarity

logger = logging.getLogger(__name__)

_WHITESPACE_RE = re.compile(r"\s+")
_TERM_SPLIT_RE = re.compile(r"[;|]")

# Semantic-first moiety scoring buckets.
SCORE_EXACT_ACTIVE_MOIETY = 1.0
SCORE_SAME_DRUG_SUBCLASS = 0.75
SCORE_SAME_MOA_CLASS = 0.5
SCORE_SAME_THERAPEUTIC_CLASS = 0.25
SCORE_SAME_ATC_LEVEL_4 = 0.25


@dataclass(frozen=True)
class _SemanticProfile:
    active_moiety: set[str]
    moa_class: set[str]
    therapeutic_class: set[str]
    drug_subclass: set[str]
    atc_level_4: set[str]


_FIELD_ALIASES = {
    "active_moiety": (
        "active_moiety",
        "verified_active_moiety_normalized",
        "verified_active_moiety_raw",
    ),
    "moa_class": (
        "moa_class",
        "moa_classes",
        "verified_moa_classes_normalized",
        "verified_moa_classes_raw",
    ),
    "therapeutic_class": (
        "therapeutic_class",
        "drug_class",
        "csv_therapeutic_class_normalized",
        "csv_therapeutic_class_raw",
    ),
    "drug_subclass": (
        "drug_subclass",
        "therapeutic_subclass",
        "pharmacologic_subclass",
    ),
    "atc_level_4": ("atc_level_4", "atc4"),
}


def _normalize_text(value: object) -> str | None:
    normalized = normalize_simple_text(value)
    if normalized is None:
        return None
    return _WHITESPACE_RE.sub(" ", normalized)


def _as_mapping(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _extract_raw_values(source: object, aliases: Iterable[str]) -> list[object]:
    values: list[object] = []

    mapping = _as_mapping(source)
    nested_rxnorm = _as_mapping(mapping.get("rxnorm"))
    nested_ref = _as_mapping(mapping.get("rxnorm_ref"))

    for alias in aliases:
        if alias in mapping:
            values.append(mapping.get(alias))
        if alias in nested_rxnorm:
            values.append(nested_rxnorm.get(alias))
        if alias in nested_ref:
            values.append(nested_ref.get(alias))

        if not isinstance(source, dict):
            values.append(getattr(source, alias, None))

    if not isinstance(source, dict):
        obj_rxnorm = _as_mapping(getattr(source, "rxnorm", None))
        obj_ref = _as_mapping(getattr(source, "rxnorm_ref", None))
        for alias in aliases:
            if alias in obj_rxnorm:
                values.append(obj_rxnorm.get(alias))
            if alias in obj_ref:
                values.append(obj_ref.get(alias))

    return values


def _term_set_from_value(value: object) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, (list, tuple, set)):
        merged: set[str] = set()
        for item in value:
            merged.update(_term_set_from_value(item))
        return merged

    normalized = _normalize_text(value)
    if normalized is None:
        return set()
    terms = {_normalize_text(part) for part in _TERM_SPLIT_RE.split(normalized)}
    return {term for term in terms if term}


def _metadata_set(source: object, field_name: str) -> set[str]:
    aliases = _FIELD_ALIASES[field_name]
    values = _extract_raw_values(source, aliases)
    result: set[str] = set()
    for value in values:
        result.update(_term_set_from_value(value))
    return result


def _build_profile(source: object) -> _SemanticProfile:
    return _SemanticProfile(
        active_moiety=_metadata_set(source, "active_moiety"),
        moa_class=_metadata_set(source, "moa_class"),
        therapeutic_class=_metadata_set(source, "therapeutic_class"),
        drug_subclass=_metadata_set(source, "drug_subclass"),
        atc_level_4=_metadata_set(source, "atc_level_4"),
    )


def _has_overlap(left: set[str], right: set[str]) -> bool:
    return bool(left and right and (left & right))


def _semantic_score(left: _SemanticProfile, right: _SemanticProfile) -> float:
    candidates: list[float] = []

    if _has_overlap(left.active_moiety, right.active_moiety):
        candidates.append(SCORE_EXACT_ACTIVE_MOIETY)
    if _has_overlap(left.drug_subclass, right.drug_subclass):
        candidates.append(SCORE_SAME_DRUG_SUBCLASS)
    if _has_overlap(left.moa_class, right.moa_class):
        candidates.append(SCORE_SAME_MOA_CLASS)
    if _has_overlap(left.therapeutic_class, right.therapeutic_class):
        candidates.append(SCORE_SAME_THERAPEUTIC_CLASS)
    if _has_overlap(left.atc_level_4, right.atc_level_4):
        candidates.append(SCORE_SAME_ATC_LEVEL_4)

    return max(candidates) if candidates else 0.0


def _primary_active_moiety(source: object) -> str | None:
    for value in _extract_raw_values(source, _FIELD_ALIASES["active_moiety"]):
        normalized = _normalize_text(value)
        if normalized:
            return normalized
    return None


def moiety_match(drugA_rxnorm, drugB_rxnorm) -> float:
    """Compare active_moiety values and return a bucket score with insufficient-data status."""
    profile_a = _build_profile(drugA_rxnorm)
    profile_b = _build_profile(drugB_rxnorm)

    semantic_score = _semantic_score(profile_a, profile_b)
    if semantic_score > 0.0:
        moiety_match.last_result = {"insufficient_data": False}
        return semantic_score

    moiety_a = _primary_active_moiety(drugA_rxnorm)
    moiety_b = _primary_active_moiety(drugB_rxnorm)

    insufficient_data = moiety_a is None or moiety_b is None
    if insufficient_data:
        logger.info("moiety_match: insufficient_data because active_moiety is missing.")

    moiety_match.last_result = {"insufficient_data": insufficient_data}

    if insufficient_data:
        return 0.0
    return soft_bucket_from_text_similarity(moiety_a, moiety_b)


moiety_match.last_result = {"insufficient_data": False}
