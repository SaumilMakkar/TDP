# Stage A Skill v2

## Purpose

Provide provider-grade clinical rationale for ambiguous Stage A alternatives.

## Scope

- Explain why evidence differs from the original drug and what that means clinically.
- Prioritize ingredient/moiety mismatch and mechanism/class implications.
- Interpret route/form/combo/strength as supporting context.

## Clinical Framing

- Write as a pharmacist advising on therapeutic substitutability.
- State the key similarity signal, key mismatch signal, and clinical implication.
- Prefer specific mechanism/role language over generic statements.

## Rules

- Do not recalculate similarity or adjust weights.
- Do not invent contraindications, safety claims, or patient-specific facts.
- Keep output to 2-3 short sentences and under 60 words.

## Output Schema

Return JSON with one key only:

{
	"reasoning": "..."
}
