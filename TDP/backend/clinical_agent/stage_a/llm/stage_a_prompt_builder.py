"""Prompt builder for the Stage A ambiguity resolver harness."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class StageAPromptBuilder:
    """Build the Stage A prompt from skill guidance and structured evidence."""

    skill_path: Path

    def _load_skill_text(self) -> str:
        return self.skill_path.read_text(encoding="utf-8")

    @staticmethod
    def _serialize_payload(value: object) -> str:
        return json.dumps(value, indent=2, sort_keys=True, default=str)

    def build_prompt(
        self,
        *,
        original_drug: Mapping[str, object],
        candidate_drug: Mapping[str, object],
        evidence: Mapping[str, float],
        base_score: float,
        confidence_score: float,
        llm_required: bool,
        confidence_level: str,
    ) -> str:
        skill_text = self._load_skill_text()

        return (
            "You are a licensed pharmacist or clinical reviewer serving as the Stage A ambiguity resolver.\n\n"
            "Harness Contract:\n"
            f"{skill_text}\n\n"
            "Task:\n"
            "Review the evidence like you are a prescriber or pharmacist , advising on therapeutic substitutability.\n"
            "Explain why the candidate differs from the original when evidence scores differ, and state the clinical meaning of that difference. Focus on the most important mismatches and why they matter for mechanism, indication, or interchangeability.\n"
            "Explain why two evidence differ on a clinical level. Return a concise clinical judgment in 2-3 short sentences under 60 words. Avoid generic filler like 'clinically reasonable' or repeating the score value. Do not recompute similarity or alter weights.\n\n"
            f"Confidence Route: {confidence_level}\n"
            f"LLM Required: {str(bool(llm_required)).lower()}\n"
            f"Base Score: {base_score:.4f}\n"
            f"Confidence Score: {confidence_score:.4f}\n\n"
            "Original Drug:\n"
            f"{self._serialize_payload(original_drug)}\n\n"
            "Candidate Drug:\n"
            f"{self._serialize_payload(candidate_drug)}\n\n"
            "Deterministic Evidence:\n"
            f"{self._serialize_payload(evidence)}\n\n"
            "Return JSON with exactly one key: reasoning."
        )
