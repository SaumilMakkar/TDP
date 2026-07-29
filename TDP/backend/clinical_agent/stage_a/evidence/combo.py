"""Combination-product evidence matching for Stage A Sprint 4."""

from __future__ import annotations

import re


_WHITESPACE_RE = re.compile(r"\s+")


def _normalize_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text or text == "nan":
        return None
    return _WHITESPACE_RE.sub(" ", text)


def _ingredient_set(drug: object) -> set[str]:
    values = list(getattr(drug, "ingredients", []) or [])
    normalized: set[str] = set()
    for value in values:
        item = _normalize_text(value)
        if item:
            normalized.add(item)
    return normalized


def combo_match(drugA, drugB) -> float:
    """
    Return a deterministic bucket score for formulation-complexity similarity.
    """
    ingredients_a = _ingredient_set(drugA)
    ingredients_b = _ingredient_set(drugB)

    if not ingredients_a or not ingredients_b:
        return 0.0

    if ingredients_a == ingredients_b:
        return 1.0

    overlap = ingredients_a & ingredients_b
    smaller_size = min(len(ingredients_a), len(ingredients_b))
    overlap_ratio = (len(overlap) / smaller_size) if smaller_size else 0.0

    is_combo_a = len(ingredients_a) > 1
    is_combo_b = len(ingredients_b) > 1

    if is_combo_a == is_combo_b:
        if overlap_ratio >= 1.0:
            return 0.75
        if overlap_ratio >= 0.5:
            return 0.5
        return 0.25

    if overlap_ratio > 0.0:
        return 0.25
    return 0.0
