"""Stage A ambiguity resolver service for optional LLM reasoning."""

from __future__ import annotations

import asyncio
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping

from app.llm.llm import call_llm
from stage_a.llm.stage_a_prompt_builder import StageAPromptBuilder


LLMCaller = Callable[[str], Awaitable[str]]

_SKILL_VERSION_FILES = {
    "default": "stage_a_skill.md",
    "v1": "stage_a_skill_v1.md",
    "v2": "stage_a_skill_v2.md",
}


def _run_async_blocking(coro: Any) -> Any:
    """Run a coroutine from sync code, even when an event loop is already running."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(asyncio.run, coro)
        return future.result()


def _default_skill_path() -> Path:
    return Path(__file__).resolve().parent / "stage_a_skill.md"


def _skill_path_for_version(skill_version: str | None) -> Path:
    version = (skill_version or "").strip().lower()
    if not version:
        version = os.getenv("STAGE_A_SKILL_VERSION", "default").strip().lower() or "default"

    filename = _SKILL_VERSION_FILES.get(version)
    if filename is None:
        allowed = ", ".join(sorted(_SKILL_VERSION_FILES.keys()))
        raise ValueError(f"Unsupported Stage A skill version '{skill_version}'. Allowed: {allowed}.")
    return Path(__file__).resolve().parent / filename


def _parse_reasoning(raw_response: object) -> str:
    if raw_response is None:
        return ""
    if isinstance(raw_response, dict):
        reasoning = raw_response.get("reasoning")
        return str(reasoning).strip() if reasoning is not None else ""

    text = str(raw_response).strip()
    if not text:
        return ""

    try:
        payload = json.loads(text)
        if isinstance(payload, dict):
            reasoning = payload.get("reasoning")
            return str(reasoning).strip() if reasoning is not None else text
    except Exception:
        pass

    return text


def _compact_reasoning(reasoning: str, max_words: int = 60) -> str:
    text = " ".join(reasoning.strip().split())
    if not text:
        return ""

    sentences = [segment.strip() for segment in re.split(r"(?<=[.!?])\s+", text.replace("\n", " ")) if segment.strip()]
    if sentences:
        text = " ".join(sentences[:2]).strip()
        if text and text[-1] not in ".!?":
            text += "."

    words = text.split()
    if len(words) > max_words:
        text = " ".join(words[:max_words]).rstrip(".,;:") + "..."
    return text


@dataclass
class AmbiguityResolver:
    """Resolve low-confidence Stage A cases using the LLM for reasoning only."""

    prompt_builder: StageAPromptBuilder
    llm_caller: LLMCaller = call_llm

    async def resolve(
        self,
        *,
        original_drug: Mapping[str, object],
        candidate_drug: Mapping[str, object],
        evidence: Mapping[str, float],
        base_score: float,
        confidence_score: float,
        llm_required: bool,
        confidence_level: str,
    ) -> dict[str, Any]:
        if not llm_required:
            return {"reasoning": ""}

        prompt = self.prompt_builder.build_prompt(
            original_drug=original_drug,
            candidate_drug=candidate_drug,
            evidence=evidence,
            base_score=base_score,
            confidence_score=confidence_score,
            llm_required=llm_required,
            confidence_level=confidence_level,
        )

        raw_response = await self.llm_caller(
            prompt,
            response_format={"type": "json_object"},
            temperature=0,
        )
        reasoning = _compact_reasoning(_parse_reasoning(raw_response))
        return {"reasoning": reasoning}

    def resolve_sync(self, **kwargs: Any) -> dict[str, Any]:
        return _run_async_blocking(self.resolve(**kwargs))


def build_default_stage_a_resolver(
    *,
    skill_version: str | None = None,
    skill_path: Path | None = None,
) -> AmbiguityResolver:
    resolved_skill_path = skill_path or _skill_path_for_version(skill_version)
    return AmbiguityResolver(prompt_builder=StageAPromptBuilder(skill_path=resolved_skill_path))
