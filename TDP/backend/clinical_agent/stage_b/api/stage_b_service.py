"""Stage B orchestration for Sprint B1-B10 with Stage A handoff integration."""

from __future__ import annotations

from typing import Any

from stage_a.api.stage_a_service import run_stage_a_pipeline
from stage_b.normalization.patient_normalizer import build_patient, resolve_member_id
from stage_b.evidence import (
    evaluate_age_risk,
    evaluate_allergy_risk,
    evaluate_condition_match,
    evaluate_contraindication,
    evaluate_duplicate_therapy,
    evaluate_interaction_risk,
    evaluate_renal_hepatic_suitability,
)
from stage_b.evidence.common import candidate_drug_context, normalize_list
from stage_b.scoring import aggregate_stage_b_score
from stage_b.scoring.confidence import apply_llm_adjustment, stage_b_confidence_engine

try:
    from stage_b.llm.ambiguity_resolver import StageBAmbiguityResolver
except Exception:  # pragma: no cover - resolver is optional in offline test runs
    StageBAmbiguityResolver = Any


class StageBPipelineError(Exception):
    """Raised when Stage B cannot produce a valid response."""


def _coerce_member_id(stage_b_input: dict[str, object]) -> str:
    raw_member_id = stage_b_input.get("member") or stage_b_input.get("mbr_id")
    if raw_member_id is None:
        raise StageBPipelineError("Stage B input payload must include 'member' or 'mbr_id'.")
    if not str(raw_member_id).strip():
        raise StageBPipelineError("member/mbr_id must be a non-empty string.")
    try:
        return resolve_member_id(raw_member_id)
    except Exception as exc:
        raise StageBPipelineError(str(exc)) from exc


def _resolve_stage_b_adjustment(
    ambiguity_resolver,
    *,
    patient_payload: dict[str, object],
    candidate_payload: dict[str, object],
    stage_b_evidence: dict[str, object],
    base_score: float,
    confidence_level: str,
) -> dict[str, object]:
    if ambiguity_resolver is None:
        return {"adjustment": 0.0, "confidence": 0.0, "reasoning": ""}

    try:
        resolve_fn = getattr(ambiguity_resolver, "resolve_sync", None)
        if callable(resolve_fn):
            response = resolve_fn(
                patient=patient_payload,
                candidate_drug=candidate_payload,
                stage_b_evidence=stage_b_evidence,
                base_score=base_score,
                confidence_level=confidence_level,
            )
            return {
                "adjustment": float(response.get("adjustment", 0.0)),
                "confidence": float(response.get("confidence", 0.0)),
                "reasoning": str(response.get("reasoning", "") or ""),
            }
    except Exception as _exc:  # noqa: BLE001
        import sys, warnings
        warnings.warn(f"[Stage B] ambiguity resolver failed: {_exc}", stacklevel=2)

    return {"adjustment": 0.0, "confidence": 0.0, "reasoning": ""}


def _normalize_patient_profile(patient) -> dict[str, object]:
    return {
        "mbr_sk": int(patient.mbr_sk),
        "mbr_id": str(patient.mbr_id),
        "plan_sk": int(patient.plan_sk),
        "age": int(patient.age),
        "conditions": normalize_list(list(patient.conditions)),
        "allergies": normalize_list(list(patient.allergies)),
        "current_medications": normalize_list(list(patient.current_medications)),
    }


def _stage_b_evidence_template(
    *,
    allergy_result: dict[str, object],
    condition_result: dict[str, object],
    age_result: dict[str, object],
    contraindication_result: dict[str, object],
    interaction_result: dict[str, object],
    renal_hepatic_result: dict[str, object],
    duplicate_therapy_result: dict[str, object],
) -> dict[str, float]:
    return {
        "allergy": float(allergy_result.get("allergy_risk", 0.0)),
        "condition": float(condition_result.get("condition_match", 0.5)),
        "age": float(age_result.get("age_risk", 0.0)),
        "contraindication": float(contraindication_result.get("contraindication_score", 0.0)),
        "interaction": float(interaction_result.get("interaction_score", 0.0)),
        "renal_hepatic": float(renal_hepatic_result.get("score", 1.0)),
        "duplicate_therapy": float(duplicate_therapy_result.get("score", 1.0)),
    }


def run_stage_b_sprint1_8(
    stage_b_input: dict[str, object],
    *,
    stage_a_output: dict[str, Any],
    ambiguity_resolver: StageBAmbiguityResolver | None = None,
) -> dict[str, object]:
    """Attach normalized patient context and B3-B8 evidence to Stage A alternatives.

    This implements Sprint B1-B8:
    - Sprint B1 canonical Patient object
    - Sprint B2 member retrieval by MBR_ID
    - Sprint B3 allergy risk signal
    - Sprint B4 condition appropriateness signal
    - Sprint B5 age risk signal
    - Sprint B6 contraindication signal
    - Sprint B7 interaction risk signal
    - Sprint B8 weighted risk aggregation
    - Sprint B9 confidence routing
    - Sprint B10 bounded LLM review
    """
    member_id = _coerce_member_id(stage_b_input)
    try:
        patient = build_patient(member_id)
    except KeyError as exc:
        raise StageBPipelineError(str(exc)) from exc
    except ValueError as exc:
        raise StageBPipelineError(str(exc)) from exc

    alternatives = list(stage_a_output.get("alternatives", []))
    normalized_patient = _normalize_patient_profile(patient)
    normalized_candidate_context: dict[int, dict[str, object]] = {}
    for alternative in alternatives:
        prod_id_raw = alternative.get("prod_id", -1)
        try:
            prod_id = int(prod_id_raw)
        except (TypeError, ValueError):
            continue
        if prod_id <= 0 or prod_id in normalized_candidate_context:
            continue
        normalized_candidate_context[prod_id] = candidate_drug_context(prod_id)

    enriched_alternatives: list[dict[str, object]] = []
    stage_b_alternatives: list[dict[str, object]] = []

    for alternative in alternatives:
        alt = dict(alternative)
        prod_id = int(alt.get("prod_id", -1))
        if prod_id <= 0:
            continue

        candidate_context = normalized_candidate_context.get(prod_id)

        allergy_result = evaluate_allergy_risk(
            allergies=list(normalized_patient["allergies"]),
            candidate_prod_id=prod_id,
            candidate_context=candidate_context,
        )
        condition_result = evaluate_condition_match(
            conditions=list(normalized_patient["conditions"]),
            candidate_prod_id=prod_id,
            candidate_context=candidate_context,
        )
        age_result = evaluate_age_risk(
            age=patient.age,
            candidate_prod_id=prod_id,
            candidate_context=candidate_context,
        )
        contraindication_result = evaluate_contraindication(
            conditions=list(normalized_patient["conditions"]),
            allergies=list(normalized_patient["allergies"]),
            candidate_prod_id=prod_id,
            candidate_context=candidate_context,
        )
        interaction_result = evaluate_interaction_risk(
            current_medications=list(normalized_patient["current_medications"]),
            candidate_prod_id=prod_id,
            candidate_context=candidate_context,
        )
        renal_hepatic_result = evaluate_renal_hepatic_suitability(
            mbr_sk=patient.mbr_sk,
            candidate_prod_id=prod_id,
            candidate_context=candidate_context,
        )
        duplicate_therapy_result = evaluate_duplicate_therapy(
            current_medications=list(normalized_patient["current_medications"]),
            candidate_prod_id=prod_id,
            candidate_context=candidate_context,
        )

        interaction_severity = str(interaction_result.get("interaction_severity", "none")).strip().lower()

        conflict_detected = float(condition_result.get("condition_match", 0.0)) >= 0.9 and (
            bool(contraindication_result["contraindication"]) or interaction_severity in {"major", "contraindicated"}
        )
        evidence_quality = {
            "has_conditions": bool(normalized_patient["conditions"]),
            "has_allergies": bool(normalized_patient["allergies"]),
            "has_current_medications": bool(normalized_patient["current_medications"]),
            "renal_hepatic_data_complete": bool(renal_hepatic_result.get("data_complete", False)),
            "conflict_detected": bool(conflict_detected),
        }

        score_result = aggregate_stage_b_score(
            allergy_risk=float(allergy_result["allergy_risk"]),
            interaction_score=float(interaction_result["interaction_score"]),
            age_risk=float(age_result["age_risk"]),
            condition_match=float(condition_result["condition_match"]),
            contraindication_score=float(contraindication_result["contraindication_score"]),
            renal_hepatic_score=float(renal_hepatic_result.get("score", 1.0)),
            duplicate_therapy_score=float(duplicate_therapy_result.get("score", 1.0)),
        )
        base_stage_b_score = float(score_result["patient_safety_score"])
        confidence_result = stage_b_confidence_engine(
            stage_b_score=base_stage_b_score,
            contraindication=bool(contraindication_result["contraindication"]),
            interaction_severity=interaction_severity,
            evidence_quality=evidence_quality,
        )

        llm_result = {"adjustment": 0.0, "confidence": 0.0, "reasoning": ""}
        final_stage_b_score = base_stage_b_score
        if bool(confidence_result["llm_required"]):
            llm_result = _resolve_stage_b_adjustment(
                ambiguity_resolver,
                patient_payload=patient.to_dict(),
                candidate_payload={
                    "prod_id": int(alt.get("prod_id", prod_id)),
                    "prod_name": str(alt.get("prod_name", "") or ""),
                },
                stage_b_evidence={
                    "allergy": allergy_result,
                    "condition": condition_result,
                    "age": age_result,
                    "contraindication": contraindication_result,
                    "interaction": interaction_result,
                    "renal_hepatic": renal_hepatic_result,
                    "duplicate_therapy": duplicate_therapy_result,
                    "soft_risks": {
                        "interaction_severity": interaction_result.get("interaction_severity"),
                        "age_risk": age_result.get("age_risk"),
                        "condition_match": condition_result.get("condition_match"),
                        "renal_hepatic_score": renal_hepatic_result.get("score"),
                        "duplicate_therapy_score": duplicate_therapy_result.get("score"),
                    },
                    "confidence": confidence_result,
                    "evidence_quality": evidence_quality,
                    "risk_aggregation": score_result,
                },
                base_score=base_stage_b_score,
                confidence_level=str(confidence_result["confidence_level"]),
            )
            adjusted = apply_llm_adjustment(
                base_score=base_stage_b_score,
                adjustment=float(llm_result["adjustment"]),
            )
            llm_result["adjustment"] = float(adjusted["adjustment"])
            final_stage_b_score = float(adjusted["final_score"])

        final_decision = str(confidence_result["decision"])
        if final_decision == "review":
            final_decision = "accept" if final_stage_b_score >= 0.60 else "reject"

        final_status = "accepted" if final_decision == "accept" else "rejected"
        stage_b_reasoning = str(llm_result.get("reasoning", "") or "")
        stage_b_evidence_scores = _stage_b_evidence_template(
            allergy_result=allergy_result,
            condition_result=condition_result,
            age_result=age_result,
            contraindication_result=contraindication_result,
            interaction_result=interaction_result,
            renal_hepatic_result=renal_hepatic_result,
            duplicate_therapy_result=duplicate_therapy_result,
        )

        alt["stage_b_evidence"] = {
            "normalized_patient_profile": normalized_patient,
            "normalized_candidate": dict(candidate_context or {}),
            "scores": stage_b_evidence_scores,
            "allergy": allergy_result,
            "condition": condition_result,
            "age": age_result,
            "contraindication": contraindication_result,
            "interaction": interaction_result,
            "renal_hepatic": renal_hepatic_result,
            "duplicate_therapy": duplicate_therapy_result,
            "soft_risks": {
                "interaction_severity": interaction_result.get("interaction_severity"),
                "age_risk": age_result.get("age_risk"),
                "condition_match": condition_result.get("condition_match"),
                "renal_hepatic_score": renal_hepatic_result.get("score"),
                "duplicate_therapy_score": duplicate_therapy_result.get("score"),
            },
            "evidence_quality": evidence_quality,
            "risk_aggregation": score_result,
            "confidence": confidence_result,
            "llm_review": llm_result,
        }
        alt["patient_safety_score"] = float(final_stage_b_score)
        alt["stage_b_score"] = float(final_stage_b_score)
        alt["stage_b_base_score"] = float(base_stage_b_score)
        alt["stage_b_decision"] = final_status
        alt["stage_b_llm_required"] = bool(confidence_result["llm_required"])
        alt["stage_b_reasoning"] = stage_b_reasoning

        stage_b_alternatives.append(
            {
                "prod_id": int(alt.get("prod_id", prod_id)),
                "prod_name": str(alt.get("prod_name", "") or ""),
                "evidence": stage_b_evidence_scores,
                "score": float(final_stage_b_score),
                "status": final_status,
                "llm_required": bool(confidence_result["llm_required"]),
                "reasoning": stage_b_reasoning,
            }
        )
        enriched_alternatives.append(alt)

    return {
        "stage": "B",
        "implemented_sprints": ["B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "B9", "B10"],
        "patient": patient.to_dict(),
        "normalized_patient_profile": normalized_patient,
        "request_context": {
            "member": member_id,
            "diagnosis": stage_b_input.get("diagnosis"),
            "original_drug": stage_b_input.get("original_drug"),
            "candidate_drug": stage_b_input.get("candidate_drug"),
        },
        "original": dict(stage_a_output.get("original", {})),
        "alternatives": stage_b_alternatives,
        "alternative_count": len(stage_b_alternatives),
        "from_stage_a": {
            "original": dict(stage_a_output.get("original", {})),
            "alternatives": enriched_alternatives,
            "alternative_count": len(enriched_alternatives),
        },
    }


def run_stage_b_sprint1_2(
    stage_b_input: dict[str, object],
    *,
    stage_a_output: dict[str, Any],
    ambiguity_resolver: StageBAmbiguityResolver | None = None,
) -> dict[str, object]:
    """Compatibility wrapper retained for existing tests/callers."""
    output = run_stage_b_sprint1_8(
        stage_b_input,
        stage_a_output=stage_a_output,
        ambiguity_resolver=ambiguity_resolver,
    )
    output["implemented_sprints"] = ["B1", "B2"]
    return output


def run_stage_b_sprint1_5(
    stage_b_input: dict[str, object],
    *,
    stage_a_output: dict[str, Any],
    ambiguity_resolver: StageBAmbiguityResolver | None = None,
) -> dict[str, object]:
    """Compatibility wrapper retained for existing tests/callers."""
    output = run_stage_b_sprint1_8(
        stage_b_input,
        stage_a_output=stage_a_output,
        ambiguity_resolver=ambiguity_resolver,
    )
    output["implemented_sprints"] = ["B1", "B2", "B3", "B4", "B5"]
    return output


def run_stage_a_to_b_sprint1_8(
    *,
    stage_a_input: dict[str, object] | int | str,
    stage_b_input: dict[str, object],
    ambiguity_resolver: StageBAmbiguityResolver | None = None,
) -> dict[str, object]:
    """Run Stage A then hand off alternatives into Stage B Sprint B1-B8."""
    stage_a_output = run_stage_a_pipeline(stage_a_input, ambiguity_resolver=ambiguity_resolver)
    stage_b_output = run_stage_b_sprint1_8(
        stage_b_input,
        stage_a_output=stage_a_output,
        ambiguity_resolver=ambiguity_resolver,
    )
    return {
        "stage_a": stage_a_output,
        "stage_b": stage_b_output,
    }


def run_stage_a_to_b_sprint1_5(
    *,
    stage_a_input: dict[str, object] | int | str,
    stage_b_input: dict[str, object],
    ambiguity_resolver=None,
) -> dict[str, object]:
    """Compatibility wrapper retained for existing tests/callers."""
    output = run_stage_a_to_b_sprint1_8(
        stage_a_input=stage_a_input,
        stage_b_input=stage_b_input,
        ambiguity_resolver=ambiguity_resolver,
    )
    output["stage_b"]["implemented_sprints"] = ["B1", "B2", "B3", "B4", "B5"]
    return output


def run_stage_a_to_b_sprint1_2(
    *,
    stage_a_input: dict[str, object] | int | str,
    stage_b_input: dict[str, object],
    ambiguity_resolver=None,
) -> dict[str, object]:
    """Compatibility wrapper retained for existing tests/callers."""
    output = run_stage_a_to_b_sprint1_8(
        stage_a_input=stage_a_input,
        stage_b_input=stage_b_input,
        ambiguity_resolver=ambiguity_resolver,
    )
    output["stage_b"]["implemented_sprints"] = ["B1", "B2"]
    return output
