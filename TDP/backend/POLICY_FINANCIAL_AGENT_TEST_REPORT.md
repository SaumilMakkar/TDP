# Policy and Financial Agent Test Report

Generated on 2026-07-02.

## Scope

This report documents:

- input contracts for the Policy Agent and Financial Agent
- how focused test cases were generated
- actual observed results from representative runs against the current CSV-backed dataset

## Policy Agent

### Input Contract

The Policy Agent evaluates one candidate drug at a time against formulary, prior authorization, step therapy, and quantity rules.

Expected input:

```json
{
  "drug_id": "<candidate PROD_SK>",
  "plan_id": "<PLN_SK>",
  "member_id": "<MBR_SK>",
  "quantity": 30,
  "fill_date": "2025-06-01"
}
```

### Test Case Generation Approach

The following Policy Agent cases were selected to cover the main rule branches:

1. Clean covered pass case
2. Unknown drug deny case
3. Prior authorization pending case
4. Quantity limit violation case

The restricted cases were selected from real rows in `v_d_plan_drug_status.csv` for plan `3010`:

- `1008` with status `PA`
- `1039` with status `QL` and quantity limit `30`

### Expected Output

Expected output format:

```json
{
  "drug_id": "<candidate PROD_SK>",
  "covered": true,
  "tier": "<FORMULARY_TIER|null>",
  "pa_required": false,
  "pa_met": true,
  "step_therapy_required": false,
  "step_therapy_met": true,
  "quantity_ok": true,
  "violations": ["<violation if any>"],
  "score": 0.95,
  "notes": "<human-readable note>",
  "summary": {
    "decision": "pass|pending|deny",
    "reason": "<human-readable reason>",
    "score": 0.95
  }
}
```

Expected output by case:

```json
{
  "P1_covered_pass": {
    "covered": true,
    "pa_required": false,
    "step_therapy_required": false,
    "quantity_ok": true,
    "summary": { "decision": "pass" }
  },
  "P2_unknown_drug": {
    "covered": false,
    "summary": { "decision": "deny" }
  },
  "P3_pa_pending": {
    "covered": true,
    "pa_required": true,
    "pa_met": false,
    "summary": { "decision": "pending" }
  },
  "P4_quantity_limit_violation": {
    "covered": true,
    "quantity_ok": false,
    "summary": { "decision": "pending" }
  }
}
```

### Test Cases and Results

#### Case P1: Covered pass

Input:

```json
{
  "drug_id": "1033",
  "plan_id": "3010",
  "member_id": "2001",
  "quantity": 30,
  "fill_date": "2025-06-01"
}
```

Observed result:

```json
{
  "drug_id": "1033",
  "covered": true,
  "tier": "3",
  "pa_required": false,
  "pa_met": true,
  "step_therapy_required": false,
  "step_therapy_met": true,
  "quantity_ok": true,
  "violations": [],
  "score": 0.95,
  "notes": "All policy checks passed.",
  "summary": {
    "decision": "pass",
    "reason": "All policy checks passed.",
    "score": 0.95
  }
}
```

#### Case P2: Unknown drug

Input:

```json
{
  "drug_id": "999999",
  "plan_id": "3010",
  "member_id": "2001",
  "quantity": 30,
  "fill_date": "2025-06-01"
}
```

Observed result:

```json
{
  "drug_id": "999999",
  "covered": false,
  "tier": null,
  "pa_required": false,
  "pa_met": false,
  "step_therapy_required": false,
  "step_therapy_met": false,
  "quantity_ok": true,
  "score": 0.1,
  "violations": [
    "Unknown drug (PROD_SK=999999)."
  ],
  "notes": "Unknown drug (PROD_SK=999999).",
  "summary": {
    "decision": "deny",
    "reason": "Unknown drug (PROD_SK=999999).",
    "score": 0.1
  }
}
```

#### Case P3: Prior authorization pending

Input:

```json
{
  "drug_id": "1008",
  "plan_id": "3010",
  "member_id": "2001",
  "quantity": 30,
  "fill_date": "2025-06-01"
}
```

Observed result:

```json
{
  "drug_id": "1008",
  "covered": true,
  "tier": "4",
  "pa_required": true,
  "pa_met": false,
  "step_therapy_required": false,
  "step_therapy_met": true,
  "quantity_ok": true,
  "score": 0.45,
  "violations": [
    "Prior authorization required and not yet evidenced."
  ],
  "notes": "Prior authorization required and not yet evidenced.",
  "summary": {
    "decision": "pending",
    "reason": "Prior authorization required and not yet evidenced.",
    "score": 0.45
  }
}
```

#### Case P4: Quantity limit violation

Input:

```json
{
  "drug_id": "1039",
  "plan_id": "3010",
  "member_id": "2001",
  "quantity": 60,
  "fill_date": "2025-06-01"
}
```

Observed result:

```json
{
  "drug_id": "1039",
  "covered": true,
  "tier": "1",
  "pa_required": false,
  "pa_met": true,
  "step_therapy_required": false,
  "step_therapy_met": true,
  "quantity_ok": false,
  "score": 0.45,
  "violations": [
    "Requested quantity 60 exceeds plan limit 30."
  ],
  "notes": "Requested quantity 60 exceeds plan limit 30.",
  "summary": {
    "decision": "pending",
    "reason": "Requested quantity 60 exceeds plan limit 30.",
    "score": 0.45
  }
}
```

### Policy Agent Summary

- Pass branch verified
- Deny branch verified
- Prior authorization pending branch verified
- Quantity limit pending branch verified

## Financial Agent

### Input Contract

The Financial Agent prices one candidate drug and optionally compares it to the originally prescribed drug.

Expected input:

```json
{
  "drug_id": "<candidate PROD_SK>",
  "plan_id": "<PLN_SK>",
  "member_id": "<MBR_SK>",
  "fill_date": "2025-06-01",
  "original_drug_id": "<original PROD_SK>"
}
```

`original_drug_id` is optional. If omitted, the agent falls back to absolute affordability scoring.

### Test Case Generation Approach

The following Financial Agent cases were selected to cover the main pricing branches:

1. Candidate compared against a valid original drug
2. Candidate compared against a valid original drug but more expensive branch
3. Candidate covered by formulary but unpriceable for the requested fill date
4. Candidate covered but original not priceable (fallback branch)
5. Member identifier missing (phase defaults to INITIAL_COVERAGE)

The comparison case uses real pricing and plan data for:

- candidate drug `1033`
- original drug `1018`
- plan `3010`
- member `2001`
- fill date `2025-06-01`

### Expected Output

Expected output format:

```json
{
  "drug_id": "<candidate PROD_SK>",
  "covered": true,
  "tier": "<FORMULARY_TIER|null>",
  "final_cost": 22.89,
  "estimated_patient_pay": 22.89,
  "pricing_source": "Negotiated|MAC|null",
  "original_drug_id": "<original PROD_SK|null>",
  "original_final_cost": 33.0,
  "original_patient_pay": 33.0,
  "estimated_savings": 10.11,
  "savings_pct": 0.3064,
  "insurance_context": {
    "phase": "DEDUCTIBLE|INITIAL_COVERAGE|CATASTROPHIC"
  },
  "financial_phase_decision_hint": "<phase comparison hint|null>",
  "score": 0.806,
  "notes": "<human-readable explanation>",
  "summary": {
    "decision": "not_covered|unpriceable|fallback_absolute|fallback_original_unpriceable|unknown|cheaper|more_expensive|same_cost",
    "reason": "<human-readable reason>",
    "score": 0.806,
    "estimated_savings": 10.11,
    "candidate_patient_pay": 22.89,
    "original_patient_pay": 33.0
  }
}
```

Expected output by case:

```json
{
  "F1_cheaper_comparison": {
    "covered": true,
    "estimated_savings": "> 0",
    "summary": { "decision": "cheaper" }
  },
  "F2_more_expensive_comparison": {
    "covered": true,
    "estimated_savings": "< 0",
    "summary": { "decision": "more_expensive" }
  },
  "F3_unpriceable_candidate": {
    "covered": true,
    "final_cost": null,
    "summary": { "decision": "unpriceable" }
  },
  "F4_original_unpriceable_fallback": {
    "covered": true,
    "original_final_cost": null,
    "summary": { "decision": "fallback_original_unpriceable" }
  },
  "F5_missing_member_phase_default": {
    "covered": true,
    "insurance_context": { "phase": "INITIAL_COVERAGE" },
    "summary": { "decision": "cheaper|more_expensive|same_cost" }
  }
}
```

### Test Cases and Results

#### Case F1: Comparison against original drug (cheaper branch)

Input:

```json
{
  "drug_id": "1033",
  "plan_id": "3010",
  "member_id": "2001",
  "fill_date": "2025-06-01",
  "original_drug_id": "1018"
}
```

Observed result:

```json
{
  "drug_id": "1033",
  "covered": true,
  "tier": "3",
  "final_cost": 22.89,
  "estimated_patient_pay": 22.89,
  "pricing_source": "Negotiated",
  "original_drug_id": "1018",
  "original_final_cost": 33.0,
  "original_patient_pay": 33.0,
  "estimated_savings": 10.11,
  "savings_pct": 0.3064,
  "insurance_context": {
    "phase": "DEDUCTIBLE"
  },
  "score": 0.806,
  "financial_phase_decision_hint": "No phase-boundary difference: both stay in DEDUCTIBLE.",
  "notes": "Candidate 1033 is cheaper than original 1018 in the same deductible phase.",
  "summary": {
    "decision": "cheaper",
    "reason": "Candidate 1033 saves the original drug 1018 under the same deductible-phase context.",
    "score": 0.806,
    "estimated_savings": 10.11,
    "candidate_patient_pay": 22.89,
    "original_patient_pay": 33.0
  }
}
```

Key interpretation:

- Member is in `DEDUCTIBLE` phase
- Candidate saves `$10.11` versus original
- Savings percentage is `+31%`
- Financial score rises above threshold because the alternative is materially cheaper

#### Case F2: Comparison against original drug (more_expensive branch)

Input:

```json
{
  "drug_id": "1047",
  "plan_id": "3010",
  "member_id": "2001",
  "fill_date": "2025-06-01",
  "original_drug_id": "1018"
}
```

Observed result:

```json
{
  "drug_id": "1047",
  "covered": true,
  "tier": "2",
  "final_cost": 34.73,
  "estimated_patient_pay": 34.73,
  "pricing_source": "MAC",
  "original_drug_id": "1018",
  "original_final_cost": 33.0,
  "original_patient_pay": 33.0,
  "estimated_savings": -1.73,
  "savings_pct": -0.0524,
  "insurance_context": {
    "phase": "DEDUCTIBLE"
  },
  "financial_phase_decision_hint": "No phase-boundary difference: both stay in DEDUCTIBLE.",
  "score": 0.448,
  "notes": "Candidate 1047 is more expensive than original 1018 in the same deductible phase.",
  "summary": {
    "decision": "more_expensive",
    "reason": "Candidate 1047 costs more than original 1018 under the same deductible-phase context.",
    "score": 0.448,
    "estimated_savings": -1.73,
    "candidate_patient_pay": 34.73,
    "original_patient_pay": 33.0
  }
}
```

Key interpretation:

- Full candidate-vs-original comparison is available
- Candidate is slightly more expensive than original
- Score drops below threshold because savings are negative

#### Case F3: Candidate unpriceable (no valid pricing row for fill date)

Input:

```json
{
  "drug_id": "1033",
  "plan_id": "3010",
  "member_id": "2001",
  "fill_date": "2035-01-01",
  "original_drug_id": "1018"
}
```

Observed result:

```json
{
  "drug_id": "1033",
  "covered": true,
  "tier": "3",
  "final_cost": null,
  "estimated_patient_pay": null,
  "pricing_source": null,
  "original_drug_id": null,
  "original_final_cost": null,
  "original_patient_pay": null,
  "estimated_savings": null,
  "savings_pct": null,
  "insurance_context": {
    "phase": "DEDUCTIBLE"
  },
  "financial_phase_decision_hint": null,
  "score": 0.3,
  "notes": "No pricing record valid for 1033 as of 2035-01-01.",
  "summary": {
    "decision": "unpriceable",
    "reason": "No pricing record valid for 1033 as of 2035-01-01.",
    "score": 0.3,
    "estimated_savings": null,
    "candidate_patient_pay": null,
    "original_patient_pay": null
  }
}
```

Key interpretation:

- Candidate has a payable formulary status but no valid pricing version for the requested date
- Financial agent exits through the unpriceable branch before comparison math

#### Case F4: Original drug unpriceable (fallback_original_unpriceable)

Input:

```json
{
  "drug_id": "1033",
  "plan_id": "3010",
  "member_id": "2001",
  "fill_date": "2025-06-01",
  "original_drug_id": "999999"
}
```

Observed result:

```json
{
  "drug_id": "1033",
  "covered": true,
  "tier": "3",
  "final_cost": 22.89,
  "estimated_patient_pay": 22.89,
  "pricing_source": "Negotiated",
  "original_drug_id": "999999",
  "original_final_cost": null,
  "original_patient_pay": null,
  "estimated_savings": null,
  "savings_pct": null,
  "insurance_context": {
    "phase": "DEDUCTIBLE"
  },
  "financial_phase_decision_hint": null,
  "score": 0.85,
  "notes": "Original drug could not be priced; candidate valid coverage treated as an improvement.",
  "summary": {
    "decision": "fallback_original_unpriceable",
    "reason": "Original drug could not be priced; candidate valid coverage treated as an improvement.",
    "score": 0.85,
    "estimated_savings": null,
    "candidate_patient_pay": 22.89,
    "original_patient_pay": null
  }
}
```

Key interpretation:

- Candidate is priceable but original is not
- Agent uses dedicated fallback score for original-unpriceable condition

#### Case F5: Missing member_id (phase default behavior)

Input:

```json
{
  "drug_id": "1033",
  "plan_id": "3010",
  "fill_date": "2025-06-01",
  "original_drug_id": "1018"
}
```

Observed result:

```json
{
  "drug_id": "1033",
  "covered": true,
  "tier": "3",
  "final_cost": 22.89,
  "estimated_patient_pay": 10.3,
  "pricing_source": "Negotiated",
  "original_drug_id": "1018",
  "original_final_cost": 33.0,
  "original_patient_pay": 14.85,
  "estimated_savings": 4.55,
  "savings_pct": 0.3064,
  "financial_phase_decision_hint": "No phase-boundary difference: both stay in INITIAL_COVERAGE.",
  "score": 0.806,
  "notes": "With member history unavailable, initial-coverage estimate still shows candidate cheaper than original.",
  "insurance_context": {
    "phase": "INITIAL_COVERAGE",
    "note": "member_id not supplied; defaulted to INITIAL_COVERAGE phase."
  },
  "summary": {
    "decision": "cheaper",
    "reason": "With member history unavailable, initial-coverage estimate still shows candidate cheaper than original.",
    "score": 0.806,
    "estimated_savings": 4.55,
    "candidate_patient_pay": 10.3,
    "original_patient_pay": 14.85
  }
}
```

Key interpretation:

- Without member history, phase defaults to INITIAL_COVERAGE
- Coinsurance-based estimate is used instead of deductible accumulator logic

### Financial Agent Summary

- Comparison-based pricing branch verified
- More-expensive comparison branch verified
- Candidate-unpriceable early-exit branch verified
- Original-unpriceable fallback branch verified
- Missing-member phase default branch verified
- Deductible-phase patient pay calculation verified
- Insurance context and phase projection returned as expected

## Overall Notes

- Both agents are deterministic and do not use LLMs
- Both agents return structured output suitable for orchestrator consumption
- The test results above were captured from the current code and dataset, not hand-written expectations