# Load environment variables from .env file FIRST, before any other imports
try:
    from pathlib import Path
    from dotenv import load_dotenv
    dotenv_path = Path(__file__).resolve().parent.parent / ".env"
    load_dotenv(dotenv_path)
    import sys
    print(f"[INFO] Backend loaded .env from: {dotenv_path}", file=sys.stderr, flush=True)
except ImportError:
    import sys
    print(f"[WARNING] python-dotenv not installed for backend. Relying on system environment.", file=sys.stderr, flush=True)
except Exception as e:
    import sys
    print(f"[WARNING] Failed to load .env in backend: {e}", file=sys.stderr, flush=True)

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from typing import Any, Dict, List, Optional, AsyncGenerator
from pydantic import BaseModel
from pathlib import Path
import importlib.util
import asyncio
import csv
import json
import os
import sys
import time
import uuid
from datetime import datetime

from app.tools.lookups import lookup_pbm_context

app = FastAPI()

# Progress tracking for frontend SSE.
_progress_store: Dict[str, List[Dict[str, Any]]] = {}
_progress_seen: Dict[str, set] = {}


def _tail_lines(path: Path, limit: int = 50) -> List[str]:
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        return [line.rstrip("\n") for line in lines[-max(1, limit):]]
    except Exception:
        return []


def emit_progress(trace_id: str, stage: str, step: str, status: str) -> None:
    if not trace_id:
        return

    marker = (stage, step, status)
    seen = _progress_seen.setdefault(trace_id, set())
    if marker in seen:
        return
    seen.add(marker)

    event = {
        "trace_id": trace_id,
        "stage": stage,
        "step": step,
        "status": status,
        "timestamp": datetime.now().isoformat(),
    }

    queue = _progress_store.setdefault(trace_id, [])
    queue.append(event)
    if len(queue) > 500:
        del queue[:100]


def _emit_progress_from_trace(trace_id: str, message: str) -> None:
    msg = str(message or "")

    if "Input payload received" in msg:
        emit_progress(trace_id, "Stage 1", "c1", "active")
        emit_progress(trace_id, "Stage 1", "c1", "done")
        emit_progress(trace_id, "Stage 1", "c2", "active")
    elif "Building clinical input" in msg:
        emit_progress(trace_id, "Stage 1", "c2", "active")
    elif "Sending request to clinical agent" in msg:
        emit_progress(trace_id, "Stage 1", "c2", "done")
        emit_progress(trace_id, "Stage 1", "c3", "active")
    elif "Clinical output received" in msg:
        emit_progress(trace_id, "Stage 1", "c3", "done")
        emit_progress(trace_id, "Stage 2", "p1", "active")
        emit_progress(trace_id, "Stage 2", "f1", "active")
        emit_progress(trace_id, "Stage 2", "d1", "active")
    elif "Running downstream orchestration layers" in msg:
        emit_progress(trace_id, "Stage 2", "p1", "done")
        emit_progress(trace_id, "Stage 2", "f1", "done")
        emit_progress(trace_id, "Stage 2", "d1", "done")
        emit_progress(trace_id, "Stage 2", "p2", "active")
        emit_progress(trace_id, "Stage 2", "f2", "active")
        emit_progress(trace_id, "Stage 2", "d2", "active")
        emit_progress(trace_id, "Stage 2", "d3", "active")
        emit_progress(trace_id, "Stage 2", "d4", "active")
    elif "Orchestration complete" in msg:
        emit_progress(trace_id, "Stage 2", "p2", "done")
        emit_progress(trace_id, "Stage 2", "f2", "done")
        emit_progress(trace_id, "Stage 2", "d2", "done")
        emit_progress(trace_id, "Stage 2", "d3", "done")
        emit_progress(trace_id, "Stage 2", "d4", "done")

def _append_trace(request_id: str, message: str) -> None:
    """Append trace message to both stderr and trace file."""
    trace_msg = f"[TRACE] [TRC-{request_id}] {message}"
    print(trace_msg, file=sys.stderr, flush=True)
    _emit_progress_from_trace(request_id, message)
    
    # Append to trace file
    trace_file = Path(__file__).parent.parent / "trace_output.txt"
    with open(trace_file, "a", encoding="utf-8") as f:
        f.write(trace_msg + "\n")
        f.flush()

_ORCHESTRATOR_NEW_PATH = Path(__file__).resolve().parent / "agents" / "orchestrator" / "orchestrator_new.py"
_ORCHESTRATOR_NEW_MODULE = None
_CLINICAL_BUNDLE_PATH = Path(__file__).resolve().parent.parent / "clinical_agent"


def _load_orchestrator_new_module():
    global _ORCHESTRATOR_NEW_MODULE
    if _ORCHESTRATOR_NEW_MODULE is not None:
        return _ORCHESTRATOR_NEW_MODULE

    if not _ORCHESTRATOR_NEW_PATH.exists():
        raise HTTPException(
            status_code=500,
            detail=f"orchestrator_new.py not found at {_ORCHESTRATOR_NEW_PATH}",
        )

    spec = importlib.util.spec_from_file_location("pbm_orchestrator_new", _ORCHESTRATOR_NEW_PATH)
    if spec is None or spec.loader is None:
        raise HTTPException(status_code=500, detail="Failed to load orchestrator_new.py module.")

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    _ORCHESTRATOR_NEW_MODULE = module
    return module


def _coerce_claim_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Accept either canonical claim payload (drug_id/member_id/plan_id)
    or frontend intake payload (patient/drug/NPI/pharmacy form fields).
    """
    if all(payload.get(k) for k in ("drug_id", "member_id", "plan_id")):
        return payload

    resolved = lookup_pbm_context(payload)
    normalized = resolved.get("normalized_payload") or {}
    merged = {**payload, **normalized}
    return merged


def _build_orchestrator_new_payload(payload: Dict[str, Any], module) -> Dict[str, Any]:
    claim_payload = _coerce_claim_payload(payload)
    resolved = lookup_pbm_context(claim_payload)
    normalized = resolved.get("normalized_payload") or {}
    medication_row = resolved.get("drug") or {}

    drug_id = str(normalized.get("drug_id") or claim_payload.get("drug_id") or "")
    diagnosis = normalized.get("diagnosis") or claim_payload.get("diagnosis") or ""
    diagnosis_code = diagnosis.get("code") if isinstance(diagnosis, dict) else str(diagnosis)

    form_input = module._build_default_form_input()
    form_input["member_id"] = str(normalized.get("member_id") or claim_payload.get("member_id") or form_input.get("member_id") or "")
    form_input["prescriber_npi"] = str(
        normalized.get("provider_npi_number")
        or claim_payload.get("provider_npi_number")
        or form_input.get("prescriber_npi")
        or ""
    )
    form_input["pharmacy_id"] = str(normalized.get("pharmacy_id") or claim_payload.get("pharmacy_id") or form_input.get("pharmacy_id") or "")
    form_input["plan_id"] = str(normalized.get("plan_id") or claim_payload.get("plan_id") or "")
    form_input["fill_date"] = str(normalized.get("fill_date") or claim_payload.get("fill_date") or "")
    form_input["diagnosis"] = {
        "code": str(diagnosis_code or ""),
        "name": str(diagnosis_code or diagnosis or "Unknown diagnosis"),
    }
    form_input["medication"] = {
        "drug_id": drug_id,
        "drug_name": str(
            medication_row.get("PROD_NM")
            or claim_payload.get("drug_name")
            or f"Drug_{drug_id}" if drug_id else "Drug"
        ),
    }
    form_input["strength"] = str(claim_payload.get("strength") or claim_payload.get("dosage") or form_input.get("strength") or "Unknown")
    form_input["frequency"] = str(claim_payload.get("frequency") or form_input.get("frequency") or "Once daily")
    form_input["days_supply"] = int(normalized.get("quantity") or claim_payload.get("days_supply") or claim_payload.get("quantity") or 30)

    # Prefer resolved member-specific accumulators from lookups so downstream
    # financial context is not static across members.
    form_input["insurance_context"] = (
        normalized.get("insurance_context")
        or claim_payload.get("insurance_context")
        or resolved.get("accumulators")
        or {}
    )
    return form_input


def _build_live_runtime_options(payload: Dict[str, Any], module, request_id: Optional[str] = None) -> Dict[str, Any]:
    """Build runtime options from claim context instead of testcase presets.

    This path is used for backend claim endpoints so outcomes reflect request data.
    """
    claim_payload = _coerce_claim_payload(payload)
    drug_id = claim_payload.get("drug_id")
    member_id = claim_payload.get("member_id")
    drug_name = claim_payload.get("drug_name")
    trace_id = request_id or payload.get("request_id", "???")

    _append_trace(trace_id, f"2) Building clinical input: drug_id={drug_id} member_id={member_id}")

    if drug_id and member_id and _CLINICAL_BUNDLE_PATH.exists():
        bundle_path = str(_CLINICAL_BUNDLE_PATH)
        if bundle_path not in sys.path:
            sys.path.insert(0, bundle_path)

        try:
            _append_trace(trace_id, "2) Sending request to clinical agent...")
            from clinical_agent_pipeline import run_clinical_agent_pipeline  # type: ignore

            clinical_output = run_clinical_agent_pipeline(
                {
                    "prod_sk": int(drug_id),
                    "member_id": str(member_id),
                    "drug_name": drug_name,
                },
                trace=True,
                trace_writer=lambda message: _append_trace(trace_id, message.replace("[TRACE] ", "")),
            )
            if isinstance(clinical_output, dict) and isinstance(clinical_output.get("ranked_alternatives"), list):
                _append_trace(
                    trace_id, 
                    f"3) Clinical output received: {len(clinical_output.get('ranked_alternatives', []))} alternatives"
                )
                return {
                    "clinical_output_inline": clinical_output,
                    "runtime_source": "live_clinical_pipeline",
                }
        except Exception as e:
            _append_trace(trace_id, f"3) Clinical output failed: {str(e)}")
            # Fall through to file-backed clinical output as a best-effort fallback.
            pass

    clinical_output_json = _CLINICAL_BUNDLE_PATH / "clinical_agent_output.json"
    if clinical_output_json.exists():
        _append_trace(trace_id, "3) Clinical output received from file-backed source")
        return {
            "clinical_output_json_path": str(clinical_output_json),
            "runtime_source": "file_backed_clinical_output",
        }

    # Last resort: retain legacy preset behavior if no live source is available.
    _append_trace(trace_id, "3) No clinical output source available, using preset fallback")
    return module._build_runtime_options("auto_accept")


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _run_orchestrator_new(
    payload: Dict[str, Any],
    *,
    request_id: Optional[str] = None,
    case: str = "auto_accept",
    runtime_options: Optional[Dict[str, Any]] = None,
    provider_selected_alternative_id: Optional[str] = None,
) -> Dict[str, Any]:
    module = _load_orchestrator_new_module()
    request_id = request_id or str(uuid.uuid4())

    _progress_store[request_id] = []
    _progress_seen[request_id] = set()
    
    # Clear trace file at start of new test case
    trace_file = Path(__file__).parent.parent / "trace_output.txt"
    with open(trace_file, "w", encoding="utf-8") as f:
        f.write("")
    
    claim_payload = _coerce_claim_payload(payload)
    _append_trace(
        request_id,
        f"1) Input payload received: drug={claim_payload.get('drug_id')} plan={claim_payload.get('plan_id')} member={claim_payload.get('member_id')}"
    )
    
    orchestrator_payload = _build_orchestrator_new_payload(payload, module)
    _append_trace(request_id, f"Payload normalized: {len(orchestrator_payload)} fields")
    
    orchestrator_runtime_options = _build_live_runtime_options(payload, module, request_id=request_id)
    _append_trace(request_id, "Live runtime options built")

    if provider_selected_alternative_id:
        orchestrator_runtime_options["provider_selected_alternative_id"] = provider_selected_alternative_id
        _append_trace(request_id, f"Provider override set: {provider_selected_alternative_id}")

    config = module.load_config()
    orchestrator_output_dir = module._resolve_output_dir(config.output_dir)
    config = config.__class__(**{**config.__dict__, "output_dir": str(orchestrator_output_dir)})
    
    _append_trace(request_id, "4) Running downstream orchestration layers...")
    pipeline = module.OrchestratorPipeline(config=config)
    orchestrator_input = module.OrchestratorInput(
        request_id=request_id,
        payload=orchestrator_payload,
        runtime_options=orchestrator_runtime_options,
    )

    output = pipeline.run(orchestrator_input)
    output_dict = output.to_dict()
    compact_output = module._build_compact_output(output_dict)
    output_path = module._save_compact_output(compact_output, pipeline.config.output_dir)
    phase_results_output = module._build_phase_results_output(output_dict)
    phase_results_path = module._save_phase_results_output(phase_results_output, pipeline.config.output_dir)
    compact_output["output_path"] = str(output_path)
    compact_output["phase_results_path"] = str(phase_results_path)

    _append_trace(
        request_id,
        f"Orchestration complete: final_outcome={compact_output.get('final_outcome')}"
    )
    return compact_output


# --------------------------------------------------------------------------- #
# Request model for /api/claim/evaluate
# --------------------------------------------------------------------------- #
class ClaimEvaluateRequest(BaseModel):
    drug_id: str                        # PROD_SK of the originally prescribed drug
    plan_id: str                        # PLN_SK
    member_id: str                      # MBR_SK
    fill_date: Optional[str] = None     # ISO date, defaults to today if omitted
    quantity: Optional[int] = None      # units being requested
    diagnosis: Optional[str] = None     # ICD-10 code (e.g. "I48.19")
    pharmacy_id: Optional[str] = None
    provider_npi_number: Optional[str] = None


class OrchestratorNewRunRequest(BaseModel):
    request_id: Optional[str] = None
    case: str = "auto_accept"
    payload: Optional[Dict[str, Any]] = None
    runtime_options: Optional[Dict[str, Any]] = None
    provider_selected_alternative_id: Optional[str] = None

@app.get("/")
def home():
    return {"message": "API Running"}


@app.get("/progress/{trace_id}")
async def stream_progress(trace_id: str):
    """Server-Sent Events endpoint for real-time orchestration progress."""

    async def event_generator() -> AsyncGenerator[str, None]:
        last_index = 0
        while True:
            if trace_id in _progress_store:
                events = _progress_store[trace_id][last_index:]
                for event in events:
                    yield f"data: {json.dumps(event)}\n\n"
                last_index = len(_progress_store[trace_id])
            else:
                # Keep-alive comment to prevent idle connection timeouts.
                yield ": keep-alive\n\n"

            await asyncio.sleep(0.15)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@app.get("/progress/debug/{trace_id}")
def debug_progress(trace_id: str, tail: int = 25):
    """Debug view for recent progress events and trace lines for one trace id."""
    events = list(_progress_store.get(trace_id, []))
    trace_file = Path(__file__).parent.parent / "trace_output.txt"
    trace_lines = _tail_lines(trace_file, limit=max(10, min(tail, 200)))
    trace_matches = [line for line in trace_lines if f"[TRC-{trace_id}]" in line]

    return {
        "trace_id": trace_id,
        "event_count": len(events),
        "events": events[-max(1, min(tail, 200)):],
        "trace_tail_total": len(trace_lines),
        "trace_tail_matching_trace_id": trace_matches,
    }


@app.post("/resolve-intake")
def resolve_intake(payload: dict):
    return lookup_pbm_context(payload)


@app.post("/api/claim/evaluate")
async def evaluate_claim(request: ClaimEvaluateRequest):
    """
    Main claim evaluation endpoint.

    Workflow:
      1. Fetches alternative drug candidates via formulary lookup
         (Clinical Agent placeholder — will be swapped when Clinical Agent is ready).
      2. Runs Policy Agent and Financial Agent in parallel for each candidate.
      3. Clinical and Past Decisions scores are N/A (not yet integrated).
      4. Dynamic LLM-based weights are resolved once per claim for policy + financial.
      5. Orchestrator applies per-agent thresholds and routing logic:

         AUTO-APPROVE   — policy ≥ 0.70, financial ≥ 0.60, combined ≥ 0.80
         REVIEW         — policy pending (PA/step-therapy/QL open) AND financial passes
         REVIEW         — policy ≥ 0.70, financial ≥ 0.60, combined < 0.80
         REJECT         — financial fails (hard gate), regardless of policy outcome
         REJECT         — no candidate clears both policy and financial

    Returns the orchestrator decision with summary, routing decision, and per-candidate scores.
    """
    try:
        payload = request.dict(exclude_none=True)
        result = _run_orchestrator_new(payload, request_id=str(uuid.uuid4()))
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Claim evaluation failed: {str(e)}")


@app.post("/api/orchestrate")
async def orchestrate_claim(payload: Dict[str, Any]):
    """
    Legacy orchestration endpoint (kept for backward compatibility).
    Prefer /api/claim/evaluate for new integrations.
    """
    try:
        claim_payload = _coerce_claim_payload(payload)
        if not all(claim_payload.get(k) for k in ["drug_id", "member_id", "plan_id"]):
            raise HTTPException(
                status_code=400,
                detail="Missing required fields: drug_id, member_id, plan_id"
            )
        trace_id = payload.get("trace_id") or payload.get("request_id")
        result = _run_orchestrator_new(claim_payload, request_id=trace_id)
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Orchestration failed: {str(e)}"
        )


@app.post("/api/orchestrator/new")
async def orchestrate_new(request: OrchestratorNewRunRequest):
    """Run the standalone orchestrator_new pipeline through the backend."""
    try:
        payload = request.payload or {}
        return _run_orchestrator_new(
            payload,
            request_id=request.request_id,
            case=request.case,
            runtime_options=request.runtime_options,
            provider_selected_alternative_id=request.provider_selected_alternative_id,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"orchestrator_new run failed: {str(e)}")


# --------------------------------------------------------------------------- #
# Request models for doctor decision feedback
# --------------------------------------------------------------------------- #
class ClaimAcceptRequest(BaseModel):
    member_id: str
    plan_id: str
    original_drug_id: str
    recommended_drug_id: str
    diagnosis: Optional[str] = None
    doctor_id: Optional[str] = None
    npi_number: Optional[str] = None
    policy_score: Optional[float] = None
    clinical_score: Optional[float] = None
    financial_score: Optional[float] = None
    past_score: Optional[float] = None
    confidence_score: Optional[float] = None


class ClaimRejectRequest(BaseModel):
    member_id: str
    plan_id: str
    original_drug_id: str
    recommended_drug_id: str
    diagnosis: Optional[str] = None
    doctor_id: Optional[str] = None
    npi_number: Optional[str] = None
    rejection_reason: Optional[str] = None
    policy_score: Optional[float] = None
    clinical_score: Optional[float] = None
    financial_score: Optional[float] = None
    past_score: Optional[float] = None
    confidence_score: Optional[float] = None


def _get_doctor_responses_path() -> str:
    """Get path to doctor feedback CSV used by past-decisions scoring."""
    # main.py is under backend/app, so backend/data is one level up from here.
    data_dir = os.environ.get("PBM_DATA_DIR", os.path.join(os.path.dirname(__file__), "..", "data"))
    feedback_file = os.environ.get("PBM_DOCTOR_RESPONSES_FILE", "doctor_responses_revised_5.csv")
    return os.path.join(data_dir, feedback_file)


def _append_doctor_decision(decision: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Append a doctor decision row to the configured feedback CSV and return the recorded row."""
    csv_path = _get_doctor_responses_path()
    
    case_id = f"CASE{datetime.now().strftime('%Y%m%d%H%M%S')}{str(uuid.uuid4().hex[:4])}"
    claim_nbr = f"CLM{str(uuid.uuid4().hex[:6]).upper()}"
    rx_nbr = f"RX{str(uuid.uuid4().hex[:6]).upper()}"
    
    now = datetime.now()
    response_dt = now.strftime("%Y-%m-%d")
    response_time = now.strftime("%H:%M:%S")
    
    row = {
        "CASE_ID": case_id,
        "CLAIM_NBR": claim_nbr,
        "RX_NBR": rx_nbr,
        "MBR_SK": payload.get("member_id", ""),
        "DOCTOR_ID": payload.get("doctor_id", "DOC000001"),
        "NPI_NUMBER": payload.get("npi_number", "0000000000"),
        "ORIGINAL_DRUG": f"Drug_{payload.get('original_drug_id', '')}",
        "ORIGINAL_PROD_SK": payload.get("original_drug_id", ""),
        "RECOMMENDED_DRUG": f"Drug_{payload.get('recommended_drug_id', '')}",
        "RECOMMENDED_PROD_SK": payload.get("recommended_drug_id", ""),
        "DECISION": decision,
        "MODIFIED_DRUG": "",
        "REASON_IF_REJECTED": payload.get("rejection_reason", "") if decision == "REJECTED" else "",
        "CONFIDENCE_SCORE": payload.get("confidence_score", ""),
        "POLICY_AGENT_SCORE": payload.get("policy_score", ""),
        "FINANCIAL_AGENT_SCORE": payload.get("financial_score", ""),
        "CLINICAL_AGENT_SCORE": payload.get("clinical_score", ""),
        "PAST_DEC_AGENT_SCORE": payload.get("past_score", ""),
        "ESCALATION_DT": response_dt,
        "RESPONSE_DT": response_dt,
        "RESPONSE_TIME": response_time,
        "RESPONSE_DAYS": "0",
        "DX_CD": payload.get("diagnosis", ""),
        "PLN_SK": payload.get("plan_id", ""),
        "FEEDBACK_STORED_FLG": "Y",
    }
    
    # Append to CSV
    file_exists = os.path.exists(csv_path)
    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=row.keys())
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)
    
    return {
        "case_id": case_id,
        "status": "recorded",
        "decision": decision,
        "message": f"Doctor decision '{decision}' recorded for member {payload.get('member_id')}, "
                   f"original drug {payload.get('original_drug_id')}, "
                   f"recommended drug {payload.get('recommended_drug_id')}."
    }


@app.post("/api/claim/accept")
async def accept_claim(request: ClaimAcceptRequest):
    """
    Record doctor acceptance of a recommended drug.
    
    This writes the acceptance decision to doctor_responses.csv so that 
    the Past Decisions Agent will increase its confidence score for this 
    (original_drug -> recommended_drug) substitution on future similar claims.
    
    Expected workflow:
      1. Call /api/claim/evaluate to get orchestrator decision
      2. If decision is 'doctor_review', doctor chooses a recommended drug
      3. Call /api/claim/accept with the accepted recommendation
      4. Restart/reload backend so Past Decisions Agent picks up new feedback
      5. Re-run same claim -> past_score should now be higher
    """
    try:
        payload = request.dict(exclude_none=True)
        result = _append_doctor_decision("ACCEPTED", payload)
        return result
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to record acceptance: {str(e)}"
        )


@app.post("/api/claim/reject")
async def reject_claim(request: ClaimRejectRequest):
    """
    Record doctor rejection of a recommended drug.
    
    This writes the rejection decision to doctor_responses.csv so that 
    the Past Decisions Agent will decrease its confidence score for this 
    (original_drug -> recommended_drug) substitution on future similar claims.
    
    Expected workflow:
      1. Call /api/claim/evaluate to get orchestrator decision
      2. If decision is 'doctor_review', doctor rejects the recommendation
      3. Call /api/claim/reject with the rejection reason
      4. Restart/reload backend so Past Decisions Agent picks up new feedback
      5. Re-run same claim -> past_score should now be lower
    """
    try:
        payload = request.dict(exclude_none=True)
        result = _append_doctor_decision("REJECTED", payload)
        return result
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to record rejection: {str(e)}"
        )
