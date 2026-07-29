"""Clinical agent adapter for orchestrator Stage 1 candidate generation.

Primary behavior:
- Call the standalone clinical bundle pipeline under backend/clinical_agent
- Adapt ranked alternatives into orchestrator contract

Contract returned to orchestrator:
{
  "candidates": [
    {
      "drug_id": str,
      "drug_name": str,
      "clinical_score": float,
      "safe": bool,
      ...
    }
  ],
  "notes": str,
  "_pipeline": "clinical_bundle"
}
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger("pbm.clinical_agent_adapter")

# backend/app/agents/clinical_agent.py -> backend/clinical_agent
_BUNDLE_DIR = Path(__file__).resolve().parents[2] / "clinical_agent"


def _adapt_pipeline_output(pipeline_result: Dict[str, Any]) -> Dict[str, Any]:
    def _flag_is_escalation_true(value: Any) -> bool:
        """Parse safety flags conservatively for mandatory escalation.

        The clinical bundle may emit string severities (for example
        "none", "low", "moderate", "high"). A plain bool(value) would
        incorrectly treat any non-empty string as True.
        """
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value > 0
        if isinstance(value, str):
            norm = value.strip().lower()
            if norm in {"", "0", "false", "no", "none", "na", "n/a", "low", "moderate"}:
                return False
            return norm in {"1", "true", "yes", "y", "high", "severe", "critical", "required", "mandatory"}
        return False

    ranked = pipeline_result.get("ranked_alternatives") or []
    candidates: List[Dict[str, Any]] = []

    for alt in ranked:
        drug_id = str(alt.get("candidate_id") or "").strip()
        if not drug_id:
            continue

        stage_c = alt.get("stage_c") or {}
        composite_score = float(stage_c.get("composite_score") or 0.0)
        threshold_passed = bool(stage_c.get("threshold_passed", composite_score >= 0.50))
        if not threshold_passed:
            continue

        safety_flags = stage_c.get("safety_flags") or {}
        stage_b = alt.get("stage_b") or {}
        stage_a = alt.get("stage_a") or {}

        # Conservative safety signal for orchestrator gate.
        safe = not (
            _flag_is_escalation_true(safety_flags.get("cumulative_risk"))
            and _flag_is_escalation_true(safety_flags.get("clinical_ambiguity"))
        )
        if str(stage_b.get("status") or "").lower() in ("reject", "rejected"):
            safe = False

        reasoning_parts: List[str] = []
        if stage_b.get("reasoning"):
            reasoning_parts.append(str(stage_b.get("reasoning")))
        if stage_a.get("reasoning"):
            reasoning_parts.append(str(stage_a.get("reasoning")))

        candidates.append(
            {
                "drug_id": drug_id,
                "drug_name": alt.get("candidate_name") or "",
                "clinical_score": round(composite_score, 4),
                "safe": safe,
                "rationale": " | ".join(reasoning_parts) if reasoning_parts else None,
                "requires_mandatory_escalation": (
                    _flag_is_escalation_true(safety_flags.get("cumulative_risk"))
                    and _flag_is_escalation_true(safety_flags.get("clinical_ambiguity"))
                ),
                "stage_a_score": float(stage_a.get("score") or 0.0),
                "stage_b_score": float(stage_b.get("score") or 0.0),
                "composite_score": round(composite_score, 4),
            }
        )

    return {
        "candidates": candidates,
        "notes": f"Clinical bundle pipeline returned {len(candidates)} candidate(s).",
        "_pipeline": "clinical_bundle",
        "original_drug": pipeline_result.get("original_drug") or {},
    }


def _run_bundle_sync(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not _BUNDLE_DIR.exists():
        raise FileNotFoundError(f"Clinical bundle directory not found: {_BUNDLE_DIR}")

    bundle_path = str(_BUNDLE_DIR)
    if bundle_path not in sys.path:
        sys.path.insert(0, bundle_path)

    from clinical_agent_pipeline import run_clinical_agent_pipeline  # type: ignore

    prod_sk = payload.get("prod_sk") or payload.get("drug_id")
    member_id = payload.get("member_id") or payload.get("patient_id")
    if not prod_sk or not member_id:
        raise ValueError("Clinical agent requires prod_sk/drug_id and member_id.")

    pipeline_input: Dict[str, Any] = {
        "prod_sk": int(prod_sk),
        "member_id": str(member_id),
    }
    if payload.get("drug_name"):
        pipeline_input["drug_name"] = payload.get("drug_name")

    result = run_clinical_agent_pipeline(pipeline_input)
    if not isinstance(result, dict):
        raise RuntimeError("Clinical bundle returned unexpected payload type.")
    return _adapt_pipeline_output(result)


async def clinical_agent(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Run the clinical bundle and return orchestrator-compatible candidates.

    Raises on hard failures so orchestrator can execute its lookup fallback path.
    """
    loop = asyncio.get_event_loop()
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return await loop.run_in_executor(pool, lambda: _run_bundle_sync(payload))
