"""Phase 3 of Stage C: additional informational safety flags for provider visibility.

Verified Stage B integration notes:
- Enriched per-alternative Stage B output stores `stage_b_llm_required: bool` and
  `stage_b_evidence` on `from_stage_a.alternatives`, while the compact public
  `alternatives` list exposes `llm_required: bool` and summary evidence only.
- Stage B evidence is a nested object, not a list of strings. Cumulative-risk logic
  therefore counts mild/moderate concern categories from the real nested fields.
- Stage B already consumes age, condition, contraindication, interaction,
  renal/hepatic, and duplicate-therapy signals in `aggregate_stage_b_score`; Phase 3
  only re-surfaces them for provider visibility and does not mutate any score.
- Stage B's private renal/hepatic helper only returns a subset of lab columns, so
  Phase 3 reuses the same Stage B lab table to expose the full row needed for the
  missing-data flag instead of inventing a new lab source.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any, Mapping

from stage_b.evidence.renal_hepatic_engine import PATIENT_LABS_DF
from stage_b.normalization.patient_normalizer import _split_multi_value

from .models import StageCCandidate, StageCFlags


POLYPHARMACY_THRESHOLD = 5
CUMULATIVE_RISK_THRESHOLD = 3
REQUIRED_LAB_FIELDS = (
    "eGFR",
    "CrCl",
    "Creatinine",
    "AST",
    "ALT",
    "Bilirubin",
    "Child_Pugh",
)
MILD_MODERATE_SEVERITIES = {"LOW", "MINOR", "MODERATE"}


def _is_missing(value: object) -> bool:
    return value is None or str(value).strip() == ""


def _to_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if is_dataclass(value):
        return asdict(value)
    if value is None:
        return {}
    data = getattr(value, "__dict__", None)
    if isinstance(data, dict):
        return dict(data)
    return {}


def _current_medications_value(member: Any) -> str | list[str] | None:
    member_payload = _to_mapping(member)
    if member_payload:
        for key in ("CURRENT_MEDICATIONS", "current_medications"):
            if key in member_payload:
                return member_payload[key]

    for attr in ("CURRENT_MEDICATIONS", "current_medications"):
        if hasattr(member, attr):
            return getattr(member, attr)
    return None


def _normalize_medications(current_medications: str | list[str] | None) -> list[str]:
    if current_medications is None:
        return []
    if isinstance(current_medications, list):
        return [str(item).strip() for item in current_medications if str(item).strip()]
    return _split_multi_value(current_medications)


def load_stage_b_patient_labs(member: Any) -> dict[str, Any]:
    """Load the full Stage B patient-lab row for a member using the existing Stage B table."""

    member_payload = _to_mapping(member)
    raw_mbr_sk = member_payload.get("mbr_sk", member_payload.get("MBR_SK"))
    if raw_mbr_sk is None and hasattr(member, "mbr_sk"):
        raw_mbr_sk = getattr(member, "mbr_sk")
    if raw_mbr_sk is None:
        return {}

    try:
        mbr_sk = int(raw_mbr_sk)
    except (TypeError, ValueError):
        return {}

    if PATIENT_LABS_DF.empty:
        return {}

    matches = PATIENT_LABS_DF[PATIENT_LABS_DF["MBR_SK"].astype("Int64") == mbr_sk]
    if matches.empty:
        return {}

    row = matches.iloc[0]
    return {field: (None if _is_missing(row.get(field)) else row.get(field)) for field in REQUIRED_LAB_FIELDS}


def evaluate_polypharmacy(current_medications: str | list[str] | None) -> bool:
    """Why: highlight heavy existing medication burden even though Stage B focuses on interactions."""

    medications = _normalize_medications(current_medications)
    return len(medications) >= POLYPHARMACY_THRESHOLD


def evaluate_missing_clinical_data(patient_labs: Mapping[str, Any] | None) -> bool:
    """Why: inform the provider when renal/hepatic support data is incomplete."""

    labs = dict(patient_labs or {})
    for field in REQUIRED_LAB_FIELDS:
        aliases = {field}
        if field == "eGFR":
            aliases.add("egfr")
        elif field == "CrCl":
            aliases.add("crcl")
        elif field == "Child_Pugh":
            aliases.add("child_pugh")

        if not any(alias in labs and not _is_missing(labs.get(alias)) for alias in aliases):
            return True
    return False


def evaluate_clinical_ambiguity(stage_a_llm_required: bool | None, stage_b_llm_required: bool | None) -> bool:
    """Why: surface that either upstream stage required LLM review and was not fully deterministic."""

    return bool(stage_a_llm_required) or bool(stage_b_llm_required)


def _count_cumulative_concerns(stage_b_evidence: Mapping[str, Any] | None) -> int:
    evidence = dict(stage_b_evidence or {})
    concern_count = 0

    allergy = evidence.get("allergy", {})
    if isinstance(allergy, Mapping) and str(allergy.get("severity", "")).strip().upper() in MILD_MODERATE_SEVERITIES:
        concern_count += 1

    age = evidence.get("age", {})
    if isinstance(age, Mapping) and str(age.get("risk_band", "")).strip().lower() == "moderate":
        concern_count += 1

    condition = evidence.get("condition", {})
    if isinstance(condition, Mapping):
        condition_reason = str(condition.get("reason", "")).strip().lower()
        if condition_reason in {"condition_class_partial_alignment", "condition_weak_class_alignment"}:
            concern_count += 1

    interaction = evidence.get("interaction", {})
    if isinstance(interaction, Mapping) and str(interaction.get("interaction_severity", "")).strip().upper() in {
        "MINOR",
        "MODERATE",
    }:
        concern_count += 1

    contraindication = evidence.get("contraindication", {})
    if isinstance(contraindication, Mapping) and str(contraindication.get("severity", "")).strip().upper() in {
        "MINOR",
        "MODERATE",
    }:
        concern_count += 1

    renal_hepatic = evidence.get("renal_hepatic", {})
    if isinstance(renal_hepatic, Mapping) and str(renal_hepatic.get("severity", "")).strip().upper() in {
        "MINOR",
        "MODERATE",
    }:
        concern_count += 1

    duplicate_therapy = evidence.get("duplicate_therapy", {})
    if isinstance(duplicate_therapy, Mapping) and str(duplicate_therapy.get("severity", "")).strip().upper() in {
        "MINOR",
        "MODERATE",
    }:
        concern_count += 1

    return concern_count


def evaluate_cumulative_risk(stage_b_evidence: Mapping[str, Any] | None) -> bool:
    """Why: bundle several individually acceptable mild or moderate concerns into one review signal."""

    return _count_cumulative_concerns(stage_b_evidence) >= CUMULATIVE_RISK_THRESHOLD


def evaluate_safety_flags(
    candidate: StageCCandidate,
    member: Any,
    patient_labs: Mapping[str, Any] | None,
    stage_b_evidence: Mapping[str, Any] | None,
) -> StageCFlags:
    """Evaluate independent informational flags for a packaged Stage C candidate."""

    current_medications = _current_medications_value(member)
    flags = StageCFlags(
        polypharmacy=evaluate_polypharmacy(current_medications),
        missing_clinical_data=evaluate_missing_clinical_data(patient_labs),
        clinical_ambiguity=evaluate_clinical_ambiguity(
            candidate.stage_a_llm_required,
            candidate.stage_b_llm_required,
        ),
        cumulative_risk=evaluate_cumulative_risk(stage_b_evidence),
    )
    candidate.stage_c_flags = flags
    return flags