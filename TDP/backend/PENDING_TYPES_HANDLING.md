# Pending Types Handling

This document describes the implemented pending-type behavior in Policy and Orchestrator.

## What Changed

Policy now returns explicit workflow fields:

- `policy_state`: `pass | pending | deny`
- `pending_type`: `doctor_review | pharmacy_review | admin_review | mixed_review | null`
- `pending_reasons`: list of unresolved rule violations
- `review_recommendation`: human-readable action guidance

Orchestrator now routes by `policy_state` for policy outcomes:

- `pass`: candidate can proceed through normal gating and scoring
- `pending`: candidate is reviewable and enters review pool
- `deny`: candidate is blocked and not reviewable

## Pending Type Classification Rules

### `doctor_review`
Assigned when pending is caused by any of:

- Prior authorization required and not evidenced
- Step therapy required and not evidenced
- Quantity limit exceeded

### `pharmacy_review`
Assigned when pending is caused by any of:

- Selected pharmacy cannot dispense
- Selected pharmacy has insufficient stock
- Selected pharmacy reports out of stock

### `admin_review`
Assigned when pending is caused by:

- Pharmacy inventory record exists but is not active for the fill date

### `mixed_review`
Assigned when more than one pending category is present in a single candidate (for example, `doctor_review` + `pharmacy_review`).

## Doctor Action Model (Three Options)

Doctor has three actions: `accept`, `reject`, `modify`.

### For `doctor_review`
- `accept`: approve candidate override
- `reject`: keep original prescription
- `modify`: adjust parameters (for example quantity) and proceed with review intent

### For `pharmacy_review`
- `accept`: approve clinically; operational pharmacy follow-up required
- `reject`: keep original prescription
- `modify`: approve with alternate pharmacy intent/follow-up note

### For `admin_review`
- `accept`: approve clinically; admin follow-up required
- `reject`: keep original prescription
- `modify`: approve with pending admin resolution note

### For `mixed_review`
- `accept`: approve with combined follow-up obligations
- `reject`: keep original prescription
- `modify`: resolve part of issue and keep remaining obligations explicit

## Response Shape Example

```json
{
  "policy": {
    "policy_state": "pending",
    "pending_type": "pharmacy_review",
    "pending_reasons": [
      "Selected pharmacy 4001 reports this drug out of stock."
    ],
    "review_recommendation": "Pharmacy follow-up needed; route to doctor review fallback (accept/reject/modify)."
  },
  "policy_summary": {
    "decision": "pending",
    "reason": "Selected pharmacy 4001 reports this drug out of stock.",
    "score": 0.58
  }
}
```

## Orchestrator Review Basis Labels

Pending review candidates now carry `score_basis` labels like:

- `policy_pending_doctor_review`
- `policy_pending_pharmacy_review`
- `policy_pending_admin_review`
- `policy_pending_mixed_review`

These labels are used in review explanations and candidate lists.

## Validation

Implemented tests cover:

- Policy pending classification by type
- Mixed pending classification
- Admin pending classification
- Orchestrator branch behavior with pending routing into review
- End-to-end candidate output with policy metadata intact
