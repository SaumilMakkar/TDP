"""Phase 1 of Stage C: select candidates accepted by both upstream stages."""

from __future__ import annotations

from typing import Any


def _index_candidates(
    candidates: list[dict[str, Any]],
    *,
    source_name: str,
) -> dict[int | str, dict[str, Any]]:
    indexed: dict[int | str, dict[str, Any]] = {}
    for candidate in candidates:
        candidate_id = _candidate_id(candidate)
        if candidate_id in indexed:
            raise ValueError(
                f"Duplicate candidate_id {candidate_id!r} found in {source_name}. "
                "Stage C refuses to silently overwrite malformed upstream data."
            )
        indexed[candidate_id] = candidate
    return indexed


def _extract_candidates(payload: dict[str, Any] | list[dict[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return payload

    for key in ("eligible_candidates", "alternatives", "candidates", "records"):
        candidates = payload.get(key)
        if isinstance(candidates, list):
            return [candidate for candidate in candidates if isinstance(candidate, dict)]

    return []


def _candidate_id(record: dict[str, Any]) -> int | str:
    for key in ("candidate_id", "id", "prod_id"):
        if key in record:
            return record[key]
    raise ValueError("Candidate record is missing an identifier field.")


def _stage_view(record: dict[str, Any], stage_key: str) -> dict[str, Any]:
    stage_payload = record.get(stage_key)
    if isinstance(stage_payload, dict):
        return stage_payload
    return record


def _stage_a_status(record: dict[str, Any]) -> str:
    stage_a_payload = _stage_view(record, "stage_a")
    return str(stage_a_payload.get("status", record.get("stage_a_status", ""))).strip().lower()


def _stage_b_decision(record: dict[str, Any]) -> str:
    stage_b_payload = _stage_view(record, "stage_b")
    raw_decision = stage_b_payload.get("decision")
    if raw_decision is None:
        raw_decision = record.get("stage_b_decision", stage_b_payload.get("status", ""))
    return str(raw_decision).strip().lower()


def _normalize_stage_b_decision(decision: str) -> str:
    if decision == "accepted":
        return "accept"
    if decision == "rejected":
        return "reject"
    return decision


def _extract_stage_b_candidates(payload: dict[str, Any] | list[dict[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return payload

    # Stage B's richer per-alternative evidence lives under from_stage_a.alternatives,
    # while the public summary list under alternatives keeps only compact fields.
    enriched = payload.get("from_stage_a")
    if isinstance(enriched, dict):
        candidates = enriched.get("alternatives")
        if isinstance(candidates, list):
            return [candidate for candidate in candidates if isinstance(candidate, dict)]

    return _extract_candidates(payload)


def select_candidates(stage_a_output: dict, stage_b_output: dict) -> dict[str, list[dict[str, Any]]]:
    """Return only candidates accepted by Stage A and accepted for progression by Stage B.

    Phase 1 is the Stage C entry point. It receives Stage A and Stage B JSON payloads,
    aligns candidate records by identifier, and keeps only those that satisfy both
    upstream acceptance conditions.
    """

    stage_a_candidates = _extract_candidates(stage_a_output)
    stage_b_candidates = _extract_stage_b_candidates(stage_b_output)

    stage_a_by_id = _index_candidates(stage_a_candidates, source_name="Stage A candidates")
    stage_b_by_id = _index_candidates(stage_b_candidates, source_name="Stage B candidates")

    eligible_candidates: list[dict[str, Any]] = []
    for candidate_id, stage_a_candidate in stage_a_by_id.items():
        stage_b_candidate = stage_b_by_id.get(candidate_id)
        if stage_b_candidate is None:
            continue

        stage_a_status = _stage_a_status(stage_a_candidate)
        stage_b_decision = _normalize_stage_b_decision(_stage_b_decision(stage_b_candidate))
        if stage_a_status != "accepted" or stage_b_decision != "accept":
            continue

        merged_candidate = dict(stage_a_candidate)
        merged_candidate["candidate_id"] = candidate_id
        if "stage_a" not in merged_candidate:
            merged_candidate["stage_a"] = _stage_view(stage_a_candidate, "stage_a")
        merged_candidate["stage_b"] = _stage_view(stage_b_candidate, "stage_b")
        merged_candidate["stage_b_decision"] = stage_b_decision

        for field in ("prod_name", "name"):
            if field not in merged_candidate and field in stage_b_candidate:
                merged_candidate[field] = stage_b_candidate[field]

        eligible_candidates.append(merged_candidate)

    return {"eligible_candidates": eligible_candidates}