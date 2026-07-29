"""Sprint 7 confidence engine for Stage A pre-LLM routing."""

from __future__ import annotations

from typing import Mapping


DIRECT_ACCEPT_THRESHOLD = 0.50
LLM_REVIEW_MIN_THRESHOLD = 0.30


def _is_same_signal(score: float) -> bool:
    return float(score) >= 1.0


def confidence_engine(
    evidence: Mapping[str, float],
    base_similarity_score: float,
) -> dict[str, object]:
    """Return routing metadata from deterministic Stage A evidence."""
    ingredient = float(evidence.get("ingredient", 0.0))
    moiety = float(evidence.get("moiety", 0.0))
    therapeutic_class = float(evidence.get("class", 0.0))
    score = float(base_similarity_score)

# HIGH_CONFIDENCE_SCORE_FLOOR = 0.64
    # # High confidence shortcut from redesign doc: same ingredient or same moiety.
    # if _is_same_signal(ingredient) or _is_same_signal(moiety):
    #     return {
    #         "llm_required": False,
    #         "confidence_level": "high",
    #         "routing_decision": "direct_accept",
    #     }

    # # Low confidence rule from prompt: same class with different ingredient/moiety.
    # if therapeutic_class >= 0.5 and ingredient < 1.0 and moiety < 1.0:
    #     return {
    #         "llm_required": True,
    #         "confidence_level": "low",
    #         "routing_decision": "llm_review",
    #     }

    # Generic deterministic threshold routing for remaining candidates.
    if score >= DIRECT_ACCEPT_THRESHOLD:
        return {
            "llm_required": False,
            "confidence_level": "high",
            "routing_decision": "direct_accept",
        }

    if score >= LLM_REVIEW_MIN_THRESHOLD:
        return {
            "llm_required": True,
            "confidence_level": "low",
            "routing_decision": "llm_review",
        }

    return {
        "llm_required": False,
        "confidence_level": "low",
        "routing_decision": "direct_reject",
    }
