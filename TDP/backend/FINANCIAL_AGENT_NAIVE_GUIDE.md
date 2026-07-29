# Financial Agent: Simple Guide

## What this agent does
The Financial Agent answers one question:

Is this alternative drug cheaper (or costlier) for this member and plan than the original drug?

It uses only real tables (no LLM judgment): plan coverage status, pricing table, and member claim history.

## Inputs it needs
- `drug_id` (original drug from claim context)
- `plan_id`
- `fill_date`
- `candidate drug_id` (one at a time)
- `member_id` (optional, but strongly recommended)

## Hard checks (strict checks)
These are hard because if they fail, we cannot do a real financial comparison.

1. Candidate priceability check
- If status is not payable under plan (for example `EX`, `NC`, `NF`, or no rule), candidate is treated as not covered.

2. Candidate pricing availability check
- If there is no valid pricing row for the fill date, candidate is unpriceable.

3. Original pricing availability check (for comparison mode)
- If original cannot be priced, we switch to fallback mode (candidate-only affordability), not direct comparison.

## Soft checks (influence score, do not hard-fail)
1. Insurance phase logic
- `DEDUCTIBLE`, `INITIAL_COVERAGE`, `CATASTROPHIC` change estimated patient pay.

2. Member context availability
- If `member_id` is missing, we still estimate pay, but default to `INITIAL_COVERAGE` and accumulator-after fields stay `null`.

3. Relative savings strength
- More savings => higher score.
- Higher cost => lower score.

## Scoring (simple)
### A) Normal comparison mode (both candidate and original are priceable)
Formula:

`score = clip(0.50 + savings_pct, 0.05, 0.95)`

Where:
- `savings_pct = (original_patient_pay - candidate_patient_pay) / original_patient_pay`

Meaning:
- same cost -> score near `0.50`
- cheaper candidate -> score above `0.50`
- more expensive candidate -> score below `0.50`

### B) Fallback scores (when comparison cannot be done)
- Candidate not covered: `0.10`
- Candidate has no valid price row: `0.30`
- Original unpriceable but candidate priceable: `0.85`
- Catastrophic phase (both effectively paid by plan): neutral `0.50`

## End-to-end workflow (Financial Agent)
1. Read claim and candidate.
2. Determine insurance phase using member YTD OOP (if member exists).
3. Price candidate drug for plan + date.
4. Price original drug for same plan + date.
5. Estimate patient pay for both using phase logic.
6. Compute savings and score.
7. Return a structured JSON result with notes and summary.

## What is sent to orchestrator
For each candidate, orchestrator uses mainly:
- `financial.score`
- financial response details for audit/explanation (`notes`, `summary`, `insurance_context`)

In orchestrator stage-2 scoring, candidate scores are combined like:
- `policy` score
- `clinical` score
- `financial` score (from this agent)
- `past` decisions score

Then orchestrator applies thresholds and weighted combination to decide auto-approve vs doctor review.

## Practical tip
Always pass `member_id` in production. Without it, the agent can still run, but phase tracking and after-fill accumulator values are approximate.
