from __future__ import annotations

# ===== models.py =====

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class OrchestratorInput:
    request_id: str
    payload: dict[str, Any]
    runtime_options: dict[str, Any] = field(default_factory=dict)


@dataclass
class PhaseResult:
    name: str
    status: str
    data: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


@dataclass
class OrchestratorOutput:
    request_id: str
    status: str
    phase_results: list[PhaseResult]
    final_payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

# ===== config.py =====

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class OrchestratorConfig:
    name: str
    log_level: str
    output_dir: str
    debug: bool
    policy_threshold: float
    clinical_threshold: float
    financial_threshold: float
    past_decision_threshold: float
    overall_threshold: float
    policy_weight: float
    financial_weight: float
    past_decision_weight: float
    score_fusion_weight: float
    borda_weight: float
    clinical_ambiguity_penalty: float
    cumulative_risk_penalty: float
    polypharmacy_penalty: float
    auto_accept_threshold: float
    llm_governance_review_threshold: float
    provider_review_threshold: float



def _to_bool(value: str, default: bool = False) -> bool:
    normalized = (value or "").strip().lower()
    if not normalized:
        return default
    return normalized in {"1", "true", "yes", "y", "on"}


def _resolve_output_dir(output_dir: str | os.PathLike[str] | None = None) -> Path:
    candidate = Path(output_dir or "outputs").expanduser()
    if not candidate.is_absolute():
        candidate = Path(__file__).resolve().parent / candidate
    return candidate



def load_config() -> OrchestratorConfig:
    return OrchestratorConfig(
        name=os.getenv("ORCHESTRATOR_NAME", "pbm-orchestrator"),
        log_level=os.getenv("ORCHESTRATOR_LOG_LEVEL", "INFO"),
        output_dir=str(_resolve_output_dir(os.getenv("ORCHESTRATOR_OUTPUT_DIR", "outputs"))),
        debug=_to_bool(os.getenv("ORCHESTRATOR_DEBUG", "false")),
        policy_threshold=0.70,
        clinical_threshold=0.65,
        financial_threshold=0.60,
        past_decision_threshold=0.50,
        overall_threshold=0.80,
        policy_weight=0.35,
        financial_weight=0.30,
        past_decision_weight=0.35,
        score_fusion_weight=0.70,
        borda_weight=0.30,
        clinical_ambiguity_penalty=-0.05,
        cumulative_risk_penalty=-0.05,
        polypharmacy_penalty=-0.03,
        llm_governance_review_threshold=0.70,
        auto_accept_threshold=0.80,
        provider_review_threshold=0.50,
    )

# ===== clinical_agent_client.py =====

import json
from pathlib import Path
from typing import Any


class ClinicalAgentClient:
    """Adapter for clinical-agent interaction.

    Current implementation loads a clinical-agent response JSON from disk.
    This keeps orchestration flow complete while allowing a later swap to API/SDK calls.
    """

    def get_ranked_alternatives(
        self,
        member_id: str,
        medication: dict[str, Any],
        output_json_path: str,
    ) -> dict[str, Any]:
        response_path = Path(output_json_path)
        if not response_path.exists():
            raise FileNotFoundError(f"Clinical agent output file not found: {response_path}")

        response = json.loads(response_path.read_text(encoding="utf-8"))
        ranked_alternatives = response.get("ranked_alternatives", [])
        if not isinstance(ranked_alternatives, list):
            raise ValueError("Clinical agent output must contain ranked_alternatives as a list.")

        return {
            "request_sent": {
                "member_id": member_id,
                "medication": {
                    "drug_id": medication.get("drug_id"),
                    "drug_name": medication.get("drug_name"),
                },
            },
            "response": response,
        }

# ===== downstream_agent_clients.py =====

import json
from pathlib import Path
from typing import Any


class BaseAgentClient:
    agent_name = "base"

    def evaluate(self, request: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError


class FileBackedOrMockAgentClient(BaseAgentClient):
    def __init__(self, response_dir: str | None = None) -> None:
        self.response_dir = Path(response_dir) if response_dir else None
        self.inline_response_payload: dict[str, Any] | None = None
        self.inline_response_payloads: dict[str, Any] | None = None

    def evaluate(self, request: dict[str, Any]) -> dict[str, Any]:
        inline_response = self._load_inline_response(request)
        if inline_response is not None:
            return inline_response

        file_response = self._load_file_response(request)
        if file_response is not None:
            return file_response
        return self._build_mock_response(request)

    def _load_inline_response(self, request: dict[str, Any]) -> dict[str, Any] | None:
        if isinstance(self.inline_response_payloads, dict):
            alternative = self._request_alternative_id(request)
            if alternative is not None:
                for key in (str(alternative), alternative):
                    if key in self.inline_response_payloads:
                        return json.loads(json.dumps(self.inline_response_payloads[key]))

        if self.inline_response_payload is None:
            return None

        return json.loads(json.dumps(self.inline_response_payload))

    def _request_alternative_id(self, request: dict[str, Any]) -> Any:
        alternative = request.get("alternative", {})
        if isinstance(alternative, dict):
            return alternative.get("drug_id")
        return None

    def _load_file_response(self, request: dict[str, Any]) -> dict[str, Any] | None:
        if self.response_dir is None:
            return None

        alternative = request.get("alternative", {})
        alternative_id = alternative.get("drug_id")
        if alternative_id is None:
            return None

        response_path = self.response_dir / f"{alternative_id}.json"
        if not response_path.exists():
            return None

        return json.loads(response_path.read_text(encoding="utf-8"))

    def _build_mock_response(self, request: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError


class PolicyAgentClient(FileBackedOrMockAgentClient):
    agent_name = "policy"

    def _build_mock_response(self, request: dict[str, Any]) -> dict[str, Any]:
        from app.agents.policy_agent import _evaluate as policy_evaluate
        from app.tools.lookups import resolve_formulary

        plan_id = str(request.get("plan_id") or "")
        member_id = str(request.get("member_id") or "")
        fill_date = request.get("fill_date")
        alternative = request.get("alternative", {})
        original_drug = request.get("original_drug", {})

        result = dict(policy_evaluate({
            "drug_id": alternative.get("drug_id"),
            "plan_id": plan_id,
            "member_id": member_id,
            "quantity": request.get("quantity"),
            "fill_date": fill_date,
        }))

        original_formulary = resolve_formulary(plan_id, original_drug.get("drug_id"), fill_date).get("status") or {}
        alternative_formulary = resolve_formulary(plan_id, alternative.get("drug_id"), fill_date).get("status") or {}

        def _label(row: dict[str, Any]) -> str:
            if not isinstance(row, dict):
                return ""
            return str(
                row.get("PLN_DRG_STAT_DESC")
                or row.get("PLN_DRG_STAT_CD")
                or row.get("FORMULARY_TIER")
                or ""
            ).strip()

        result["original_status"] = _label(original_formulary) or ("Covered" if result.get("covered") else "Not Covered")
        alt_label = _label(alternative_formulary)
        if not alt_label:
            alt_label = "Covered" if bool(result.get("covered", False)) else "Not Covered"
        result["alternative_status"] = alt_label
        result["coverage_status"] = "covered" if bool(result.get("covered", False)) else "not_covered"
        result["policy_notes"] = str(result.get("notes", ""))
        return result


class FinancialAgentClient(FileBackedOrMockAgentClient):
    agent_name = "financial"

    def _build_mock_response(self, request: dict[str, Any]) -> dict[str, Any]:
        from app.agents.financial_agent import _evaluate as financial_evaluate
        from app.tools.lookups import resolve_formulary

        plan_id = str(request.get("plan_id") or "")
        member_id = str(request.get("member_id") or "")
        fill_date = request.get("fill_date")
        original_drug = request.get("original_drug", {})
        alternative = request.get("alternative", {})

        result = dict(financial_evaluate({
            "drug_id": alternative.get("drug_id"),
            "plan_id": plan_id,
            "member_id": member_id,
            "fill_date": fill_date,
            "original_drug_id": original_drug.get("drug_id"),
            "days_supply": request.get("days_supply"),
            "frequency": request.get("frequency"),
        }))

        original_formulary = resolve_formulary(plan_id, original_drug.get("drug_id"), fill_date).get("status") or {}
        alternative_formulary = resolve_formulary(plan_id, alternative.get("drug_id"), fill_date).get("status") or {}

        def _tier(row: dict[str, Any]) -> str:
            if not isinstance(row, dict):
                return ""
            return str(row.get("FORMULARY_TIER") or "").strip()

        result["original_tier"] = _tier(original_formulary)
        result["alternative_tier"] = _tier(alternative_formulary) or str(result.get("tier", ""))
        
        # Use annual costs if available, otherwise fall back to per-fill
        cand_total_cost = _safe_float(result.get("annual_final_cost"), 0.0) or _safe_float(result.get("final_cost"), 0.0)
        cand_patient_pay = _safe_float(result.get("annual_patient_pay"), 0.0) or _safe_float(result.get("estimated_patient_pay"), 0.0)
        orig_total_cost = _safe_float(result.get("original_annual_final_cost"), 0.0) or _safe_float(result.get("original_final_cost"), 0.0)
        orig_patient_pay = _safe_float(result.get("original_annual_patient_pay"), 0.0) or _safe_float(result.get("original_patient_pay"), 0.0)
        
        result["original_plan_paid"] = round(orig_total_cost - orig_patient_pay, 2)
        result["alternative_plan_paid"] = round(cand_total_cost - cand_patient_pay, 2)
        result["summary"] = {
            "decision": result.get("summary", {}).get("decision", "cheaper" if _safe_float(result.get("estimated_savings"), 0.0) > 0 else "same_cost"),
            "reason": result.get("notes", ""),
            "score": result.get("score"),
            "estimated_savings": result.get("estimated_savings"),
            "candidate_patient_pay": cand_patient_pay,
            "original_patient_pay": orig_patient_pay,
        }
        return result


class PastDecisionAgentClient(FileBackedOrMockAgentClient):
    agent_name = "past_decision"

    def _build_mock_response(self, request: dict[str, Any]) -> dict[str, Any]:
        rank = int(request.get("clinical_rank", 1))
        base_score = round(max(0.4, 0.91 - ((rank - 1) * 0.05)), 4)
        historical_score = round(max(0.35, base_score - 0.02), 4)
        adjustment_score = round(0.08 - ((rank - 1) * 0.01), 4)
        original_drug = request.get("original_drug", {})
        alternative = request.get("alternative", {})
        diagnosis_code = request.get("diagnosis_code", "")

        top_case_score = round(min(1.0, base_score + 0.09), 4)
        case_score = round(min(1.0, base_score + 0.05), 4)

        return {
            "average_confidence_score": base_score,
            "final_score": base_score,
            "historical_score": historical_score,
            "rule_based_patient_adjustment_score": adjustment_score,
            "final_statement": (
                f"Mock historical evidence supports {alternative.get('drug_name', 'the alternative')} "
                f"for diagnosis {diagnosis_code} with consistent positive prior outcomes."
            ),
            "top_cases": [
                {
                    "rank": 1,
                    "case_id": f"MOCKCASE{alternative.get('drug_id', '0000')}",
                    "claim_id": f"MOCKCLM{alternative.get('drug_id', '0000')}",
                    "date": "7/20/2026",
                    "decision": "ACCEPTED",
                    "modified_drug": None,
                    "decision_reason": None,
                    "original_drug": original_drug.get("drug_name"),
                    "recommended_drug": alternative.get("drug_name"),
                    "diagnosis": diagnosis_code,
                    "structured_similarity_score": top_case_score,
                    "similarity_score": top_case_score,
                    "decision_weight": 0.97,
                    "time_decay": 0.92,
                    "modified_score_after_time_decay_and_decision_weight": case_score,
                    "rule_adjustment_score": adjustment_score,
                    "combined_patient_adjustment_score": adjustment_score,
                    "final_score_after_patient_adjustment": round(case_score + adjustment_score, 4),
                    "rule_adjustment_explanation": "Mock patient adjustment based on aligned member profile and medication history.",
                    "reasoning": [
                        "Original drug matches the current case context.",
                        "Recommended drug matches the current alternative under review.",
                        f"Diagnosis aligns with current request: {diagnosis_code}.",
                        "Historical decision trend supports the recommendation.",
                    ],
                }
            ],
        }

# ===== layer7_llm_client.py =====

import inspect
import os
import time
from typing import Any

try:
    import httpx
except ImportError:  # pragma: no cover - dependency validated at runtime.
    httpx = None

try:
    import openai
except ImportError:  # pragma: no cover - dependency validated at runtime.
    openai = None

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dependency validated at runtime.
    load_dotenv = None


if load_dotenv is not None:
    load_dotenv()
    load_dotenv(Path(__file__).with_name(".env"), override=False)


_TOKEN_CACHE: dict[str, Any] = {"access_token": None, "expires_at": 0.0}


def _env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    return value if value else default


class Layer7LLMClient:
    """Azure/UHG OpenAI caller for Layer 7 governance checks."""

    async def _get_access_token(self) -> str:
        cached_token = _TOKEN_CACHE["access_token"]
        expires_at = float(_TOKEN_CACHE["expires_at"])
        if cached_token and time.time() < expires_at:
            return str(cached_token)

        import urllib.request
        import urllib.parse
        import sys

        auth_url = _env("UHG_AUTH_URL", "https://api.uhg.com/oauth2/token")
        scope = _env("UHG_SCOPE", "https://api.uhg.com/.default")
        client_id = _env("UHG_CLIENT_ID")
        client_secret = _env("UHG_CLIENT_SECRET")

        if not client_id or not client_secret:
            print(f"[ERROR] UHG_CLIENT_ID or UHG_CLIENT_SECRET is missing.", file=sys.stderr, flush=True)
            raise RuntimeError("UHG_CLIENT_ID and UHG_CLIENT_SECRET must be configured for Layer 7.")

        body = urllib.parse.urlencode({
            "grant_type": "client_credentials",
            "scope": scope,
            "client_id": client_id,
            "client_secret": client_secret,
        }).encode()

        req = urllib.request.Request(
            auth_url,
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        try:
            print(f"[INFO] Attempting UHG auth to {auth_url} with client_id={client_id[:8]}...", file=sys.stderr, flush=True)
            with urllib.request.urlopen(req, timeout=60) as resp:
                payload = json.loads(resp.read())
            print(f"[INFO] UHG auth successful", file=sys.stderr, flush=True)
        except Exception as auth_err:
            import traceback
            print(f"[ERROR] Failed to get UHG access token: {type(auth_err).__name__}: {str(auth_err)}", file=sys.stderr, flush=True)
            traceback.print_exc(file=sys.stderr)
            raise RuntimeError(f"UHG auth failed: {auth_err}") from auth_err

        access_token = payload["access_token"]
        expires_in = int(payload.get("expires_in", 3600))
        _TOKEN_CACHE["access_token"] = access_token
        _TOKEN_CACHE["expires_at"] = time.time() + max(expires_in - 60, 0)
        return str(access_token)

    async def call_governance_llm(self, prompt: str) -> str:
        if openai is None:
            raise RuntimeError("Layer 7 LLM dependency missing: openai is not installed.")

        try:
            return await self._call_uhg_llm(prompt)
        except Exception as uhg_err:
            import sys
            print(f"[WARNING] UHG LLM call failed, attempting direct OpenAI fallback: {type(uhg_err).__name__}: {str(uhg_err)}", file=sys.stderr, flush=True)
            try:
                return await self._call_direct_openai_llm(prompt)
            except Exception as openai_err:
                print(f"[ERROR] Both UHG and direct OpenAI LLM calls failed: {type(openai_err).__name__}: {str(openai_err)}", file=sys.stderr, flush=True)
                raise

    async def _call_uhg_llm(self, prompt: str) -> str:
        """Call LLM via UHG shared quota endpoint using urllib (avoids httpx version conflicts)."""
        import urllib.request
        import sys

        access_token = await self._get_access_token()
        shared_quota_endpoint = _env(
            "UHG_SHARED_QUOTA_ENDPOINT",
            "https://api.uhg.com/api/cloud/api-management/ai-gateway/1.0",
        )
        api_version = _env("UHG_AZURE_OPENAI_API_VERSION", "2025-01-01-preview")
        deployment_name = _env("UHG_AZURE_OPENAI_DEPLOYMENT", "gpt-4o_2024-11-20")
        project_id = _env("UHG_PROJECT_ID", "")

        url = f"{shared_quota_endpoint}/openai/deployments/{deployment_name}/chat/completions?api-version={api_version}"

        json_prompt = (
            "Return strictly valid JSON only. Do not include markdown fences or prose.\n\n"
            + str(prompt)
        )
        payload = json.dumps({
            "messages": [{"role": "user", "content": json_prompt}],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }).encode("utf-8")

        req = urllib.request.Request(url, data=payload, headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}",
            "projectId": project_id,
        })

        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                result = json.loads(resp.read())
            content = result["choices"][0]["message"]["content"]
            if not content:
                raise RuntimeError("Layer 7 LLM returned an empty response.")
            return content
        except Exception as api_err:
            print(f"[ERROR] UHG LLM API call failed (url={url}): {type(api_err).__name__}: {str(api_err)}", file=sys.stderr, flush=True)
            raise

    async def _call_direct_openai_llm(self, prompt: str) -> str:
        """Fallback: Call LLM directly via OpenAI API if OPENAI_API_KEY is set."""
        api_key = _env("OPENAI_API_KEY", "")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured. Cannot use direct OpenAI fallback.")

        client = openai.AsyncOpenAI(api_key=api_key)
        try:
            json_prompt = (
                "Return strictly valid JSON only. Do not include markdown fences or prose.\n\n"
                + str(prompt)
            )
            response = await client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": json_prompt}],
                temperature=0,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content
            if content is None:
                raise RuntimeError("Direct OpenAI LLM returned an empty response.")
            return content
        finally:
            close_method = getattr(client, "aclose", None) or getattr(client, "close", None)
            if callable(close_method):
                maybe_awaitable = close_method()
                if inspect.isawaitable(maybe_awaitable):
                    await maybe_awaitable

# ===== layer7_prompt_builder.py =====

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Layer7PromptBuilder:
    """Build governance prompts for Layer 7 downgrade-only review."""

    @staticmethod
    def _serialize(value: Any) -> str:
        return json.dumps(value, indent=2, sort_keys=True, default=str)

    def build_prompt(
        self,
        *,
        request_id: str,
        selected_alternative: dict[str, Any],
        final_ranking: list[dict[str, Any]],
        agent_scores: dict[str, float],
        agent_rationales: dict[str, str],
        consensus_indicators: dict[str, Any],
        risk_adjustment_details: dict[str, Any],
    ) -> str:
        ranking_preview = final_ranking[:5]

        return (
            "You are the Layer 7 LLM Governance Validator for PBM recommendations.\n\n"
            "Role:\n"
            "- Validate governance quality only for this selected recommendation.\n"
            "- You are NOT a ranking authority.\n\n"
            "Allowed triggers only:\n"
            "1) UNADDRESSED_SAFETY_CONCERN\n"
            "2) MATERIAL_REASONING_CONFLICT\n"
            "3) INSUFFICIENT_RATIONALE\n\n"
            "Downgrade is allowed ONLY if ALL are true:\n"
            "- trigger_detected=true\n"
            "- trigger_type is one of allowed triggers\n"
            "- confidence >= 0.90\n"
            "- evidence is present and specific\n\n"
            "Guardrails:\n"
            "- Do not re-rank alternatives\n"
            "- Do not modify scores\n"
            "- Do not override deterministic rules\n"
            "- Do not add new clinical facts\n"
            "- Do not downgrade based on preference\n\n"
            "Return valid JSON with exactly these keys:\n"
            "{\n"
            "  \"trigger_detected\": false,\n"
            "  \"trigger_type\": null,\n"
            "  \"confidence\": 0.00,\n"
            "  \"evidence\": null,\n"
            "  \"note\": \"<=40 words\"\n"
            "}\n\n"
            f"Request ID:\n{request_id}\n\n"
            "Selected Alternative (Band 2 candidate):\n"
            f"{self._serialize(selected_alternative)}\n\n"
            "Final Ranking Snapshot (top 5):\n"
            f"{self._serialize(ranking_preview)}\n\n"
            "Agent Scores:\n"
            f"{self._serialize(agent_scores)}\n\n"
            "Agent Rationales:\n"
            f"{self._serialize(agent_rationales)}\n\n"
            "Consensus Indicators:\n"
            f"{self._serialize(consensus_indicators)}\n\n"
            "Risk Adjustment Details:\n"
            f"{self._serialize(risk_adjustment_details)}"
        )

# ===== layer8_prompt_builder.py =====

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Layer8PromptBuilder:
    """Build summary-generation prompts for Layer 8."""

    @staticmethod
    def _serialize(value: Any) -> str:
        return json.dumps(value, indent=2, sort_keys=True, default=str)

    def build_prompt(
        self,
        *,
        request_id: str,
        alternative: dict[str, Any],
        final_band: int,
        clinical_context: dict[str, Any],
        policy_context: dict[str, Any],
        financial_context: dict[str, Any],
        past_decision_context: dict[str, Any],
    ) -> str:
        # stage_a_context = alternative.get("stage_a", {}) if isinstance(alternative.get("stage_a", {}), dict) else {}
        # stage_b_context = alternative.get("stage_b", {}) if isinstance(alternative.get("stage_b", {}), dict) else {}
        # stage_c_context = alternative.get("stage_c", {}) if isinstance(alternative.get("stage_c", {}), dict) else {}

        # Extract clinical_agent_result from the ranked_item (alternative parameter)
        clinical_agent_result = alternative.get("clinical_agent_result", {}) if isinstance(alternative.get("clinical_agent_result", {}), dict) else {}
       
        # Extract stage contexts from clinical_agent_result
        stage_a_context = clinical_agent_result.get("stage_a", {}) if isinstance(clinical_agent_result.get("stage_a", {}), dict) else {}
        stage_b_context = clinical_agent_result.get("stage_b", {}) if isinstance(clinical_agent_result.get("stage_b", {}), dict) else {}
        stage_c_context = clinical_agent_result.get("stage_c", {}) if isinstance(clinical_agent_result.get("stage_c", {}), dict) else {}
        
        return (
          "You are a PBM Orchestrator Layer 8 Summary Generator.\n\n"
            "Task:\n"
            "Generate a structured, concise, audit-ready summary for this single alternative.\n"
            "Do not invent new facts. Use only the provided inputs.\n"
            "The summary must read like a justified clinical review, not a generic narrative.\n\n"
            "How to write the clinical section:\n"
            "- `clinical_summary` must contain exactly 4 short bullets.\n"
            "- Build these bullets primarily from Stage A fields: `evidence`, `status`, and `reasoning` when present.\n"
            "- Focus only on comparison between the prescribed drug and the alternative drug.\n"
            "- The 4 bullets must cover:\n"
            "  1. Ingredient similarity.\n"
            "  2. Class similarity.\n"
            "  3. Route/form similarity.\n"
            "  4. Mechanism of action similarity.\n"
            "- Generate exactly one bullet for each category above.\n"
            "- Each bullet must be extremely concise, with a maximum of 5-6 words.\n"
            "- Use simple comparison language such as:\n"
            "  - \"Different active ingredient\"\n"
            "  - \"Same therapeutic class\"\n"
            "  - \"Same oral route\"\n"
            "  - \"Similar mechanism of action\"\n"
            "- Determine whether each attribute is same, similar, partial match, or different based on Stage A evidence and reasoning.\n"
            "- Do not mention scores, statuses, strengths, thresholds, acceptance decisions, or detailed clinical explanations.\n"
            "- Do not copy raw evidence values.\n\n"
            "How to write the safety section:\n"
            "- `safety_summary` must contain exactly 4 short bullets.\n"
            "- Build these bullets primarily from Stage B fields: `evidence`, `status`, and `reasoning` when present.\n"
            "- The 4 bullets must cover:\n"
            "  1. Allergy assessment.\n"
            "  2. Age assessment.\n"
            "  3. Contraindication assessment.\n"
            "  4. Interaction assessment.\n"
            "- Generate exactly one bullet for each category above.\n"
            "- Each bullet must be extremely concise, with a maximum of 5-6 words.\n"
            "- Use simple safety language such as:\n"
            "  - \"No allergy concern identified\"\n"
            "  - \"No age-related concern\"\n"
            "  - \"No contraindication identified\"\n"
            "  - \"No major interaction concern\"\n"
            "- If Stage B reasoning indicates caution, reflect it briefly in the relevant bullet.\n"
            "- Do not mention scores, statuses, acceptance decisions, or raw evidence values.\n\n"
            "How to write the provider-review agent summary:\n"
            "- `agent_summary` must contain exactly 2 bullets.\n"
            "- Applicable when the final band is Provider Review; otherwise don't give agent_summary section at all.\n"
            "- Build these bullets only from Stage A and Stage B `reasoning` fields when present.\n"
            "- The first bullet should summarize the primary clinical justification.\n"
            "- The second bullet should summarize the primary safety consideration or caution.\n"
            "- Each bullet must be concise and no more than 15 words.\n"
            "- Keep the summary provider-facing, decision-oriented, and fact-based.\n"
            "- Do not repeat evidence values, scores, or statuses.\n"
            "- Do not quote reasoning verbatim unless necessary to preserve clinical meaning.\n"
            "- If Stage A reasoning and Stage B reasoning both are unavailable, use: \"No LLM review required.\"\n"
            "- If Stage A reasoning or Stage B reasoning any one is available, give only one point accordingly.\n"
            "Rules:\n"
            "- Keep statuses short and deterministic.\n"
            "- Return valid JSON only.\n"
            "- Never invent a clinical fact that is not supported by the supplied Stage A, Stage B, or Stage C context.\n\n"
            "Return JSON in exactly this shape:\n"
            "{\n"
            "  \"financial_agent\": {\n"
            "    \"status\": \"COST_FAVORABLE\",\n"
            "    \"original_drug\": \"\",\n"
            "    \"alternative_drug\": \"\",\n"
            "    \"original_tier\": \"\",\n"
            "    \"alternative_tier\": \"\",\n"
            "    \"original_total_price\": \"\",\n"
            "    \"alternative_total_price\": \"\",\n"
            "    \"original_copay\": \"\",\n"
            "    \"alternative_copay\": \"\",\n"
            "    \"original_plan_paid\": \"\",\n"
            "    \"alternative_plan_paid\": \"\",\n"
            "    \"annual_savings\": \"\",\n"
            "    \"savings_percent\": \"\",\n"
            "    \"summary\": \"\"\n"
            "  },\n"
            "  \"insurance_context\": {\n"
            "    \"insurance_phase\": \"\",\n"
            "    \"ytd_oop\": \"\",\n"
            "    \"coinsurance\": \"\",\n"
            "    \"deductible_limit\": \"\",\n"
            "    \"deductible_met\": \"\",\n"
            "    \"deductible_remaining\": \"\",\n"
            "    \"oop_max\": \"\",\n"
            "    \"oop_used\": \"\",\n"
            "    \"oop_remaining\": \"\"\n"
            "  },\n"
            "  \"clinical_agent\": {\n"
            "    \"status\": \"CLINICALLY_ACCEPTABLE\",\n"
            "    \"clinical_summary\": [\"\", \"\", \"\", \"\"],\n"
            "    \"safety_summary\": [\"\", \"\", \"\", \"\"],\n"
            "    \"agent_summary\": [\"\", \"\"]\n"
            "  },\n"
            "  \"policy_agent\": {\n"
            "    \"status\": \"POLICY_APPROVED\",\n"
            "    \"original_status\": \"\",\n"
            "    \"alternative_status\": \"\",\n"
            "    \"formulary_preference\": \"\",\n"
            "    \"coverage_status\": \"\",\n"
            "    \"policy_checks_passed\": true,\n"
            "    \"policy_notes\": \"\",\n"
            "    \"key_findings\": []\n"
            "  },\n"
            "  \"past_decision_agent\": {\n"
            "    \"status\": \"RECOMMENDED\",\n"
            "    \"historical_confidence\": \"High\",\n"
            "    \"summary\": \"\",\n"
            "    \"recommendation_supported\": true\n"
            "  }\n"
            "}\n\n"
            f"Request ID:\n{request_id}\n\n"
            f"Final Band:\n{final_band}\n\n"
            f"Alternative Drug:\n{alternative.get('alternative_name', 'Unknown')}\n\n"
            f"Alternative ID:\n{alternative.get('alternative_id', 'Unknown')}\n\n"
            "Stage A (Clinical Similarity) Context:\n"
            f"{self._serialize(stage_a_context)}\n\n"
            "Stage B (Safety Assessment) Context:\n"
            f"{self._serialize(stage_b_context)}\n\n"
            "Stage C (Acceptability Thresholds) Context:\n"
            f"{self._serialize(stage_c_context)}\n\n"
            "Policy Agent Assessment:\n"
            f"{self._serialize(policy_context)}\n\n"
            "Financial Agent Assessment:\n"
            f"{self._serialize(financial_context)}\n\n"
            "Past Decision Evidence:\n"
            f"{self._serialize(past_decision_context)}"
        )
            

# ===== phases.py =====

import asyncio
import json
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any



def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _trace(request_id: str, message: str) -> None:
    import sys
    from pathlib import Path

    rid = request_id or "???"
    trace_msg = f"[TRACE] [TRC-{rid}] {message}"
    print(trace_msg, file=sys.stderr, flush=True)
    
    # Append to trace file
    trace_file = Path(__file__).parent.parent.parent.parent / "trace_output.txt"
    with open(trace_file, "a", encoding="utf-8") as f:
        f.write(trace_msg + "\n")
        f.flush()


def _run_async_blocking(coro: Any) -> Any:
    """Run a coroutine from sync code, even if an event loop is already running."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(asyncio.run, coro)
        return future.result()


def _extract_clinical_composite_score(item: dict[str, Any]) -> float:
    return _safe_float(
        item.get("clinical_agent_result", {}).get("stage_c", {}).get("composite_score"),
        0.0,
    )


def _extract_stage_c(item: dict[str, Any]) -> dict[str, Any]:
    clinical_result = item.get("clinical_agent_result", {})
    stage_c = clinical_result.get("stage_c", {}) if isinstance(clinical_result, dict) else {}
    return stage_c if isinstance(stage_c, dict) else {}


def _extract_stage_b(item: dict[str, Any]) -> dict[str, Any]:
    clinical_result = item.get("clinical_agent_result", {})
    stage_b = clinical_result.get("stage_b", {}) if isinstance(clinical_result, dict) else {}
    return stage_b if isinstance(stage_b, dict) else {}


def _extract_policy_score(item: dict[str, Any]) -> float:
    response = item.get("policy_agent", {}).get("response", {})
    return _safe_float(
        response.get("score", response.get("result", {}).get("score")),
        0.0,
    )


def _extract_projected_total_cost(item: dict[str, Any]) -> float:
    financial_response = item.get("financial_agent", {}).get("response", {})
    result = financial_response.get("result", {}) if isinstance(financial_response.get("result", {}), dict) else {}
    final_cost = financial_response.get("final_cost", result.get("final_cost"))
    if final_cost is not None:
        return _safe_float(final_cost, float("inf"))
    return _safe_float(
        financial_response.get("estimated_patient_pay", result.get("estimated_patient_pay")),
        float("inf"),
    )


def _extract_historical_approval_rate(item: dict[str, Any]) -> float:
    past_response = item.get("past_decision_agent", {}).get("response", {})
    top_cases = past_response.get("top_cases", past_response.get("match", {}))
    if isinstance(top_cases, dict):
        top_cases = [top_cases]
    if not top_cases:
        return 0.0

    accepted_count = 0
    considered_count = 0
    for case in top_cases:
        decision = str(case.get("decision", "")).strip().upper()
        if not decision:
            continue
        considered_count += 1
        if decision == "ACCEPTED":
            accepted_count += 1

    if considered_count == 0:
        return 0.0

    return accepted_count / considered_count


def _extract_policy_response(item: dict[str, Any]) -> dict[str, Any]:
    response = item.get("policy_agent", {}).get("response", {})
    result = response.get("result", {}) if isinstance(response.get("result", {}), dict) else {}
    return result or response


def _extract_financial_response(item: dict[str, Any]) -> dict[str, Any]:
    response = item.get("financial_agent", {}).get("response", {})
    result = response.get("result", {}) if isinstance(response.get("result", {}), dict) else {}
    return result or response


def _extract_past_decision_response(item: dict[str, Any]) -> dict[str, Any]:
    response = item.get("past_decision_agent", {}).get("response", {})
    result = response.get("result", {}) if isinstance(response.get("result", {}), dict) else {}
    return result or response


def _extract_policy_state(item: dict[str, Any]) -> str:
    policy_response = _extract_policy_response(item)
    return str(policy_response.get("policy_state", policy_response.get("summary", {}).get("decision", "pass"))).strip().lower()


def _extract_past_score(item: dict[str, Any]) -> float:
    past_response = _extract_past_decision_response(item)
    return _safe_float(
        past_response.get("final_score", past_response.get("score", past_response.get("average_confidence_score"))),
        0.0,
    )


def _extract_past_has_signal(item: dict[str, Any]) -> bool:
    past_response = _extract_past_decision_response(item)
    if "has_signal" in past_response:
        return bool(past_response.get("has_signal"))
    if "has_signal" in item.get("past_decision_agent", {}).get("response", {}):
        return bool(item.get("past_decision_agent", {}).get("response", {}).get("has_signal"))
    if past_response.get("match"):
        return True
    top_cases = past_response.get("top_cases")
    return isinstance(top_cases, list) and len(top_cases) > 0


def _extract_clinical_threshold_pass(item: dict[str, Any], config: OrchestratorConfig) -> bool:
    stage_c = _extract_stage_c(item)
    threshold_passed = stage_c.get("threshold_passed")
    if threshold_passed is not None:
        return bool(threshold_passed)
    return _extract_clinical_composite_score(item) >= config.clinical_threshold


def _extract_missing_clinical_data(item: dict[str, Any]) -> bool:
    safety_flags = _extract_stage_c(item).get("safety_flags", {})
    return bool(safety_flags.get("missing_clinical_data", False))


def _extract_requires_mandatory_escalation(item: dict[str, Any]) -> bool:
    stage_c = _extract_stage_c(item)
    if bool(stage_c.get("requires_mandatory_escalation", False)):
        return True
    safety_flags = stage_c.get("safety_flags", {}) if isinstance(stage_c.get("safety_flags", {}), dict) else {}
    return bool(safety_flags.get("cumulative_risk", False) and safety_flags.get("clinical_ambiguity", False))


def _extract_safe(item: dict[str, Any]) -> bool:
    clinical_result = item.get("clinical_agent_result", {})
    overall_status = str(clinical_result.get("overall_status", "")).strip().lower() if isinstance(clinical_result, dict) else ""
    stage_b_status = str(_extract_stage_b(item).get("status", "")).strip().lower()
    if overall_status in {"reject", "rejected"}:
        return False
    if stage_b_status in {"reject", "rejected"}:
        return False
    return True


def _ranking_tuple(item: dict[str, Any], agent_key: str, score_field: str) -> tuple[float, float, float, float]:
    response = item.get(agent_key, {}).get("response", {})
    nested_result = response.get("result", {}) if isinstance(response.get("result", {}), dict) else {}
    nested_match = response.get("match", {}) if isinstance(response.get("match", {}), dict) else {}
    if agent_key == "past_decision_agent":
        primary_score = _extract_past_score(item)
    else:
        primary_score = _safe_float(
            response.get(score_field, nested_result.get(score_field, nested_match.get(score_field))),
            0.0,
        )
    clinical_score = _extract_clinical_composite_score(item)
    policy_score = _extract_policy_score(item)
    projected_cost = _extract_projected_total_cost(item)
    historical_approval_rate = _extract_historical_approval_rate(item)

    return (
        primary_score,
        clinical_score,
        policy_score,
        -projected_cost,
        historical_approval_rate,
    )


def _is_unresolved_tie(left: dict[str, Any], right: dict[str, Any], agent_key: str, score_field: str) -> bool:
    return _ranking_tuple(left, agent_key, score_field) == _ranking_tuple(right, agent_key, score_field)


def _rank_alternative_evaluations(
    alternative_evaluations: list[dict[str, Any]],
    agent_key: str,
    score_field: str,
) -> list[dict[str, Any]]:
    sorted_evaluations = sorted(
        alternative_evaluations,
        key=lambda item: _ranking_tuple(item, agent_key, score_field),
        reverse=True,
    )

    ranked = []
    for index, item in enumerate(sorted_evaluations, start=1):
        response = item.get(agent_key, {}).get("response", {})
        unresolved_tie = False
        if index > 1 and _is_unresolved_tie(sorted_evaluations[index - 2], item, agent_key, score_field):
            unresolved_tie = True
        if index < len(sorted_evaluations) and _is_unresolved_tie(item, sorted_evaluations[index], agent_key, score_field):
            unresolved_tie = True

        ranked.append(
            {
                "rank": index,
                "alternative_id": item.get("alternative_id"),
                "alternative_name": item.get("alternative_name"),
                "clinical_rank": item.get("clinical_rank"),
                "score": response.get(
                    score_field,
                    response.get("result", {}).get(score_field, response.get("match", {}).get(score_field)),
                ),
                "agent": agent_key,
                "response": response,
                "tie_break_context": {
                    "clinical_composite_score": _extract_clinical_composite_score(item),
                    "policy_score": _extract_policy_score(item),
                    "projected_total_cost": _extract_projected_total_cost(item),
                    "historical_approval_rate": _extract_historical_approval_rate(item),
                    "unresolved_tie": unresolved_tie,
                },
            }
        )

    return ranked


class BasePhase(ABC):
    name = "base"

    @abstractmethod
    def execute(self, context: dict[str, Any]) -> PhaseResult:
        raise NotImplementedError


class IntakePhase(BasePhase):
    name = "phase_01_intake"

    required_fields = [
        "member_id",
        "prescriber_npi",
        "pharmacy_id",
        "diagnosis",
        "medication",
        "strength",
        "frequency",
        "days_supply",
    ]

    def execute(self, context: dict[str, Any]) -> PhaseResult:
        payload = context.get("payload", {})
        if not isinstance(payload, dict):
            return PhaseResult(
                name=self.name,
                status="failed",
                errors=["Input payload must be a JSON object."],
            )
        if not payload:
            return PhaseResult(
                name=self.name,
                status="failed",
                errors=["Input payload is empty."],
            )

        missing = [field for field in self.required_fields if field not in payload]
        if missing:
            return PhaseResult(
                name=self.name,
                status="failed",
                errors=[f"Missing required fields: {', '.join(missing)}"],
            )

        diagnosis = payload.get("diagnosis")
        if not isinstance(diagnosis, dict) or not diagnosis.get("code") or not diagnosis.get("name"):
            return PhaseResult(
                name=self.name,
                status="failed",
                errors=["diagnosis must be an object with code and name."],
            )

        medication = payload.get("medication")
        if not isinstance(medication, dict) or not medication.get("drug_id") or not medication.get("drug_name"):
            return PhaseResult(
                name=self.name,
                status="failed",
                errors=["medication must be an object with drug_id and drug_name."],
            )

        return PhaseResult(
            name=self.name,
            status="success",
            data={
                "received_keys": sorted(payload.keys()),
                "message": "Input payload accepted.",
                "clinical_agent_request": {
                    "member_id": payload["member_id"],
                    "medication": {
                        "drug_id": payload["medication"]["drug_id"],
                        "drug_name": payload["medication"]["drug_name"],
                    },
                },
            },
        )


class ClinicalPhase(BasePhase):
    name = "phase_02_clinical"

    def __init__(self, client: ClinicalAgentClient | None = None) -> None:
        self.client = client or ClinicalAgentClient()

    def execute(self, context: dict[str, Any]) -> PhaseResult:
        payload = context.get("payload", {})
        runtime_options = context.get("runtime_options", {})

        clinical_output_inline = runtime_options.get("clinical_output_inline")
        if clinical_output_inline is not None:
            if not isinstance(clinical_output_inline, dict):
                return PhaseResult(
                    name=self.name,
                    status="failed",
                    errors=["clinical_output_inline must be a JSON object."],
                )

            response = clinical_output_inline
            ranked_alternatives = response.get("ranked_alternatives", [])
            if not isinstance(ranked_alternatives, list):
                return PhaseResult(
                    name=self.name,
                    status="failed",
                    errors=["clinical_output_inline must contain ranked_alternatives as a list."],
                )

            medication = payload.get("medication", {})
            return PhaseResult(
                name=self.name,
                status="success",
                data={
                    "message": "Clinical agent response received.",
                    "request_sent": {
                        "member_id": str(payload.get("member_id", "")),
                        "medication": {
                            "drug_id": medication.get("drug_id"),
                            "drug_name": medication.get("drug_name"),
                        },
                    },
                    "ranked_alternatives_count": len(ranked_alternatives),
                    "clinical_agent_output": response,
                },
            )

        clinical_output_json_path = runtime_options.get("clinical_output_json_path")
        if not clinical_output_json_path:
            return PhaseResult(
                name=self.name,
                status="failed",
                errors=["Missing runtime option clinical_output_json_path."],
            )

        medication = payload.get("medication", {})
        call_result = self.client.get_ranked_alternatives(
            member_id=str(payload.get("member_id", "")),
            medication=medication,
            output_json_path=str(clinical_output_json_path),
        )

        response = call_result.get("response", {})
        ranked_alternatives = response.get("ranked_alternatives", [])

        return PhaseResult(
            name=self.name,
            status="success",
            data={
                "message": "Clinical agent response received.",
                "request_sent": call_result.get("request_sent", {}),
                "ranked_alternatives_count": len(ranked_alternatives),
                "clinical_agent_output": response,
            },
        )


class DownstreamAgentsPhase(BasePhase):
    name = "phase_03_downstream_agents"

    def __init__(
        self,
        policy_client: PolicyAgentClient | None = None,
        financial_client: FinancialAgentClient | None = None,
        past_decision_client: PastDecisionAgentClient | None = None,
    ) -> None:
        self.policy_client = policy_client or PolicyAgentClient()
        self.financial_client = financial_client or FinancialAgentClient()
        self.past_decision_client = past_decision_client or PastDecisionAgentClient()

    def execute(self, context: dict[str, Any]) -> PhaseResult:
        request_id = str(context.get("request_id", ""))
        payload = context.get("payload", {})
        runtime_options = context.get("runtime_options", {})
        clinical_phase_data = context.get("phase_02_clinical", {})
        clinical_output = clinical_phase_data.get("clinical_agent_output", {})
        ranked_alternatives = clinical_output.get("ranked_alternatives", [])

        if not ranked_alternatives:
            return PhaseResult(
                name=self.name,
                status="failed",
                errors=["No ranked alternatives available from clinical agent output."],
            )

        self._apply_runtime_paths(runtime_options)

        _trace(
            request_id,
            "4) Sending ranked alternatives to Policy, Financial, and Past Decision agents"
        )

        phase_started_at = time.perf_counter()
        alternative_evaluations = []
        for alternative in ranked_alternatives:
            alternative_evaluations.append(
                self._evaluate_alternative(payload, alternative, request_id=request_id)
            )
        phase_elapsed_seconds = time.perf_counter() - phase_started_at
        _trace(
            request_id,
            f"5) Downstream agent outputs received: alternatives={len(alternative_evaluations)} elapsed={phase_elapsed_seconds:.3f}s"
        )

        return PhaseResult(
            name=self.name,
            status="success",
            data={
                "message": "Policy, financial, and past-decision agent outputs received.",
                "alternatives_processed": len(alternative_evaluations),
                "elapsed_seconds": phase_elapsed_seconds,
                "alternative_evaluations": alternative_evaluations,
                "policy_ranked_alternatives": _rank_alternative_evaluations(
                    alternative_evaluations,
                    agent_key="policy_agent",
                    score_field="score",
                ),
                "financial_ranked_alternatives": _rank_alternative_evaluations(
                    alternative_evaluations,
                    agent_key="financial_agent",
                    score_field="score",
                ),
                "past_decision_ranked_alternatives": _rank_alternative_evaluations(
                    alternative_evaluations,
                    agent_key="past_decision_agent",
                    score_field="final_score",
                ),
            },
        )

    def _apply_runtime_paths(self, runtime_options: dict[str, Any]) -> None:
        policy_dir = runtime_options.get("policy_response_dir")
        financial_dir = runtime_options.get("financial_response_dir")
        past_decision_dir = runtime_options.get("past_decision_response_dir")
        policy_inline = runtime_options.get("policy_inline_response_payload")
        financial_inline = runtime_options.get("financial_inline_response_payload")
        past_decision_inline = runtime_options.get("past_decision_inline_response_payload")
        policy_inline_many = runtime_options.get("policy_inline_response_payloads")
        financial_inline_many = runtime_options.get("financial_inline_response_payloads")
        past_decision_inline_many = runtime_options.get("past_decision_inline_response_payloads")

        if policy_dir:
            self.policy_client.response_dir = Path(policy_dir)
        if financial_dir:
            self.financial_client.response_dir = Path(financial_dir)
        if past_decision_dir:
            self.past_decision_client.response_dir = Path(past_decision_dir)

        if isinstance(policy_inline, dict):
            self.policy_client.inline_response_payload = policy_inline
        if isinstance(financial_inline, dict):
            self.financial_client.inline_response_payload = financial_inline
        if isinstance(past_decision_inline, dict):
            self.past_decision_client.inline_response_payload = past_decision_inline
        if isinstance(policy_inline_many, dict):
            self.policy_client.inline_response_payloads = policy_inline_many
        if isinstance(financial_inline_many, dict):
            self.financial_client.inline_response_payloads = financial_inline_many
        if isinstance(past_decision_inline_many, dict):
            self.past_decision_client.inline_response_payloads = past_decision_inline_many

    def _evaluate_alternative(self, payload: dict[str, Any], alternative: dict[str, Any], *, request_id: str) -> dict[str, Any]:
        policy_request = self._build_policy_request(payload, alternative)
        financial_request = self._build_financial_request(payload, alternative)
        past_decision_request = self._build_past_decision_request(payload, alternative)
        alt_id = alternative.get("candidate_id")
        alt_name = alternative.get("candidate_name")
        _trace(request_id, f"4.a) Alternative [{alt_id}] {alt_name}: dispatching agent calls")

        # Process this alternative's downstream agent calls in parallel.
        started_at = time.perf_counter()
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {
                executor.submit(self.policy_client.evaluate, policy_request): "policy",
                executor.submit(self.financial_client.evaluate, financial_request): "financial",
                executor.submit(self.past_decision_client.evaluate, past_decision_request): "past",
            }

            responses: dict[str, dict[str, Any]] = {}
            for future in as_completed(futures):
                agent_name = futures[future]
                response = future.result()
                responses[agent_name] = response
                if agent_name == "policy":
                    _trace(
                        request_id,
                        f"5.a) Alternative [{alt_id}] Policy received: state={response.get('policy_state')} score={_safe_float(response.get('score')):.2f}",
                    )
                elif agent_name == "financial":
                    _trace(
                        request_id,
                        f"5.b) Alternative [{alt_id}] Financial received: score={_safe_float(response.get('score')):.2f} cost={response.get('final_cost')}",
                    )
                else:
                    past_score = response.get("final_score")
                    if past_score is None:
                        past_score = response.get("average_confidence_score")
                    _trace(
                        request_id,
                        f"5.c) Alternative [{alt_id}] Past Decision received: score={_safe_float(past_score):.2f}",
                    )

            policy_response = responses.get("policy", {})
            financial_response = responses.get("financial", {})
            past_decision_response = responses.get("past", {})
        elapsed_seconds = time.perf_counter() - started_at

        return {
            "alternative_id": alternative.get("candidate_id"),
            "alternative_name": alternative.get("candidate_name"),
            "clinical_rank": alternative.get("rank"),
            "elapsed_seconds": elapsed_seconds,
            "clinical_agent_result": alternative,
            "policy_agent": {
                "request": policy_request,
                "response": policy_response,
            },
            "financial_agent": {
                "request": financial_request,
                "response": financial_response,
            },
            "past_decision_agent": {
                "request": past_decision_request,
                "response": past_decision_response,
            },
        }

    def _build_policy_request(self, payload: dict[str, Any], alternative: dict[str, Any]) -> dict[str, Any]:
        medication = payload.get("medication", {})
        return {
            "member_id": payload.get("member_id"),
            "plan_id": payload.get("plan_id"),
            "fill_date": payload.get("fill_date"),
            "drug": {
                "drug_id": medication.get("drug_id"),
                "drug_name": medication.get("drug_name"),
            },
            "original_drug": {
                "drug_id": medication.get("drug_id"),
                "drug_name": medication.get("drug_name"),
            },
            "frequency": payload.get("frequency"),
            "days_supply": payload.get("days_supply"),
            "alternative": {
                "drug_id": alternative.get("candidate_id"),
                "drug_name": alternative.get("candidate_name"),
            },
            "clinical_rank": alternative.get("rank"),
        }

    def _build_financial_request(self, payload: dict[str, Any], alternative: dict[str, Any]) -> dict[str, Any]:
        medication = payload.get("medication", {})
        return {
            "member_id": payload.get("member_id"),
            "plan_id": payload.get("plan_id"),
            "fill_date": payload.get("fill_date"),
            "insurance_context": payload.get("insurance_context", {}),
            "original_drug": {
                "drug_id": medication.get("drug_id"),
                "drug_name": medication.get("drug_name"),
            },
            "alternative": {
                "drug_id": alternative.get("candidate_id"),
                "drug_name": alternative.get("candidate_name"),
            },
            "frequency": payload.get("frequency"),
            "days_supply": payload.get("days_supply"),
            "clinical_rank": alternative.get("rank"),
        }

    def _build_past_decision_request(self, payload: dict[str, Any], alternative: dict[str, Any]) -> dict[str, Any]:
        medication = payload.get("medication", {})
        diagnosis = payload.get("diagnosis", {})
        return {
            "member_id": payload.get("member_id"),
            "drug_name": medication.get("drug_name"),
            "diagnosis_code": diagnosis.get("code"),
            "alternative": {
                "drug_id": alternative.get("candidate_id"),
                "drug_name": alternative.get("candidate_name"),
            },
            "original_drug": {
                "drug_id": medication.get("drug_id"),
                "drug_name": medication.get("drug_name"),
            },
            "clinical_rank": alternative.get("rank"),
        }

class HardRulesAndWeightsPhase(BasePhase):
    name = "phase_04_hard_rules_and_weights"

    def execute(self, context: dict[str, Any]) -> PhaseResult:
        request_id = str(context.get("request_id", ""))
        config = context.get("config")
        downstream_phase_data = context.get("phase_03_downstream_agents", {})
        alternative_evaluations = downstream_phase_data.get("alternative_evaluations", [])

        if not alternative_evaluations:
            return PhaseResult(
                name=self.name,
                status="failed",
                errors=["No downstream agent evaluations available for hard-rule processing."],
            )

        _trace(request_id, "6) Applying hard rules and static weights")

        filtered_alternatives = []
        removed_alternatives = []
        escalated_alternatives = []
        escalation_reasons = []

        for evaluation in alternative_evaluations:
            policy_response = _extract_policy_response(evaluation)
            clinical_result = evaluation.get("clinical_agent_result", {})
            safety_flags = _extract_stage_c(evaluation).get("safety_flags", {})

            removal_reasons = self._get_policy_removal_reasons(policy_response)
            policy_state = _extract_policy_state(evaluation)
            missing_clinical_data = bool(safety_flags.get("missing_clinical_data", False))

            # Hard-gate flags that require immediate provider review handling.
            policy_pending_state = policy_state == "pending"
            pa_required_unmet = bool(policy_response.get("pa_required", False)) and not bool(policy_response.get("pa_met", True))
            step_therapy_unmet = bool(policy_response.get("step_therapy_required", False)) and not bool(policy_response.get("step_therapy_met", True))
            quantity_limit_triggered = (
                bool(policy_response.get("quantity_limit_exceeded", False))
                or bool(policy_response.get("quantity_limits_exceeded", False))
                or (policy_response.get("quantity_ok") is False)
            )

            hard_gate_flags: list[str] = []
            if policy_pending_state:
                hard_gate_flags.append("policy_state_pending")
            if pa_required_unmet:
                hard_gate_flags.append("pa_required")
            if step_therapy_unmet:
                hard_gate_flags.append("step_therapy_required")
            if quantity_limit_triggered:
                hard_gate_flags.append("quantity_limits")
            if missing_clinical_data:
                hard_gate_flags.append("missing_clinical_data")

            requires_mandatory_escalation = (
                _extract_requires_mandatory_escalation(evaluation)
                or bool(hard_gate_flags)
            )

            filtered_record = {
                "alternative_id": evaluation.get("alternative_id"),
                "alternative_name": evaluation.get("alternative_name"),
                "clinical_rank": evaluation.get("clinical_rank"),
                "clinical_agent_result": clinical_result,
                "policy_agent": evaluation.get("policy_agent", {}),
                "financial_agent": evaluation.get("financial_agent", {}),
                "past_decision_agent": evaluation.get("past_decision_agent", {}),
                "layer_2": {
                    "removed_from_ranking": bool(removal_reasons),
                    "removal_reasons": removal_reasons,
                    "missing_clinical_data": missing_clinical_data,
                    "policy_state": policy_state,
                    "safe": _extract_safe(evaluation),
                    "requires_mandatory_escalation": requires_mandatory_escalation,
                    "hard_gate_flags": hard_gate_flags,
                },
            }

            alt_id = evaluation.get("alternative_id")
            alt_name = evaluation.get("alternative_name")
            if requires_mandatory_escalation:
                escalated_alternatives.append(filtered_record)
                for flag in hard_gate_flags:
                    escalation_reasons.append(
                        {
                            "alternative_id": alt_id,
                            "alternative_name": alt_name,
                            "reason": flag,
                        }
                    )
                    if flag == "missing_clinical_data":
                        _trace(request_id, f"6) Hard gate TRIGGERED [{alt_id}] {alt_name}: flag=missing_clinical_data → escalated to provider review (incomplete safety/clinical data)")
                    elif flag == "policy_state_pending":
                        _trace(request_id, f"6) Hard gate TRIGGERED [{alt_id}] {alt_name}: flag=policy_state_pending → escalated to provider review (policy marked pending)")
                    elif flag == "pa_required":
                        _trace(request_id, f"6) Hard gate TRIGGERED [{alt_id}] {alt_name}: flag=pa_required → escalated to provider review (prior authorization required)")
                    elif flag == "step_therapy_required":
                        _trace(request_id, f"6) Hard gate TRIGGERED [{alt_id}] {alt_name}: flag=step_therapy_required → escalated to provider review (step therapy criteria unmet)")
                    elif flag == "quantity_limits":
                        _trace(request_id, f"6) Hard gate TRIGGERED [{alt_id}] {alt_name}: flag=quantity_limits → escalated to provider review (quantity limit check failed)")
            for reason in removal_reasons:
                _trace(request_id, f"6) Hard gate TRIGGERED [{alt_id}] {alt_name}: flag={reason} → denied by policy and removed from final review pool")

            if removal_reasons:
                removed_alternatives.append(filtered_record)
            filtered_alternatives.append(filtered_record)

        agent_weights = {
            "policy_agent": config.policy_weight,
            "financial_agent": config.financial_weight,
            "past_decision_agent": config.past_decision_weight,
        }

        return PhaseResult(
            name=self.name,
            status="success",
            data={
                "message": "Layer 2 hard rules and Layer 3 static weights applied.",
                "escalation_required": bool(escalation_reasons),
                "escalation_reasons": escalation_reasons,
                "surviving_alternatives": filtered_alternatives,
                "escalated_alternatives": escalated_alternatives,
                "removed_alternatives": removed_alternatives,
                "surviving_alternatives_count": len(filtered_alternatives),
                "escalated_alternatives_count": len(escalated_alternatives),
                "removed_alternatives_count": len(removed_alternatives),
                "agent_weights": agent_weights,
                "weights_sum": round(sum(agent_weights.values()), 2),
            },
        )

    def _get_policy_removal_reasons(self, policy_response: dict[str, Any]) -> list[str]:
        reasons = []

        if str(policy_response.get("policy_state", "")).strip().lower() == "deny":
            reasons.append("policy_state_deny")

        return reasons


class Layer4ScoringPhase(BasePhase):
    name = "phase_05_layer_4_scoring"

    def execute(self, context: dict[str, Any]) -> PhaseResult:
        request_id = str(context.get("request_id", ""))
        config = context.get("config")
        layer_2_and_3 = context.get("phase_04_hard_rules_and_weights", {})
        surviving_alternatives = layer_2_and_3.get("surviving_alternatives", [])
        agent_weights = layer_2_and_3.get("agent_weights", {})

        _trace(request_id, "7) Layer 4: weighted score fusion + weighted Borda consensus")

        if not surviving_alternatives:
            return PhaseResult(
                name=self.name,
                status="success",
                data={
                    "message": "Layer 4 skipped because no alternatives survived Layer 2.",
                    "surviving_alternatives_count": 0,
                    "score_fusion_ranked_alternatives": [],
                    "borda_ranked_alternatives": [],
                    "aggregate_ranked_alternatives": [],
                },
            )

        policy_ranking = _rank_alternative_evaluations(surviving_alternatives, "policy_agent", "score")
        financial_ranking = _rank_alternative_evaluations(surviving_alternatives, "financial_agent", "score")
        past_candidates = [item for item in surviving_alternatives if _extract_past_has_signal(item)]
        past_decision_ranking = _rank_alternative_evaluations(past_candidates, "past_decision_agent", "final_score")

        borda_norm_by_alternative = self._compute_borda_norm(
            policy_ranking,
            financial_ranking,
            past_decision_ranking,
            agent_weights,
        )

        scored_alternatives = []
        for item in surviving_alternatives:
            alternative_id = item.get("alternative_id")
            policy_score = _safe_float(item.get("policy_agent", {}).get("response", {}).get("score"), 0.0)
            financial_score = _safe_float(item.get("financial_agent", {}).get("response", {}).get("score"), 0.0)
            past_decision_score = _extract_past_score(item)

            active_scores = {
                "policy_agent": policy_score,
                "financial_agent": financial_score,
            }
            if _extract_past_has_signal(item):
                active_scores["past_decision_agent"] = past_decision_score

            active_weight_total = sum(agent_weights.get(agent_key, 0.0) for agent_key in active_scores) or 1.0

            score_fusion = round(
                sum(
                    agent_weights.get(agent_key, 0.0) * score
                    for agent_key, score in active_scores.items()
                ) / active_weight_total,
                4,
            )
            borda_norm = round(borda_norm_by_alternative.get(alternative_id, 1.0), 4)
            aggregate_score = round(
                (config.score_fusion_weight * score_fusion) + (config.borda_weight * borda_norm),
                4,
            )

            scored_alternatives.append(
                {
                    **item,
                    "layer_4": {
                        "score_fusion": score_fusion,
                        "borda_norm": borda_norm,
                        "aggregate_score": aggregate_score,
                        "score_inputs": {
                            "policy_score": policy_score,
                            "financial_score": financial_score,
                            "past_decision_score": past_decision_score,
                            "past_decision_has_signal": _extract_past_has_signal(item),
                        },
                    },
                }
            )

        score_fusion_ranked = sorted(
            scored_alternatives,
            key=lambda item: (item.get("layer_4", {}).get("score_fusion", 0.0),) + _ranking_tuple(item, "policy_agent", "score")[1:],
            reverse=True,
        )
        aggregate_ranked = sorted(
            scored_alternatives,
            key=lambda item: (item.get("layer_4", {}).get("aggregate_score", 0.0),) + _ranking_tuple(item, "policy_agent", "score")[1:],
            reverse=True,
        )

        return PhaseResult(
            name=self.name,
            status="success",
            data={
                "message": "Layer 4 score fusion, Borda consensus, and aggregate score computed.",
                "surviving_alternatives_count": len(surviving_alternatives),
                "score_fusion_weight": config.score_fusion_weight,
                "borda_weight": config.borda_weight,
                "policy_ranked_survivors": policy_ranking,
                "financial_ranked_survivors": financial_ranking,
                "past_decision_ranked_survivors": past_decision_ranking,
                "scored_alternatives": scored_alternatives,
                "score_fusion_ranked_alternatives": self._format_ranked_output(score_fusion_ranked, "score_fusion"),
                "borda_ranked_alternatives": self._format_ranked_output(scored_alternatives, "borda_norm"),
                "aggregate_ranked_alternatives": self._format_ranked_output(aggregate_ranked, "aggregate_score"),
            },
        )

    def _compute_borda_norm(
        self,
        policy_ranking: list[dict[str, Any]],
        financial_ranking: list[dict[str, Any]],
        past_decision_ranking: list[dict[str, Any]],
        agent_weights: dict[str, float],
    ) -> dict[Any, float]:
        rankings_by_agent = {
            "policy_agent": policy_ranking,
            "financial_agent": financial_ranking,
            "past_decision_agent": past_decision_ranking,
        }

        if not policy_ranking:
            return {}

        all_alternative_ids = {
            row.get("alternative_id")
            for ranking in rankings_by_agent.values()
            for row in ranking
        }
        borda_scores: dict[Any, float] = {}
        active_weight_totals: dict[Any, float] = {}
        for agent_key, ranking in rankings_by_agent.items():
            alternatives_count = len(ranking)
            if alternatives_count == 0:
                continue
            for row in ranking:
                points = alternatives_count - row.get("rank", 0) + 1
                alternative_id = row.get("alternative_id")
                borda_scores[alternative_id] = borda_scores.get(alternative_id, 0.0) + (
                    agent_weights.get(agent_key, 0.0) * points
                )
                active_weight_totals[alternative_id] = active_weight_totals.get(alternative_id, 0.0) + agent_weights.get(agent_key, 0.0)

        for alternative_id in all_alternative_ids:
            weight_total = active_weight_totals.get(alternative_id, 0.0)
            if weight_total > 0:
                borda_scores[alternative_id] = borda_scores.get(alternative_id, 0.0) / weight_total

        min_borda = min(borda_scores.values())
        max_borda = max(borda_scores.values())
        if max_borda == min_borda:
            return {alternative_id: 1.0 for alternative_id in borda_scores}

        normalized: dict[Any, float] = {}
        for alternative_id, borda_score in borda_scores.items():
            normalized[alternative_id] = (borda_score - min_borda) / (max_borda - min_borda)

        return normalized

    def _format_ranked_output(self, items: list[dict[str, Any]], metric_key: str) -> list[dict[str, Any]]:
        sorted_items = sorted(
            items,
            key=lambda item: (item.get("layer_4", {}).get(metric_key, 0.0),) + _ranking_tuple(item, "policy_agent", "score")[1:],
            reverse=True,
        )

        ranked_output = []
        for index, item in enumerate(sorted_items, start=1):
            ranked_output.append(
                {
                    "rank": index,
                    "alternative_id": item.get("alternative_id"),
                    "alternative_name": item.get("alternative_name"),
                    "clinical_rank": item.get("clinical_rank"),
                    metric_key: item.get("layer_4", {}).get(metric_key),
                    "layer_4": item.get("layer_4", {}),
                    "tie_break_context": {
                        "clinical_composite_score": _extract_clinical_composite_score(item),
                        "policy_score": _extract_policy_score(item),
                        "projected_total_cost": _extract_projected_total_cost(item),
                        "historical_approval_rate": _extract_historical_approval_rate(item),
                    },
                }
            )

        return ranked_output


class Layer5RiskAdjustmentPhase(BasePhase):
    name = "phase_06_layer_5_risk_adjustment"

    def execute(self, context: dict[str, Any]) -> PhaseResult:
        request_id = str(context.get("request_id", ""))
        config = context.get("config")
        layer_4_data = context.get("phase_05_layer_4_scoring", {})
        scored_alternatives = layer_4_data.get("scored_alternatives", [])

        _trace(request_id, "7) Layer 5: risk adjustment")

        if not scored_alternatives:
            return PhaseResult(
                name=self.name,
                status="success",
                data={
                    "message": "Layer 5 skipped because no scored alternatives available.",
                    "risk_adjusted_alternatives": [],
                    "risk_adjusted_ranked_alternatives": [],
                },
            )

        risk_penalties = {
            "clinical_ambiguity": config.clinical_ambiguity_penalty,
            "cumulative_risk": config.cumulative_risk_penalty,
            "polypharmacy": config.polypharmacy_penalty,
        }

        risk_adjusted_alternatives = []
        for item in scored_alternatives:
            clinical_result = item.get("clinical_agent_result", {})
            safety_flags = clinical_result.get("stage_c", {}).get("safety_flags", {})

            applied_penalties = []
            total_penalty = 0.0
            for flag_name, penalty_value in risk_penalties.items():
                if bool(safety_flags.get(flag_name, False)):
                    applied_penalties.append({"flag": flag_name, "penalty": penalty_value})
                    total_penalty += penalty_value

            aggregate_score = _safe_float(item.get("layer_4", {}).get("aggregate_score"), 0.0)
            adjusted_score = round(max(0.0, aggregate_score + total_penalty), 4)

            risk_adjusted_alternatives.append(
                {
                    **item,
                    "layer_5": {
                        "safety_flags": safety_flags,
                        "applied_penalties": applied_penalties,
                        "total_penalty": round(total_penalty, 4),
                        "adjusted_score": adjusted_score,
                    },
                }
            )
            _trace(request_id, f"7) Layer 5 [{item.get('alternative_id')}] {item.get('alternative_name')}: adjusted_score={adjusted_score:.4f} (aggregate={aggregate_score:.4f}, risk_penalty={total_penalty:.4f})")

        risk_adjusted_ranked = sorted(
            risk_adjusted_alternatives,
            key=lambda item: (item.get("layer_5", {}).get("adjusted_score", 0.0),) + _ranking_tuple(item, "policy_agent", "score")[1:],
            reverse=True,
        )

        return PhaseResult(
            name=self.name,
            status="success",
            data={
                "message": "Layer 5 risk adjustment applied.",
                "scoring_alternatives_count": len(scored_alternatives),
                "risk_penalties_config": risk_penalties,
                "risk_adjusted_alternatives": risk_adjusted_alternatives,
                "risk_adjusted_ranked_alternatives": self._format_ranked_output(risk_adjusted_ranked),
            },
        )

    def _format_ranked_output(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        ranked_output = []
        for index, item in enumerate(items, start=1):
            ranked_output.append(
                {
                    "rank": index,
                    "alternative_id": item.get("alternative_id"),
                    "alternative_name": item.get("alternative_name"),
                    "clinical_rank": item.get("clinical_rank"),
                    "adjusted_score": item.get("layer_5", {}).get("adjusted_score"),
                    "layer_5": item.get("layer_5", {}),
                    "tie_break_context": {
                        "clinical_composite_score": _extract_clinical_composite_score(item),
                        "policy_score": _extract_policy_score(item),
                        "projected_total_cost": _extract_projected_total_cost(item),
                        "historical_approval_rate": _extract_historical_approval_rate(item),
                    },
                }
            )
        return ranked_output


class Layer6FinalRankingPhase(BasePhase):
    name = "phase_07_layer_6_final_ranking"

    def execute(self, context: dict[str, Any]) -> PhaseResult:
        request_id = str(context.get("request_id", ""))
        config = context.get("config")
        layer_5_data = context.get("phase_06_layer_5_risk_adjustment", {})
        
        risk_adjusted_alternatives = layer_5_data.get("risk_adjusted_alternatives", [])

        # Escalation is carried from Layer 2 flags on each alternative; do not duplicate rows.
        all_alternatives = risk_adjusted_alternatives
        escalated_count = sum(
            1
            for alt in all_alternatives
            if bool((alt.get("layer_2", {}) if isinstance(alt.get("layer_2", {}), dict) else {}).get("requires_mandatory_escalation", False))
        )

        if not all_alternatives:
            return PhaseResult(
                name=self.name,
                status="success",
                data={
                    "message": "Layer 6 skipped because no alternatives available.",
                    "final_ranked_alternatives": [],
                },
            )

        final_ranked = sorted(
            all_alternatives,
            key=lambda item: self._final_ranking_tuple(item),
            reverse=True,
        )

        _trace(request_id, "7) Layer 6: final ranking and decision band assignment")

        return PhaseResult(
            name=self.name,
            status="success",
            data={
                "message": "Layer 6 final ranking and decision bands computed.",
                "normal_path_alternatives": len(risk_adjusted_alternatives),
                "escalated_alternatives": escalated_count,
                "final_ranked_alternatives": self._format_final_ranked_output(final_ranked, config, request_id),
                "decision_band_thresholds": {
                    "auto_accept_threshold": config.auto_accept_threshold,
                    "llm_governance_review_threshold": config.llm_governance_review_threshold,
                    "provider_review_threshold": config.provider_review_threshold,
                },
            },
        )

    def _final_ranking_tuple(self, item: dict[str, Any]) -> tuple[float, float, float, float, float]:
        return (
            _safe_float(item.get("layer_5", {}).get("adjusted_score"), 0.0),
            _extract_clinical_composite_score(item),
            _extract_policy_score(item),
            -_extract_projected_total_cost(item),
            _extract_historical_approval_rate(item),
        )

    def _is_unresolved_final_tie(self, left: dict[str, Any], right: dict[str, Any]) -> bool:
        return self._final_ranking_tuple(left) == self._final_ranking_tuple(right)

    def _decision_band(
        self,
        adjusted_score: float,
        requires_mandatory_escalation: bool,
        hard_gate_flags: list[str],
        config: Any,
    ) -> dict[str, Any]:
        if requires_mandatory_escalation:
            reason_suffix = ",".join(hard_gate_flags) if hard_gate_flags else "hard_gate"
            return {
                "band": 3,
                "label": "Provider Review",
                "decision": "Provider Review",
                "provider_review_required": True,
                "reason": f"hard_gate_triggered:{reason_suffix}",
                "governance_review_candidate": False,
            }

        if adjusted_score > config.auto_accept_threshold:
            return {
                "band": 1,
                "label": "Auto Accept",
                "decision": "Auto Accept",
                "provider_review_required": False,
                "reason": "score_above_auto_accept_threshold",
                "governance_review_candidate": False,
            }

        if adjusted_score >= config.llm_governance_review_threshold:
            return {
                "band": 2,
                "label": "LLM Governance Review",
                "decision": "Pending LLM Review",
                "provider_review_required": False,
                "reason": "score_in_llm_governance_review_band",
                "governance_review_candidate": True,
            }

        if adjusted_score >= config.provider_review_threshold:
            return {
                "band": 3,
                "label": "Provider Review",
                "decision": "Provider Review",
                "provider_review_required": False,
                "reason": "score_in_provider_review_band",
                "governance_review_candidate": False,
            }

        return {
            "band": 4,
            "label": "Dispense as Written (DAW)",
            "decision": "Dispense as Written",
            "provider_review_required": False,
            "reason": "score_below_provider_review_threshold",
            "governance_review_candidate": False,
        }

    def _format_final_ranked_output(self, items: list[dict[str, Any]], config: Any, request_id: str = "") -> list[dict[str, Any]]:
        ranked_output = []
        previous_tuple: tuple[float, float, float, float, float] | None = None
        previous_rank = 0
        for index, item in enumerate(items, start=1):
            unresolved_tie = False
            if index > 1 and self._is_unresolved_final_tie(items[index - 2], item):
                unresolved_tie = True
            if index < len(items) and self._is_unresolved_final_tie(item, items[index]):
                unresolved_tie = True

            current_tuple = self._final_ranking_tuple(item)
            if previous_tuple is not None and current_tuple == previous_tuple:
                rank = previous_rank
            else:
                rank = index
            previous_tuple = current_tuple
            previous_rank = rank

            adjusted_score = _safe_float(item.get("layer_5", {}).get("adjusted_score"), 0.0)
            layer_2 = item.get("layer_2", {}) if isinstance(item.get("layer_2", {}), dict) else {}
            requires_mandatory_escalation = bool(layer_2.get("requires_mandatory_escalation", False))
            hard_gate_flags_raw = layer_2.get("hard_gate_flags", [])
            hard_gate_flags = [str(flag) for flag in hard_gate_flags_raw] if isinstance(hard_gate_flags_raw, list) else []
            decision_band = self._decision_band(
                adjusted_score,
                requires_mandatory_escalation,
                hard_gate_flags,
                config,
            )

            policy_state = _extract_policy_state(item)

            safe = _extract_safe(item)
            clinical_pass = _extract_clinical_threshold_pass(item, config)
            financial_pass = _safe_float(_extract_financial_response(item).get("score"), 0.0) >= config.financial_threshold
            past_has_signal = _extract_past_has_signal(item)
            past_pass = True if not past_has_signal else _extract_past_score(item) >= config.past_decision_threshold

            core_three_pass = (
                safe
                and policy_state == "pass"
                and clinical_pass
                and financial_pass
            )
            full_survivor = core_three_pass and (not requires_mandatory_escalation) and (not past_has_signal or past_pass)
            fails_only_past = core_three_pass and (not requires_mandatory_escalation) and past_has_signal and (not past_pass)
            policy_pending_reviewable = (
                policy_state == "pending"
                and safe
                and clinical_pass
                and financial_pass
                and (not past_has_signal or past_pass)
            )
            requires_clinical_escalation_only = (
                requires_mandatory_escalation
                and core_three_pass
                and (not past_has_signal or past_pass)
            )
            review_eligible = (
                full_survivor
                or fails_only_past
                or policy_pending_reviewable
                or requires_clinical_escalation_only
            )

            if int(_safe_float(decision_band.get("band"), 0.0)) == 3 and not review_eligible:
                decision_band = {
                    **decision_band,
                    "band": 4,
                    "label": "Dispense as Written (DAW)",
                    "decision": "Dispense as Written",
                    "provider_review_required": False,
                    "reason": "not_review_eligible_after_gate_checks",
                }

            if policy_state == "deny":
                decision_band = {
                    **decision_band,
                    "band": 4,
                    "label": "Policy Denied",
                    "decision": "Policy Denied",
                    "provider_review_required": False,
                }

            trace_label = str(decision_band.get('label') or '')

            _trace(request_id, f"7) Layer 6 rank={rank} [{item.get('alternative_id')}] {item.get('alternative_name')}: adjusted_score={adjusted_score:.4f} → band={decision_band.get('band')} ({trace_label})")

            ranked_output.append(
                {
                    "rank": rank,
                    "alternative_id": item.get("alternative_id"),
                    "alternative_name": item.get("alternative_name"),
                    "clinical_rank": item.get("clinical_rank"),
                    "adjusted_score": adjusted_score,
                    "clinical_agent_result": item.get("clinical_agent_result", {}),
                    "policy_agent": item.get("policy_agent", {}),
                    "financial_agent": item.get("financial_agent", {}),
                    "past_decision_agent": item.get("past_decision_agent", {}),
                    "layer_4": item.get("layer_4", {}),
                    "layer_5": item.get("layer_5", {}),
                    "decision_band": decision_band,
                    "tie_break_context": {
                        "clinical_composite_score": _extract_clinical_composite_score(item),
                        "policy_score": _extract_policy_score(item),
                        "projected_total_cost": _extract_projected_total_cost(item),
                        "historical_approval_rate": _extract_historical_approval_rate(item),
                        "unresolved_tie": unresolved_tie,
                    },
                }
            )

        return ranked_output


class Layer7LLMGovernanceReviewPhase(BasePhase):
    name = "phase_08_layer_7_llm_governance_review"
    _ALLOWED_TRIGGER_TYPES = {
        "UNADDRESSED_SAFETY_CONCERN",
        "MATERIAL_REASONING_CONFLICT",
        "INSUFFICIENT_RATIONALE",
    }

    def __init__(
        self,
        llm_client: Layer7LLMClient | None = None,
        prompt_builder: Layer7PromptBuilder | None = None,
    ) -> None:
        self.llm_client = llm_client or Layer7LLMClient()
        self.prompt_builder = prompt_builder or Layer7PromptBuilder()

    def execute(self, context: dict[str, Any]) -> PhaseResult:
        request_id = str(context.get("request_id", ""))
        runtime_options = context.get("runtime_options", {})
        layer_6_data = context.get("phase_07_layer_6_final_ranking", {})
        layer_5_data = context.get("phase_06_layer_5_risk_adjustment", {})
        final_ranked_alternatives = layer_6_data.get("final_ranked_alternatives", [])

        if not final_ranked_alternatives:
            return PhaseResult(
                name=self.name,
                status="success",
                data={
                    "message": "Layer 7 skipped because no Layer 6 alternatives are available.",
                    "reviewed_alternatives_count": 0,
                    "llm_calls_made": 0,
                    "llm_fail_safe_count": 0,
                    "layer_7_decisions": [],
                },
            )

        risk_adjusted_by_id: dict[Any, dict[str, Any]] = {
            item.get("alternative_id"): item
            for item in layer_5_data.get("risk_adjusted_alternatives", [])
        }

        decisions: list[dict[str, Any]] = []
        llm_calls_made = 0
        llm_fail_safe_count = 0

        _trace(request_id, "8) Layer 7 governance review: checking Band 2 candidates")

        for ranked_item in final_ranked_alternatives:
            pre_band = ranked_item.get("decision_band", {}).get("band")
            should_review = (pre_band == 2)

            if not should_review:
                decisions.append(
                    {
                        "rank": ranked_item.get("rank"),
                        "alternative_id": ranked_item.get("alternative_id"),
                        "alternative_name": ranked_item.get("alternative_name"),
                        "pre_layer_7_band": pre_band,
                        "post_layer_7_band": pre_band,
                        "governance_review_applied": False,
                        "downgraded": False,
                        "final_decision": ranked_item.get("decision_band", {}).get("decision"),
                        "governance_output": None,
                    }
                )
                continue

            llm_calls_made += 1

            governance_output, fail_safe_error = self._run_governance_review(
                request_id=str(context.get("request_id", "")),
                ranked_item=ranked_item,
                full_ranking=final_ranked_alternatives,
                risk_adjusted_item=risk_adjusted_by_id.get(ranked_item.get("alternative_id")),
                runtime_options=runtime_options,
            )

            if fail_safe_error is not None:
                llm_fail_safe_count += 1
                decisions.append(
                    self._build_fail_safe_decision(
                        ranked_item,
                        governance_output,
                        fail_safe_error,
                    )
                )
                continue

            should_downgrade = self._should_downgrade(governance_output)
            if should_downgrade:
                decisions.append(
                    {
                        "rank": ranked_item.get("rank"),
                        "alternative_id": ranked_item.get("alternative_id"),
                        "alternative_name": ranked_item.get("alternative_name"),
                        "pre_layer_7_band": 2,
                        "post_layer_7_band": 3,
                        "governance_review_applied": True,
                        "downgraded": True,
                        "final_decision": "Provider Review",
                        "governance_output": governance_output,
                    }
                )
            else:
                decisions.append(
                    {
                        "rank": ranked_item.get("rank"),
                        "alternative_id": ranked_item.get("alternative_id"),
                        "alternative_name": ranked_item.get("alternative_name"),
                        "pre_layer_7_band": 2,
                        "post_layer_7_band": 1,
                        "governance_review_applied": True,
                        "downgraded": False,
                        "final_decision": "Auto Accept",
                        "governance_output": governance_output,
                    }
                )

        return PhaseResult(
            name=self.name,
            status="success",
            data={
                "message": "Layer 7 LLM governance review completed.",
                "reviewed_alternatives_count": sum(1 for item in decisions if item.get("governance_review_applied")),
                "llm_calls_made": llm_calls_made,
                "llm_fail_safe_count": llm_fail_safe_count,
                "layer_7_decisions": decisions,
                "allowed_trigger_types": sorted(self._ALLOWED_TRIGGER_TYPES),
                "downgrade_requirements": {
                    "trigger_detected": True,
                    "trigger_type_must_be_allowed": True,
                    "confidence_at_least": 0.90,
                    "evidence_required": True,
                },
            },
        )

    def _build_fail_safe_decision(
        self,
        ranked_item: dict[str, Any],
        governance_output: dict[str, Any],
        fail_safe_error: str,
    ) -> dict[str, Any]:
        return {
            "rank": ranked_item.get("rank"),
            "alternative_id": ranked_item.get("alternative_id"),
            "alternative_name": ranked_item.get("alternative_name"),
            "pre_layer_7_band": 2,
            "post_layer_7_band": 3,
            "governance_review_applied": True,
            "downgraded": True,
            "final_decision": "Provider Review",
            "governance_output": governance_output,
            "fail_safe_reason": fail_safe_error,
        }

    def _run_governance_review(
        self,
        *,
        request_id: str,
        ranked_item: dict[str, Any],
        full_ranking: list[dict[str, Any]],
        risk_adjusted_item: dict[str, Any] | None,
        runtime_options: dict[str, Any],
    ) -> tuple[dict[str, Any], str | None]:
        alt_id = ranked_item.get("alternative_id")
        mock_response = self._lookup_mock_response(runtime_options, ranked_item.get("alternative_id"))
        if mock_response is not None:
            normalized = self._normalize_governance_output(mock_response)
            if normalized is None:
                return self._default_governance_output(), "llm_schema_failure"
            _trace(request_id, f"8.a) Layer 7 governance response received for alternative [{alt_id}] (mock)")
            return normalized, None

        try:
            _trace(request_id, f"8.a) Calling Layer 7 governance for alternative [{alt_id}]")
            prompt = self.prompt_builder.build_prompt(
                request_id=request_id,
                selected_alternative=ranked_item,
                final_ranking=full_ranking,
                agent_scores=self._extract_agent_scores(risk_adjusted_item),
                agent_rationales=self._extract_agent_rationales(risk_adjusted_item),
                consensus_indicators=self._extract_consensus_indicators(risk_adjusted_item),
                risk_adjustment_details=(risk_adjusted_item or {}).get("layer_5", {}),
            )
            try:
                raw_response = _run_async_blocking(self.llm_client.call_governance_llm(prompt))
            except Exception as llm_err:
                return self._default_governance_output(), "llm_processing_failure"
            parsed = self._parse_governance_response(raw_response)
            normalized = self._normalize_governance_output(parsed)
            if normalized is None:
                return self._default_governance_output(), "llm_schema_failure"
            _trace(request_id, f"8.b) Layer 7 governance response received for alternative [{alt_id}]")
            return normalized, None
        except Exception as e:
            import traceback
            import sys
            print(f"[ERROR] Layer 7 LLM unexpected exception: {type(e).__name__}: {str(e)}", file=sys.stderr, flush=True)
            traceback.print_exc(file=sys.stderr)
            sys.stderr.flush()
            return self._default_governance_output(), "llm_processing_failure"

    def _lookup_mock_response(self, runtime_options: dict[str, Any], alternative_id: Any) -> dict[str, Any] | None:
        mock_by_alt = runtime_options.get("layer_7_mock_response_by_alternative_id")
        if isinstance(mock_by_alt, dict):
            if alternative_id in mock_by_alt:
                return mock_by_alt[alternative_id]
            alt_key = str(alternative_id)
            if alt_key in mock_by_alt:
                return mock_by_alt[alt_key]
        return None

    def _extract_agent_scores(self, risk_adjusted_item: dict[str, Any] | None) -> dict[str, float]:
        if not risk_adjusted_item:
            return {
                "policy_score": 0.0,
                "financial_score": 0.0,
                "past_decision_score": 0.0,
                "score_fusion": 0.0,
                "borda_norm": 0.0,
                "aggregate_score": 0.0,
                "adjusted_score": 0.0,
            }
        return {
            "policy_score": _safe_float(risk_adjusted_item.get("policy_agent", {}).get("response", {}).get("score"), 0.0),
            "financial_score": _safe_float(risk_adjusted_item.get("financial_agent", {}).get("response", {}).get("score"), 0.0),
            "past_decision_score": _safe_float(
                risk_adjusted_item.get("past_decision_agent", {}).get("response", {}).get("final_score"),
                0.0,
            ),
            "score_fusion": _safe_float(risk_adjusted_item.get("layer_4", {}).get("score_fusion"), 0.0),
            "borda_norm": _safe_float(risk_adjusted_item.get("layer_4", {}).get("borda_norm"), 0.0),
            "aggregate_score": _safe_float(risk_adjusted_item.get("layer_4", {}).get("aggregate_score"), 0.0),
            "adjusted_score": _safe_float(risk_adjusted_item.get("layer_5", {}).get("adjusted_score"), 0.0),
        }

    def _extract_agent_rationales(self, risk_adjusted_item: dict[str, Any] | None) -> dict[str, str]:
        if not risk_adjusted_item:
            return {"policy": "", "financial": "", "past_decision": ""}
        return {
            "policy": str(risk_adjusted_item.get("policy_agent", {}).get("response", {}).get("notes", "")).strip(),
            "financial": str(risk_adjusted_item.get("financial_agent", {}).get("response", {}).get("notes", "")).strip(),
            "past_decision": str(risk_adjusted_item.get("past_decision_agent", {}).get("response", {}).get("notes", "")).strip(),
        }

    def _extract_consensus_indicators(self, risk_adjusted_item: dict[str, Any] | None) -> dict[str, Any]:
        if not risk_adjusted_item:
            return {}
        layer_4 = risk_adjusted_item.get("layer_4", {})
        return {
            "clinical_rank": risk_adjusted_item.get("clinical_rank"),
            "score_fusion": _safe_float(layer_4.get("score_fusion"), 0.0),
            "borda_norm": _safe_float(layer_4.get("borda_norm"), 0.0),
            "aggregate_score": _safe_float(layer_4.get("aggregate_score"), 0.0),
        }

    def _parse_governance_response(self, raw_response: Any) -> dict[str, Any]:
        if isinstance(raw_response, dict):
            return raw_response
        if raw_response is None:
            return {}
        text = str(raw_response).strip()
        if not text:
            return {}
        return json.loads(text)

    def _normalize_governance_output(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        if not isinstance(payload, dict):
            return None

        trigger_detected = bool(payload.get("trigger_detected", False))
        trigger_type_raw = payload.get("trigger_type")
        trigger_type = None if trigger_type_raw in (None, "", "null") else str(trigger_type_raw).strip().upper()
        confidence = _safe_float(payload.get("confidence"), 0.0)
        evidence = payload.get("evidence")
        note = str(payload.get("note", "")).strip()

        if trigger_type is not None and trigger_type not in self._ALLOWED_TRIGGER_TYPES:
            trigger_type = None

        if len(note.split()) > 40:
            note = " ".join(note.split()[:40])

        return {
            "trigger_detected": trigger_detected,
            "trigger_type": trigger_type,
            "confidence": round(confidence, 4),
            "evidence": evidence,
            "note": note,
        }

    def _default_governance_output(self) -> dict[str, Any]:
        return {
            "trigger_detected": False,
            "trigger_type": None,
            "confidence": 0.0,
            "evidence": None,
            "note": "Fail-safe applied.",
        }

    def _has_evidence(self, evidence: Any) -> bool:
        if evidence is None:
            return False
        if isinstance(evidence, str):
            return bool(evidence.strip())
        if isinstance(evidence, (list, tuple, set, dict)):
            return len(evidence) > 0
        return True

    def _should_downgrade(self, governance_output: dict[str, Any]) -> bool:
        return (
            bool(governance_output.get("trigger_detected", False))
            and str(governance_output.get("trigger_type") or "") in self._ALLOWED_TRIGGER_TYPES
            and _safe_float(governance_output.get("confidence"), 0.0) >= 0.90
            and self._has_evidence(governance_output.get("evidence"))
        )


class Layer8SummaryGenerationPhase(BasePhase):
    name = "phase_09_layer_8_summary_generation"

    def __init__(
        self,
        llm_client: Layer7LLMClient | None = None,
        prompt_builder: Layer8PromptBuilder | None = None,
    ) -> None:
        self.llm_client = llm_client or Layer7LLMClient()
        self.prompt_builder = prompt_builder or Layer8PromptBuilder()

    def execute(self, context: dict[str, Any]) -> PhaseResult:
        request_id = str(context.get("request_id", ""))
        runtime_options = context.get("runtime_options", {})
        layer_6_data = context.get("phase_07_layer_6_final_ranking", {})
        layer_7_data = context.get("phase_08_layer_7_llm_governance_review", {})
        config = context.get("config")
        final_ranked = layer_6_data.get("final_ranked_alternatives", [])

        _trace(request_id, "9) Layer 8 summary generation")

        if not final_ranked:
            return PhaseResult(
                name=self.name,
                status="success",
                data={
                    "message": "Layer 8 skipped because no alternatives are available.",
                    "resolution": {
                        "final_outcome": "NO_ALTERNATIVES",
                        "evaluated_alternatives": [],
                        "discarded_alternative_ids": [],
                        "provider_review_list": [],
                        "selected_alternative": None,
                    },
                    "alternatives_summarized": 0,
                    "llm_calls_made": 0,
                    "llm_fail_safe_count": 0,
                    "alternative_summaries": [],
                    "provider_packet": {
                        "required": False,
                        "alternatives": [],
                    },
                    "pbm_packet": {
                        "sent": False,
                        "selected_alternative": None,
                    },
                    "pharmacist_packet": {
                        "sent": False,
                        "selected_alternative": None,
                    },
                },
            )

        layer_7_decisions = layer_7_data.get("layer_7_decisions", [])
        post_band_by_alternative: dict[Any, int] = {}
        for decision in layer_7_decisions:
            post_band_by_alternative[decision.get("alternative_id")] = int(
                _safe_float(decision.get("post_layer_7_band"), 0.0)
            )

        resolution = self._resolve_recommendation_flow(
            final_ranked=final_ranked,
            post_band_by_alternative=post_band_by_alternative,
            config=config,
            runtime_options=runtime_options,
        )

        summaries_map: dict[Any, dict[str, Any]] = {}
        llm_calls_made = 0
        llm_fail_safe_count = 0

        ranked_by_id: dict[Any, dict[str, Any]] = {
            item.get("alternative_id"): item for item in final_ranked
        }

        for alternative_id in resolution["summary_candidate_ids"]:
            ranked_item = ranked_by_id.get(alternative_id)
            if not ranked_item:
                continue

            final_band = int(_safe_float(resolution["band_by_alternative_id"].get(alternative_id), 0.0))
            llm_calls_made += 1
            summary_payload, fail_safe_reason = self._generate_summary_once(
                context=context,
                runtime_options=runtime_options,
                ranked_item=ranked_item,
                final_band=final_band,
            )
            self._overlay_agent_scores_into_summary(summary_payload, ranked_item)

            if fail_safe_reason is not None:
                llm_fail_safe_count += 1

            summary_cards = self._shape_summary_for_band(summary_payload, final_band)

            summaries_map[alternative_id] = {
                "rank": ranked_item.get("rank"),
                "alternative_id": alternative_id,
                "alternative_name": ranked_item.get("alternative_name"),
                "final_band": final_band,
                "summary_cards": summary_cards,
                "summary_generation_fail_safe": fail_safe_reason,
            }

        provider_packet = self._build_provider_packet(resolution, summaries_map)
        pbm_packet = self._build_pbm_packet(resolution, summaries_map, provider_packet)
        pharmacist_packet = self._build_pharmacist_packet(resolution, pbm_packet)

        alternative_summaries = [
            summaries_map[item.get("alternative_id")]
            for item in resolution.get("evaluated_alternatives", [])
            if item.get("alternative_id") in summaries_map
        ]

        return PhaseResult(
            name=self.name,
            status="success",
            data={
                "message": "Layer 8 recommendation resolution and selective summary generation completed.",
                "resolution": {
                    "final_outcome": resolution["final_outcome"],
                    "evaluated_alternatives": resolution["evaluated_alternatives"],
                    "discarded_alternative_ids": resolution["discarded_alternative_ids"],
                    "provider_review_list": resolution["provider_review_list"],
                    "selected_alternative": resolution["selected_alternative"],
                },
                "legacy_routing_summary": resolution["legacy_routing_summary"],
                "alternatives_summarized": len(alternative_summaries),
                "llm_calls_made": llm_calls_made,
                "llm_fail_safe_count": llm_fail_safe_count,
                "alternative_summaries": alternative_summaries,
                "provider_packet": provider_packet,
                "pbm_packet": pbm_packet,
                "pharmacist_packet": pharmacist_packet,
            },
        )

    def _status_from_band(self, band: int) -> str:
        if band == 1:
            return "AUTO_ACCEPT"
        if band == 3:
            return "PROVIDER_REVIEW"
        return "DAW"

    def _resolve_recommendation_flow(
        self,
        *,
        final_ranked: list[dict[str, Any]],
        post_band_by_alternative: dict[Any, int],
        config: OrchestratorConfig,
        runtime_options: dict[str, Any],
    ) -> dict[str, Any]:
        evaluated_alternatives = [
            self._build_candidate_record(item, post_band_by_alternative, config)
            for item in final_ranked
        ]

        full_survivors = [item for item in evaluated_alternatives if self._fully_survives(item)]
        auto_accept_candidates = [
            item
            for item in full_survivors
            if bool(item.get("clears_overall_threshold", False)) and not item.get("governance_downgraded", False)
        ]

        if auto_accept_candidates:
            selected = max(auto_accept_candidates, key=lambda item: item.get("adjusted_score", 0.0))
            selected_id = selected.get("alternative_id")
            discarded_ids = [
                item.get("alternative_id")
                for item in evaluated_alternatives
                if item.get("alternative_id") != selected_id
            ]
            return {
                "final_outcome": "AUTO_ACCEPT_SELECTED",
                "selected_alternative": selected,
                "provider_review_list": [],
                "summary_candidate_ids": [selected_id],
                "discarded_alternative_ids": discarded_ids,
                "band_by_alternative_id": {item.get("alternative_id"): int(item.get("final_band", 0)) for item in evaluated_alternatives},
                "evaluated_alternatives": evaluated_alternatives,
                "legacy_routing_summary": self._build_legacy_routing_summary(
                    decision="auto_approve",
                    chosen_drug=selected_id,
                    review_candidates=[],
                    evaluated_alternatives=evaluated_alternatives,
                    reason="Combined score cleared the overall threshold; candidate swapped in automatically.",
                ),
            }

        review_pool = []
        review_seen: set[Any] = set()
        for candidate in full_survivors:
            self._append_review_candidate(review_pool, review_seen, candidate)
        for candidate in evaluated_alternatives:
            if self._fails_only_past(candidate):
                self._append_review_candidate(review_pool, review_seen, candidate)
            elif self._policy_pending_reviewable(candidate):
                self._append_review_candidate(review_pool, review_seen, candidate)
            elif self._requires_clinical_escalation_only(candidate):
                self._append_review_candidate(review_pool, review_seen, candidate)

        if review_pool:
            selected_id = runtime_options.get("provider_selected_alternative_id")
            selected = None
            if selected_id is not None:
                for item in review_pool:
                    if str(item.get("alternative_id")) == str(selected_id):
                        selected = item
                        break

            discarded_ids = [
                item.get("alternative_id")
                for item in evaluated_alternatives
                if item.get("alternative_id") not in review_seen
            ]
            review_ids = [item.get("alternative_id") for item in review_pool]
            return {
                "final_outcome": "PROVIDER_REVIEW_SELECTION_PENDING" if selected is None else "PROVIDER_SELECTED",
                "selected_alternative": selected,
                "provider_review_list": review_pool,
                "summary_candidate_ids": review_ids,
                "discarded_alternative_ids": discarded_ids,
                "band_by_alternative_id": {item.get("alternative_id"): int(item.get("final_band", 0)) for item in evaluated_alternatives},
                "evaluated_alternatives": evaluated_alternatives,
                "legacy_routing_summary": self._build_legacy_routing_summary(
                    decision="doctor_review",
                    chosen_drug=selected.get("alternative_id") if selected else None,
                    review_candidates=review_pool,
                    evaluated_alternatives=evaluated_alternatives,
                    reason=self._review_reason(review_pool),
                ),
            }

        discarded_ids = [item.get("alternative_id") for item in evaluated_alternatives]
        return {
            "final_outcome": "DISPENSE_AS_WRITTEN",
            "selected_alternative": None,
            "provider_review_list": [],
            "summary_candidate_ids": [],
            "discarded_alternative_ids": discarded_ids,
            "band_by_alternative_id": {item.get("alternative_id"): int(item.get("final_band", 0)) for item in evaluated_alternatives},
            "evaluated_alternatives": evaluated_alternatives,
            "legacy_routing_summary": self._build_legacy_routing_summary(
                decision="keep_original",
                chosen_drug=None,
                review_candidates=[],
                evaluated_alternatives=evaluated_alternatives,
                reason="No candidate cleared the core routing gates; original prescription kept as written.",
            ),
        }

    def _build_candidate_record(
        self,
        item: dict[str, Any],
        post_band_by_alternative: dict[Any, int],
        config: OrchestratorConfig,
    ) -> dict[str, Any]:
        alternative_id = item.get("alternative_id")
        policy_state = _extract_policy_state(item)
        safe = _extract_safe(item)
        past_has_signal = _extract_past_has_signal(item)
        past_score = _extract_past_score(item)
        clinical_pass = _extract_clinical_threshold_pass(item, config)
        policy_pass = policy_state == "pass"
        financial_pass = _safe_float(_extract_financial_response(item).get("score"), 0.0) >= config.financial_threshold
        past_pass = True if not past_has_signal else past_score >= config.past_decision_threshold
        requires_mandatory_escalation = bool(
            item.get("layer_2", {}).get("requires_mandatory_escalation", False)
            or _extract_requires_mandatory_escalation(item)
            or _extract_missing_clinical_data(item)
        )
        adjusted_score = _safe_float(item.get("adjusted_score", item.get("layer_5", {}).get("adjusted_score")), 0.0)
        final_band = post_band_by_alternative.get(
            alternative_id,
            int(_safe_float(item.get("decision_band", {}).get("band"), 0.0)),
        )
        governance_downgraded = final_band == 3 and int(_safe_float(item.get("decision_band", {}).get("band"), 0.0)) == 1

        return {
            "rank": item.get("rank"),
            "alternative_id": alternative_id,
            "alternative_name": item.get("alternative_name"),
            "clinical_rank": item.get("clinical_rank"),
            "adjusted_score": adjusted_score,
            "combined_score": adjusted_score,
            "final_band": final_band,
            "governance_downgraded": governance_downgraded,
            "safe": safe,
            "requires_mandatory_escalation": requires_mandatory_escalation,
            "policy_state": policy_state,
            "pending_type": _extract_policy_response(item).get("pending_type"),
            "has_signal": {
                "policy": True,
                "clinical": True,
                "financial": True,
                "past": past_has_signal,
            },
            "threshold_pass": {
                "policy": policy_pass,
                "clinical": clinical_pass,
                "financial": financial_pass,
                "past": past_pass,
            },
            "passed_gate": safe and not requires_mandatory_escalation and policy_pass and clinical_pass and financial_pass and past_pass,
            "clears_overall_threshold": safe and not requires_mandatory_escalation and policy_pass and clinical_pass and financial_pass and past_pass and adjusted_score >= config.overall_threshold,
            "policy_agent": item.get("policy_agent", {}),
            "financial_agent": item.get("financial_agent", {}),
            "past_decision_agent": item.get("past_decision_agent", {}),
            "clinical_agent_result": item.get("clinical_agent_result", {}),
            "layer_4": item.get("layer_4", {}),
            "layer_5": item.get("layer_5", {}),
        }

    def _core_three_pass(self, candidate: dict[str, Any]) -> bool:
        threshold_pass = candidate.get("threshold_pass", {})
        return (
            bool(candidate.get("safe", True))
            and bool(threshold_pass.get("policy", False))
            and bool(threshold_pass.get("clinical", False))
            and bool(threshold_pass.get("financial", False))
        )

    def _fully_survives(self, candidate: dict[str, Any]) -> bool:
        threshold_pass = candidate.get("threshold_pass", {})
        has_signal = candidate.get("has_signal", {})
        return (
            self._core_three_pass(candidate)
            and not bool(candidate.get("requires_mandatory_escalation", False))
            and (not bool(has_signal.get("past", False)) or bool(threshold_pass.get("past", False)))
            and str(candidate.get("policy_state", "")) == "pass"
        )

    def _fails_only_past(self, candidate: dict[str, Any]) -> bool:
        threshold_pass = candidate.get("threshold_pass", {})
        has_signal = candidate.get("has_signal", {})
        return (
            self._core_three_pass(candidate)
            and not bool(candidate.get("requires_mandatory_escalation", False))
            and bool(has_signal.get("past", False))
            and not bool(threshold_pass.get("past", False))
        )

    def _policy_pending_reviewable(self, candidate: dict[str, Any]) -> bool:
        threshold_pass = candidate.get("threshold_pass", {})
        has_signal = candidate.get("has_signal", {})
        return (
            str(candidate.get("policy_state", "")) == "pending"
            and bool(candidate.get("safe", True))
            and bool(threshold_pass.get("clinical", False))
            and bool(threshold_pass.get("financial", False))
            and (
                (not bool(has_signal.get("past", False)))
                or bool(threshold_pass.get("past", False))
            )
        )

    def _requires_clinical_escalation_only(self, candidate: dict[str, Any]) -> bool:
        threshold_pass = candidate.get("threshold_pass", {})
        has_signal = candidate.get("has_signal", {})
        return (
            bool(candidate.get("requires_mandatory_escalation", False))
            and self._core_three_pass(candidate)
            and (not bool(has_signal.get("past", False)) or bool(threshold_pass.get("past", False)))
        )

    def _append_review_candidate(
        self,
        review_pool: list[dict[str, Any]],
        review_seen: set[Any],
        candidate: dict[str, Any],
    ) -> None:
        alternative_id = candidate.get("alternative_id")
        if alternative_id in review_seen:
            return
        review_seen.add(alternative_id)
        review_pool.append(candidate)

    def _review_reason(self, review_pool: list[dict[str, Any]]) -> str:
        if len(review_pool) == 1:
            candidate = review_pool[0]
            if self._policy_pending_reviewable(candidate):
                return "Single candidate requires doctor review because Policy marked it pending while the non-policy gates passed."
            if self._fails_only_past(candidate):
                return "Single candidate requires doctor review because only Past Decisions failed after the core gates passed."
            if self._requires_clinical_escalation_only(candidate):
                return "Single candidate requires doctor review because the clinical layer flagged mandatory escalation."
            return "Single candidate requires doctor review because it passed the core gates but did not qualify for automatic approval."
        return "Multiple candidates require doctor review; the review pool preserves all viable options that passed the core routing gates."

    def _build_candidate_outcomes(self, evaluated_alternatives: list[dict[str, Any]]) -> list[dict[str, Any]]:
        outcomes = []
        for candidate in evaluated_alternatives:
            if bool(candidate.get("clears_overall_threshold", False)) and not bool(candidate.get("governance_downgraded", False)):
                outcomes.append(
                    {
                        "alternative_id": candidate.get("alternative_id"),
                        "outcome": "auto_approved",
                        "passed_gate": candidate.get("passed_gate"),
                        "combined_score": candidate.get("combined_score"),
                        "clears_overall_threshold": candidate.get("clears_overall_threshold"),
                    }
                )
                continue

            if (
                self._fails_only_past(candidate)
                or self._policy_pending_reviewable(candidate)
                or self._requires_clinical_escalation_only(candidate)
                or (self._fully_survives(candidate) and not bool(candidate.get("clears_overall_threshold", False)))
                or bool(candidate.get("governance_downgraded", False))
            ):
                if self._policy_pending_reviewable(candidate):
                    escalation_reason = "Candidate requires doctor review because Policy marked it pending while the non-policy gates passed."
                elif self._fails_only_past(candidate):
                    escalation_reason = "Candidate requires doctor review because core Policy/Clinical/Financial checks passed, but Past Decisions failed threshold."
                elif self._requires_clinical_escalation_only(candidate):
                    escalation_reason = "Candidate requires doctor review because the clinical layer flagged mandatory escalation."
                elif bool(candidate.get("governance_downgraded", False)):
                    escalation_reason = "Candidate requires doctor review because the governance layer downgraded a provisional auto-approval."
                else:
                    escalation_reason = "Candidate requires doctor review because it passed the gate but stayed below the overall approval threshold."

                outcomes.append(
                    {
                        "alternative_id": candidate.get("alternative_id"),
                        "outcome": "escalated",
                        "passed_gate": candidate.get("passed_gate"),
                        "combined_score": candidate.get("combined_score"),
                        "clears_overall_threshold": candidate.get("clears_overall_threshold"),
                        "escalation_reason": escalation_reason,
                    }
                )
                continue

            outcomes.append(
                {
                    "alternative_id": candidate.get("alternative_id"),
                    "outcome": "rejected",
                    "passed_gate": candidate.get("passed_gate"),
                    "combined_score": candidate.get("combined_score"),
                    "clears_overall_threshold": candidate.get("clears_overall_threshold"),
                    "rejection_reason": "One or more gate checks failed.",
                }
            )

        return outcomes

    def _build_legacy_routing_summary(
        self,
        *,
        decision: str,
        chosen_drug: Any,
        review_candidates: list[dict[str, Any]],
        evaluated_alternatives: list[dict[str, Any]],
        reason: str,
    ) -> dict[str, Any]:
        return {
            "decision": decision,
            "chosen_drug": chosen_drug,
            "review_options": [candidate.get("alternative_id") for candidate in review_candidates],
            "reason": reason,
            "confidence_score": max((candidate.get("combined_score", 0.0) for candidate in evaluated_alternatives), default=None),
            "escalated": decision == "doctor_review",
            "candidate_outcomes": self._build_candidate_outcomes(evaluated_alternatives),
        }

    def _build_provider_packet(
        self,
        resolution: dict[str, Any],
        summaries_map: dict[Any, dict[str, Any]],
    ) -> dict[str, Any]:
        provider_list = resolution.get("provider_review_list", [])
        if not provider_list:
            return {
                "required": False,
                "alternatives": [],
            }

        alternatives = []
        for item in provider_list:
            alternative_id = item.get("alternative_id")
            if alternative_id not in summaries_map:
                continue
            summary_for_provider = json.loads(json.dumps(summaries_map[alternative_id]))
            summary_cards = summary_for_provider.get("summary_cards", {}) if isinstance(summary_for_provider.get("summary_cards", {}), dict) else {}
            clinical_card = summary_cards.get("clinical_agent", {}) if isinstance(summary_cards.get("clinical_agent", {}), dict) else {}

            stage_a_reasoning = str(item.get("clinical_agent_result", {}).get("stage_a", {}).get("reasoning") or "").strip()
            stage_b_reasoning = str(item.get("clinical_agent_result", {}).get("stage_b", {}).get("reasoning") or "").strip()
            agent_reasoning: dict[str, str] = {
                "stage_a": stage_a_reasoning,
                "stage_b": stage_b_reasoning,
            }
            clinical_card["agent_reasoning"] = agent_reasoning
            summary_cards["clinical_agent"] = clinical_card
            summary_for_provider["summary_cards"] = summary_cards

            alternatives.append(
                {
                    "rank": item.get("rank"),
                    "alternative_id": alternative_id,
                    "alternative_name": item.get("alternative_name"),
                    "summary": summary_for_provider,
                }
            )

        return {
            "required": True,
            "alternatives": alternatives,
        }

    def _build_pbm_packet(
        self,
        resolution: dict[str, Any],
        summaries_map: dict[Any, dict[str, Any]],
        provider_packet: dict[str, Any],
    ) -> dict[str, Any]:
        def _strip_provider_only_reasoning(payload: dict[str, Any]) -> dict[str, Any]:
            cloned = json.loads(json.dumps(payload))
            summary_cards = cloned.get("summary_cards", {}) if isinstance(cloned.get("summary_cards", {}), dict) else {}
            clinical = summary_cards.get("clinical_agent", {}) if isinstance(summary_cards.get("clinical_agent", {}), dict) else {}
            clinical.pop("agent_reasoning", None)
            clinical.pop("agent_summary", None)
            summary_cards["clinical_agent"] = clinical
            cloned["summary_cards"] = summary_cards
            return cloned

        final_outcome = str(resolution.get("final_outcome", "")).strip().upper()
        selected = resolution.get("selected_alternative")
        provider_alternatives = provider_packet.get("alternatives", []) if isinstance(provider_packet, dict) else []

        if final_outcome == "AUTO_ACCEPT_SELECTED" and selected:
            selected_id = selected.get("alternative_id")
            return {
                "sent": True,
                "selected_alternative": {
                    **selected,
                    "summary": summaries_map.get(selected_id),
                },
                "review_alternatives": [],
            }

        if provider_alternatives:
            pbm_review_alternatives = []
            for alt in provider_alternatives:
                if not isinstance(alt, dict):
                    continue
                alt_summary = alt.get("summary") if isinstance(alt.get("summary"), dict) else {}
                pbm_review_alternatives.append(
                    {
                        "rank": alt.get("rank"),
                        "alternative_id": alt.get("alternative_id"),
                        "alternative_name": alt.get("alternative_name"),
                        "summary": _strip_provider_only_reasoning(alt_summary),
                    }
                )

            selected_payload = None
            if selected:
                selected_id = selected.get("alternative_id")
                selected_payload = {
                    **selected,
                    "summary": _strip_provider_only_reasoning(summaries_map.get(selected_id, {})),
                }
            return {
                "sent": True,
                "selected_alternative": selected_payload,
                "review_alternatives": pbm_review_alternatives,
            }

        if final_outcome == "DISPENSE_AS_WRITTEN":
            return {
                "sent": True,
                "selected_alternative": None,
                "review_alternatives": [],
                "daw": True,
            }

        if not selected:
            return {
                "sent": False,
                "selected_alternative": None,
                "review_alternatives": [],
            }

        selected_id = selected.get("alternative_id")
        return {
            "sent": True,
            "selected_alternative": {
                **selected,
                "summary": _strip_provider_only_reasoning(summaries_map.get(selected_id, {})),
            },
            "review_alternatives": [],
        }

    def _build_pharmacist_packet(self, resolution: dict[str, Any], pbm_packet: dict[str, Any]) -> dict[str, Any]:
        final_outcome = str(resolution.get("final_outcome", "")).strip().upper()
        if not pbm_packet.get("sent", False) and final_outcome != "DISPENSE_AS_WRITTEN":
            return {
                "sent": False,
                "selected_alternative": None,
                "review_alternatives": [],
            }

        packet = {
            "sent": True,
            "selected_alternative": pbm_packet.get("selected_alternative"),
            "review_alternatives": pbm_packet.get("review_alternatives", []),
        }
        if final_outcome == "DISPENSE_AS_WRITTEN":
            packet["daw"] = True
        return packet

    def _generate_summary_once(
        self,
        *,
        context: dict[str, Any],
        runtime_options: dict[str, Any],
        ranked_item: dict[str, Any],
        final_band: int,
    ) -> tuple[dict[str, Any], str | None]:
        request_id = str(context.get("request_id", ""))
        alt_id = ranked_item.get("alternative_id")
        try:
            clinical_context = ranked_item.get("clinical_agent_result", {})
            policy_context = ranked_item.get("policy_agent", {}).get("response", {})
            financial_context = ranked_item.get("financial_agent", {}).get("response", {})
            past_decision_context = ranked_item.get("past_decision_agent", {}).get("response", {})

            prompt = self.prompt_builder.build_prompt(
                request_id=str(context.get("request_id", "")),
                alternative=ranked_item,
                final_band=final_band,
                clinical_context=clinical_context,
                policy_context=policy_context,
                financial_context=financial_context,
                past_decision_context=past_decision_context,
            )
            _trace(request_id, f"9.a) Calling Layer 8 summary for alternative [{alt_id}]")
            try:
                raw_response = _run_async_blocking(self.llm_client.call_governance_llm(prompt))
            except Exception as llm_err:
                import sys
                print(f"[ERROR] Layer 8 LLM call failed for alt_id={alt_id}: {type(llm_err).__name__}: {str(llm_err)}", file=sys.stderr, flush=True)
                _trace(request_id, f"9.x) Layer 8 LLM failed: {type(llm_err).__name__}: {str(llm_err)}")
                return self._fallback_summary_payload(ranked_item), "llm_processing_failure"
            parsed = self._parse_json_payload(raw_response)
            normalized = self._normalize_summary_payload(parsed)
            if normalized is None:
                return self._fallback_summary_payload(ranked_item), "llm_schema_failure"
            _trace(request_id, f"9.b) Layer 8 summary received for alternative [{alt_id}]")
            return normalized, None
        except Exception as e:
            import traceback
            import sys
            print(f"[ERROR] Layer 8 LLM unexpected exception: {type(e).__name__}: {str(e)}", file=sys.stderr, flush=True)
            traceback.print_exc(file=sys.stderr)
            sys.stderr.flush()
            return self._fallback_summary_payload(ranked_item), "llm_processing_failure"

    def _lookup_mock_response(self, runtime_options: dict[str, Any], alternative_id: Any) -> dict[str, Any] | None:
        mock_by_alt = runtime_options.get("layer_8_mock_response_by_alternative_id")
        if isinstance(mock_by_alt, dict):
            if alternative_id in mock_by_alt:
                return mock_by_alt[alternative_id]
            alt_key = str(alternative_id)
            if alt_key in mock_by_alt:
                return mock_by_alt[alt_key]
        return None

    def _parse_json_payload(self, raw_response: Any) -> dict[str, Any]:
        if isinstance(raw_response, dict):
            return raw_response
        text = str(raw_response or "").strip()
        if not text:
            return {}
        return json.loads(text)

    def _shape_summary_for_band(self, payload: dict[str, Any], final_band: int) -> dict[str, Any]:
        shaped = {
            "financial_agent": payload.get("financial_agent", {}),
            "insurance_context": payload.get("insurance_context", {}),
            "clinical_agent": payload.get("clinical_agent", {}),
            "policy_agent": payload.get("policy_agent", {}),
            "past_decision_agent": payload.get("past_decision_agent", {}),
        }

        clinical_card = dict(shaped.get("clinical_agent", {}))
        if final_band != 3 and "agent_summary" in clinical_card:
            clinical_card.pop("agent_summary", None)
        shaped["clinical_agent"] = clinical_card
        return shaped

    def _normalize_summary_payload(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        if not isinstance(payload, dict):
            return None

        financial = payload.get("financial_agent", {}) if isinstance(payload.get("financial_agent", {}), dict) else {}
        insurance = payload.get("insurance_context", {}) if isinstance(payload.get("insurance_context", {}), dict) else {}
        clinical = payload.get("clinical_agent", {}) if isinstance(payload.get("clinical_agent", {}), dict) else {}
        policy = payload.get("policy_agent", {}) if isinstance(payload.get("policy_agent", {}), dict) else {}
        past = payload.get("past_decision_agent", {}) if isinstance(payload.get("past_decision_agent", {}), dict) else {}

        return {
            "financial_agent": {
                "status": str(financial.get("status", "COST_FAVORABLE")),
                "original_drug": str(financial.get("original_drug", "")),
                "alternative_drug": str(financial.get("alternative_drug", "")),
                "original_tier": str(financial.get("original_tier", "")),
                "alternative_tier": str(financial.get("alternative_tier", "")),
                "original_total_price": str(financial.get("original_total_price", "")),
                "alternative_total_price": str(financial.get("alternative_total_price", "")),
                "original_copay": str(financial.get("original_copay", "")),
                "alternative_copay": str(financial.get("alternative_copay", "")),
                "original_plan_paid": str(financial.get("original_plan_paid", "")),
                "alternative_plan_paid": str(financial.get("alternative_plan_paid", "")),
                "annual_savings": str(financial.get("annual_savings", "")),
                "savings_percent": str(financial.get("savings_percent", "")),
                "summary": str(financial.get("summary", "")),
                "score": _safe_float(financial.get("score"), 0.0),
            },
            "insurance_context": {
                "insurance_phase": str(insurance.get("insurance_phase", "")),
                "ytd_oop": str(insurance.get("ytd_oop", "")),
                "coinsurance": str(insurance.get("coinsurance", "")),
                "deductible_limit": str(insurance.get("deductible_limit", "")),
                "deductible_met": str(insurance.get("deductible_met", "")),
                "deductible_remaining": str(insurance.get("deductible_remaining", "")),
                "oop_max": str(insurance.get("oop_max", "")),
                "oop_used": str(insurance.get("oop_used", "")),
                "oop_remaining": str(insurance.get("oop_remaining", "")),
            },
            "clinical_agent": {
                "status": str(clinical.get("status", "CLINICALLY_ACCEPTABLE")),
                "clinical_summary": self._normalize_list(clinical.get("clinical_summary"), length=4),
                "safety_summary": self._normalize_list(clinical.get("safety_summary"), length=4),
                "agent_summary": self._normalize_list(clinical.get("agent_summary"), length=2),
            },
            "policy_agent": {
                "status": str(policy.get("status", "POLICY_APPROVED")),
                "original_status": str(policy.get("original_status", "")),
                "alternative_status": str(policy.get("alternative_status", "")),
                "formulary_preference": str(policy.get("formulary_preference", "")),
                "coverage_status": str(policy.get("coverage_status", "")),
                "policy_checks_passed": bool(policy.get("policy_checks_passed", True)),
                "policy_notes": str(policy.get("policy_notes", "")),
                "key_findings": self._normalize_list(policy.get("key_findings"), length=None),
                "score": _safe_float(policy.get("score"), 0.0),
            },
            "past_decision_agent": {
                "status": str(past.get("status", "RECOMMENDED")),
                "historical_confidence": str(past.get("historical_confidence", "High")),
                "summary": str(past.get("summary", "")),
                "recommendation_supported": bool(past.get("recommendation_supported", True)),
                "score": _safe_float(past.get("score"), 0.0),
            },
        }

    def _overlay_agent_scores_into_summary(self, summary_payload: dict[str, Any], ranked_item: dict[str, Any]) -> None:
        """Inject authoritative agent scores from the trace into the summary cards."""
        if not isinstance(summary_payload, dict) or not isinstance(ranked_item, dict):
            return
        policy_resp = (ranked_item.get("policy_agent") or {}).get("response") or {}
        financial_resp = (ranked_item.get("financial_agent") or {}).get("response") or {}
        past_resp = (ranked_item.get("past_decision_agent") or {}).get("response") or {}

        fin_card = summary_payload.get("financial_agent")
        if isinstance(fin_card, dict):
            fin_card["score"] = _safe_float(financial_resp.get("score"), fin_card.get("score", 0.0))

        pol_card = summary_payload.get("policy_agent")
        if isinstance(pol_card, dict):
            pol_card["score"] = _safe_float(policy_resp.get("score"), pol_card.get("score", 0.0))

        past_card = summary_payload.get("past_decision_agent")
        if isinstance(past_card, dict):
            past_card["score"] = _safe_float(
                past_resp.get("final_score", past_resp.get("average_confidence_score")),
                past_card.get("score", 0.0),
            )

    def _normalize_list(self, value: Any, *, length: int | None) -> list[str]:
        items: list[str] = []
        if isinstance(value, list):
            items = [str(item).strip() for item in value if str(item).strip()]
        elif value is not None:
            text = str(value).strip()
            if text:
                items = [text]

        if length is None:
            return items

        if len(items) < length:
            items.extend(["Not provided."] * (length - len(items)))
        return items[:length]

    def _extract_stage_reasoning(self, clinical_result: dict[str, Any], stage_key: str) -> str:
        stage_data = clinical_result.get(stage_key, {}) if isinstance(clinical_result.get(stage_key, {}), dict) else {}
        possible_keys = [
            "reasoning",
            "llm_reasoning",
            "summary",
            "final_statement",
            "note",
        ]
        for key in possible_keys:
            value = stage_data.get(key)
            if value is None:
                continue
            text = str(value).strip()
            if text:
                return text
        return "Reasoning not available in clinical output."

    def _fallback_summary_payload(self, ranked_item: dict[str, Any]) -> dict[str, Any]:
        policy = ranked_item.get("policy_agent", {}).get("response", {})
        financial = ranked_item.get("financial_agent", {}).get("response", {})
        past = ranked_item.get("past_decision_agent", {}).get("response", {})
        clinical = ranked_item.get("clinical_agent_result", {})

        insurance = financial.get("insurance_context", {}) if isinstance(financial.get("insurance_context", {}), dict) else {}

        return {
            "financial_agent": {
                "status": "COST_FAVORABLE" if _safe_float(financial.get("estimated_savings"), 0.0) > 0 else "COST_NEUTRAL",
                "original_drug": str(financial.get("original_drug_id", "")),
                "alternative_drug": str(financial.get("drug_id", "")),
                "original_tier": str(financial.get("original_tier", "")),
                "alternative_tier": str(financial.get("alternative_tier", financial.get("tier", ""))),
                "original_total_price": str(financial.get("original_annual_final_cost", "") or financial.get("original_final_cost", "")),
                "alternative_total_price": str(financial.get("annual_final_cost", "") or financial.get("final_cost", "")),
                "original_copay": str(financial.get("original_annual_patient_pay", "") or financial.get("original_patient_pay", "")),
                "alternative_copay": str(financial.get("annual_patient_pay", "") or financial.get("estimated_patient_pay", "")),
                "original_plan_paid": str(financial.get("original_plan_paid", "")),
                "alternative_plan_paid": str(financial.get("alternative_plan_paid", "")),
                "annual_savings": str(financial.get("estimated_savings", "")),
                "savings_percent": str(financial.get("savings_pct", "")),
                "summary": str(financial.get("notes", "")),
                "score": _safe_float(financial.get("score"), 0.0),
            },
            "insurance_context": {
                "insurance_phase": str(insurance.get("phase", "")),
                "ytd_oop": str(insurance.get("ytd_oop", "")),
                "coinsurance": "",
                "deductible_limit": str(insurance.get("deductible_cap", "")),
                "deductible_met": "",
                "deductible_remaining": str(insurance.get("deductible_remaining", "")),
                "oop_max": str(insurance.get("oop_max_cap", "")),
                "oop_used": "",
                "oop_remaining": str(insurance.get("oop_remaining", "")),
            },
            "clinical_agent": {
                "status": "CLINICALLY_ACCEPTABLE",
                "clinical_summary": [
                    f"Clinical composite score: {_safe_float(clinical.get('stage_c', {}).get('composite_score'), 0.0):.4f}.",
                    f"Clinical rank: {ranked_item.get('clinical_rank')}.",
                    "Stage A and B were considered by the clinical agent.",
                    "No additional clinical recomputation was performed in Layer 8.",
                ],
                "safety_summary": [
                    f"clinical_ambiguity: {bool(clinical.get('stage_c', {}).get('safety_flags', {}).get('clinical_ambiguity', False))}.",
                    f"cumulative_risk: {bool(clinical.get('stage_c', {}).get('safety_flags', {}).get('cumulative_risk', False))}.",
                    f"polypharmacy: {bool(clinical.get('stage_c', {}).get('safety_flags', {}).get('polypharmacy', False))}.",
                    f"missing_clinical_data: {bool(clinical.get('stage_c', {}).get('safety_flags', {}).get('missing_clinical_data', False))}.",
                ],
                "agent_summary": [
                    self._extract_stage_reasoning(clinical, "stage_a"),
                    self._extract_stage_reasoning(clinical, "stage_b"),
                ],
            },
            "policy_agent": {
                "status": "POLICY_APPROVED" if str(policy.get("policy_state", "")).lower() == "pass" else "POLICY_PENDING",
                "original_status": "",
                "alternative_status": str(policy.get("policy_state", "")),
                "formulary_preference": str(policy.get("formulary_preference", "")),
                "coverage_status": "covered" if bool(policy.get("covered", False)) else "not_covered",
                "policy_checks_passed": str(policy.get("policy_state", "")).lower() == "pass",
                "policy_notes": str(policy.get("notes", "")),
                "key_findings": [str(item) for item in policy.get("pending_reasons", []) if str(item).strip()],
                "score": _safe_float(policy.get("score"), 0.0),
            },
            "past_decision_agent": {
                "status": "RECOMMENDED" if _safe_float(past.get("final_score"), 0.0) >= 0.5 else "NOT_RECOMMENDED",
                "historical_confidence": "High" if _safe_float(past.get("final_score"), 0.0) >= 0.8 else "Medium",
                "summary": str(past.get("final_statement", "")),
                "recommendation_supported": _safe_float(past.get("final_score"), 0.0) >= 0.5,
                "score": _safe_float(past.get("final_score", past.get("average_confidence_score")), 0.0),
            },
        }


def default_phases() -> list[BasePhase]:
    return [
        IntakePhase(),
        ClinicalPhase(),
        DownstreamAgentsPhase(),
        HardRulesAndWeightsPhase(),
        Layer4ScoringPhase(),
        Layer5RiskAdjustmentPhase(),
        Layer6FinalRankingPhase(),
        Layer7LLMGovernanceReviewPhase(),
        Layer8SummaryGenerationPhase(),
    ]

# ===== pipeline.py =====

from pathlib import Path
import json
from typing import Any



class OrchestratorPipeline:
    def __init__(
        self,
        config: OrchestratorConfig | None = None,
        phases: list[BasePhase] | None = None,
    ) -> None:
        self.config = config or load_config()
        self.phases = phases or default_phases()

    def run(self, orchestrator_input: OrchestratorInput) -> OrchestratorOutput:
        context: dict[str, Any] = {
            "request_id": orchestrator_input.request_id,
            "payload": orchestrator_input.payload,
            "runtime_options": orchestrator_input.runtime_options,
            "config": self.config,
        }

        phase_results: list[PhaseResult] = []
        for phase in self.phases:
            try:
                result = phase.execute(context)
            except Exception as exc:
                result = PhaseResult(
                    name=getattr(phase, "name", phase.__class__.__name__),
                    status="failed",
                    errors=[f"Unhandled exception: {exc}"],
                )

            phase_results.append(result)
            context[result.name] = result.data

            if result.status != "success":
                break

        status = "success" if all(p.status == "success" for p in phase_results) else "failed"

        final_payload: dict[str, Any] = {
            "orchestrator": self.config.name,
            "request_id": orchestrator_input.request_id,
            "phase_count": len(phase_results),
            "summary": {
                "successful_phases": sum(1 for p in phase_results if p.status == "success"),
                "failed_phases": sum(1 for p in phase_results if p.status != "success"),
            },
            "input_payload": orchestrator_input.payload,
            "clinical_agent": context.get("phase_02_clinical", {}),
            "downstream_agents": context.get("phase_03_downstream_agents", {}),
            "layer_2_and_3": context.get("phase_04_hard_rules_and_weights", {}),
            "layer_4": context.get("phase_05_layer_4_scoring", {}),
            "layer_5": context.get("phase_06_layer_5_risk_adjustment", {}),
            "layer_6": context.get("phase_07_layer_6_final_ranking", {}),
            "layer_7": context.get("phase_08_layer_7_llm_governance_review", {}),
            "layer_8": context.get("phase_09_layer_8_summary_generation", {}),
        }

        return OrchestratorOutput(
            request_id=orchestrator_input.request_id,
            status=status,
            phase_results=phase_results,
            final_payload=final_payload,
        )

    def save_output(self, output: OrchestratorOutput, filename: str = "latest_output.json") -> Path:
        output_dir = _resolve_output_dir(self.config.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        output_path = output_dir / filename
        output_path.write_text(json.dumps(output.to_dict(), indent=2), encoding="utf-8")
        return output_path

# ===== run.py =====

import argparse
import json
import uuid
from pathlib import Path
from typing import Any



# Edit these templates directly to change the default testcase.
FORM_INPUT_TEMPLATE: dict[str, Any] = {
    "member_id": 2001,
    "prescriber_npi": "1234567890",
    "pharmacy_id": "PHARM0001",
    "diagnosis": {
        "code": "I10",
        "name": "Essential hypertension",
    },
    "medication": {
        "drug_id": 1013,
        "drug_name": "Sertraline 50mg",
    },
    "strength": "50 mg",
    "frequency": "Once daily",
    "days_supply": 30,
}

CLINICAL_OUTPUT_TEMPLATE: dict[str, Any] = {
    "original_drug": {
        "prod_id": 1013,
        "prod_name": "Sertraline 50mg",
    },
    "ranked_alternatives": [
        {
            "rank": 1,
            "candidate_id": 1014,
            "candidate_name": "Escitalopram 10mg",
            "overall_status": "PASS",
            "stage_a": {
                "prod_id": 1014,
                "prod_name": "Escitalopram 10mg",
                "evidence": {
                    "ingredient": 0.5,
                    "moiety": 0.5,
                    "class": 1.0,
                    "moa": 1.0,
                    "combo": 0.25,
                    "route": 1.0,
                    "form": 1.0,
                    "strength": 0.25,
                },
                "score": 0.6298,
                "status": "accepted",
                "llm_required": False,
                "reasoning": None,
            },
            "stage_b": {
                "prod_id": 1014,
                "prod_name": "Escitalopram 10mg",
                "evidence": {
                    "allergy": 0.25,
                    "condition": 0.5,
                    "age": 0.0,
                    "contraindication": 0.0,
                    "interaction": 0.0,
                    "renal_hepatic": 0.0,
                    "duplicate_therapy": 1.0,
                },
                "score": 0.7125,
                "status": "accept",
                "llm_required": True,
                "reasoning": "Escitalopram has a moderate alignment with the case due to its therapeutic profile, but caution is advised.",
            },
            "stage_c": {
                "composite_score": 0.6794,
                "threshold_passed": True,
                "safety_flags": {
                    "polypharmacy": False,
                    "missing_clinical_data": False,
                    "clinical_ambiguity": True,
                    "cumulative_risk": True,
                },
            },
        },
        {
            "rank": 2,
            "candidate_id": 1042,
            "candidate_name": "Bupropion 150mg",
            "overall_status": "PASS",
            "stage_a": {
                "prod_id": 1042,
                "prod_name": "Bupropion 150mg",
                "evidence": {
                    "ingredient": 0.5,
                    "moiety": 0.5,
                    "class": 0.0,
                    "moa": 0.5,
                    "combo": 0.25,
                    "route": 1.0,
                    "form": 1.0,
                    "strength": 1.0,
                },
                "score": 0.4882,
                "status": "accepted",
                "llm_required": True,
                "reasoning": "Sertraline and Bupropion differ significantly in pharmacologic class (SSRI vs NDRI), which impacts their mechanism of action and therapeutic use.",
            },
            "stage_b": {
                "prod_id": 1042,
                "prod_name": "Bupropion 150mg",
                "evidence": {
                    "allergy": 0.0,
                    "condition": 0.5,
                    "age": 0.0,
                    "contraindication": 0.0,
                    "interaction": 0.0,
                    "renal_hepatic": 0.0,
                    "duplicate_therapy": 1.0,
                },
                "score": 0.765,
                "status": "accept",
                "llm_required": True,
                "reasoning": "Bupropion may exacerbate heart failure due to its potential to increase heart rate and blood pressure, which is clinically relevant given the patient's condition.",
            },
            "stage_c": {
                "composite_score": 0.6543,
                "threshold_passed": True,
                "safety_flags": {
                    "polypharmacy": False,
                    "missing_clinical_data": False,
                    "clinical_ambiguity": True,
                    "cumulative_risk": False,
                },
            },
        },
    ],
}


def _build_case_templates(case_name: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    clinical_output = _clone(CLINICAL_OUTPUT_TEMPLATE)
    policy_output = _clone(POLICY_AGENT_OUTPUT_TEMPLATES)
    financial_output = _clone(FINANCIAL_AGENT_OUTPUT_TEMPLATES)
    past_decision_output = _clone(PAST_DECISION_AGENT_OUTPUT_TEMPLATES)

    for alternative in clinical_output.get("ranked_alternatives", []):
        stage_c = alternative.get("stage_c", {})
        safety_flags = stage_c.get("safety_flags", {})
        for flag_name in list(safety_flags.keys()):
            safety_flags[flag_name] = False

    for alternative_id, policy_payload in policy_output.items():
        policy_payload["score"] = policy_payload.get("result", {}).get("score", 0.0)
        policy_payload.setdefault("result", {})["score"] = policy_payload["score"]

    for alternative_id, financial_payload in financial_output.items():
        financial_payload["score"] = financial_payload.get("result", {}).get("score", 0.0)
        financial_payload.setdefault("result", {})["score"] = financial_payload["score"]

    for alternative_id, past_payload in past_decision_output.items():
        past_payload["final_score"] = past_payload.get("score", 0.0)

    if case_name == "auto_accept":
        policy_output["1042"]["score"] = 0.75
        policy_output["1042"]["result"]["score"] = 0.75
        financial_output["1042"]["score"] = 0.75
        financial_output["1042"]["result"]["score"] = 0.75
        past_decision_output["1042"]["final_score"] = 0.75
        past_decision_output["1042"]["score"] = 0.75
    elif case_name == "provider_review":
        for alternative in clinical_output.get("ranked_alternatives", []):
            safety_flags = alternative.get("stage_c", {}).get("safety_flags", {})
            safety_flags["missing_clinical_data"] = True
            safety_flags["clinical_ambiguity"] = False
            safety_flags["cumulative_risk"] = False
            safety_flags["polypharmacy"] = False

        for alternative_id in ("1014", "1042"):
            policy_output[alternative_id]["score"] = 0.70
            policy_output[alternative_id]["result"]["score"] = 0.70
            financial_output[alternative_id]["score"] = 0.70
            financial_output[alternative_id]["result"]["score"] = 0.70
            past_decision_output[alternative_id]["final_score"] = 0.70
            past_decision_output[alternative_id]["score"] = 0.70

        financial_output["1042"]["result"]["final_cost"] = financial_output["1014"]["result"]["final_cost"]
        financial_output["1042"]["result"]["estimated_patient_pay"] = financial_output["1014"]["result"]["estimated_patient_pay"]
        financial_output["1042"]["result"]["original_final_cost"] = financial_output["1014"]["result"]["original_final_cost"]
        financial_output["1042"]["result"]["original_patient_pay"] = financial_output["1014"]["result"]["original_patient_pay"]
        financial_output["1042"]["result"]["estimated_savings"] = financial_output["1014"]["result"]["estimated_savings"]
        financial_output["1042"]["result"]["savings_pct"] = financial_output["1014"]["result"]["savings_pct"]
        financial_output["1042"]["score"] = financial_output["1014"]["score"]
        financial_output["1042"]["final_cost"] = financial_output["1042"]["result"]["final_cost"]
        financial_output["1042"]["estimated_patient_pay"] = financial_output["1042"]["result"]["estimated_patient_pay"]
        financial_output["1042"]["original_final_cost"] = financial_output["1042"]["result"]["original_final_cost"]
        financial_output["1042"]["original_patient_pay"] = financial_output["1042"]["result"]["original_patient_pay"]
        financial_output["1042"]["estimated_savings"] = financial_output["1042"]["result"]["estimated_savings"]
        financial_output["1042"]["savings_pct"] = financial_output["1042"]["result"]["savings_pct"]

        clinical_output["ranked_alternatives"][1]["stage_c"]["composite_score"] = clinical_output["ranked_alternatives"][0]["stage_c"]["composite_score"]
        clinical_output["ranked_alternatives"][1]["stage_a"]["score"] = clinical_output["ranked_alternatives"][0]["stage_a"]["score"]
        clinical_output["ranked_alternatives"][1]["stage_b"]["score"] = clinical_output["ranked_alternatives"][0]["stage_b"]["score"]
    else:
        raise ValueError(f"Unknown testcase preset: {case_name}")

    return (
        clinical_output,
        policy_output,
        financial_output,
        past_decision_output,
        {"case_name": case_name},
    )

POLICY_AGENT_OUTPUT_TEMPLATES: dict[str, Any] = {
    "1014": {
        "claim_context": {
            "drug_id": "1018",
            "plan_id": "3010",
            "member_id": "2001",
            "quantity": 30,
            "fill_date": "2025-06-01",
        },
        "candidate_drug_id": "1014",
        "result": {
            "drug_id": "1014",
            "covered": True,
            "tier": "1",
            "pa_required": False,
            "pa_met": True,
            "step_therapy_required": False,
            "step_therapy_met": True,
            "quantity_ok": True,
            "formulary_preference": "Preferred",
            "violations": [],
            "policy_state": "pass",
            "pending_type": None,
            "pending_reasons": [],
            "review_recommendation": None,
            "score": 0.92,
            "notes": "Preferred formulary preference. All policy checks passed.",
            "summary": {
                "decision": "pass",
                "reason": "Preferred formulary preference. All policy checks passed.",
                "score": 0.92,
            },
        },
    },
    "1042": {
        "claim_context": {
            "drug_id": "1018",
            "plan_id": "3010",
            "member_id": "2001",
            "quantity": 30,
            "fill_date": "2025-06-01",
        },
        "candidate_drug_id": "1042",
        "result": {
            "drug_id": "1042",
            "covered": True,
            "tier": "4",
            "pa_required": True,
            "pa_met": False,
            "step_therapy_required": False,
            "step_therapy_met": True,
            "quantity_ok": True,
            "formulary_preference": "Exception Only",
            "violations": ["Prior authorization required and not yet evidenced."],
            "policy_state": "pending",
            "pending_type": "doctor_review",
            "pending_reasons": ["Prior authorization required and not yet evidenced."],
            "review_recommendation": "Doctor review required (accept/reject/modify).",
            "score": 0.32,
            "notes": "Prior authorization required and not yet evidenced.",
            "summary": {
                "decision": "pending",
                "reason": "Prior authorization required and not yet evidenced.",
                "score": 0.32,
            },
        },
    },
}

FINANCIAL_AGENT_OUTPUT_TEMPLATES: dict[str, Any] = {
    "1014": {
        "claim_context": {
            "drug_id": "1034",
            "plan_id": "3009",
            "fill_date": "2025-06-01",
        },
        "candidate_drug_id": "1014",
        "result": {
            "drug_id": "1014",
            "covered": True,
            "tier": "3",
            "final_cost": 22.89,
            "estimated_patient_pay": 22.89,
            "pricing_source": "Negotiated",
            "original_drug_id": "1034",
            "original_final_cost": 401.04,
            "original_patient_pay": 401.04,
            "estimated_savings": 378.15,
            "savings_pct": 0.9429,
            "insurance_context": {
                "phase": "DEDUCTIBLE",
                "ytd_oop": 192.16,
                "deductible_cap": 1500.0,
                "oop_max_cap": 3000.0,
                "deductible_remaining": 1307.84,
                "oop_remaining": 2807.84,
                "note": None,
                "candidate_fill_projection": {
                    "phase_before": "DEDUCTIBLE",
                    "phase_after": "DEDUCTIBLE",
                    "phase_crossed": False,
                    "patient_pay": 22.89,
                    "effective_coinsurance": 1.0,
                    "deductible_component": 22.89,
                    "coinsurance_component": 0.0,
                    "deductible_remaining_after": 1284.95,
                    "oop_remaining_after": 2784.95,
                    "ytd_oop_after": 215.05,
                    "note": None,
                },
                "original_fill_projection": {
                    "phase_before": "DEDUCTIBLE",
                    "phase_after": "DEDUCTIBLE",
                    "phase_crossed": False,
                    "patient_pay": 401.04,
                    "effective_coinsurance": 1.0,
                    "deductible_component": 401.04,
                    "coinsurance_component": 0.0,
                    "deductible_remaining_after": 906.8,
                    "oop_remaining_after": 2406.8,
                    "ytd_oop_after": 593.2,
                    "note": None,
                },
            },
            "financial_phase_decision_hint": "No phase-boundary difference: both stay in DEDUCTIBLE.",
            "score": 0.95,
            "notes": "[DEDUCTIBLE -> candidate:DEDUCTIBLE / original:DEDUCTIBLE] YTD OOP $192.16, deductible cap $1500.00, OOP max $3000.00. Candidate 1014 ($22.89, tier 3) saves the original drug 1034 ($401.04, tier 5), a savings of $378.15 (+94%).",
            "summary": {
                "decision": "cheaper",
                "reason": "[DEDUCTIBLE -> candidate:DEDUCTIBLE / original:DEDUCTIBLE] YTD OOP $192.16, deductible cap $1500.00, OOP max $3000.00. Candidate 1014 ($22.89, tier 3) saves the original drug 1034 ($401.04, tier 5), a savings of $378.15 (+94%).",
                "score": 0.95,
                "estimated_savings": 378.15,
                "candidate_patient_pay": 22.89,
                "original_patient_pay": 401.04,
            },
        },
    },
    "1042": {
        "claim_context": {
            "drug_id": "1004",
            "plan_id": "3001",
            "fill_date": "2025-06-01",
        },
        "candidate_drug_id": "1042",
        "result": {
            "drug_id": "1042",
            "covered": True,
            "tier": "1",
            "final_cost": 9.98,
            "estimated_patient_pay": 2.2,
            "pricing_source": "MAC",
            "original_drug_id": "1004",
            "original_final_cost": 23.94,
            "original_patient_pay": 10.77,
            "estimated_savings": 8.57,
            "savings_pct": 0.7957,
            "insurance_context": {
                "phase": "INITIAL_COVERAGE",
                "ytd_oop": 73.05,
                "deductible_cap": 0.0,
                "oop_max_cap": 7000.0,
                "deductible_remaining": 0.0,
                "oop_remaining": 6926.95,
                "note": None,
                "candidate_fill_projection": {
                    "phase_before": "INITIAL_COVERAGE",
                    "phase_after": "INITIAL_COVERAGE",
                    "phase_crossed": False,
                    "patient_pay": 2.2,
                    "effective_coinsurance": 0.2204,
                    "deductible_component": 0.0,
                    "coinsurance_component": 2.2,
                    "deductible_remaining_after": 0.0,
                    "oop_remaining_after": 6924.75,
                    "ytd_oop_after": 75.25,
                    "note": None,
                },
                "original_fill_projection": {
                    "phase_before": "INITIAL_COVERAGE",
                    "phase_after": "INITIAL_COVERAGE",
                    "phase_crossed": False,
                    "patient_pay": 10.77,
                    "effective_coinsurance": 0.4499,
                    "deductible_component": 0.0,
                    "coinsurance_component": 10.77,
                    "deductible_remaining_after": 0.0,
                    "oop_remaining_after": 6916.18,
                    "ytd_oop_after": 83.82,
                    "note": None,
                },
            },
            "financial_phase_decision_hint": "No phase-boundary difference: both stay in INITIAL_COVERAGE.",
            "score": 0.95,
            "notes": "[INITIAL_COVERAGE -> candidate:INITIAL_COVERAGE / original:INITIAL_COVERAGE] YTD OOP $73.05, deductible cap $0.00, OOP max $7000.00. Candidate 1042 ($2.20, tier 1) saves the original drug 1004 ($10.77, tier 3), a savings of $8.57 (+80%).",
            "summary": {
                "decision": "cheaper",
                "reason": "[INITIAL_COVERAGE -> candidate:INITIAL_COVERAGE / original:INITIAL_COVERAGE] YTD OOP $73.05, deductible cap $0.00, OOP max $7000.00. Candidate 1042 ($2.20, tier 1) saves the original drug 1004 ($10.77, tier 3), a savings of $8.57 (+80%).",
                "score": 0.95,
                "estimated_savings": 8.57,
                "candidate_patient_pay": 2.2,
                "original_patient_pay": 10.77,
            },
        },
    },
}

PAST_DECISION_AGENT_OUTPUT_TEMPLATES: dict[str, Any] = {
    "1014": {
        "match": {
            "rank": 1,
            "case_id": "CASE7000250",
            "claim_id": "CLM100250",
            "date": "2025-02-06",
            "decision": "ACCEPTED",
            "modified_drug": None,
            "decision_reason": None,
            "original_drug": "Azithromycin 250mg",
            "recommended_drug": "Azithromycin 250mg",
            "diagnosis": "J22",
            "structured_similarity_score": 0.91,
            "similarity_score": 0.87,
            "decision_weight": 0.96,
            "time_decay": 0.84,
            "modified_score_after_time_decay_and_decision_weight": 0.7003,
            "rule_adjustment_score": 0.0412,
            "combined_patient_adjustment_score": 0.0412,
            "final_score_after_patient_adjustment": 0.7415,
            "rule_adjustment_explanation": "Rule-based patient adjustment: age_similarity=0.50, sex_similarity=1.00, medication_pattern_similarity=0.25, allergy_profile_similarity=0.00.",
            "reasoning": [
                "Original drug matches the current case.",
                "Recommended drug is clinically similar to the current recommendation.",
                "Diagnosis matches exactly: J22.",
                "Historical decision was accepted, which supports the recommendation.",
            ],
        },
        "score": 0.496,
        "has_signal": True,
        "final_statement": "Historical evidence generally supports the recommendation because similar past cases were accepted by doctors. The Orchestrator can treat Past Decisions as a supportive signal.",
        "average_confidence_score": 0.496,
        "notes": "Historical precedent evaluated.",
        "top_cases": [
            {
                "rank": 1,
                "case_id": "CASE7000250",
                "claim_id": "CLM100250",
                "date": "2025-02-06",
                "decision": "ACCEPTED",
                "original_drug": "Azithromycin 250mg",
                "recommended_drug": "Azithromycin 250mg",
                "diagnosis": "J22",
                "final_score_after_patient_adjustment": 0.7415,
            }
        ],
        "raw": {},
    },
    "1042": {
        "match": {
            "rank": 1,
            "case_id": "CASE7000066",
            "claim_id": "CLM100066",
            "date": "2025-03-10",
            "decision": "ACCEPTED",
            "modified_drug": None,
            "decision_reason": None,
            "original_drug": "Sertraline 50mg",
            "recommended_drug": "Bupropion 150mg",
            "diagnosis": "I10",
            "structured_similarity_score": 0.84,
            "similarity_score": 0.79,
            "decision_weight": 0.95,
            "time_decay": 0.83,
            "modified_score_after_time_decay_and_decision_weight": 0.6634,
            "rule_adjustment_score": 0.031,
            "combined_patient_adjustment_score": 0.031,
            "final_score_after_patient_adjustment": 0.6944,
            "rule_adjustment_explanation": "Rule-based patient adjustment: age_similarity=1.00, sex_similarity=1.00, medication_pattern_similarity=0.20, allergy_profile_similarity=0.00.",
            "reasoning": [
                "Original drug matches the current case.",
                "Recommended drug is clinically similar to the recommendation.",
                "Diagnosis matches exactly: I10.",
                "Historical decision was accepted, which supports the recommendation.",
            ],
        },
        "score": 0.512,
        "has_signal": True,
        "final_statement": "Historical evidence generally supports the recommendation with related accepted cases.",
        "average_confidence_score": 0.512,
        "notes": "Historical precedent evaluated.",
        "top_cases": [
            {
                "rank": 1,
                "case_id": "CASE7000066",
                "claim_id": "CLM100066",
                "date": "2025-03-10",
                "decision": "ACCEPTED",
                "original_drug": "Sertraline 50mg",
                "recommended_drug": "Bupropion 150mg",
                "diagnosis": "I10",
                "final_score_after_patient_adjustment": 0.6944,
            }
        ],
        "raw": {},
    },
}


def _clone(value: Any) -> Any:
    return json.loads(json.dumps(value))


def _build_default_form_input() -> dict[str, Any]:
    return _clone(FORM_INPUT_TEMPLATE)


def _build_runtime_options(case_name: str = "auto_accept") -> dict[str, Any]:
    clinical_output, policy_output, financial_output, past_decision_output, metadata = _build_case_templates(case_name)
    return {
        "clinical_output_inline": clinical_output,
        "policy_inline_response_payloads": policy_output,
        "financial_inline_response_payloads": financial_output,
        "past_decision_inline_response_payloads": past_decision_output,
        "testcase_metadata": metadata,
    }


def _build_compact_output(output_dict: dict[str, Any]) -> dict[str, Any]:
    final_payload = output_dict.get("final_payload", {})
    layer_8 = final_payload.get("layer_8", {})
    resolution = layer_8.get("resolution", {})
    legacy_routing = layer_8.get("legacy_routing_summary", {})

    raw_decision = str(legacy_routing.get("decision") or "").strip().lower()
    decision_aliases = {
        "auto_approv": "auto_approve",
        "auto_approved": "auto_approve",
    }
    decision = decision_aliases.get(raw_decision, raw_decision) if raw_decision else None

    final_outcome = resolution.get("final_outcome")
    if final_outcome is None and decision:
        decision_to_outcome = {
            "auto_approve": "AUTO_ACCEPT_SELECTED",
            "doctor_review": "PROVIDER_REVIEW_SELECTION_PENDING",
            "keep_original": "DISPENSE_AS_WRITTEN",
        }
        final_outcome = decision_to_outcome.get(decision)

    def _final_status_from_band(band: Any) -> str:
        band_int = int(_safe_float(band, 0.0))
        if band_int == 1:
            return "AUTO_ACCEPT"
        if band_int == 3:
            return "PROVIDER_REVIEW"
        if band_int == 4:
            return "DISPENSE_AS_WRITTEN"
        if band_int == 2:
            return "PENDING_LLM_REVIEW"
        return "UNKNOWN"

    def _strip_provider_only_reasoning(summary_payload: Any) -> Any:
        if not isinstance(summary_payload, dict):
            return summary_payload
        cleaned = json.loads(json.dumps(summary_payload))
        summary_cards = cleaned.get("summary_cards", {}) if isinstance(cleaned.get("summary_cards", {}), dict) else {}
        clinical_card = summary_cards.get("clinical_agent", {}) if isinstance(summary_cards.get("clinical_agent", {}), dict) else {}
        clinical_card.pop("agent_reasoning", None)
        clinical_card.pop("agent_summary", None)
        summary_cards["clinical_agent"] = clinical_card
        cleaned["summary_cards"] = summary_cards
        return cleaned

    def _compact_alternative(alt: dict[str, Any] | None, *, include_provider_reasoning: bool = False) -> dict[str, Any] | None:
        if not isinstance(alt, dict):
            return None
        summary_payload = alt.get("summary")
        if not include_provider_reasoning:
            summary_payload = _strip_provider_only_reasoning(summary_payload)
        return {
            "rank": alt.get("rank"),
            "alternative_id": alt.get("alternative_id"),
            "alternative_name": alt.get("alternative_name"),
            "adjusted_score": alt.get("adjusted_score"),
            "final_band": alt.get("final_band"),
            "final_status": _final_status_from_band(alt.get("final_band")),
            "summary": summary_payload,
        }

    selected_alternative = _compact_alternative(layer_8.get("pbm_packet", {}).get("selected_alternative"))

    provider_review_list_raw = layer_8.get("provider_packet", {}).get("alternatives", [])
    provider_review_list = []
    if isinstance(provider_review_list_raw, list):
        provider_review_list = [
            compacted
            for compacted in (_compact_alternative(item, include_provider_reasoning=False) for item in provider_review_list_raw)
            if compacted is not None
        ]

    pharmacist_selected = _compact_alternative(layer_8.get("pharmacist_packet", {}).get("selected_alternative"))

    pbm_selected = _compact_alternative(layer_8.get("pbm_packet", {}).get("selected_alternative"))
    pbm_review_raw = layer_8.get("pbm_packet", {}).get("review_alternatives", [])
    pbm_review_alternatives = []
    if isinstance(pbm_review_raw, list):
        pbm_review_alternatives = [
            {
                "rank": item.get("rank"),
                "alternative_id": item.get("alternative_id"),
                "alternative_name": item.get("alternative_name"),
                "summary": _strip_provider_only_reasoning(item.get("summary")),
            }
            for item in pbm_review_raw
            if isinstance(item, dict)
        ]

    provider_packet = {
        "required": bool(layer_8.get("provider_packet", {}).get("required", False)),
        "alternatives": provider_review_list_raw if isinstance(provider_review_list_raw, list) else [],
    }

    pbm_packet = {
        "sent": bool(layer_8.get("pbm_packet", {}).get("sent", False)),
        "selected_alternative": pbm_selected,
        "review_alternatives": pbm_review_alternatives,
    }
    if bool(layer_8.get("pbm_packet", {}).get("daw", False)):
        pbm_packet["daw"] = True

    evaluated_raw = resolution.get("evaluated_alternatives", [])
    evaluated_alternatives = []
    if isinstance(evaluated_raw, list):
        for item in evaluated_raw:
            if not isinstance(item, dict):
                continue
            evaluated_alternatives.append(
                {
                    "rank": item.get("rank"),
                    "alternative_id": item.get("alternative_id"),
                    "alternative_name": item.get("alternative_name"),
                    "adjusted_score": item.get("adjusted_score"),
                    "final_band": item.get("final_band"),
                    "final_status": _final_status_from_band(item.get("final_band")),
                }
            )

    compact_output = {
        "orchestrator": final_payload.get("orchestrator"),
        "request_id": output_dict.get("request_id"),
        "status": output_dict.get("status"),
        "final_outcome": final_outcome,
        "selected_alternative": selected_alternative,
        "provider_review_list": provider_review_list,
        "provider_packet": provider_packet,
        "pbm_packet": pbm_packet,
        "pharmacist_packet": {
            "sent": bool(layer_8.get("pharmacist_packet", {}).get("sent", False)),
            "selected_alternative": pharmacist_selected,
            "review_alternatives": pbm_review_alternatives,
        },
        "summary": {
            "alternatives_evaluated": len(resolution.get("evaluated_alternatives", [])),
            "alternatives_summarized": layer_8.get("alternatives_summarized", 0),
            "llm_calls_made": layer_8.get("llm_calls_made", 0),
            "llm_fail_safe_count": layer_8.get("llm_fail_safe_count", 0),
        },
        "evaluated_alternatives": evaluated_alternatives,
    }

    if bool(layer_8.get("pharmacist_packet", {}).get("daw", False)):
        compact_output["pharmacist_packet"]["daw"] = True

    return compact_output


def _build_phase_results_output(output_dict: dict[str, Any]) -> dict[str, Any]:
    return {
        "orchestrator": output_dict.get("final_payload", {}).get("orchestrator"),
        "request_id": output_dict.get("request_id"),
        "status": output_dict.get("status"),
        "phase_results": output_dict.get("phase_results", []),
    }


def _save_compact_output(compact_output: dict[str, Any], output_dir: str) -> Path:
    output_path = _resolve_output_dir(output_dir) / "latest_output.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(compact_output, indent=2), encoding="utf-8")
    return output_path


def _save_phase_results_output(phase_results_output: dict[str, Any], output_dir: str) -> Path:
    output_path = _resolve_output_dir(output_dir) / "phase_results.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(phase_results_output, indent=2), encoding="utf-8")
    return output_path


def _print_execution_trace(output_dict: dict[str, Any]) -> None:
    phase_results = output_dict.get("phase_results", [])
    phase_messages = {
        "phase_01_intake": "Request checked.",
        "phase_02_clinical": "Clinical choices loaded.",
        "phase_03_downstream_agents": "Policy, cost, and history checked for each choice.",
        "phase_04_hard_rules_and_weights": "Basic rules applied and ineligible choices removed.",
        "phase_05_layer_4_scoring": "Remaining choices were scored together.",
        "phase_06_layer_5_risk_adjustment": "Safety flags were used to adjust scores.",
        "phase_07_layer_6_final_ranking": "Choices were ranked and grouped by outcome.",
        "phase_08_layer_7_llm_governance_review": "Extra review ran for flagged choices.",
        "phase_09_layer_8_summary_generation": "Final recommendation and summaries were prepared.",
    }

    print("Orchestrator trace:")
    for phase_result in phase_results:
        phase_name = phase_result.get("name", "") if isinstance(phase_result, dict) else ""
        print(f"- {phase_messages.get(phase_name, 'Step completed.')}")


def _read_payload(input_json_path: str | None, inline_json: str | None) -> dict[str, Any]:
    if input_json_path:
        return json.loads(Path(input_json_path).read_text(encoding="utf-8"))
    if inline_json:
        return json.loads(inline_json)
    return _build_default_form_input()


def main() -> None:
    # Load environment variables from .env file
    try:
        from dotenv import load_dotenv
        dotenv_path = Path(__file__).resolve().parent.parent.parent.parent / ".env"
        load_dotenv(dotenv_path)
        import sys
        print(f"[INFO] Loaded .env from: {dotenv_path}", file=sys.stderr, flush=True)
    except ImportError:
        import sys
        print(f"[WARNING] python-dotenv not installed. Relying on system environment variables.", file=sys.stderr, flush=True)
    except Exception as e:
        import sys
        print(f"[WARNING] Failed to load .env: {e}", file=sys.stderr, flush=True)

    parser = argparse.ArgumentParser(description="Run standalone orchestrator pipeline.")
    parser.add_argument(
        "--case",
        default="auto_accept",
        choices=["auto_accept", "provider_review"],
        help="Choose which testcase preset to run.",
    )
    parser.add_argument("--request-id", default=None, help="Optional request id.")
    parser.add_argument("--input-json", default=None, help="Path to input JSON file.")
    parser.add_argument(
        "--inline-json",
        default=None,
        help="Inline JSON payload string. Ignored if --input-json is provided.",
    )
    parser.add_argument(
        "--provider-selected-alternative-id",
        default=None,
        help=(
            "Optional provider-selected alternative id for provider-review demo flow. "
            "If omitted, provider selection remains pending."
        ),
    )

    args = parser.parse_args()
    request_id = args.request_id or str(uuid.uuid4())

    payload = _read_payload(args.input_json, args.inline_json)
    runtime_options = _build_runtime_options(args.case)
    if args.provider_selected_alternative_id:
        runtime_options["provider_selected_alternative_id"] = args.provider_selected_alternative_id

    orchestrator_input = OrchestratorInput(
        request_id=request_id,
        payload=payload,
        runtime_options=runtime_options,
    )

    pipeline = OrchestratorPipeline()
    output = pipeline.run(orchestrator_input)
    output_dict = output.to_dict()
    compact_output = _build_compact_output(output_dict)
    output_path = _save_compact_output(compact_output, pipeline.config.output_dir)
    phase_results_output = _build_phase_results_output(output_dict)
    phase_results_path = _save_phase_results_output(phase_results_output, pipeline.config.output_dir)

    _print_execution_trace(output_dict)
    print(f"Output written to: {output_path.resolve()}")
    print(f"Phase results written to: {phase_results_path.resolve()}")


if __name__ == "__main__":
    main()

