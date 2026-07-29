"""Shared models used by the Stage C pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


CandidateId = int | str
EvidenceMap = dict[str, Any]


@dataclass(slots=True)
class StageCFlags:
    """Informational provider-facing safety flags that do not alter Stage B scoring."""

    polypharmacy: bool
    missing_clinical_data: bool
    clinical_ambiguity: bool
    cumulative_risk: bool


@dataclass(slots=True)
class StageCCandidate:
    """Packaged candidate payload forwarded from Stages A and B into Stage C."""

    candidate_id: CandidateId
    stage_a_score: float | None
    stage_a_evidence: EvidenceMap
    stage_a_llm_required: bool | None
    stage_a_reasoning: str
    stage_b_score: float | None
    stage_b_evidence: EvidenceMap
    stage_b_llm_required: bool | None
    stage_b_decision: str
    candidate_name: str = ""
    stage_b_reasoning: str = ""
    composite_score: float | None = None
    threshold_passed: bool | None = None
    stage_c_flags: StageCFlags | None = None
    rank: int | None = None
    clinical_rationale: list[str] = field(default_factory=list)
