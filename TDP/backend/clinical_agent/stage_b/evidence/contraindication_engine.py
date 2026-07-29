"""Stage B Sprint B6 contraindication checks."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from stage_b.config import STAGE_B_DATA_DIR
from stage_b.evidence.common import (
    best_semantic_similarity,
    candidate_drug_context,
    normalize_list,
    normalize_text,
)


CONTRAINDICATION_CSV = STAGE_B_DATA_DIR / "drug_contraindication_reference.csv"


def _load_contra_reference(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=["ingredient", "condition", "severity", "rule_source"])
    return pd.read_csv(path, low_memory=False)


CONTRA_REF_DF = _load_contra_reference(CONTRAINDICATION_CSV)

_SEVERITY_TO_SCORE = {
    "CONTRAINDICATED": 1.0,
    "MAJOR": 0.75,
    "MODERATE": 0.5,
    "MINOR": 0.25,
}


def evaluate_contraindication(
    *,
    conditions: list[str],
    allergies: list[str],
    candidate_prod_id: int,
    candidate_context: dict[str, object] | None = None,
) -> dict[str, object]:
    """Return contraindication signal and normalized risk score."""
    normalized_conditions = normalize_list(conditions)
    normalized_allergies = normalize_list(allergies)

    # Allow allergy-based contraindication rows like "Penicillin Allergy" to match.
    derived_conditions = set(normalized_conditions)
    for allergy in normalized_allergies:
        if allergy:
            derived_conditions.add(f"{allergy} allergy")

    candidate = (
        dict(candidate_context)
        if isinstance(candidate_context, dict)
        else candidate_drug_context(candidate_prod_id)
    )
    candidate_tokens = set(candidate["tokens"])
    candidate_ingredients = set(candidate["ingredients"])

    best_match: dict[str, object] | None = None
    best_score = 0.0

    for _, row in CONTRA_REF_DF.iterrows():
        ingredient = normalize_text(row.get("ingredient"))
        condition = normalize_text(row.get("condition"))
        severity = str(row.get("severity", "")).strip().upper() or "MINOR"
        rule_source = str(row.get("rule_source", "")).strip() or None

        if not ingredient or not condition:
            continue

        ingredient_hit = best_semantic_similarity(ingredient, candidate_ingredients | candidate_tokens) >= 0.5
        if not ingredient_hit:
            continue

        matched_patient_condition = None
        for patient_condition in derived_conditions:
            if best_semantic_similarity(condition, [patient_condition]) >= 0.5:
                matched_patient_condition = patient_condition
                break
        if matched_patient_condition is None:
            continue

        score = float(_SEVERITY_TO_SCORE.get(severity, 0.25))
        if score > best_score:
            best_score = score
            best_match = {
                "contraindication": True,
                "contraindication_score": score,
                "matched_condition": matched_patient_condition,
                "matched_reference_condition": condition,
                "matched_ingredient": ingredient,
                "severity": severity,
                "rule_source": rule_source,
            }

    if best_match is not None:
        return best_match

    return {
        "contraindication": False,
        "contraindication_score": 0.0,
        "matched_condition": None,
        "matched_reference_condition": None,
        "matched_ingredient": None,
        "severity": None,
        "rule_source": None,
    }
