"""
Comprehensive orchestrator test suite -- covers every routing outcome.

IMPORTANT: the original prescribed drug is now a REAL, priced drug (1018,
$14.85 patient pay under plan 3010) rather than a fake placeholder ID. This
matters because Financial Agent now compares every candidate's cost against
this original -- a fake ID would always trigger the "original unpriced"
fallback path and never actually exercise the real savings/cost-increase
comparison logic. All financial scores below are REAL, computed by the
agent itself, not assumed constants -- run it yourself to verify.

Policy and Financial run for real against the actual dataset. Clinical and
Past Decisions are monkey-patched per test case, with a DIFFERENT Past
Decisions score deliberately chosen in each case so every branch of the
threshold logic gets exercised.

Run: python3 test_orchestrator_branches.py
"""
import asyncio
import json
import sys
sys.path.insert(0, ".")

from app.agents import orchestrator

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"

# Real original drug for every case: 1018 under plan 3010, $14.85 patient pay.
# Real candidate financial scores against this original (verified by running
# financial_agent.py directly before writing these cases):
#   1033 (cheaper, $10.30)   -> financial score 0.806  (saves ~31%)
#   1011 (cheaper, $11.30)   -> financial score 0.739  (saves ~24%)
#   1008 (pricier, $85.29)   -> financial score 0.05   (floor -- costs far more)
#   1001 (not covered)       -> financial score 0.10   (comparison moot)
ORIGINAL_DRUG = "1018"


def make_clinical_stub(candidates):
    async def _stub(payload):
        return {"candidates": candidates}
    return _stub


def make_past_stub(score_by_drug):
    """score_by_drug: {drug_id: float|None}. None = no comparable case at all
    (has_signal=False, excluded from gating). A float = a real LLM-produced
    similarity score that must clear the 0.50 threshold like any other."""
    async def _stub(candidate):
        drug_id = candidate["drug_id"]
        score = score_by_drug.get(drug_id)
        if score is None:
            return {"match": None, "score": 0.0, "has_signal": False}
        return {"match": {"similar_case": True}, "score": score, "has_signal": True}
    return _stub


BASE = {
    "drug_id": ORIGINAL_DRUG,
    "member_id": "2001",
    "plan_id": "3010",
    "pharmacy_id": "4001",
    "quantity": 30,
    "fill_date": "2025-06-01",
}

results = []


async def run_case(name, clinical_candidates, past_scores, checks, trace_id):
    print("=" * 78)
    print(name)
    print("=" * 78)
    orchestrator.clinical_agent = make_clinical_stub(clinical_candidates)
    orchestrator.past_decisions_agent = make_past_stub(past_scores)
    r = await orchestrator.run_claim(dict(BASE, trace_id=trace_id))
    print(json.dumps(r, indent=2))
    ok = True
    for desc, cond in checks:
        passed = cond(r)
        print(f"  [{'ok' if passed else 'FAIL'}] {desc}")
        ok = ok and passed
    print(f"  ==> {PASS if ok else FAIL}\n")
    results.append((name, ok))


async def main():
    # ---- Case 1: pending candidate enters doctor review pool ---------------
    # 1001: no formulary rule (policy deny path, dropped).
    # 1008: PA required & unmet (policy pending path) and far pricier than
    #       the original. Pending is now reviewable instead of dropped.
    await run_case(
        "CASE 1: single_drug_approval (policy pending candidate routed to review)",
        clinical_candidates=[
            {"drug_id": "1001", "clinical_score": 0.90, "safe": True},
            {"drug_id": "1008", "clinical_score": 0.85, "safe": True},
        ],
        past_scores={},
        checks=[
            ("escalation_type == single_drug_approval", lambda r: r["escalation_type"] == "single_drug_approval"),
            ("recommended_drug == 1008", lambda r: r.get("recommended_drug") == "1008"),
            ("score_basis is policy pending", lambda r: str(r.get("score_basis", "")).startswith("policy_pending_")),
        ],
        trace_id="CASE-1",
    )

    # ---- Case 2: orchestrated_decision -- clean auto-approve ---------------
    # 1033: policy 0.95, financial 0.806 (real ~31% saving vs the original),
    # clinical and past both set strong -> combined easily clears 0.80.
    await run_case(
        "CASE 2: orchestrated_decision (full survivor clears overall bar)",
        clinical_candidates=[{"drug_id": "1033", "clinical_score": 0.95, "safe": True}],
        past_scores={"1033": 0.90},
        checks=[
            ("escalated is False", lambda r: r["escalated"] is False),
            ("chosen_drug == 1033", lambda r: r["chosen_drug"] == "1033"),
            ("real savings reflected in financial_detail",
             lambda r: r["financial_detail"]["estimated_savings"] > 0),
        ],
        trace_id="CASE-2",
    )

    # ---- Case 3: single review, source = full survivor below bar ----------
    # 1011: policy 0.95, financial 0.739 (real ~24% saving). Clinical and
    # past both set just above their own bars, but not high enough to push
    # the combined score over 0.80.
    await run_case(
        "CASE 3: single_drug_approval (ONE full survivor, but combined score below overall bar)",
        clinical_candidates=[{"drug_id": "1011", "clinical_score": 0.66, "safe": True}],
        past_scores={"1011": 0.55},
        checks=[
            ("escalation_type == single_drug_approval", lambda r: r["escalation_type"] == "single_drug_approval"),
            ("score_basis == all_signals_considered", lambda r: r["score_basis"] == "all_signals_considered"),
            ("recommended_drug == 1011", lambda r: r["recommended_drug"] == "1011"),
        ],
        trace_id="CASE-3",
    )

    # ---- Case 4: single review, source = past-only failure ----------------
    # 1033 again: policy 0.95, financial 0.806, clinical strong -- everything
    # clears except Past Decisions, which has a real but low score.
    await run_case(
        "CASE 4: single_drug_approval (ONE candidate, fails ONLY Past Decisions)",
        clinical_candidates=[{"drug_id": "1033", "clinical_score": 0.90, "safe": True}],
        past_scores={"1033": 0.20},
        checks=[
            ("escalation_type == single_drug_approval", lambda r: r["escalation_type"] == "single_drug_approval"),
            ("score_basis == excludes_past_low_confidence", lambda r: r["score_basis"] == "excludes_past_low_confidence"),
            ("recommended_drug == 1033", lambda r: r["recommended_drug"] == "1033"),
            ("doctor_question present", lambda r: "doctor_question" in r),
        ],
        trace_id="CASE-4",
    )

    # ---- Case 5: multiple review, ALL full survivors below bar ------------
    await run_case(
        "CASE 5: multiple_candidate_options (two full survivors, both below overall bar)",
        clinical_candidates=[
            {"drug_id": "1033", "clinical_score": 0.66, "safe": True},
            {"drug_id": "1011", "clinical_score": 0.66, "safe": True},
        ],
        past_scores={"1033": 0.55, "1011": 0.60},
        checks=[
            ("escalation_type == multiple_candidate_options", lambda r: r["escalation_type"] == "multiple_candidate_options"),
            ("2 candidates shown", lambda r: len(r["candidates_shown"]) == 2),
            ("both basis == all_signals_considered",
             lambda r: all(c["score_basis"] == "all_signals_considered" for c in r["candidates_shown"])),
        ],
        trace_id="CASE-5",
    )

    # ---- Case 6: multiple review, ALL past-only failures -------------------
    await run_case(
        "CASE 6: multiple_candidate_options (two candidates, BOTH fail only Past Decisions)",
        clinical_candidates=[
            {"drug_id": "1033", "clinical_score": 0.90, "safe": True},
            {"drug_id": "1011", "clinical_score": 0.88, "safe": True},
        ],
        past_scores={"1033": 0.20, "1011": 0.15},
        checks=[
            ("escalation_type == multiple_candidate_options", lambda r: r["escalation_type"] == "multiple_candidate_options"),
            ("2 candidates shown", lambda r: len(r["candidates_shown"]) == 2),
            ("both basis == excludes_past_low_confidence",
             lambda r: all(c["score_basis"] == "excludes_past_low_confidence" for c in r["candidates_shown"])),
        ],
        trace_id="CASE-6",
    )

    # ---- Case 7: THE KEY EDGE CASE -- mixed pool ---------------------------
    # 1011 = full survivor, below bar (same as Case 3).
    # 1033 = past-only failure (same as Case 4).
    # Both must appear together, proving the past-only candidate is NOT
    # dropped just because a full survivor exists.
    await run_case(
        "CASE 7 (key edge case): mixed pool -- one full-survivor-below-bar "
        "+ one past-only-failure, shown TOGETHER",
        clinical_candidates=[
            {"drug_id": "1011", "clinical_score": 0.66, "safe": True},
            {"drug_id": "1033", "clinical_score": 0.90, "safe": True},
        ],
        past_scores={"1011": 0.55, "1033": 0.10},
        checks=[
            ("escalation_type == multiple_candidate_options", lambda r: r["escalation_type"] == "multiple_candidate_options"),
            ("2 candidates shown", lambda r: len(r["candidates_shown"]) == 2),
            ("1011 present with basis all_signals_considered",
             lambda r: any(c["drug_id"] == "1011" and c["score_basis"] == "all_signals_considered"
                           for c in r["candidates_shown"])),
            ("1033 present with basis excludes_past_low_confidence",
             lambda r: any(c["drug_id"] == "1033" and c["score_basis"] == "excludes_past_low_confidence"
                           for c in r["candidates_shown"])),
        ],
        trace_id="CASE-7",
    )

    # ---- Case 8: mandatory clinical escalation (NTI / controlled substance) -
    # 1021 = warfarin, narrow-therapeutic-index flagged by the real Clinical
    # Agent. Even with every score clearing its bar, this must land in the
    # review pool, never auto-approve.
    await run_case(
        "CASE 8: requires_mandatory_clinical_escalation (NTI-flagged candidate, "
        "all scores pass, must still review)",
        clinical_candidates=[
            {"drug_id": "1021", "clinical_score": 0.95, "safe": True,
             "requires_mandatory_escalation": True, "escalation_flags": ["narrow_therapeutic_index"]},
        ],
        past_scores={"1021": 0.90},
        checks=[
            ("escalation_type == single_drug_approval", lambda r: r["escalation_type"] == "single_drug_approval"),
            ("score_basis == requires_mandatory_clinical_escalation",
             lambda r: r["score_basis"] == "requires_mandatory_clinical_escalation"),
            ("recommended_drug == 1021", lambda r: r["recommended_drug"] == "1021"),
        ],
        trace_id="CASE-8",
    )

    print("=" * 78)
    print("SUMMARY")
    print("=" * 78)
    for name, ok in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    all_ok = all(ok for _, ok in results)
    print()
    print("ALL CASES PASSED" if all_ok else "SOME CASES FAILED")
    if not all_ok:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
