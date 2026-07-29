"""Stage B deterministic duplicate therapy checks."""

from __future__ import annotations

import pandas as pd

from stage_a.config import PRODUCT_CSV_NAME, csv_path
from stage_b.evidence.common import (
    best_semantic_similarity,
    candidate_drug_context,
    normalize_list,
    normalize_text,
)


def _load_product_lookup() -> pd.DataFrame:
    try:
        path = csv_path(PRODUCT_CSV_NAME)
    except Exception:
        return pd.DataFrame(columns=["PROD_NM", "GNRC_NM", "THRPC_CLASS_NM"])
    return pd.read_csv(path, low_memory=False)


PRODUCT_LOOKUP_DF = _load_product_lookup()


def _med_lookup_context(medication_text: str) -> dict[str, str | None]:
    med_norm = normalize_text(medication_text)
    if not med_norm or PRODUCT_LOOKUP_DF.empty:
        return {"generic": None, "therapeutic_class": None}

    for _, row in PRODUCT_LOOKUP_DF.iterrows():
        product_name = normalize_text(row.get("PROD_NM"))
        generic_name = normalize_text(row.get("GNRC_NM"))
        therapeutic_class = normalize_text(row.get("THRPC_CLASS_NM"))

        if product_name and (product_name in med_norm or med_norm in product_name):
            return {"generic": generic_name or None, "therapeutic_class": therapeutic_class or None}
        if generic_name and (generic_name in med_norm or med_norm in generic_name):
            return {"generic": generic_name or None, "therapeutic_class": therapeutic_class or None}

    return {"generic": None, "therapeutic_class": None}


def _contains_all_tokens(text: str, phrase: str) -> bool:
    text_tokens = set(normalize_text(text).split())
    phrase_tokens = [token for token in normalize_text(phrase).split() if token]
    if not phrase_tokens:
        return False
    return all(token in text_tokens for token in phrase_tokens)


def evaluate_duplicate_therapy(
    *,
    current_medications: list[str],
    candidate_prod_id: int,
    candidate_context: dict[str, object] | None = None,
) -> dict[str, object]:
    """Return duplicate therapy status and soft score for candidate vs current meds."""
    meds = normalize_list(current_medications)
    candidate = (
        dict(candidate_context)
        if isinstance(candidate_context, dict)
        else candidate_drug_context(candidate_prod_id)
    )
    candidate_generic = normalize_text(candidate.get("generic_name"))
    candidate_class = normalize_text(candidate.get("therapeutic_class"))
    candidate_ingredients = set(candidate.get("ingredients", []))

    if not meds:
        return {
            "status": "PASS",
            "severity": "UNKNOWN",
            "score": 0.5,
            "reason": "current_medications_unavailable",
            "match_type": None,
            "matched_medication": None,
        }

    # Exact duplicate gate.
    for med in meds:
        if candidate_generic and (
            _contains_all_tokens(med, candidate_generic)
            or best_semantic_similarity(candidate_generic, [med]) >= 0.75
        ):
            return {
                "status": "FAIL",
                "severity": "HIGH",
                "score": 0.0,
                "reason": "exact_duplicate_therapy",
                "match_type": "exact_duplicate",
                "matched_medication": med,
            }

    # Same active ingredient duplicate risk.
    for med in meds:
        for ingredient in candidate_ingredients:
            if ingredient and best_semantic_similarity(ingredient, [med]) >= 0.5:
                return {
                    "status": "PASS",
                    "severity": "MODERATE",
                    "score": 0.5,
                    "reason": "same_active_ingredient_detected",
                    "match_type": "same_ingredient",
                    "matched_medication": med,
                }

    # Same therapeutic class overlap risk.
    for med in meds:
        context = _med_lookup_context(med)
        med_class = normalize_text(context.get("therapeutic_class"))
        if med_class and candidate_class and best_semantic_similarity(med_class, [candidate_class]) >= 0.5:
            return {
                "status": "PASS",
                "severity": "MINOR",
                "score": 0.75,
                "reason": "same_therapeutic_class_detected",
                "match_type": "same_class",
                "matched_medication": med,
            }

    return {
        "status": "PASS",
        "severity": "NONE",
        "score": 1.0,
        "reason": "no_duplicate_therapy_signal",
        "match_type": None,
        "matched_medication": None,
    }
