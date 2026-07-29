"""Phase 6 of Stage C: rank threshold-passing candidates into final recommendation order."""

from __future__ import annotations

from .models import StageCCandidate


def rank_candidates(candidates: list[StageCCandidate]) -> list[StageCCandidate]:
    """Produce the final recommendation order.

    Phase 6 expects candidates that already passed Phases 1-5. It does not re-check
    Stage A or Stage B acceptance because Phase 1 already guaranteed those conditions.
    As a defensive guard, any candidate whose `threshold_passed` is not true is
    skipped rather than ranked. Ties on `composite_score` preserve input order from
    the thresholded candidate list.
    """

    passing_candidates = [candidate for candidate in candidates if candidate.threshold_passed is True]
    ranked_candidates = sorted(
        enumerate(passing_candidates),
        key=lambda item: (-float(item[1].composite_score or 0.0), item[0]),
    )

    ordered_candidates: list[StageCCandidate] = []
    for rank, (_, candidate) in enumerate(ranked_candidates, start=1):
        candidate.rank = rank
        ordered_candidates.append(candidate)

    return ordered_candidates
