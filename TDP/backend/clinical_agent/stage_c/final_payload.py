"""Phase 10 of Stage C: build the final payload emitted to the orchestrator."""

from __future__ import annotations

from .models import StageCCandidate


def _stage_b_findings(stage_b_evidence: dict[str, object]) -> dict[str, object]:
    scores = stage_b_evidence.get("scores")
    if isinstance(scores, dict):
        return dict(scores)
    return dict(stage_b_evidence)


def build_final_payload(original_drug: dict, candidates: list[StageCCandidate]) -> dict[str, object]:
    """Assemble the exact final Stage C payload for the orchestrator."""

    ranked_alternatives: list[dict[str, object]] = []
    for candidate in candidates:
        if candidate.threshold_passed is not True:
            continue

        ranked_alternatives.append(
            {
                "rank": candidate.rank,
                "candidate_id": candidate.candidate_id,
                "candidate_name": candidate.candidate_name,
                # Only threshold-passing candidates are ranked and emitted here.
                "overall_status": "PASS",
                "stage_a": {
                    "prod_id": candidate.candidate_id,
                    "prod_name": candidate.candidate_name,
                    "evidence": dict(candidate.stage_a_evidence),
                    "score": candidate.stage_a_score,
                    "status": "accepted",
                    "llm_required": bool(candidate.stage_a_llm_required),
                    "reasoning": candidate.stage_a_reasoning or None,
                },
                "stage_b": {
                    "prod_id": candidate.candidate_id,
                    "prod_name": candidate.candidate_name,
                    "evidence": _stage_b_findings(candidate.stage_b_evidence),
                    "score": candidate.stage_b_score,
                    "status": candidate.stage_b_decision,
                    "llm_required": bool(candidate.stage_b_llm_required),
                    "reasoning": candidate.stage_b_reasoning or None,
                },
                "stage_c": {
                    "composite_score": candidate.composite_score,
                    "threshold_passed": bool(candidate.threshold_passed),
                    "safety_flags": (
                        {
                            "polypharmacy": candidate.stage_c_flags.polypharmacy,
                            "missing_clinical_data": candidate.stage_c_flags.missing_clinical_data,
                            "clinical_ambiguity": candidate.stage_c_flags.clinical_ambiguity,
                            "cumulative_risk": candidate.stage_c_flags.cumulative_risk,
                        }
                        if candidate.stage_c_flags is not None
                        else {}
                    ),
                },
            }
        )

    return {
        "original_drug": dict(original_drug),
        "ranked_alternatives": ranked_alternatives,
    }