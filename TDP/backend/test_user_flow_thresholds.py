"""
test_user_flow_thresholds.py

Validates the exact flow described by the user:

1) Clinical agent generates alternatives and enforces its own thresholding
   before orchestrator routing (and returns at most TOP_K candidates).
2) If policy/clinical/financial are all below threshold -> reject directly.
3) If policy/clinical/financial are above threshold:
   - combined score >= overall threshold -> auto approve
   - combined score < overall threshold -> provider review
4) If policy/clinical/financial are above, but past is a real low score,
   escalate to provider review (past-only failure path).

Past Decisions is intentionally stubbed in all orchestrator-flow cases.

Run: python test_user_flow_thresholds.py
"""

import asyncio
import sys

sys.path.insert(0, ".")

from app.agents import orchestrator
from app.agents.clinical_agent import clinical_agent as real_clinical_agent


PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
results = []


def check(desc, cond):
    ok = bool(cond)
    print(f"  [{'ok' if ok else 'FAIL'}] {desc}")
    results.append((desc, ok))
    return ok


def fixed_weight_llm(system_prompt, user_prompt):
    # Keep weights deterministic so these tests validate routing logic,
    # not dynamic-weight variance.
    return {
        "weights": {"policy": 0.30, "clinical": 0.30, "financial": 0.20, "past": 0.20},
        "rationale": "Deterministic test weights for flow validation.",
    }


def make_clinical_stub(candidates):
    async def _stub(payload):
        return {"candidates": candidates}

    return _stub


def make_policy_stub(score_by_drug):
    async def _stub(candidate_payload):
        drug_id = candidate_payload["drug_id"]
        score = float(score_by_drug[drug_id])
        return {
            "drug_id": drug_id,
            "covered": score >= 0.70,
            "tier": "2",
            "pa_required": False,
            "pa_met": True,
            "step_therapy_required": False,
            "step_therapy_met": True,
            "quantity_ok": True,
            "violations": [],
            "score": score,
            "notes": "stub policy",
            "summary": {
                "decision": "pass" if score >= 0.70 else "deny",
                "reason": "stub policy",
                "score": score,
            },
        }

    return _stub


def make_financial_stub(score_by_drug):
    async def _stub(candidate_payload):
        drug_id = candidate_payload["drug_id"]
        score = float(score_by_drug[drug_id])
        return {
            "drug_id": drug_id,
            "covered": score >= 0.60,
            "tier": "2",
            "final_cost": 20.0,
            "estimated_patient_pay": 10.0,
            "pricing_source": "stub",
            "original_drug_id": candidate_payload.get("original_drug_id"),
            "original_final_cost": 30.0,
            "original_patient_pay": 15.0,
            "estimated_savings": 5.0,
            "savings_pct": 0.33,
            "insurance_context": {"phase": "INITIAL_COVERAGE"},
            "financial_phase_decision_hint": None,
            "score": score,
            "notes": "stub financial",
            "summary": {
                "decision": "cheaper" if score >= 0.60 else "more_expensive",
                "reason": "stub financial",
                "score": score,
                "estimated_savings": 5.0,
                "candidate_patient_pay": 10.0,
                "original_patient_pay": 15.0,
            },
        }

    return _stub


def make_past_stub(score_by_drug, has_signal_by_drug):
    async def _stub(candidate_payload):
        drug_id = candidate_payload["drug_id"]
        has_signal = bool(has_signal_by_drug.get(drug_id, False))
        score = float(score_by_drug.get(drug_id, 0.0))
        if not has_signal:
            return {"match": None, "score": 0.0, "has_signal": False}
        return {"match": {"similar_case": True}, "score": score, "has_signal": True}

    return _stub


BASE = {
    "drug_id": "1018",
    "member_id": "2001",
    "plan_id": "3010",
    "quantity": 30,
    "fill_date": "2025-06-01",
}


async def run_orchestrator_case(name, clinical_candidates, policy_scores, financial_scores,
                                past_scores, past_signals, assertions, trace_id):
    print("=" * 78)
    print(name)
    print("=" * 78)
    orchestrator.clinical_agent = make_clinical_stub(clinical_candidates)
    orchestrator.policy_agent = make_policy_stub(policy_scores)
    orchestrator.financial_agent = make_financial_stub(financial_scores)
    orchestrator.past_decisions_agent = make_past_stub(past_scores, past_signals)

    result = await orchestrator.run_claim(dict(BASE, trace_id=trace_id), llm_fn=fixed_weight_llm)
    ok = True
    for desc, fn in assertions:
        passed = fn(result)
        print(f"  [{'ok' if passed else 'FAIL'}] {desc}")
        ok = ok and passed
    print(f"  ==> {PASS if ok else FAIL}\n")
    return ok


async def main():
    print("=" * 78)
    print("FLOW TEST 1: Clinical pre-filter behavior (real clinical agent)")
    print("=" * 78)
    real_clinical = await real_clinical_agent({
        "drug_id": "1011",
        "member_id": "2001",
        "plan_id": "3010",
        "quantity": 30,
        "fill_date": "2025-06-01",
        "diagnosis": "K21.9",
    })

    candidates = real_clinical.get("candidates", [])
    check("clinical returns at most TOP_K (=3) alternatives", len(candidates) <= 3)
    check("each returned clinical alternative is above clinical threshold",
          all(float(c.get("clinical_score", 0.0)) >= 0.65 for c in candidates))
    print()

    ok2 = await run_orchestrator_case(
        name="FLOW TEST 2: policy+clinical+financial all below -> direct reject",
        clinical_candidates=[{"drug_id": "1033", "clinical_score": 0.40, "safe": True}],
        policy_scores={"1033": 0.30},
        financial_scores={"1033": 0.20},
        past_scores={"1033": 0.10},
        past_signals={"1033": True},
        assertions=[
            ("escalation_type is all_dropped", lambda r: r.get("escalation_type") == "all_dropped"),
            ("kept original drug", lambda r: r.get("kept_original_drug") is True),
        ],
        trace_id="USER-FLOW-2",
    )

    ok3 = await run_orchestrator_case(
        name="FLOW TEST 3: all above + overall above -> auto approve",
        clinical_candidates=[{"drug_id": "1033", "clinical_score": 0.90, "safe": True}],
        policy_scores={"1033": 0.95},
        financial_scores={"1033": 0.90},
        past_scores={"1033": 0.0},
        past_signals={"1033": False},
        assertions=[
            ("not escalated", lambda r: r.get("escalated") is False),
            ("chosen drug is 1033", lambda r: r.get("chosen_drug") == "1033"),
            ("confidence score clears overall threshold", lambda r: float(r.get("confidence_score", 0.0)) >= 0.80),
        ],
        trace_id="USER-FLOW-3",
    )

    ok4 = await run_orchestrator_case(
        name="FLOW TEST 4: all above + overall below -> provider review",
        clinical_candidates=[{"drug_id": "1033", "clinical_score": 0.66, "safe": True}],
        policy_scores={"1033": 0.72},
        financial_scores={"1033": 0.61},
        past_scores={"1033": 0.0},
        past_signals={"1033": False},
        assertions=[
            ("escalated", lambda r: r.get("escalated") is True),
            ("single provider-review path", lambda r: r.get("escalation_type") == "single_drug_approval"),
            ("recommended drug is 1033", lambda r: r.get("recommended_drug") == "1033"),
        ],
        trace_id="USER-FLOW-4",
    )

    ok5 = await run_orchestrator_case(
        name="FLOW TEST 5: policy/clinical/financial above + past below -> provider review",
        clinical_candidates=[{"drug_id": "1033", "clinical_score": 0.90, "safe": True}],
        policy_scores={"1033": 0.95},
        financial_scores={"1033": 0.90},
        past_scores={"1033": 0.20},
        past_signals={"1033": True},
        assertions=[
            ("escalated", lambda r: r.get("escalated") is True),
            ("single provider-review path", lambda r: r.get("escalation_type") == "single_drug_approval"),
            ("score basis excludes low-confidence past", lambda r: r.get("score_basis") == "excludes_past_low_confidence"),
        ],
        trace_id="USER-FLOW-5",
    )

    all_ok = all(ok for _, ok in results) and ok2 and ok3 and ok4 and ok5

    print("=" * 78)
    print("SUMMARY")
    print("=" * 78)
    for desc, ok in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {desc}")
    print(f"  [{'PASS' if ok2 else 'FAIL'}] FLOW TEST 2")
    print(f"  [{'PASS' if ok3 else 'FAIL'}] FLOW TEST 3")
    print(f"  [{'PASS' if ok4 else 'FAIL'}] FLOW TEST 4")
    print(f"  [{'PASS' if ok5 else 'FAIL'}] FLOW TEST 5")
    print()
    print("ALL CHECKS PASSED" if all_ok else "SOME CHECKS FAILED")
    if not all_ok:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
