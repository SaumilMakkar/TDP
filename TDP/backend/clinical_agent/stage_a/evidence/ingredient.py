"""Ingredient evidence matching for Stage A Sprint 4."""

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

# Semantic-first ingredient scoring buckets.
SCORE_EXACT_INGREDIENT = 1.0
SCORE_SAME_ACTIVE_MOIETY = 0.75
SCORE_SAME_DRUG_SUBCLASS = 0.5
SCORE_SAME_MOA_CLASS = 0.5
SCORE_SAME_THERAPEUTIC_CLASS = 0.25
SCORE_SAME_ATC_LEVEL_4 = 0.25
SCORE_SAME_ATC_LEVEL_3 = 0.25


@dataclass(frozen=True)
class _SemanticProfile:
    primary_ingredient: str | None
    ingredients: set[str]
    active_moiety: set[str]
    moa_class: set[str]
    therapeutic_class: set[str]
    drug_class: set[str]
    drug_subclass: set[str]
    atc_level_1: set[str]
    atc_level_2: set[str]
    atc_level_3: set[str]
    atc_level_4: set[str]
    atc_level_5: set[str]


_FIELD_ALIASES = {
    "ingredient": (
        "ingredient",
        "rxnorm_ingredient",
        "verified_ingredient_normalized",
        "verified_ingredient_raw",
        "csv_generic_name",
        "generic_name",
    ),
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
        "csv_therapeutic_class_normalized",
        "csv_therapeutic_class_raw",
    ),
    "drug_class": (
        "drug_class",
        "drg_class_nm",
        "therapeutic_class",
        "csv_therapeutic_class_normalized",
    ),
    "drug_subclass": (
        "drug_subclass",
        "therapeutic_subclass",
        "pharmacologic_subclass",
    ),
    "atc_level_1": ("atc_level_1", "atc1"),
    "atc_level_2": ("atc_level_2", "atc2"),
    "atc_level_3": ("atc_level_3", "atc3"),
    "atc_level_4": ("atc_level_4", "atc4"),
    "atc_level_5": ("atc_level_5", "atc5"),
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


def _normalized_set(values: Iterable[object] | None) -> set[str]:
    if values is None:
        return set()
    normalized: set[str] = set()
    for value in values:
        item = _normalize_text(value)
        if item:
            normalized.add(item)
    return normalized


def _metadata_set(source: object, field_name: str) -> set[str]:
    aliases = _FIELD_ALIASES[field_name]
    values = _extract_raw_values(source, aliases)
    result: set[str] = set()
    for value in values:
        result.update(_term_set_from_value(value))
    return result


def _canonical_ingredient(source: object) -> str | None:
    # Prefer normalized RxNorm ingredient if available.
    for value in _extract_raw_values(source, _FIELD_ALIASES["ingredient"]):
        candidate = _normalize_text(value)
        if candidate:
            return candidate

    ingredients = _get_csv_ingredients(source)
    if len(ingredients) == 1:
        return next(iter(ingredients))
    return None


def _build_profile(source: object) -> _SemanticProfile:
    ingredient_values = _metadata_set(source, "ingredient")
    ingredient_values.update(_get_csv_ingredients(source))
    canonical = _canonical_ingredient(source)
    if canonical:
        ingredient_values.add(canonical)

    return _SemanticProfile(
        primary_ingredient=canonical,
        ingredients=ingredient_values,
        active_moiety=_metadata_set(source, "active_moiety"),
        moa_class=_metadata_set(source, "moa_class"),
        therapeutic_class=_metadata_set(source, "therapeutic_class"),
        drug_class=_metadata_set(source, "drug_class"),
        drug_subclass=_metadata_set(source, "drug_subclass"),
        atc_level_1=_metadata_set(source, "atc_level_1"),
        atc_level_2=_metadata_set(source, "atc_level_2"),
        atc_level_3=_metadata_set(source, "atc_level_3"),
        atc_level_4=_metadata_set(source, "atc_level_4"),
        atc_level_5=_metadata_set(source, "atc_level_5"),
    )


def _has_overlap(left: set[str], right: set[str]) -> bool:
    return bool(left and right and (left & right))


def _semantic_score(left: _SemanticProfile, right: _SemanticProfile) -> float:
    candidates: list[float] = []

    exact_primary_match = (
        left.primary_ingredient is not None
        and right.primary_ingredient is not None
        and left.primary_ingredient == right.primary_ingredient
    )
    exact_set_match = bool(left.ingredients and right.ingredients and left.ingredients == right.ingredients)

    if exact_primary_match or exact_set_match:
        candidates.append(SCORE_EXACT_INGREDIENT)
    if _has_overlap(left.active_moiety, right.active_moiety):
        candidates.append(SCORE_SAME_ACTIVE_MOIETY)
    if _has_overlap(left.drug_subclass, right.drug_subclass):
        candidates.append(SCORE_SAME_DRUG_SUBCLASS)
    if _has_overlap(left.moa_class, right.moa_class):
        candidates.append(SCORE_SAME_MOA_CLASS)
    if _has_overlap(left.therapeutic_class, right.therapeutic_class) or _has_overlap(left.drug_class, right.drug_class):
        candidates.append(SCORE_SAME_THERAPEUTIC_CLASS)
    if _has_overlap(left.atc_level_4, right.atc_level_4):
        candidates.append(SCORE_SAME_ATC_LEVEL_4)
    if _has_overlap(left.atc_level_3, right.atc_level_3):
        candidates.append(SCORE_SAME_ATC_LEVEL_3)

    return max(candidates) if candidates else 0.0


def _get_rxnorm_ingredient(drug: object) -> str | None:
    if drug is None:
        return None

    if isinstance(drug, dict):
        source = drug.get("rxnorm") if isinstance(drug.get("rxnorm"), dict) else drug
        return _normalize_text(source.get("ingredient"))

    rxnorm = getattr(drug, "rxnorm", None)
    if isinstance(rxnorm, dict):
        return _normalize_text(rxnorm.get("ingredient"))

    return _normalize_text(getattr(drug, "rxnorm_ingredient", None))


def _get_csv_ingredients(drug: object) -> set[str]:
    if drug is None:
        return set()

    if isinstance(drug, dict):
        values = drug.get("ingredients")
        if not isinstance(values, list):
            return set()
        return _normalized_set(values)

    return _normalized_set(getattr(drug, "ingredients", None))


def _best_partial_name_score(left_values: set[str], right_values: set[str]) -> float:
    best = 0.0
    for left in left_values:
        for right in right_values:
            best = max(best, soft_bucket_from_text_similarity(left, right))
            if best == 1.0:
                return best
    return best


def ingredient_match(drugA, drugB) -> float:
    """
    Return a deterministic bucket score for ingredient similarity.

    Missing values never raise and always return 0, with status recorded in
    ingredient_match.last_result.
    """
    profile_a = _build_profile(drugA)
    profile_b = _build_profile(drugB)

    rx_a = _get_rxnorm_ingredient(drugA)
    rx_b = _get_rxnorm_ingredient(drugB)

    source = "csv"
    insufficient_data = False

    semantic_score = _semantic_score(profile_a, profile_b)
    if semantic_score > 0.0:
        score = semantic_score
        if rx_a and rx_b:
            source = "rxnorm"
    elif rx_a and rx_b:
        source = "rxnorm"
        score = soft_bucket_from_text_similarity(rx_a, rx_b)
    else:
        ingredients_a = profile_a.ingredients
        ingredients_b = profile_b.ingredients
        if not ingredients_a or not ingredients_b:
            score = 0.0
            insufficient_data = True
        else:
            overlap = ingredients_a & ingredients_b
            if ingredients_a == ingredients_b:
                score = 1.0
            elif overlap:
                smaller_size = min(len(ingredients_a), len(ingredients_b))
                overlap_ratio = len(overlap) / smaller_size if smaller_size else 0.0
                if overlap_ratio == 1.0:
                    score = 0.75
                elif overlap_ratio >= 0.5:
                    score = 0.5
                else:
                    score = 0.25
            else:
                score = _best_partial_name_score(ingredients_a, ingredients_b)

    ingredient_match.last_result = {
        "insufficient_data": insufficient_data,
        "source": source,
    }

    if insufficient_data:
        logger.info("ingredient_match: insufficient_data due to missing/empty ingredient list.")

    return score


ingredient_match.last_result = {
    "insufficient_data": False,
    "source": "csv",
}
