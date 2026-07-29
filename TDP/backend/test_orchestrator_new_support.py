from __future__ import annotations

import json
from typing import Any

from app.main import _run_orchestrator_new


DEFAULT_PAYLOAD: dict[str, Any] = {
    "drug_id": "1018",
    "member_id": "2001",
    "plan_id": "3010",
    "pharmacy_id": "4001",
    "quantity": 30,
    "fill_date": "2025-06-01",
    "diagnosis": "I10",
}


def make_candidate(
    candidate_id: str,
    candidate_name: str,
    *,
    rank: int = 1,
    clinical_score: float = 0.95,
    threshold_passed: bool = True,
    safe: bool = True,
    overall_status: str = "PASS",
    safety_flags: dict[str, bool] | None = None,
) -> dict[str, Any]:
    flags = {
        "polypharmacy": False,
        "missing_clinical_data": False,
        "clinical_ambiguity": False,
        "cumulative_risk": False,
    }
    if safety_flags:
        flags.update(safety_flags)

    return {
        "rank": rank,
        "candidate_id": str(candidate_id),
        "candidate_name": candidate_name,
        "overall_status": overall_status,
        "safe": safe,
        "stage_a": {
            "score": clinical_score,
            "status": "accepted" if overall_status.upper() != "REJECT" else "rejected",
        },
        "stage_b": {
            "score": clinical_score,
            "status": "accept" if overall_status.upper() != "REJECT" else "reject",
        },
        "stage_c": {
            "composite_score": clinical_score,
            "threshold_passed": threshold_passed,
            "safety_flags": flags,
        },
    }


def build_runtime_options(
    original_drug_id: str,
    candidates: list[dict[str, Any]],
    *,
    policy_scores: dict[str, float],
    financial_scores: dict[str, float],
    past_scores: dict[str, float],
    policy_states: dict[str, str] | None = None,
    past_signals: dict[str, bool] | None = None,
    governance_overrides: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    policy_states = policy_states or {}
    past_signals = past_signals or {}
    governance_overrides = governance_overrides or {}

    policy_payloads: dict[str, dict[str, Any]] = {}
    financial_payloads: dict[str, dict[str, Any]] = {}
    past_payloads: dict[str, dict[str, Any]] = {}

    for candidate in candidates:
        candidate_id = str(candidate["candidate_id"])
        candidate_name = str(candidate["candidate_name"])
        policy_score = float(policy_scores.get(candidate_id, 0.0))
        financial_score = float(financial_scores.get(candidate_id, 0.0))
        past_score = float(past_scores.get(candidate_id, 0.0))
        policy_state = str(policy_states.get(candidate_id, "pass"))
        has_signal = bool(past_signals.get(candidate_id, candidate_id in past_scores))

        policy_payloads[candidate_id] = {
            "drug_id": candidate_id,
            "policy_state": policy_state,
            "score": policy_score,
            "summary": {"decision": policy_state, "score": policy_score},
            "notes": f"policy {policy_state} for {candidate_name}",
            "result": {
                "drug_id": candidate_id,
                "policy_state": policy_state,
                "score": policy_score,
                "summary": {"decision": policy_state, "score": policy_score},
                "notes": f"policy {policy_state} for {candidate_name}",
            },
        }

        financial_payloads[candidate_id] = {
            "drug_id": candidate_id,
            "score": financial_score,
            "final_cost": round(10.0 + (1.0 - financial_score) * 5.0, 2),
            "estimated_patient_pay": round(5.0 + (1.0 - financial_score) * 2.0, 2),
            "original_drug_id": str(original_drug_id),
            "original_final_cost": 20.0,
            "original_patient_pay": 10.0,
            "estimated_savings": round(max(0.0, financial_score * 10.0), 2),
            "savings_pct": round(financial_score * 100, 2),
            "summary": {
                "decision": "cheaper" if financial_score >= 0.60 else "more_expensive",
                "score": financial_score,
                "estimated_savings": round(max(0.0, financial_score * 10.0), 2),
                "candidate_patient_pay": round(5.0 + (1.0 - financial_score) * 2.0, 2),
                "original_patient_pay": 10.0,
            },
            "result": {
                "drug_id": candidate_id,
                "score": financial_score,
                "final_cost": round(10.0 + (1.0 - financial_score) * 5.0, 2),
                "estimated_patient_pay": round(5.0 + (1.0 - financial_score) * 2.0, 2),
                "original_drug_id": str(original_drug_id),
                "original_final_cost": 20.0,
                "original_patient_pay": 10.0,
                "estimated_savings": round(max(0.0, financial_score * 10.0), 2),
                "savings_pct": round(financial_score * 100, 2),
                "summary": {
                    "decision": "cheaper" if financial_score >= 0.60 else "more_expensive",
                    "score": financial_score,
                    "estimated_savings": round(max(0.0, financial_score * 10.0), 2),
                    "candidate_patient_pay": round(5.0 + (1.0 - financial_score) * 2.0, 2),
                    "original_patient_pay": 10.0,
                },
            },
        }

        past_payloads[candidate_id] = {
            "final_score": past_score,
            "score": past_score,
            "average_confidence_score": past_score,
            "has_signal": has_signal,
            "notes": f"past decisions for {candidate_name}",
            "result": {
                "final_score": past_score,
                "score": past_score,
                "average_confidence_score": past_score,
                "has_signal": has_signal,
                "notes": f"past decisions for {candidate_name}",
            },
        }

    return {
        "clinical_output_inline": {
            "original_drug": {
                "prod_id": int(original_drug_id) if str(original_drug_id).isdigit() else original_drug_id,
                "prod_name": f"Drug_{original_drug_id}",
            },
            "ranked_alternatives": json.loads(json.dumps(candidates)),
        },
        "policy_inline_response_payloads": policy_payloads,
        "financial_inline_response_payloads": financial_payloads,
        "past_decision_inline_response_payloads": past_payloads,
        "layer_7_mock_response_by_alternative_id": governance_overrides,
    }


def run_case(
    payload: dict[str, Any] | None,
    runtime_options: dict[str, Any],
    *,
    case: str = "auto_accept",
) -> dict[str, Any]:
    claim_payload = payload or dict(DEFAULT_PAYLOAD)
    return _run_orchestrator_new(claim_payload, case=case, runtime_options=runtime_options)