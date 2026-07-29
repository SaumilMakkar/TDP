"""Phase 7 of Stage C: build provider-facing rationale lists from existing evidence."""

from __future__ import annotations

from collections.abc import Mapping

from .models import StageCCandidate


STAGE_A_EVIDENCE_LABELS = {
    "ingredient": "Ingredient similarity",
    "moiety": "Moiety similarity",
    "class": "Therapeutic class similarity",
    "moa": "Mechanism-of-action similarity",
    "combo": "Combination-therapy similarity",
    "route": "Same route of administration",
    "form": "Same dosage form",
    "strength": "Strength alignment",
}

STAGE_B_REASON_LABELS = {
    "condition_class_alignment": "Strong condition alignment identified",
    "condition_class_partial_alignment": "Partial condition alignment identified",
    "condition_weak_class_alignment": "Weak condition alignment noted",
    "insufficient_specific_condition_signal": "Condition support remains limited",
    "contraindication_condition_overlap": "Condition overlap requires caution",
}

FLAG_LABELS = {
    "polypharmacy": "Polypharmacy warning",
    "missing_clinical_data": "Clinical data incomplete",
    "clinical_ambiguity": "Clinical ambiguity required LLM review",
    "cumulative_risk": "Cumulative mild-to-moderate risk signal identified",
}

_SEVERITY_RANK = {
    None: 0,
    "NONE": 0,
    "LOW": 1,
    "MINOR": 1,
    "MODERATE": 2,
    "MAJOR": 3,
    "HIGH": 3,
    "CONTRAINDICATED": 4,
}


def _humanize_stage_a_findings(stage_a_evidence: Mapping[str, object]) -> list[str]:
    scored_findings: list[tuple[float, str]] = []
    for key, raw_value in stage_a_evidence.items():
        try:
            score = float(raw_value)
        except (TypeError, ValueError):
            continue
        if score <= 0.0:
            continue
        label = STAGE_A_EVIDENCE_LABELS.get(str(key), f"{key} similarity")
        scored_findings.append((-score, label))

    scored_findings.sort(key=lambda item: (item[0], item[1]))
    return [label for _, label in scored_findings]


def _humanize_stage_b_findings(stage_b_evidence: Mapping[str, object]) -> list[str]:
    findings: list[tuple[int, float, str]] = []

    allergy = stage_b_evidence.get("allergy")
    if isinstance(allergy, Mapping):
        allergy_risk = float(allergy.get("allergy_risk", 0.0) or 0.0)
        severity = str(allergy.get("severity", "")).strip().upper() or None
        if allergy_risk <= 0.0:
            findings.append((0, -1.0, "No allergy conflicts identified"))
        elif severity is not None:
            findings.append((_SEVERITY_RANK.get(severity, 1), -allergy_risk, f"Allergy risk identified ({severity.lower()})"))

    contraindication = stage_b_evidence.get("contraindication")
    if isinstance(contraindication, Mapping):
        severity = str(contraindication.get("severity", "")).strip().upper() or None
        if bool(contraindication.get("contraindication")):
            findings.append((_SEVERITY_RANK.get(severity, 1), -1.0, f"Contraindication identified ({str(severity or 'unknown').lower()})"))
        else:
            findings.append((0, -1.0, "No contraindications identified"))

    interaction = stage_b_evidence.get("interaction")
    if isinstance(interaction, Mapping):
        interaction_detected = bool(interaction.get("interaction_detected"))
        interaction_severity = str(interaction.get("interaction_severity", "")).strip().upper() or None
        interaction_score = float(interaction.get("interaction_score", 0.0) or 0.0)
        if not interaction_detected:
            findings.append((0, -1.0, "No drug interaction identified"))
        else:
            findings.append((_SEVERITY_RANK.get(interaction_severity, 1), -interaction_score, f"Drug interaction risk identified ({str(interaction_severity or 'unknown').lower()})"))

    renal_hepatic = stage_b_evidence.get("renal_hepatic")
    if isinstance(renal_hepatic, Mapping):
        severity = str(renal_hepatic.get("severity", "")).strip().upper() or None
        score = float(renal_hepatic.get("score", 0.0) or 0.0)
        if severity in {None, "NONE"} and score >= 1.0:
            findings.append((0, -1.0, "No renal or hepatic adjustment identified"))
        elif severity is not None:
            findings.append((_SEVERITY_RANK.get(severity, 1), -score, f"Renal/hepatic consideration identified ({severity.lower()})"))

    duplicate_therapy = stage_b_evidence.get("duplicate_therapy")
    if isinstance(duplicate_therapy, Mapping):
        severity = str(duplicate_therapy.get("severity", "")).strip().upper() or None
        score = float(duplicate_therapy.get("score", 0.0) or 0.0)
        if severity in {None, "NONE"} and score >= 1.0:
            findings.append((0, -1.0, "No duplicate therapy signal identified"))
        elif severity is not None:
            findings.append((_SEVERITY_RANK.get(severity, 1), -score, f"Duplicate therapy consideration identified ({severity.lower()})"))

    condition = stage_b_evidence.get("condition")
    if isinstance(condition, Mapping):
        condition_match = float(condition.get("condition_match", 0.0) or 0.0)
        condition_reason = str(condition.get("reason", "")).strip().lower()
        label = STAGE_B_REASON_LABELS.get(condition_reason)
        if label is not None:
            findings.append((0 if condition_match >= 0.75 else 1, -condition_match, label))

    findings.sort(key=lambda item: (item[0], item[1], item[2]))
    return [label for _, _, label in findings]


def _humanize_flag_findings(candidate: StageCCandidate) -> list[str]:
    if candidate.stage_c_flags is None:
        return []

    findings: list[str] = []
    for field_name, label in FLAG_LABELS.items():
        if bool(getattr(candidate.stage_c_flags, field_name)):
            findings.append(label)
    return findings


def build_clinical_rationale(candidate: StageCCandidate) -> list[str]:
    """Build a provider-facing rationale list from Stage A, Stage B, and Stage C flags."""

    rationale: list[str] = []
    rationale.extend(_humanize_stage_a_findings(candidate.stage_a_evidence))
    rationale.extend(_humanize_stage_b_findings(candidate.stage_b_evidence))
    rationale.extend(_humanize_flag_findings(candidate))

    candidate.clinical_rationale = rationale
    return list(candidate.clinical_rationale)
