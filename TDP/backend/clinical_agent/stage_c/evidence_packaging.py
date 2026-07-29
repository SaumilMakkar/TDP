"""Phase 2 of Stage C: package the minimal evidence needed for downstream review."""

from __future__ import annotations

from typing import Any

from .models import StageCCandidate


def _stage_view(record: dict[str, Any], stage_key: str) -> dict[str, Any]:
    stage_payload = record.get(stage_key)
    if isinstance(stage_payload, dict):
        return stage_payload
    return record


def package_evidence(eligible_candidates: list[dict[str, Any]]) -> list[StageCCandidate]:
    """Package eligible candidates into the minimal Stage C evidence model.

    Phase 2 strips the Stage A and Stage B records down to the evidence fields that
    the rest of Stage C will consume, preserving only the candidate identifier and
    the required upstream scoring and reasoning artifacts.
    """

    packaged_candidates: list[StageCCandidate] = []
    for candidate in eligible_candidates:
        candidate_id = candidate.get("candidate_id", candidate.get("prod_id", candidate.get("id")))
        if candidate_id is None:
            raise ValueError("Eligible candidate is missing an identifier field.")

        stage_a_payload = _stage_view(candidate, "stage_a")
        stage_b_payload = _stage_view(candidate, "stage_b")

        stage_b_score = stage_b_payload.get("stage_b_score", stage_b_payload.get("score"))
        stage_b_evidence = stage_b_payload.get("stage_b_evidence", stage_b_payload.get("evidence", {}))
        stage_b_llm_required = stage_b_payload.get(
            "stage_b_llm_required",
            stage_b_payload.get("llm_required"),
        )
        stage_b_decision = candidate.get(
            "stage_b_decision",
            stage_b_payload.get("stage_b_decision", stage_b_payload.get("decision", stage_b_payload.get("status", ""))),
        )
        candidate_name = str(candidate.get("prod_name", candidate.get("name", "")) or "")
        stage_b_reasoning = str(
            stage_b_payload.get(
                "stage_b_reasoning",
                stage_b_payload.get("reasoning", ""),
            )
            or ""
        )

        packaged_candidates.append(
            StageCCandidate(
                candidate_id=candidate_id,
                candidate_name=candidate_name,
                stage_a_score=stage_a_payload.get("score"),
                stage_a_evidence=dict(stage_a_payload.get("evidence", {})),
                stage_a_llm_required=stage_a_payload.get("llm_required"),
                stage_a_reasoning=str(stage_a_payload.get("reasoning", "")),
                stage_b_score=stage_b_score,
                stage_b_evidence=dict(stage_b_evidence),
                stage_b_llm_required=stage_b_llm_required,
                stage_b_decision=str(stage_b_decision),
                stage_b_reasoning=stage_b_reasoning,
            )
        )

    return packaged_candidates