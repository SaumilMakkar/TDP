# Policy Agent — Scoring and Doctor Flow

Reflects the current implementation after pharmacy/stock/admin logic was removed.

Source files:
- app/agents/policy_agent.py
- app/agents/orchestrator.py

---

## 1. What the Policy Agent Evaluates

The Policy Agent checks three things only:

- formulary coverage (is this drug covered under this plan?)
- prior authorization (is PA required and has it been granted?)
- step therapy (is the prerequisite alternative proven to have been tried?)
- quantity limit (does the requested quantity stay within the plan limit?)

It is fully deterministic — no LLM, no probability. Every outcome traces to a specific rule in the plan/drug/claims data.

---

## 2. Policy State

Every evaluation produces one of three states:

| State | Meaning |
|---|---|
| pass | covered, all policy conditions satisfied |
| pending | covered but a clinical-policy exception is unresolved |
| deny | not covered or invalid entity |

**`pending_type` is always `doctor_review`.**
That is the only remaining pending category. Pharmacy/admin/mixed types were removed.

---

## 3. Score Bands

### Pass — score driven by formulary preference

| Preference | Score |
|---|---|
| Preferred Generic | 0.98 |
| Preferred Brand | 0.90 |
| Covered | 0.84 |
| Covered (plan default fallback) | 0.80 |
| Non Preferred | 0.72 |
| Exception Only | 0.62 |

### Pending — score derived from preference

```
pending_score = max(0.20, min(0.69, preference_score - 0.30))
```

This guarantees pending always stays below the orchestrator policy threshold (0.70), but preserves relative ranking between candidates.

Examples:
- Exception Only pending (PA required): 0.62 - 0.30 = 0.32
- Covered pending (QL exceeded): 0.84 - 0.30 = 0.54
- Non Preferred pending (ST unmet): 0.72 - 0.30 = 0.42

### Deny — fixed score

- Score = 0.10 regardless of preference

---

## 4. What Causes Each State

### pass

Drug is active, plan is active, formulary rule is active, and:
- no PA required, OR PA evidence found in claim history
- no step therapy required, OR qualifying alternative found in claim history
- no quantity limit, OR requested quantity is within the limit

### pending

Drug is payable but one of these is unresolved:
- PA required and no prior claim with `PA_APPROVED_FLG = Y` for this member + drug + plan
- Step therapy required and no prior claim for any of the required alternative drugs
- Requested quantity exceeds `QUANTITY_LIMIT` in plan_drug_status

Result:
- `policy_state = pending`
- `pending_type = doctor_review`
- `review_recommendation = "Doctor review required (accept/reject/modify)."`
- `pending_reasons` = list of the specific violation strings

### deny

Any of these:
- Unknown drug or plan
- Drug not active or date-invalid
- Plan date-invalid
- Formulary status EX or NC (excluded / not covered)
- Formulary status NF (non-formulary, no standard coverage pathway)
- No formulary row on file and plan default is non-covered

Result:
- `policy_state = deny`
- `score = 0.10`
- Candidate is dropped from viable routing paths

---

## 5. Formulary Preference Logic

Preference classifier uses `PLN_DRG_STAT_CD`, `FORMULARY_TIER`, and `BRAND_IND`:

| Condition | Preference |
|---|---|
| INACTIVE group or EX/NC | Excluded |
| NF | Exception Only |
| PA or ST status | Exception Only |
| Tier 1 + generic | Preferred Generic |
| Tier 1 or 2 + brand | Preferred Brand |
| Tier >= 3 | Non Preferred |
| Otherwise | Covered |

Preference does not change the routing decision. It adjusts the score within each state, so higher-preference candidates rank better even when both are pending.

---

## 6. Orchestrator Threshold Gate

Policy is evaluated differently from other agents inside the orchestrator:

- The gate uses `policy_state`, not the numeric score
- `pass` → `passed_threshold = True`
- `pending` → `passed_threshold = False` (routes to doctor review)
- `deny` → `passed_threshold = False` (dropped)

Current thresholds from scoring_config.json:
- policy threshold = 0.70 (used for display only; actual gate is state-based)
- overall threshold = 0.80 (combined score needed to auto-approve)

---

## 7. Routing Outcomes

| Policy state | Orchestrator route |
|---|---|
| pass + combined score >= 0.80 | auto-approve |
| pass + combined score < 0.80 | doctor review pool |
| pending (doctor_review) | doctor review pool |
| deny | dropped |

---

## 8. What the Doctor Receives

The orchestrator sends the doctor one of two question shapes:

### Single candidate review

```
escalation_type: single_drug_approval
recommended_drug: <drug_id>
doctor_question: "The system recommends switching to drug X.
                  Policy marked this candidate as pending (doctor_review):
                  <violation text>.
                  Approve this drug for the patient? (yes/no)"
```

Fields available per candidate:
- `policy_state`
- `pending_type`
- `pending_reasons` — the exact violation strings
- `review_recommendation`
- `pa_required` / `pa_met`
- `step_therapy_required` / `step_therapy_met`
- `quantity_ok`
- `formulary_preference`
- `score`
- `combined_score`

### Multiple candidate review

```
escalation_type: multiple_candidate_options
candidates_shown: ranked list, each with combined_score, score_basis, and reason
```

---

## 9. Doctor Actions

The doctor always has exactly three actions:

| Action | Meaning |
|---|---|
| Accept | approve this candidate, rationale required |
| Deny | reject, keep original drug |
| Modify | select a different candidate or adjust parameters |

Every action must be accompanied by a rationale string. That rationale is stored in the audit trail.

---

## 10. Concrete Doctor Reply Examples

### PA unmet

System question:
```
Policy marked this candidate as pending (doctor_review):
Prior authorization required and not yet evidenced.
Approve this drug for the patient? (yes/no)
```

Doctor replies:
- **Accept** — "I authorize prior approval. Patient has failed first-line therapy."
- **Deny** — "Keep original prescription. PA process not initiated."
- **Modify** — "Switch to candidate X which does not require PA."

---

### Step therapy unmet

System question:
```
Policy marked this candidate as pending (doctor_review):
Step therapy required; no evidence the qualifying alternative was tried first.
Approve this drug for the patient? (yes/no)
```

Doctor replies:
- **Accept** — "Patient tried the required alternative informally. Approving step therapy exception."
- **Deny** — "Keep original. Patient should complete step therapy first."
- **Modify** — "Select a different candidate that does not require step therapy."

---

### Quantity limit exceeded

System question:
```
Policy marked this candidate as pending (doctor_review):
Requested quantity 60 exceeds plan limit 30.
Approve this drug for the patient? (yes/no)
```

Doctor replies:
- **Accept** — "Patient requires 60 units due to chronic condition. Approving quantity exception."
- **Deny** — "Reduce to plan limit of 30. Keep original drug."
- **Modify** — "Approve candidate but reduce quantity to 30 to comply with plan limit."

---

## 11. Key Rule

The policy agent and orchestrator together guarantee:

- pending always means a **clinical-policy exception** — PA, step therapy, or quantity limit
- the doctor only ever sees questions they can actually answer clinically
- no pharmacy, stock, or operational issues reach the doctor's review queue
