"""Phase 5 of Stage C: exclude weak alternatives before ranking."""

from __future__ import annotations

from .config import StageCConfig
from .models import StageCCandidate


def apply_threshold(candidate: StageCCandidate, config: StageCConfig) -> bool:
    """Why: prevents weak alternatives from reaching the ranking stage."""

    if candidate.composite_score is None:
        raise ValueError(
            f"Candidate {candidate.candidate_id!r} is missing composite_score. "
            "Phase 4 must run before Phase 5."
        )

    candidate.threshold_passed = bool(
        float(candidate.composite_score) > float(config.minimum_composite_score)
    )
    return bool(candidate.threshold_passed)


def filter_passing_candidates(
    candidates: list[StageCCandidate],
    config: StageCConfig,
) -> list[StageCCandidate]:
    """Apply threshold flags to all candidates and return only those that passed."""

    passing_candidates: list[StageCCandidate] = []
    for candidate in candidates:
        if apply_threshold(candidate, config):
            passing_candidates.append(candidate)
    return passing_candidates