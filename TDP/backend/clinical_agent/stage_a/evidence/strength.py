"""Strength evidence matching for Stage A Sprint 4."""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

_UNIT_TO_BASE = {
    "mg": ("mass_mg", 1.0),
    "g": ("mass_mg", 1000.0),
    "mcg": ("mass_mg", 0.001),
}

_INLINE_STRENGTH_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(mcg|mg|g)\b", re.IGNORECASE)


def _normalize_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text or text == "nan":
        return None
    return text


def _normalize_strength_row(row: object) -> tuple[str | None, float | None, str | None]:
    if not isinstance(row, dict):
        return (None, None, None)

    ingredient = _normalize_text(row.get("ingredient"))
    unit = _normalize_text(row.get("unit"))

    raw_strength = row.get("strength")
    if raw_strength is None:
        strength = None
    else:
        try:
            strength = float(raw_strength)
        except (TypeError, ValueError):
            strength = None

    return (ingredient, strength, unit)


def _to_base(strength: float | None, unit: str | None) -> tuple[float | None, bool]:
    if strength is None or unit is None:
        return (None, False)

    if unit in _UNIT_TO_BASE:
        base_name, factor = _UNIT_TO_BASE[unit]
        return (strength * factor, True)

    # Non-convertible units are only comparable if unit labels exactly match.
    return (strength, False)


def _is_close(left: float, right: float, tolerance: float = 1e-3) -> bool:
    return abs(left - right) <= tolerance


def _bucketed_ratio_score(left: float, right: float) -> float:
    if left <= 0.0 or right <= 0.0:
        return 0.0
    ratio = min(left, right) / max(left, right)
    if ratio >= 0.8:
        return 1.0
    if ratio >= 0.5:
        return 0.75
    if ratio >= 0.2:
        return 0.5
    if ratio > 0.0:
        return 0.25
    return 0.0


def _extract_strength_from_name(drug: object) -> tuple[float | None, str | None]:
    for text in (
        getattr(drug, "product_name", None),
        getattr(drug, "generic_name", None),
    ):
        if text is None:
            continue
        match = _INLINE_STRENGTH_RE.search(str(text))
        if not match:
            continue
        try:
            value = float(match.group(1))
        except (TypeError, ValueError):
            continue
        unit = _normalize_text(match.group(2))
        return (value, unit)
    return (None, None)


def _reference_strength(drug: object) -> tuple[float | None, str | None, str | None] | None:
    ref = getattr(drug, "rxnorm_ref", None)
    if not isinstance(ref, dict):
        return None

    status = _normalize_text(ref.get("strength_normalization_status"))
    unit = _normalize_text(ref.get("normalized_strength_unit"))
    raw_value = ref.get("normalized_strength_value")

    value: float | None
    if raw_value is None:
        value = None
    else:
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            value = None

    return (value, unit, status)


def strength_match(drugA, drugB) -> float:
    """
    Compare strengths for overlapping ingredients with unit-aware handling.

    Return 0 on insufficient comparison data, while recording status in
    strength_match.last_result.
    """
    ref_a = _reference_strength(drugA)
    ref_b = _reference_strength(drugB)

    if ref_a is not None and ref_b is not None:
        value_a, unit_a, status_a = ref_a
        value_b, unit_b, status_b = ref_b

        missing_statuses = {None, "missing", "unconvertible_unit"}
        if status_a in missing_statuses or status_b in missing_statuses:
            value_a, unit_a = _extract_strength_from_name(drugA)
            value_b, unit_b = _extract_strength_from_name(drugB)

        if value_a is not None and value_b is not None and unit_a is not None and unit_b is not None:
            base_a, convertible_a = _to_base(value_a, unit_a)
            base_b, convertible_b = _to_base(value_b, unit_b)

            if convertible_a and convertible_b and base_a is not None and base_b is not None:
                strength_match.last_result = {"insufficient_data": False}
                return _bucketed_ratio_score(base_a, base_b)

            if unit_a == unit_b:
                strength_match.last_result = {"insufficient_data": False}
                return _bucketed_ratio_score(value_a, value_b)

        strength_match.last_result = {"insufficient_data": True}
        logger.info("strength_match: insufficient_data because normalized/fallback strength values are not comparable.")
        return 0.0

    strengths_a = list(getattr(drugA, "strengths", []) or [])
    strengths_b = list(getattr(drugB, "strengths", []) or [])

    map_a: dict[str, tuple[float | None, str | None]] = {}
    map_b: dict[str, tuple[float | None, str | None]] = {}

    for row in strengths_a:
        ingredient, strength, unit = _normalize_strength_row(row)
        if ingredient is not None and ingredient not in map_a:
            map_a[ingredient] = (strength, unit)

    for row in strengths_b:
        ingredient, strength, unit = _normalize_strength_row(row)
        if ingredient is not None and ingredient not in map_b:
            map_b[ingredient] = (strength, unit)

    overlap = sorted(set(map_a) & set(map_b))
    if not overlap:
        fallback_a, fallback_unit_a = _extract_strength_from_name(drugA)
        fallback_b, fallback_unit_b = _extract_strength_from_name(drugB)
        if (
            fallback_a is not None
            and fallback_b is not None
            and fallback_unit_a is not None
            and fallback_unit_b is not None
        ):
            base_a, convertible_a = _to_base(fallback_a, fallback_unit_a)
            base_b, convertible_b = _to_base(fallback_b, fallback_unit_b)

            if convertible_a and convertible_b and base_a is not None and base_b is not None:
                strength_match.last_result = {"insufficient_data": False}
                return _bucketed_ratio_score(base_a, base_b)

            if fallback_unit_a == fallback_unit_b:
                strength_match.last_result = {"insufficient_data": False}
                return _bucketed_ratio_score(fallback_a, fallback_b)

        strength_match.last_result = {"insufficient_data": True}
        logger.info("strength_match: insufficient_data because there is no ingredient overlap.")
        return 0.0

    compared_any = False
    saw_incompatible_units = False
    scores: list[float] = []

    for ingredient in overlap:
        strength_a, unit_a = map_a[ingredient]
        strength_b, unit_b = map_b[ingredient]

        if strength_a is None or strength_b is None or unit_a is None or unit_b is None:
            strength_match.last_result = {"insufficient_data": True}
            logger.info("strength_match: insufficient_data because strength/unit is missing.")
            return 0.0

        base_a, convertible_a = _to_base(strength_a, unit_a)
        base_b, convertible_b = _to_base(strength_b, unit_b)

        if convertible_a and convertible_b:
            compared_any = True
            if base_a is None or base_b is None:
                strength_match.last_result = {"insufficient_data": True}
                return 0.0
            if _is_close(base_a, base_b):
                scores.append(1.0)
            else:
                scores.append(_bucketed_ratio_score(base_a, base_b))
            continue

        if unit_a == unit_b:
            compared_any = True
            if _is_close(strength_a, strength_b):
                scores.append(1.0)
            else:
                scores.append(_bucketed_ratio_score(strength_a, strength_b))
            continue

        saw_incompatible_units = True

    if not compared_any or saw_incompatible_units:
        strength_match.last_result = {"insufficient_data": True}
        logger.info("strength_match: insufficient_data because units are incompatible.")
        return 0.0

    if not scores:
        strength_match.last_result = {"insufficient_data": True}
        return 0.0

    strength_match.last_result = {"insufficient_data": False}
    return min(scores)


strength_match.last_result = {"insufficient_data": False}
