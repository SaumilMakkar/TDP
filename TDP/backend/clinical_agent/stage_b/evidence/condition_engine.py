"""Stage B Sprint B4 condition appropriateness checks."""

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

# Positive condition-fit heuristics when no contraindication is present.
_CONDITION_CLASS_MAP: dict[str, list[str]] = {
    "type 2 diabetes": ["biguanide", "sglt2 inhibitor", "dpp 4 inhibitor", "sulfonylurea"],
    "hypertension": ["ace inhibitor", "beta blocker", "calcium channel blocker", "thiazide"],
    "hyperlipidemia": ["statin"],
    "heart failure": ["ace inhibitor", "beta blocker", "arni", "loop diuretic"],
    "gerd": ["proton pump inhibitor"],
    "asthma": ["beta 2 agonist", "leukotriene", "inhalant", "corticosteroid"],
}


def evaluate_condition_match(
    *,
    conditions: list[str],
    candidate_prod_id: int,
    candidate_context: dict[str, object] | None = None,
) -> dict[str, object]:
    """Return condition appropriateness score in [0,1] for candidate drug."""
    normalized_conditions = normalize_list(conditions)
    candidate = (
        dict(candidate_context)
        if isinstance(candidate_context, dict)
        else candidate_drug_context(candidate_prod_id)
    )
    candidate_tokens = set(candidate["tokens"])
    candidate_ingredients = set(candidate["ingredients"])

    # Contraindication-driven low appropriateness.
    for _, row in CONTRA_REF_DF.iterrows():
        ingredient = normalize_text(row.get("ingredient"))
        condition = normalize_text(row.get("condition"))
        severity = str(row.get("severity", "")).strip().upper() or None

        if not ingredient or not condition:
            continue
        ingredient_hit = ingredient in candidate_ingredients or any(
            ingredient in token or token in ingredient for token in candidate_tokens
        )
        if not ingredient_hit:
            continue

        for patient_condition in normalized_conditions:
            if condition in patient_condition or patient_condition in condition:
                return {
                    "condition_match": 0.25,
                    "matched_condition": patient_condition,
                    "matched_reference_condition": condition,
                    "severity": severity,
                    "reason": "contraindication_condition_overlap",
                }

    # Positive condition-fit heuristics.
    for patient_condition in normalized_conditions:
        keywords = _CONDITION_CLASS_MAP.get(patient_condition, [])
        best_alignment = 0.0
        for keyword in keywords:
            best_alignment = max(best_alignment, best_semantic_similarity(keyword, candidate_tokens))

        if best_alignment >= 0.75:
            return {
                "condition_match": 1.0,
                "matched_condition": patient_condition,
                "matched_reference_condition": None,
                "severity": None,
                "reason": "condition_class_alignment",
            }
        if best_alignment >= 0.5:
            return {
                "condition_match": 0.75,
                "matched_condition": patient_condition,
                "matched_reference_condition": None,
                "severity": None,
                "reason": "condition_class_partial_alignment",
            }
        if best_alignment >= 0.25:
            return {
                "condition_match": 0.5,
                "matched_condition": patient_condition,
                "matched_reference_condition": None,
                "severity": None,
                "reason": "condition_weak_class_alignment",
            }

    # Neutral fallback: no strong evidence either way.
    return {
        "condition_match": 0.5,
        "matched_condition": None,
        "matched_reference_condition": None,
        "severity": None,
        "reason": "insufficient_specific_condition_signal",
    }
