"""Stage B Sprint B8 weighted risk aggregation."""

from __future__ import annotations

from typing import Mapping

from stage_b.scoring.ahp import get_default_stage_b_weight_percentages, get_default_stage_b_weights


DEFAULT_STAGE_B_WEIGHTS: dict[str, float] = get_default_stage_b_weights()


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def aggregate_stage_b_score(
    *,
    allergy_risk: float,
    interaction_score: float,
    age_risk: float,
    condition_match: float,
    contraindication_score: float,
    renal_hepatic_score: float,
    duplicate_therapy_score: float,
    weights: Mapping[str, float] | None = None,
) -> dict[str, object]:
    """Combine Stage B evidence into one normalized score.

    Higher `stage_b_score` means better candidate safety/appropriateness.
    """
    w = dict(weights) if weights is not None else get_default_stage_b_weights()
    weight_percent = get_default_stage_b_weight_percentages()

    components = {
        "contraindication": _clamp01(1.0 - contraindication_score),
        "allergy": _clamp01(1.0 - allergy_risk),
        "interaction": _clamp01(1.0 - interaction_score),
        "renal_hepatic": _clamp01(renal_hepatic_score),
        "duplicate_therapy": _clamp01(duplicate_therapy_score),
        "condition": _clamp01(condition_match),
        "age": _clamp01(1.0 - age_risk),
    }

    score = 0.0
    for key, weight in w.items():
        score += float(weight) * float(components.get(key, 0.0))

    final_score = round(_clamp01(score), 4)
    return {
        "stage_b_score": final_score,
        "patient_safety_score": final_score,
        "weights": w,
        "weight_percent": weight_percent,
        "normalized_components": components,
    }
