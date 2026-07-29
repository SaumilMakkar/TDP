"""Prompt builder for Stage B bounded LLM review."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class StageBPromptBuilder:
    """Build Stage B prompt from skill guidance and structured evidence."""

    skill_path: Path

    def _load_skill_text(self) -> str:
        return self.skill_path.read_text(encoding="utf-8")

    @staticmethod
    def _serialize_payload(value: object) -> str:
        return json.dumps(value, indent=2, sort_keys=True, default=str)

    def build_prompt(
        self,
        *,
        patient: Mapping[str, object],
        candidate_drug: Mapping[str, object],
        stage_b_evidence: Mapping[str, object],
        base_score: float,
        confidence_level: str,
    ) -> str:
        skill_text = self._load_skill_text()
        confidence_payload = stage_b_evidence.get("confidence", {})
        llm_required = bool(confidence_payload.get("llm_required", True))
        confidence_score = float(confidence_payload.get("confidence_score", base_score))
        return (
            "You are a licensed pharmacist or clinical reviewer serving as the Stage B ambiguity resolver.\n\n"
            "Harness Contract:\n"
            f"{skill_text}\n\n"
            "Task:\n"
            "Review the evidence like you are a prescriber or pharmacist , advising on patient-specific medication safety.\n"
            "Explain why the candidate differs in safety suitability for this patient when evidence scores differ, and state the clinical meaning of that difference. Focus on the most important mismatches and why they matter for contraindication, interaction risk, organ-function suitability, or duplicate therapy.\n"
            "Explain why two evidence differ on a clinical safety level. Return a concise clinical judgment in 2-3 short sentences under 60 words. Avoid generic filler like 'clinically reasonable' or repeating the score value. Do not recompute similarity or alter weights.\n\n"
            f"Confidence Route: {confidence_level}\n"
            f"LLM Required: {str(bool(llm_required)).lower()}\n"
            f"Base Score: {float(base_score):.4f}\n"
            f"Confidence Score: {confidence_score:.4f}\n\n"
            "Patient Profile:\n"
            f"{self._serialize_payload(patient)}\n\n"
            "Candidate Drug:\n"
            f"{self._serialize_payload(candidate_drug)}\n\n"
            "Deterministic Evidence:\n"
            f"{self._serialize_payload(stage_b_evidence)}\n\n"
            "Return JSON with exactly these keys: adjustment, confidence, reasoning.\n"
            "Adjustment must be in [-0.10, 0.10]."
        )
