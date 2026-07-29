"""Stage B Sprint B7 drug-drug interaction checks."""

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


INTERACTION_CSV = STAGE_B_DATA_DIR / "drug_interaction_reference.csv"


def _load_interaction_reference(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=["ingredient_a", "ingredient_b", "severity", "reason", "evidence_level"])
    return pd.read_csv(path, low_memory=False)


INTERACTION_REF_DF = _load_interaction_reference(INTERACTION_CSV)

_SEVERITY_RANK = {
    "NONE": 0,
    "MINOR": 1,
    "MODERATE": 2,
    "MAJOR": 3,
    "CONTRAINDICATED": 4,
}

_SEVERITY_TO_SCORE = {
    "NONE": 0.0,
    "MINOR": 0.25,
    "MODERATE": 0.5,
    "MAJOR": 0.75,
    "CONTRAINDICATED": 1.0,
}


def _normalize_medications(current_medications: list[str]) -> list[str]:
    meds: list[str] = []
    for med in normalize_list(current_medications):
        if med:
            meds.append(med)
    return meds


def evaluate_interaction_risk(
    *,
    current_medications: list[str],
    candidate_prod_id: int,
    candidate_context: dict[str, object] | None = None,
) -> dict[str, object]:
    """Return highest-severity interaction signal for candidate vs current meds."""
    meds = _normalize_medications(current_medications)
    candidate = (
        dict(candidate_context)
        if isinstance(candidate_context, dict)
        else candidate_drug_context(candidate_prod_id)
    )

    candidate_terms = set(candidate["ingredients"]) | {candidate["generic_name"]}
    candidate_tokens = set(candidate["tokens"])

    matches: list[dict[str, object]] = []
    best_severity = "NONE"

    for _, row in INTERACTION_REF_DF.iterrows():
        ingredient_a = normalize_text(row.get("ingredient_a"))
        ingredient_b = normalize_text(row.get("ingredient_b"))
        severity = str(row.get("severity", "")).strip().upper() or "MINOR"
        reason = str(row.get("reason", "")).strip() or None
        evidence_level = str(row.get("evidence_level", "")).strip() or None

        if not ingredient_a or not ingredient_b:
            continue

        candidate_has_a = best_semantic_similarity(ingredient_a, candidate_terms | candidate_tokens) >= 0.5
        candidate_has_b = best_semantic_similarity(ingredient_b, candidate_terms | candidate_tokens) >= 0.5

        if not (candidate_has_a or candidate_has_b):
            continue

        counterpart = ingredient_b if candidate_has_a else ingredient_a
        matched_med = None
        for med in meds:
            if best_semantic_similarity(counterpart, [med]) >= 0.5:
                matched_med = med
                break
        if matched_med is None:
            continue

        matches.append(
            {
                "candidate_term": ingredient_a if candidate_has_a else ingredient_b,
                "current_medication": matched_med,
                "counterpart_term": counterpart,
                "severity": severity,
                "reason": reason,
                "evidence_level": evidence_level,
            }
        )
        if _SEVERITY_RANK.get(severity, 1) > _SEVERITY_RANK.get(best_severity, 0):
            best_severity = severity

    if not matches:
        return {
            "interaction_detected": False,
            "interaction_severity": "none",
            "interaction_score": 0.0,
            "matches": [],
        }

    return {
        "interaction_detected": True,
        "interaction_severity": best_severity.lower(),
        "interaction_score": float(_SEVERITY_TO_SCORE.get(best_severity, 0.3)),
        "matches": matches,
    }
