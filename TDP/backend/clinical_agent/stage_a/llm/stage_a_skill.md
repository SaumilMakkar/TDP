# Stage A Skill

## Purpose

Stage A compares an input drug against formulary alternatives and returns a deterministic therapeutic similarity assessment.

## Existing Outputs

Stage A already computes and emits outputs from prior sprints:

- Sprints 1-2: candidate retrieval and normalized drug objects.
- Sprint 3: RxNorm-backed normalization for ingredient, active moiety, route, and dosage form.
- Sprint 4: per-criterion evidence extraction.
- Sprint 5: deterministic scoring for ingredient, moiety, class, moa, combo, route, form, and strength.
- Sprint 6: AHP-derived weights and weighted base similarity score.
- Sprint 7: confidence routing with llm_required flag.

## Deterministic Evidence

The LLM must not recompute similarity. It only receives already-computed evidence:

- ingredient
- moiety
- class
- moa
- combo
- route
- form
- strength
- base_score
- confidence score

## AHP Scoring Methodology

Stage A derives criterion weights from a pairwise comparison matrix using the principal eigenvector. The final base similarity score is computed as:

score = sum(weight * criterion_score)

## Confidence Routing Logic

- High confidence: same ingredient or same moiety.
- Low confidence: same class with different ingredient or moiety.
- Borderline cases: use deterministic thresholds to decide whether the LLM should explain ambiguity.

## Allowed Score Adjustments

The LLM must not recalculate or override similarity.

Allowed behavior:

- explain why the evidence supports or weakens the current score
- describe ambiguity in clinical terms
- summarize whether the deterministic score is clinically reasonable

Not allowed:

- recomputing similarity from scratch
- changing criterion weights
- inventing new evidence

## Output Schema

The LLM must return JSON with a single field:

{
  "reasoning": "..."
}

## Harness Requirements

- Use structured prompt sections.
- Include original drug, candidate drug, deterministic evidence, AHP base score, and confidence score.
- Keep the prompt concise and clinical.
- Treat this file as the active harness contract for Stage A.
