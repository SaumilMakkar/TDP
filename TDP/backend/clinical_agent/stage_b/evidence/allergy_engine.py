"""Stage B Sprint B3 allergy safety checks."""

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


ALLERGY_CROSS_REACTIVITY_CSV = STAGE_B_DATA_DIR / "allergy_cross_reactivity_reference.csv"


def _load_allergy_reference(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=["allergen_group", "cross_reactive_group", "severity"])
    return pd.read_csv(path, low_memory=False)


ALLERGY_REF_DF = _load_allergy_reference(ALLERGY_CROSS_REACTIVITY_CSV)


def evaluate_allergy_risk(
    *,
    allergies: list[str],
    candidate_prod_id: int,
    candidate_context: dict[str, object] | None = None,
) -> dict[str, object]:
    """Return deterministic bucketized allergy risk for patient vs candidate drug."""
    normalized_allergies = normalize_list(allergies)
    candidate = (
        dict(candidate_context)
        if isinstance(candidate_context, dict)
        else candidate_drug_context(candidate_prod_id)
    )
    candidate_tokens = set(candidate["tokens"])

    if not normalized_allergies:
        return {
            "allergy_risk": 0,
            "matched_allergen": None,
            "matched_cross_reactivity": None,
            "severity": None,
            "gate_triggered": False,
            "gate_type": None,
        }

    # Direct overlap first.
    for allergy in normalized_allergies:
        similarity = best_semantic_similarity(allergy, candidate_tokens)
        if similarity >= 0.75:
            return {
                "allergy_risk": 1,
                "matched_allergen": allergy,
                "matched_cross_reactivity": allergy,
                "severity": "HIGH",
                "gate_triggered": True,
                "gate_type": "exact_allergy_match",
            }

    # Cross-reactive groups from reference table.
    for _, row in ALLERGY_REF_DF.iterrows():
        allergen = normalize_text(row.get("allergen_group"))
        cross_group = normalize_text(row.get("cross_reactive_group"))
        severity = str(row.get("severity", "")).strip().upper() or None

        if not allergen or not cross_group:
            continue
        if best_semantic_similarity(allergen, normalized_allergies) < 0.75:
            continue

        cross_similarity = best_semantic_similarity(cross_group, candidate_tokens)
        if cross_similarity >= 0.75:
            return {
                "allergy_risk": 1,
                "matched_allergen": allergen,
                "matched_cross_reactivity": cross_group,
                "severity": severity,
                "gate_triggered": True,
                "gate_type": "cross_reactivity",
            }

    # Partial semantic overlap still contributes to soft risk, without hard gate.
    best_partial = 0.0
    matched_allergy = None
    for allergy in normalized_allergies:
        similarity = best_semantic_similarity(allergy, candidate_tokens)
        if similarity > best_partial:
            best_partial = similarity
            matched_allergy = allergy

    partial_risk = 0.0
    if best_partial >= 0.5:
        partial_risk = 0.5
    elif best_partial >= 0.25:
        partial_risk = 0.25

    if partial_risk > 0.0:
        return {
            "allergy_risk": float(partial_risk),
            "matched_allergen": matched_allergy,
            "matched_cross_reactivity": None,
            "severity": "LOW",
            "gate_triggered": False,
            "gate_type": None,
        }

    return {
        "allergy_risk": 0,
        "matched_allergen": None,
        "matched_cross_reactivity": None,
        "severity": None,
        "gate_triggered": False,
        "gate_type": None,
    }
