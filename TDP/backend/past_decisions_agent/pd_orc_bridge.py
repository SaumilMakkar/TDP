from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Union, Optional

from dotenv import load_dotenv


# ============================================================
# Environment + project import setup
# ============================================================

load_dotenv(override=True)

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


try:
    # Preferred project import
    from app.agents.app.past_decisions_agent_final import (
        DatasetPaths,
        AgentConfig,
        PastDecisionsAgent,
    )
except ImportError:
    # Fallback if this file is placed next to past_decisions_agent.py
    from past_decisions_agent_final import (
        DatasetPaths,
        AgentConfig,
        PastDecisionsAgent,
    )


# ============================================================
# JSON helper
# ============================================================

def safe_json_loads(value: Union[str, Dict[str, Any], List[Any]]) -> Union[Dict[str, Any], List[Any]]:
    """
    Accepts:
    - dict
    - list
    - raw JSON string
    - markdown-wrapped JSON string
    - JSON with accidental trailing commas

    Returns parsed dict/list.
    """

    if isinstance(value, (dict, list)):
        return value

    if not isinstance(value, str):
        raise TypeError(f"Expected dict, list, or JSON string. Got: {type(value)}")

    text = value.strip()

    # Remove markdown fences if present
    text = re.sub(r"^```json\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^```\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    # Remove accidental trailing commas before } or ]
    text = re.sub(r",(\s*[}\]])", r"\1", text)

    return json.loads(text)


# ============================================================
# Clinical Agent output extraction
# ============================================================

def extract_clinical_candidates(
    clinical_agent_output: Union[Dict[str, Any], List[Any], str],
    include_failed_clinical: bool = False,
) -> List[Dict[str, Any]]:
    """
    Extracts one or many alternatives from Clinical Agent output.

    Supports final Clinical Agent output shape:
    {
      "original_drug": {
        "prod_id": 1013,
        "prod_name": "Sertraline 50mg"
      },
      "ranked_alternatives": [...]
    }

    Also supports older wrapper keys:
    - candidates
    - alternatives
    - recommendations
    - results
    - candidate_results
    """

    parsed = safe_json_loads(clinical_agent_output)

    if isinstance(parsed, list):
        raw_candidates = parsed

    elif isinstance(parsed, dict):
        raw_candidates = None

        for key in [
            "ranked_alternatives",
            "candidates",
            "alternatives",
            "recommendations",
            "results",
            "candidate_results",
        ]:
            if key in parsed and isinstance(parsed[key], list):
                raw_candidates = parsed[key]
                break

        if raw_candidates is None:
            raw_candidates = [parsed]

    else:
        raise ValueError("Clinical Agent output must be a dict, list, or JSON string.")

    candidates: List[Dict[str, Any]] = []

    for index, candidate in enumerate(raw_candidates, start=1):
        if not isinstance(candidate, dict):
            continue

        candidate_name = (
            candidate.get("candidate_name")
            or candidate.get("recommended_drug")
            or candidate.get("recommended")
            or candidate.get("drug")
            or candidate.get("name")
        )

        if not candidate_name:
            raise ValueError(
                f"Clinical candidate #{index} is missing candidate_name/recommended_drug/recommended/drug/name."
            )

        overall_status = str(candidate.get("overall_status", "")).upper().strip()

        stage_a = candidate.get("stage_a", {})
        stage_b = candidate.get("stage_b", {})
        stage_c = candidate.get("stage_c", {})
        clinical_assessment = candidate.get("clinical_assessment", {})

        clinical_score = (
            clinical_assessment.get("clinical_score")
            or stage_c.get("composite_score")
        )

        threshold_passed = stage_c.get("threshold_passed")

        if not include_failed_clinical:
            if overall_status and overall_status != "PASS":
                continue

            if threshold_passed is False:
                continue

            recommendation = str(stage_c.get("recommendation", "")).upper().strip()
            if recommendation and recommendation not in {"PASS", "CLINICALLY_ACCEPTABLE"}:
                continue

        candidates.append({
            "candidate_id": candidate.get("candidate_id", index),
            "candidate_name": candidate_name,
            "clinical_rank": candidate.get("rank", index),
            "overall_status": candidate.get("overall_status"),
            "clinical_score": clinical_score,
            "threshold_passed": threshold_passed,
            "clinical_assessment": clinical_assessment,
            "stage_a": stage_a,
            "stage_b": stage_b,
            "stage_c": stage_c,
            "raw_clinical_candidate": candidate,
        })

    return candidates


# ============================================================
# Past Decisions Agent builder
# ============================================================

def build_past_decisions_agent(debug: bool = False) -> PastDecisionsAgent:
    """
    Builds the finalized Past Decisions Agent using the same dataset paths
    as your test runner.
    """

    dataset_paths = DatasetPaths(
        doctor_responses="C:\\Users\\karora71\\Desktop\\test\\data\\doctor_responses_revised_5.csv",
        claims="C:\\Users\\karora71\\Desktop\\test\\data\\F_CLM_TRANSACTION.csv",
        product="C:\\Users\\karora71\\Desktop\\test\\data\\v_d_product.csv",
        prescription="C:\\Users\\karora71\\Desktop\\test\\data\\v_xxiris_om_prescription.csv",
        member="C:\\Users\\karora71\\Desktop\\test\\data\\v_d_member.csv",
        patient_history="C:\\Users\\karora71\\Desktop\\test\\data\\patient_history.csv",
    )

    config = AgentConfig()
    config.debug = debug

    return PastDecisionsAgent(
        dataset_paths=dataset_paths,
        config=config,
    )


# ============================================================
# Current case extraction from orchestrator payload
# ============================================================

def extract_current_case(orchestrator_payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extracts the current case from the Orchestrator payload.

    Supported payload shapes:

    1.
    {
      "current_case": {
        "claim_id": null,
        "drug": "Atorvastatin 20mg",
        "member_key": "2020",
        "diagnosis": "E78.5"
      },
      "clinical_agent_output": {...}
    }

    2.
    {
      "claim_id": null,
      "drug": "Atorvastatin 20mg",
      "member_key": "2020",
      "diagnosis": "E78.5",
      "clinical_agent_output": {...}
    }
    """

    current_case = orchestrator_payload.get("current_case")

    if current_case is None:
        current_case = orchestrator_payload

    original_drug = (
        current_case.get("drug")
        or current_case.get("original_drug")
        or current_case.get("ORIGINAL_DRUG")
    )

    member_key = (
        current_case.get("member_key")
        or current_case.get("mbr_sk")
        or current_case.get("MBR_SK")
    )

    diagnosis = (
        current_case.get("diagnosis")
        or current_case.get("DX_CD")
        or current_case.get("dx_cd")
    )

    claim_id = (
        current_case.get("claim_id")
        or current_case.get("CLAIM_NBR")
        or current_case.get("claim_nbr")
    )

    if not original_drug:
        raise ValueError("Current case is missing original drug: expected drug/original_drug/ORIGINAL_DRUG.")

    if not member_key:
        raise ValueError("Current case is missing member key: expected member_key/mbr_sk/MBR_SK.")

    if not diagnosis:
        raise ValueError("Current case is missing diagnosis: expected diagnosis/DX_CD/dx_cd.")

    return {
        "claim_id": claim_id,
        "drug": original_drug,
        "member_key": str(member_key),
        "diagnosis": diagnosis,
    }


def extract_clinical_output_from_orchestrator_payload(
    orchestrator_payload: Dict[str, Any],
) -> Union[Dict[str, Any], List[Any], str]:
    """
    Extracts Clinical Agent output from the Orchestrator payload.

    Supported keys:
    - clinical_agent_output
    - clinical_output
    - clinical_agent
    - clinical_candidates
    - ranked_alternatives
    - candidates
    - alternatives
    """

    for key in [
        "clinical_agent_output",
        "clinical_output",
        "clinical_agent",
        "clinical_candidates",
        "ranked_alternatives",
        "candidates",
        "alternatives",
    ]:
        if key in orchestrator_payload:
            if key == "ranked_alternatives":
                return orchestrator_payload

            return orchestrator_payload[key]

    raise ValueError(
        "Orchestrator payload is missing Clinical Agent output. "
        "Expected one of: clinical_agent_output, clinical_output, clinical_agent, "
        "clinical_candidates, ranked_alternatives, candidates, alternatives."
    )


# ============================================================
# Run Past Decisions for one candidate
# ============================================================

def run_past_decisions_for_candidate(
    past_agent: PastDecisionsAgent,
    current_case_payload: Dict[str, Any],
    clinical_candidate: Dict[str, Any],
    keep_full_past_output: bool = False,
) -> Dict[str, Any]:
    """
    Runs Past Decisions Agent for one Clinical Agent candidate.

    Returns only the required fields by default:
    - average_confidence_score
    - final_statement
    """

    candidate_name = clinical_candidate["candidate_name"]

    past_result = past_agent.run(
        payload=current_case_payload,
        clinical_output={
            "recommended": candidate_name
        },
    )

    response = {
        "candidate_id": clinical_candidate.get("candidate_id"),
        "candidate_name": candidate_name,
        "past_decisions_agent": {
            "average_confidence_score": past_result.get("average_confidence_score"),
            "final_statement": past_result.get("final_statement"),
        },
    }

    if keep_full_past_output:
        response["_full_past_decisions_output"] = past_result

    return response


# ============================================================
# Main entry point called by Orchestrator
# ============================================================

def run_past_decisions_from_orchestrator(
    orchestrator_payload: Union[Dict[str, Any], str],
    include_failed_clinical: bool = False,
    keep_full_past_output: bool = False,
    debug: bool = False,
) -> Dict[str, Any]:
    """
    Main integration function.

    The Orchestrator should call this function after it has already run
    the Clinical Agent.

    Input:
    {
      "current_case": {
        "claim_id": null,
        "drug": "Atorvastatin 20mg",
        "member_key": "2020",
        "diagnosis": "E78.5"
      },
      "clinical_agent_output": {
        "candidate_id": 1005,
        "candidate_name": "Rosuvastatin 10mg",
        ...
      }
    }

    Output:
    {
      "current_case": {...},
      "candidate_count": 1,
      "past_decisions_results": [
        {
          "candidate_id": 1005,
          "candidate_name": "Rosuvastatin 10mg",
          "past_decisions_agent": {
            "average_confidence_score": 0.85,
            "final_statement": "..."
          }
        }
      ]
    }
    """

    payload = safe_json_loads(orchestrator_payload)

    if not isinstance(payload, dict):
        raise ValueError("Orchestrator payload must be a dict or JSON object string.")

    current_case_payload = extract_current_case(payload)

    clinical_agent_output = extract_clinical_output_from_orchestrator_payload(payload)

    clinical_candidates = extract_clinical_candidates(
        clinical_agent_output=clinical_agent_output,
        include_failed_clinical=include_failed_clinical,
    )

    past_agent = build_past_decisions_agent(debug=debug)

    past_results = []

    for clinical_candidate in clinical_candidates:
        past_result = run_past_decisions_for_candidate(
            past_agent=past_agent,
            current_case_payload=current_case_payload,
            clinical_candidate=clinical_candidate,
            keep_full_past_output=keep_full_past_output,
        )

        past_results.append(past_result)

    return {
        "current_case": current_case_payload,
        "candidate_count": len(past_results),
        "past_decisions_results": past_results,
    }


# ============================================================
# Optional local test
# ============================================================

if __name__ == "__main__":
    """
    This is only for local testing.
    In production, the Orchestrator should call:
        run_past_decisions_from_orchestrator(orchestrator_payload)
    """

    EXAMPLE_ORCHESTRATOR_PAYLOAD = {
    "current_case": {
        "claim_id": None,
        "drug": "Sertraline 50mg",
        "member_key": "2067",   # change if orchestrator sends a different member
        "diagnosis": "F32.9",   # change if orchestrator sends a different diagnosis
    },
    "clinical_agent_output": {
        "original_drug": {
            "prod_id": 1013,
            "prod_name": "Sertraline 50mg"
        },
        "ranked_alternatives": [
            {
                "rank": 1,
                "candidate_id": 1014,
                "candidate_name": "Escitalopram 10mg",
                "overall_status": "PASS",
                "stage_a": {
                    "prod_id": 1014,
                    "prod_name": "Escitalopram 10mg",
                    "evidence": {
                        "ingredient": 0.5,
                        "moiety": 0.5,
                        "class": 1.0,
                        "moa": 1.0,
                        "combo": 0.25,
                        "route": 1.0,
                        "form": 1.0,
                        "strength": 0.25
                    },
                    "score": 0.6298,
                    "status": "accepted",
                    "llm_required": False,
                    "reasoning": None
                },
                "stage_b": {
                    "prod_id": 1014,
                    "prod_name": "Escitalopram 10mg",
                    "evidence": {
                        "allergy": 0.25,
                        "condition": 0.5,
                        "age": 0.0,
                        "contraindication": 0.0,
                        "interaction": 0.0,
                        "renal_hepatic": 0.0,
                        "duplicate_therapy": 1.0
                    },
                    "score": 0.7125,
                    "status": "accept",
                    "llm_required": True,
                    "reasoning": (
                        "Escitalopram may exacerbate heart failure symptoms due to its potential "
                        "to cause hyponatremia, which is a concern in this condition. The condition "
                        "match score reflects weak alignment, but the risk warrants a conservative "
                        "adjustment to prioritize patient safety given the underlying heart failure."
                    )
                },
                "stage_c": {
                    "composite_score": 0.6794,
                    "threshold_passed": True,
                    "safety_flags": {
                        "polypharmacy": False,
                        "missing_clinical_data": False,
                        "clinical_ambiguity": True,
                        "cumulative_risk": True
                    }
                }
            },
            {
                "rank": 2,
                "candidate_id": 1042,
                "candidate_name": "Bupropion 150mg",
                "overall_status": "PASS",
                "stage_a": {
                    "prod_id": 1042,
                    "prod_name": "Bupropion 150mg",
                    "evidence": {
                        "ingredient": 0.5,
                        "moiety": 0.5,
                        "class": 0.0,
                        "moa": 0.5,
                        "combo": 0.25,
                        "route": 1.0,
                        "form": 1.0,
                        "strength": 1.0
                    },
                    "score": 0.4882,
                    "status": "accepted",
                    "llm_required": True,
                    "reasoning": (
                        "The candidate drug, Bupropion 150mg, differs significantly from the original "
                        "drug, Sertraline 50mg, in pharmacologic class and mechanism of action. "
                        "Sertraline is a selective serotonin reuptake inhibitor, while Bupropion is "
                        "a norepinephrine-dopamine reuptake inhibitor."
                    )
                },
                "stage_b": {
                    "prod_id": 1042,
                    "prod_name": "Bupropion 150mg",
                    "evidence": {
                        "allergy": 0.0,
                        "condition": 0.5,
                        "age": 0.0,
                        "contraindication": 0.0,
                        "interaction": 0.0,
                        "renal_hepatic": 0.0,
                        "duplicate_therapy": 1.0
                    },
                    "score": 0.765,
                    "status": "accept",
                    "llm_required": True,
                    "reasoning": (
                        "Bupropion may exacerbate heart failure due to its potential to increase "
                        "blood pressure and heart rate, which is a concern given the patient's condition. "
                        "While no direct contraindication exists, caution is warranted for cardiovascular safety."
                    )
                },
                "stage_c": {
                    "composite_score": 0.6543,
                    "threshold_passed": True,
                    "safety_flags": {
                        "polypharmacy": False,
                        "missing_clinical_data": False,
                        "clinical_ambiguity": True,
                        "cumulative_risk": False
                    }
                }
            },
            {
                "rank": 3,
                "candidate_id": 1015,
                "candidate_name": "Duloxetine 30mg",
                "overall_status": "PASS",
                "stage_a": {
                    "prod_id": 1015,
                    "prod_name": "Duloxetine 30mg",
                    "evidence": {
                        "ingredient": 0.5,
                        "moiety": 0.5,
                        "class": 0.0,
                        "moa": 0.5,
                        "combo": 0.25,
                        "route": 1.0,
                        "form": 0.5,
                        "strength": 1.0
                    },
                    "score": 0.4691,
                    "status": "accepted",
                    "llm_required": True,
                    "reasoning": (
                        "The candidate drug, Duloxetine 30mg, differs significantly from the original "
                        "drug, Sertraline 50mg, in pharmacologic class and mechanism of action. "
                        "While both are antidepressants, Sertraline is an SSRI and Duloxetine is an SNRI."
                    )
                },
                "stage_b": {
                    "prod_id": 1015,
                    "prod_name": "Duloxetine 30mg",
                    "evidence": {
                        "allergy": 0.25,
                        "condition": 0.5,
                        "age": 0.0,
                        "contraindication": 0.0,
                        "interaction": 0.0,
                        "renal_hepatic": 0.0,
                        "duplicate_therapy": 1.0
                    },
                    "score": 0.7125,
                    "status": "accept",
                    "llm_required": True,
                    "reasoning": (
                        "Duloxetine may exacerbate heart failure due to its potential to increase "
                        "blood pressure and heart rate, aligning with the condition match risk. "
                        "While no direct contraindication exists, caution is warranted."
                    )
                },
                "stage_c": {
                    "composite_score": 0.6151,
                    "threshold_passed": True,
                    "safety_flags": {
                        "polypharmacy": False,
                        "missing_clinical_data": False,
                        "clinical_ambiguity": True,
                        "cumulative_risk": True
                    }
                }
            },
            {
                "rank": 4,
                "candidate_id": 1041,
                "candidate_name": "Venlafaxine 75mg",
                "overall_status": "PASS",
                "stage_a": {
                    "prod_id": 1041,
                    "prod_name": "Venlafaxine 75mg",
                    "evidence": {
                        "ingredient": 0.5,
                        "moiety": 0.5,
                        "class": 0.0,
                        "moa": 0.5,
                        "combo": 0.25,
                        "route": 1.0,
                        "form": 0.5,
                        "strength": 0.75
                    },
                    "score": 0.463,
                    "status": "accepted",
                    "llm_required": True,
                    "reasoning": (
                        "Sertraline and Venlafaxine differ significantly in class and mechanism of action. "
                        "While they share similarities in route, form, and strength, the divergence in class "
                        "and mechanism suggests they are not interchangeable for all patients."
                    )
                },
                "stage_b": {
                    "prod_id": 1041,
                    "prod_name": "Venlafaxine 75mg",
                    "evidence": {
                        "allergy": 0.25,
                        "condition": 0.5,
                        "age": 0.0,
                        "contraindication": 0.0,
                        "interaction": 0.0,
                        "renal_hepatic": 0.0,
                        "duplicate_therapy": 1.0
                    },
                    "score": 0.7125,
                    "status": "accept",
                    "llm_required": True,
                    "reasoning": (
                        "Venlafaxine may exacerbate heart failure due to its potential to increase "
                        "blood pressure and heart rate. The moderate condition alignment warrants caution "
                        "for this patient with heart failure."
                    )
                },
                "stage_c": {
                    "composite_score": 0.6127,
                    "threshold_passed": True,
                    "safety_flags": {
                        "polypharmacy": False,
                        "missing_clinical_data": False,
                        "clinical_ambiguity": True,
                        "cumulative_risk": True
                    }
                }
            }
        ]
    }
}

    result = run_past_decisions_from_orchestrator(
        orchestrator_payload=EXAMPLE_ORCHESTRATOR_PAYLOAD,
        include_failed_clinical=False,
        keep_full_past_output=False,
        debug=False,
    )

    print(json.dumps(result, indent=2, default=str))