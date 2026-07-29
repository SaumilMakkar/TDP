# Policy Agent Scoring Guide

This document explains how policy scoring is computed in `app/agents/policy_agent.py`.

## 1) Decision Types

The policy agent returns one of these decisions:

- `deny`: hard policy failure
- `pending`: potentially coverable, but unmet requirements exist
- `pass`: policy checks are fully satisfied

## 2) Fixed Score Constants

- `SCORE_NOT_COVERED = 0.10`
- `SCORE_FALLBACK_PASS = 0.80`

The scoring threshold used by orchestration is configured outside this file (commonly 0.70).

## 3) Hard Deny Paths (Score = 0.10)

These conditions immediately return `deny` with score `0.10`:

- Unknown drug
- Unknown plan
- Drug inactive/discontinued for fill date
- Plan inactive for fill date
- Unknown pharmacy (when pharmacy_id is provided)
- Inactive pharmacy (when pharmacy_id is provided)
- Excluded / Not Covered status (`EX`, `NC`)
- Non-formulary status (`NF`)
- No plan-drug row and plan default is non-covered

## 4) Formulary Preference Hierarchy

Covered candidates are classified into this hierarchy:

1. Preferred Generic
2. Preferred Brand
3. Covered
4. Non Preferred
5. Exception Only
6. Excluded

## 5) Base Pass Scores by Preference

- Preferred Generic: `0.98`
- Preferred Brand: `0.90`
- Covered: `0.84`
- Non Preferred: `0.72`
- Exception Only: `0.62`
- Excluded: `0.10`

## 6) Preference Classification Rules

- `EX`/`NC` -> `Excluded`
- `NF` -> `Exception Only`
- `PA`/`ST` -> `Exception Only`
- Tier 1 + generic -> `Preferred Generic`
- Tier 1 or 2 + brand -> `Preferred Brand`
- Tier 3+ -> `Non Preferred`
- Else -> `Covered`

## 7) Pending Logic

If any policy violations exist, decision becomes `pending` and score is reduced while preserving preference order.

Pending score formula:

```
pending_score = max(0.20, min(0.69, base_preference_score−0.30))
```



## 8) Violations That Trigger Pending

Any of the following can add violations and move decision to `pending`:

- Prior authorization required but not evidenced
- Step therapy required but not evidenced
- Quantity limit exceeded
- Pharmacy does not dispense the drug
- Pharmacy inventory out of stock
- Pharmacy inventory has insufficient stock
- Inventory record not active for fill date

## 9) Default-Coverage Fallback Branch

If no active plan-drug status row is found:

- Plan default covered -> `pass`, score `0.80`
- Plan default non-covered -> `deny`, score `0.10`

## 10) Worked Examples

### Example A: Two covered drugs, different preference

- Drug A: Tier 1 generic -> `Preferred Generic` -> score `0.98` (if no violations)
- Drug B: Tier 3 brand -> `Non Preferred` -> score `0.72` (if no violations)

Both are covered, but Drug A gets a much better policy score.

### Example B: Exception-only with unmet PA

- Status: `PA`
- Preference: `Exception Only` (base 0.62)
- Violation: PA not met

Pending score:

- `0.62 - 0.30 = 0.32` -> decision `pending`

### Example C: Covered by plan default

- No plan-drug row
- Plan default = covered

Result:

- decision `pass`
- score `0.80`

## 11) Output Fields That Explain Policy Score

The policy output includes:

- `formulary_preference`
- `score`
- `summary.decision`
- `summary.reason`
- `violations`
- `is_discontinued`
- `pharmacy_provides`
- `out_of_stock`
