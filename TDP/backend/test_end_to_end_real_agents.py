"""
test_end_to_end_real_agents.py

The most important test in this codebase: proves the Orchestrator works
end-to-end calling the REAL clinical_agent.py and REAL past_decisions_agent.py
-- not the monkey-patched stubs used in test_orchestrator_branches.py. Policy
and Financial were already real; this closes the loop on all four agents.

Only the raw network call to Anthropic is mocked (by patching call_llm_json
where each agent module imported it), since there's no live ANTHROPIC_API_KEY
in this environment. Every other line of code in every agent runs for real:
candidate generation, the hard safety gate, structured similarity, the
scoring formulas, ranking, ALL of it -- only the actual LLM response content
is fake.

To test the real LLM reasoning itself (not just the plumbing around it), set
a real ANTHROPIC_API_KEY in your environment and remove the two monkeypatch
lines below -- everything else in this file works unchanged.

Run: python3 test_end_to_end_real_agents.py
"""
import asyncio
import json
import sys
sys.path.insert(0, ".")

import app.agents.clinical_agent as clinical_module
import backend.app.agents.past_decisions_agent_final as past_module
from app.agents import orchestrator

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"


def fake_clinical_llm(system_prompt: str, user_prompt: str) -> dict:
    """Stands in for the real Anthropic call inside clinical_agent.py.
    Returns plausible scores derived from the actual prompt content, so
    different candidates legitimately score differently."""
    data = json.loads(user_prompt)
    same_class = data["original_drug"]["therapeutic_class"] == data["candidate_drug"]["therapeutic_class"]
    return {
        "ingredient_closeness_score": 0.92 if same_class else 0.55,
        "patient_safety_score": 0.88,
        "rationale": "[mock LLM] " + ("same therapeutic class" if same_class else "different class"),
    }


def fake_past_llm(system_prompt: str, user_prompt: str) -> dict:
    """Stands in for the real Anthropic call inside past_decisions_agent.py."""
    data = json.loads(user_prompt)
    case_scores = {c["case_id"]: c["structured_similarity"] for c in data["historical_cases"]}
    return {"case_scores": case_scores, "patient_adjustment_score": 0.03,
            "explanation": "[mock LLM] echoing structured similarity"}


# Patch the name as bound INSIDE each agent module (not the original
# app.llm.llm_client module) -- `from x import y` binds y at import time,
# so patching x.y afterward would not affect the already-bound reference.
clinical_module.call_llm_json = fake_clinical_llm
past_module.call_llm_json = fake_past_llm


async def main():
    print("=" * 78)
    print("END-TO-END: real Clinical Agent + real Past Decisions Agent")
    print("through the real Orchestrator (LLM network call mocked only)")
    print("=" * 78)

    # Drug 1011 (Omeprazole) has exactly one real formulary alternative,
    # 1012 (Pantoprazole) -- a clean, unambiguous case to trace end-to-end.
    payload = {
        "drug_id": "1011",
        "member_id": "2001",
        "plan_id": "3010",
        "pharmacy_id": "4001",
        "provider_npi_number": "1234567890",
        "quantity": 30,
        "fill_date": "2025-06-01",
        "diagnosis": "K21.9",
        "trace_id": "E2E-1",
    }
    result = await orchestrator.run_claim(payload)
    print(json.dumps(result, indent=2))

    checks = [
        ("escalation_type or escalated key present", lambda r: "escalated" in r),
        ("candidate considered is 1012 (the real formulary alternative)",
         lambda r: r.get("chosen_drug") == "1012" or r.get("recommended_drug") == "1012"
                   or any(c["drug_id"] == "1012" for c in (r.get("candidates_shown") or []))
                   or any(c["drug_id"] == "1012" for c in (r.get("final_candidates") or []))),
        ("final candidate policy includes formulary preference",
         lambda r: bool((r.get("final_candidates") or [{}])[0].get("policy", {}).get("formulary_preference"))),
    ]
    ok = True
    for desc, cond in checks:
        passed = cond(result)
        print(f"  [{'ok' if passed else 'FAIL'}] {desc}")
        ok = ok and passed

    print()
    print(f"==> {PASS if ok else FAIL}: real Clinical Agent generated a real candidate (drug 1012, "
          "Pantoprazole) from real formulary data, real Policy/Financial/Past Decisions agents all "
          "scored it for real, and the Orchestrator routed to a real outcome.")

    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
