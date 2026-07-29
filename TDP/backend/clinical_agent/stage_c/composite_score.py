"""Phase 4 of Stage C: compute a composite score from Stage A similarity and Stage B safety."""

from __future__ import annotations

import math

from .config import StageCConfig
from .models import StageCCandidate


def validate_composite_weights(config: StageCConfig) -> None:
    """Validate that composite-score weights form a proper probability distribution."""

    weight_sum = float(config.similarity_weight) + float(config.safety_weight)
    if not math.isclose(weight_sum, 1.0, rel_tol=0.0, abs_tol=1e-9):
        raise ValueError(
            "Stage C composite-score weights must sum to 1.0; "
            f"got similarity_weight={config.similarity_weight} and "
            f"safety_weight={config.safety_weight}."
        )


def compute_composite_score(candidate: StageCCandidate, config: StageCConfig) -> float:
    """Compute the final Stage C score from normalized similarity and safety inputs."""

    validate_composite_weights(config)
    if candidate.stage_a_score is None:
        raise ValueError(f"Candidate {candidate.candidate_id!r} is missing Stage A similarity score.")
    if candidate.stage_b_score is None:
        raise ValueError(f"Candidate {candidate.candidate_id!r} is missing Stage B safety score.")

    composite_score = (
        float(config.similarity_weight) * float(candidate.stage_a_score)
        + float(config.safety_weight) * float(candidate.stage_b_score)
    )
    candidate.composite_score = round(float(composite_score), 4)
    return float(candidate.composite_score)


def compute_composite_scores(
    candidates: list[StageCCandidate],
    config: StageCConfig,
) -> list[StageCCandidate]:
    """Apply Phase 4 scoring to every packaged Stage C candidate."""

    for candidate in candidates:
        compute_composite_score(candidate, config)
    return candidates