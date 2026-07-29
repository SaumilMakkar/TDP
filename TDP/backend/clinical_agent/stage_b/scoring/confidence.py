"""Stage B Sprint B9 confidence routing and deterministic decision rules."""

from __future__ import annotations

from typing import Mapping


DIRECT_ACCEPT_THRESHOLD = 0.85
LLM_REVIEW_MIN_THRESHOLD = 0.50


def _is_same_signal(score: float) -> bool:
    return float(score) >= 1.0


def stage_b_confidence_engine(
    *,
    stage_b_score: float,
    contraindication: bool,
    interaction_severity: str,
    evidence_quality: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Return routing metadata from deterministic Stage B evidence."""
    _ = contraindication
    _ = interaction_severity
    _ = evidence_quality

    score = float(stage_b_score)

    # HIGH_CONFIDENCE_SCORE_FLOOR = 0.64
    # # High confidence shortcut placeholder to mirror Stage A style.
    # if _is_same_signal(stage_b_score):
    #     return {
    #         "llm_required": False,
    #         "confidence_level": "high",
    #         "routing_decision": "direct_accept",
    #     }

    # Generic deterministic threshold routing for remaining candidates.

    if score >= DIRECT_ACCEPT_THRESHOLD:
        return {
            "decision": "accept",
            "llm_required": False,
            "confidence_level": "high",
            "confidence_score": float(round(score, 4)),
            "reason_code": "direct_accept",
            "routing_decision": "direct_accept",
        }

    if score >= LLM_REVIEW_MIN_THRESHOLD:
        return {
            "decision": "review",
            "llm_required": True,
            "confidence_level": "low",
            "confidence_score": float(round(score, 4)),
            "reason_code": "llm_review",
            "routing_decision": "llm_review",
        }

    return {
        "decision": "reject",
        "llm_required": False,
        "confidence_level": "low",
        "confidence_score": float(round(score, 4)),
        "reason_code": "direct_reject",
        "routing_decision": "direct_reject",
    }


def apply_llm_adjustment(
    *,
    base_score: float,
    adjustment: float,
    min_adjustment: float = -0.10,
    max_adjustment: float = 0.10,
) -> dict[str, float]:
    """Apply bounded LLM score adjustment and return normalized final score."""
    bounded = max(min_adjustment, min(max_adjustment, float(adjustment)))
    final = max(0.0, min(1.0, float(base_score) + bounded))
    return {
        "adjustment": float(bounded),
        "final_score": float(round(final, 4)),
    }
