"""Small runnable example chaining Stage C Phases 1-10 together."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from stage_c.candidate_selection import select_candidates
from stage_c.clinical_rationale import build_clinical_rationale
from stage_c.composite_score import compute_composite_scores
from stage_c.config import load_stage_c_config
from stage_c.evidence_packaging import package_evidence
from stage_c.final_payload import build_final_payload
from stage_c.ranking import rank_candidates
from stage_c.safety_flags import evaluate_safety_flags
from stage_c.threshold import filter_passing_candidates


if __name__ == "__main__":
    stage_a_output = {
        "alternatives": [
            {
                "prod_id": 1031,
                "prod_name": "Example Alternative A",
                "stage_a": {
                    "score": 0.91,
                    "evidence": {"ingredient": 1.0},
                    "status": "accepted",
                    "llm_required": False,
                    "reasoning": "Strong therapeutic similarity.",
                },
            },
            {
                "prod_id": 1032,
                "prod_name": "Example Alternative B",
                "stage_a": {
                    "score": 0.42,
                    "evidence": {"ingredient": 0.25},
                    "status": "rejected",
                    "llm_required": True,
                    "reasoning": "Weak ingredient overlap.",
                },
            },
        ]
    }

    stage_b_output = {
        "alternatives": [
            {
                "prod_id": 1031,
                "prod_name": "Example Alternative A",
                "evidence": {
                    "allergy": 0.25,
                    "condition": 0.5,
                    "age": 0.0,
                    "contraindication": 0.0,
                    "interaction": 0.25,
                    "renal_hepatic": 0.75,
                    "duplicate_therapy": 0.75,
                },
                "score": 0.88,
                "status": "accepted",
                "llm_required": False,
                "reasoning": "No material safety blockers.",
            },
            {
                "prod_id": 1032,
                "prod_name": "Example Alternative B",
                "evidence": {
                    "allergy": 0.0,
                    "condition": 0.5,
                    "age": 0.0,
                    "contraindication": 0.0,
                    "interaction": 0.0,
                    "renal_hepatic": 0.0,
                    "duplicate_therapy": 1.0,
                },
                "score": 0.64,
                "status": "rejected",
                "llm_required": True,
                "reasoning": "Safety review did not clear progression.",
            },
        ],
        "from_stage_a": {
            "alternatives": [
                {
                    "prod_id": 1031,
                    "prod_name": "Example Alternative A",
                    "score": 0.91,
                    "status": "accepted",
                    "llm_required": False,
                    "reasoning": "Strong therapeutic similarity.",
                    "stage_b_score": 0.88,
                    "stage_b_decision": "accepted",
                    "stage_b_llm_required": False,
                    "stage_b_evidence": {
                        "allergy": {"allergy_risk": 0.25, "severity": "LOW"},
                        "condition": {
                            "condition_match": 0.5,
                            "severity": None,
                            "reason": "condition_weak_class_alignment",
                        },
                        "age": {"age_risk": 0.25, "risk_band": "moderate"},
                        "contraindication": {"contraindication": False, "severity": None},
                        "interaction": {
                            "interaction_detected": True,
                            "interaction_severity": "minor",
                            "interaction_score": 0.25,
                            "matches": [],
                        },
                        "renal_hepatic": {"severity": "MINOR", "score": 0.75, "data_complete": True},
                        "duplicate_therapy": {
                            "status": "PASS",
                            "severity": "MINOR",
                            "score": 0.75,
                            "reason": "same_therapeutic_class_detected",
                            "match_type": "same_class",
                            "matched_medication": "Medication C",
                        },
                    },
                },
                {
                    "prod_id": 1032,
                    "prod_name": "Example Alternative B",
                    "score": 0.42,
                    "status": "rejected",
                    "llm_required": True,
                    "reasoning": "Weak ingredient overlap.",
                    "stage_b_score": 0.64,
                    "stage_b_decision": "rejected",
                    "stage_b_llm_required": True,
                    "stage_b_evidence": {
                        "allergy": {"allergy_risk": 0.0, "severity": None},
                        "condition": {
                            "condition_match": 0.25,
                            "severity": "MAJOR",
                            "reason": "contraindication_condition_overlap",
                        },
                        "age": {"age_risk": 0.0, "risk_band": "low"},
                        "contraindication": {"contraindication": True, "severity": "MAJOR"},
                        "interaction": {
                            "interaction_detected": False,
                            "interaction_severity": "none",
                            "interaction_score": 0.0,
                            "matches": [],
                        },
                        "renal_hepatic": {"severity": "NONE", "score": 1.0, "data_complete": True},
                        "duplicate_therapy": {
                            "status": "PASS",
                            "severity": "NONE",
                            "score": 1.0,
                            "reason": "no_duplicate_therapy_signal",
                            "match_type": None,
                            "matched_medication": None,
                        },
                    },
                },
            ]
        },
    }

    member = {
        "MBR_SK": 9999,
        "CURRENT_MEDICATIONS": "Medication A|Medication B|Medication C|Medication D|Medication E",
    }
    patient_labs = {
        "eGFR": 55,
        "CrCl": 58,
        "Creatinine": 1.1,
        "AST": 22,
        "ALT": 19,
        "Bilirubin": 0.8,
        "Child_Pugh": "B",
    }

    selected = select_candidates(stage_a_output, stage_b_output)
    packaged = package_evidence(selected["eligible_candidates"])
    config = load_stage_c_config()
    for candidate in packaged:
        evaluate_safety_flags(candidate, member, patient_labs, candidate.stage_b_evidence)

    compute_composite_scores(packaged, config)
    passing_candidates = filter_passing_candidates(packaged, config)
    ranked_candidates = rank_candidates(passing_candidates)
    for candidate in ranked_candidates:
        build_clinical_rationale(candidate)

    original_drug = {
        "prod_id": 1034,
        "prod_name": "Sacubitril-Valsartan 24-26mg",
    }
    final_payload = build_final_payload(original_drug, ranked_candidates)

    print(json.dumps(final_payload, indent=2))