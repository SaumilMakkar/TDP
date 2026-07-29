"""Stage B Sprint B5 age-risk checks."""

from __future__ import annotations

from stage_b.evidence.common import best_semantic_similarity, candidate_drug_context


_HIGH_RISK_KEYWORDS = {
    "opioid",
    "benzodiazepine",
    "sedative",
    "anticholinergic",
}

_MODERATE_RISK_KEYWORDS = {
    "antipsychotic",
    "tricyclic",
    "antidepressant",
    "hypoglycemic",
}


def evaluate_age_risk(
    *,
    age: int,
    candidate_prod_id: int,
    candidate_context: dict[str, object] | None = None,
) -> dict[str, object]:
    """Return age risk score in [0,1], where higher is riskier."""
    candidate = (
        dict(candidate_context)
        if isinstance(candidate_context, dict)
        else candidate_drug_context(candidate_prod_id)
    )
    tokens = set(candidate["tokens"])

    has_high_risk_match = any(best_semantic_similarity(keyword, tokens) >= 0.5 for keyword in _HIGH_RISK_KEYWORDS)
    has_moderate_risk_match = any(
        best_semantic_similarity(keyword, tokens) >= 0.5 for keyword in _MODERATE_RISK_KEYWORDS
    )

    if age >= 75 and has_high_risk_match:
        return {
            "age_risk": 1.0,
            "risk_band": "high",
            "reason": "elderly_with_high_risk_drug_class",
        }
    if age >= 65 and (has_high_risk_match or has_moderate_risk_match):
        return {
            "age_risk": 0.5,
            "risk_band": "moderate",
            "reason": "older_adult_with_risk_prone_drug_class",
        }
    if age >= 75:
        return {
            "age_risk": 0.25,
            "risk_band": "moderate",
            "reason": "elderly_age_baseline_risk",
        }
    return {
        "age_risk": 0.0,
        "risk_band": "low",
        "reason": "low_age_related_risk",
    }
