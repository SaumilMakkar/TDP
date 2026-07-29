"""Stage B LLM ambiguity resolver for bounded score adjustments (Sprint B10)."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping

from app.llm.llm import call_llm
from stage_b.llm.stage_b_prompt_builder import StageBPromptBuilder


LLMCaller = Callable[[str], Awaitable[str | None]]


def _default_skill_path() -> Path:
    return Path(__file__).resolve().parent / "stage_b_skill.md"


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _parse_response(raw_response: object) -> dict[str, object]:
    if raw_response is None:
        return {"adjustment": 0.0, "confidence": 0.0, "reasoning": ""}

    if isinstance(raw_response, dict):
        payload = raw_response
    else:
        text = str(raw_response).strip()
        if not text:
            return {"adjustment": 0.0, "confidence": 0.0, "reasoning": ""}
        try:
            maybe_json = json.loads(text)
            payload = maybe_json if isinstance(maybe_json, dict) else {}
        except Exception:
            return {"adjustment": 0.0, "confidence": 0.0, "reasoning": text}

    return {
        "adjustment": _safe_float(payload.get("adjustment"), 0.0),
        "confidence": _safe_float(payload.get("confidence"), 0.0),
        "reasoning": str(payload.get("reasoning", "") or "").strip(),
    }


@dataclass
class StageBAmbiguityResolver:
    """Resolve Stage B borderline cases with bounded LLM adjustment."""

    prompt_builder: StageBPromptBuilder
    llm_caller: LLMCaller = call_llm

    async def resolve(
        self,
        *,
        patient: Mapping[str, object],
        candidate_drug: Mapping[str, object],
        stage_b_evidence: Mapping[str, object],
        base_score: float,
        confidence_level: str,
    ) -> dict[str, object]:
        prompt = self.prompt_builder.build_prompt(
            patient=patient,
            candidate_drug=candidate_drug,
            stage_b_evidence=stage_b_evidence,
            base_score=base_score,
            confidence_level=confidence_level,
        )
        raw_response = await self.llm_caller(
            prompt,
            response_format={"type": "json_object"},
        )
        return _parse_response(raw_response)

    def resolve_sync(self, **kwargs: Any) -> dict[str, object]:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None and loop.is_running():
            import concurrent.futures

            def _run_in_thread() -> dict[str, object]:
                coro = self.resolve(**kwargs)
                try:
                    return asyncio.run(coro)
                except Exception:
                    coro.close()
                    raise

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                return executor.submit(_run_in_thread).result()

        coro = self.resolve(**kwargs)
        try:
            return asyncio.run(coro)
        except Exception:
            coro.close()
            raise


def build_default_stage_b_resolver(skill_path: Path | None = None) -> StageBAmbiguityResolver:
    resolved_skill_path = skill_path or _default_skill_path()
    return StageBAmbiguityResolver(prompt_builder=StageBPromptBuilder(skill_path=resolved_skill_path))
