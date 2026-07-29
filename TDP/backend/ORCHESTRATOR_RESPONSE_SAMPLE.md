# Orchestrator Response Sample

```json
{
  "trace_id": "TRC-e85afe983236",
  "escalated": false,
  "final_candidates": [
    {
      "drug_id": "1031",
      "combined_score": 0.97,
      "agent_breakdown": {
        "policy": 0.98,
        "clinical": 0.0,
        "financial": 0.95,
        "past": 0.0
      },
      "has_signal": {
        "policy": true,
        "clinical": false,
        "financial": true,
        "past": false
      },
      "threshold_pass": {
        "policy": true,
        "clinical": true,
        "financial": true,
        "past": true
      },
      "safe": true,
      "requires_mandatory_escalation": false,
      "passed_gate": true,
      "clears_overall_threshold": true,
      "policy": {
        "covered": true,
        "tier": "1",
        "score": 0.98,
        "policy_state": "pass",
        "pending_type": null,
        "pending_reasons": [],
        "review_recommendation": null,
        "formulary_preference": "Preferred Generic",
        "pa_required": false,
        "pa_met": true,
        "step_therapy_required": false,
        "step_therapy_met": true,
        "quantity_ok": true,
        "violations": [],
        "notes": "Preferred Generic formulary preference. All policy checks passed."
      },
      "policy_summary": {
        "decision": "pass",
        "reason": "Preferred Generic formulary preference. All policy checks passed.",
        "score": 0.98
      },
      "financial": {
        "covered": true,
        "tier": "1",
        "score": 0.95,
        "final_cost": 9.76,
        "estimated_patient_pay": 9.76,
        "original_final_cost": 401.04,
        "estimated_savings": 391.28,
        "savings_pct": 0.9757,
        "pricing_source": "WAC",
        "phase": "DEDUCTIBLE",
        "insurance_context": {
          "phase": "DEDUCTIBLE",
          "ytd_oop": 192.16,
          "deductible_cap": 1500.0,
          "oop_max_cap": 3000.0,
          "deductible_remaining": 1307.84,
          "oop_remaining": 2807.84,
          "note": null,
          "candidate_fill_projection": {
            "phase_before": "DEDUCTIBLE",
            "phase_after": "DEDUCTIBLE",
            "phase_crossed": false,
            "patient_pay": 9.76,
            "effective_coinsurance": 1.0,
            "deductible_component": 9.76,
            "coinsurance_component": 0.0,
            "deductible_remaining_after": 1298.08,
            "oop_remaining_after": 2798.08,
            "ytd_oop_after": 201.92,
            "note": null
          },
          "original_fill_projection": {
            "phase_before": "DEDUCTIBLE",
            "phase_after": "DEDUCTIBLE",
            "phase_crossed": false,
            "patient_pay": 401.04,
            "effective_coinsurance": 1.0,
            "deductible_component": 401.04,
            "coinsurance_component": 0.0,
            "deductible_remaining_after": 906.8,
            "oop_remaining_after": 2406.8,
            "ytd_oop_after": 593.2,
            "note": null
          }
        },
        "notes": "[DEDUCTIBLE -> candidate:DEDUCTIBLE / original:DEDUCTIBLE] YTD OOP $192.16, deductible cap $1500.00, OOP max $3000.00. Candidate 1031 ($9.76, tier 1) saves the original drug 1034 ($401.04, tier 5), a savings of $391.28 (+98%)."
      },
      "financial_summary": {
        "decision": "cheaper",
        "reason": "[DEDUCTIBLE -> candidate:DEDUCTIBLE / original:DEDUCTIBLE] YTD OOP $192.16, deductible cap $1500.00, OOP max $3000.00. Candidate 1031 ($9.76, tier 1) saves the original drug 1034 ($401.04, tier 5), a savings of $391.28 (+98%).",
        "score": 0.95,
        "estimated_savings": 391.28,
        "candidate_patient_pay": 9.76,
        "original_patient_pay": 401.04
      }
    },
    {
      "drug_id": "1033",
      "combined_score": 0.797,
      "agent_breakdown": {
        "policy": 0.72,
        "clinical": 0.0,
        "financial": 0.95,
        "past": 0.0
      },
      "has_signal": {
        "policy": true,
        "clinical": false,
        "financial": true,
        "past": false
      },
      "threshold_pass": {
        "policy": true,
        "clinical": true,
        "financial": true,
        "past": true
      },
      "safe": true,
      "requires_mandatory_escalation": false,
      "passed_gate": true,
      "clears_overall_threshold": false,
      "policy": {
        "covered": true,
        "tier": "3",
        "score": 0.72,
        "policy_state": "pass",
        "pending_type": null,
        "pending_reasons": [],
        "review_recommendation": null,
        "formulary_preference": "Non Preferred",
        "pa_required": false,
        "pa_met": true,
        "step_therapy_required": false,
        "step_therapy_met": true,
        "quantity_ok": true,
        "violations": [],
        "notes": "Non Preferred formulary preference. All policy checks passed."
      },
      "policy_summary": {
        "decision": "pass",
        "reason": "Non Preferred formulary preference. All policy checks passed.",
        "score": 0.72
      },
      "financial": {
        "covered": true,
        "tier": "3",
        "score": 0.95,
        "final_cost": 22.89,
        "estimated_patient_pay": 22.89,
        "original_final_cost": 401.04,
        "estimated_savings": 378.15,
        "savings_pct": 0.9429,
        "pricing_source": "Negotiated",
        "phase": "DEDUCTIBLE",
        "insurance_context": {
          "phase": "DEDUCTIBLE",
          "ytd_oop": 192.16,
          "deductible_cap": 1500.0,
          "oop_max_cap": 3000.0,
          "deductible_remaining": 1307.84,
          "oop_remaining": 2807.84,
          "note": null,
          "candidate_fill_projection": {
            "phase_before": "DEDUCTIBLE",
            "phase_after": "DEDUCTIBLE",
            "phase_crossed": false,
            "patient_pay": 22.89,
            "effective_coinsurance": 1.0,
            "deductible_component": 22.89,
            "coinsurance_component": 0.0,
            "deductible_remaining_after": 1284.95,
            "oop_remaining_after": 2784.95,
            "ytd_oop_after": 215.05,
            "note": null
          },
          "original_fill_projection": {
            "phase_before": "DEDUCTIBLE",
            "phase_after": "DEDUCTIBLE",
            "phase_crossed": false,
            "patient_pay": 401.04,
            "effective_coinsurance": 1.0,
            "deductible_component": 401.04,
            "coinsurance_component": 0.0,
            "deductible_remaining_after": 906.8,
            "oop_remaining_after": 2406.8,
            "ytd_oop_after": 593.2,
            "note": null
          }
        },
        "notes": "[DEDUCTIBLE -> candidate:DEDUCTIBLE / original:DEDUCTIBLE] YTD OOP $192.16, deductible cap $1500.00, OOP max $3000.00. Candidate 1033 ($22.89, tier 3) saves the original drug 1034 ($401.04, tier 5), a savings of $378.15 (+94%)."
      },
      "financial_summary": {
        "decision": "cheaper",
        "reason": "[DEDUCTIBLE -> candidate:DEDUCTIBLE / original:DEDUCTIBLE] YTD OOP $192.16, deductible cap $1500.00, OOP max $3000.00. Candidate 1033 ($22.89, tier 3) saves the original drug 1034 ($401.04, tier 5), a savings of $378.15 (+94%).",
        "score": 0.95,
        "estimated_savings": 378.15,
        "candidate_patient_pay": 22.89,
        "original_patient_pay": 401.04
      }
    },
    {
      "drug_id": "1032",
      "combined_score": 0.1,
      "agent_breakdown": {
        "policy": 0.1,
        "clinical": 0.0,
        "financial": 0.1,
        "past": 0.0
      },
      "has_signal": {
        "policy": true,
        "clinical": false,
        "financial": true,
        "past": false
      },
      "threshold_pass": {
        "policy": false,
        "clinical": true,
        "financial": false,
        "past": true
      },
      "safe": true,
      "requires_mandatory_escalation": false,
      "passed_gate": false,
      "clears_overall_threshold": false,
      "policy": {
        "covered": false,
        "tier": null,
        "score": 0.1,
        "policy_state": "deny",
        "pending_type": null,
        "pending_reasons": [],
        "review_recommendation": null,
        "formulary_preference": "Exception Only",
        "pa_required": false,
        "pa_met": false,
        "step_therapy_required": false,
        "step_therapy_met": false,
        "quantity_ok": true,
        "violations": [
          "1032 is non-formulary under plan 3009; no standard coverage pathway."
        ],
        "notes": "1032 is non-formulary under plan 3009; no standard coverage pathway."
      },
      "policy_summary": {
        "decision": "deny",
        "reason": "1032 is non-formulary under plan 3009; no standard coverage pathway.",
        "score": 0.1
      },
      "financial": {
        "covered": false,
        "tier": "3",
        "score": 0.1,
        "final_cost": null,
        "estimated_patient_pay": null,
        "original_final_cost": 401.04,
        "estimated_savings": null,
        "savings_pct": null,
        "pricing_source": null,
        "phase": "DEDUCTIBLE",
        "insurance_context": {
          "phase": "DEDUCTIBLE",
          "ytd_oop": 192.16,
          "deductible_cap": 1500.0,
          "oop_max_cap": 3000.0,
          "deductible_remaining": 1307.84,
          "oop_remaining": 2807.84,
          "note": null
        },
        "notes": "1032 is not in a payable status under plan 3009 (status NF)."
      },
      "financial_summary": {
        "decision": "not_covered",
        "reason": "1032 is not in a payable status under plan 3009 (status NF).",
        "score": 0.1,
        "estimated_savings": null,
        "candidate_patient_pay": null,
        "original_patient_pay": 288.75
      }
    }
  ],
  "summary": {
    "architecture_note": "Each candidate is evaluated individually for gate pass and overall threshold clearance.",
    "decision": "auto_approve",
    "chosen_drug": "1031",
    "reason": "After evaluating all alternatives, 1031 was auto-approved because it passed gates and cleared the overall threshold.",
    "candidate_outcomes": [
      {
        "drug_id": "1031",
        "outcome": "auto_approved",
        "passed_gate": true,
        "combined_score": 0.97,
        "clears_overall_threshold": true
      },
      {
        "drug_id": "1033",
        "outcome": "escalated",
        "passed_gate": true,
        "combined_score": 0.797,
        "clears_overall_threshold": false,
        "escalation_reason": "Overall score below threshold despite passing gate checks."
      },
      {
        "drug_id": "1032",
        "outcome": "rejected",
        "passed_gate": false,
        "combined_score": 0.1,
        "clears_overall_threshold": false,
        "rejection_reason": "Policy and financial checks failed."
      }
    ],
    "llm_weights": {
      "policy": 0.3636363636363637,
      "clinical": 0.3181818181818182,
      "financial": 0.18181818181818185,
      "past": 0.13636363636363638
    },
    "weight_rationale": "Heart failure treatment with an ARNI requires careful policy and clinical review to ensure compliance and safety, while financial and precedent considerations are secondary due to the lack of controlled substance or narrow therapeutic index concerns.",
    "confidence_score": 0.97
  }
}
```
