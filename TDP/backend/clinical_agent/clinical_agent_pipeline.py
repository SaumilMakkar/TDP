"""Consolidated clinical agent pipeline that executes Stage A, Stage B, then Stage C.

This module accepts one consolidated input payload, runs Stage A first,
then feeds Stage A alternatives into Stage B for member-specific evaluation,
and finally packages Stage C candidates from the Stage A and Stage B outputs.
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

from stage_c.candidate_selection import select_candidates
from stage_c.clinical_rationale import build_clinical_rationale
from stage_c.composite_score import compute_composite_scores
from stage_c.config import load_stage_c_config
from stage_c.evidence_packaging import package_evidence
from stage_c.final_payload import build_final_payload
from stage_c.ranking import rank_candidates
from stage_c.safety_flags import evaluate_safety_flags, load_stage_b_patient_labs
from stage_c.threshold import filter_passing_candidates
from stage_a.api.stage_a_service import StageAPipelineError, run_stage_a_pipeline
from stage_a.llm.ambiguity_resolver import build_default_stage_a_resolver
from stage_b.api.stage_b_service import StageBPipelineError, run_stage_b_sprint1_8
from stage_b.llm.ambiguity_resolver import build_default_stage_b_resolver
from stage_b.normalization.patient_normalizer import build_patient, resolve_member_id


class ClinicalAgentPipelineError(Exception):
    """Raised when consolidated clinical agent execution cannot complete."""


TraceWriter = Callable[[str], None]


def _build_trace_writer(enabled: bool, trace_writer: TraceWriter | None) -> TraceWriter | None:
    if trace_writer is not None:
        return trace_writer
    if not enabled:
        return None
    return lambda message: print(message, flush=True)


def _trace(trace_writer: TraceWriter | None, message: str) -> None:
    if trace_writer is not None:
        trace_writer(message)


def _trace_stage(trace_writer: TraceWriter | None, stage: str, message: str) -> None:
    _trace(trace_writer, f"[TRACE] {stage}: {message}")


def _format_elapsed_seconds(value: float) -> str:
    if value >= 1.0:
        return f"{value:.2f}s"
    return f"{value:.3f}s"


def _coerce_prod_sk(payload: dict[str, object]) -> int:
    raw = payload.get("prod_sk") or payload.get("product_id")
    if raw is None:
        raise ClinicalAgentPipelineError("Consolidated input must include 'prod_sk' (or 'product_id').")
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise ClinicalAgentPipelineError(f"Invalid prod_sk '{raw}'. Expected integer.") from exc


def _coerce_member_id(payload: dict[str, object]) -> str:
    raw = payload.get("member_id") or payload.get("member") or payload.get("mbr_id")
    if raw is None:
        raise ClinicalAgentPipelineError(
            "Consolidated input must include 'member_id' (or 'member'/'mbr_id')."
        )
    if not str(raw).strip():
        raise ClinicalAgentPipelineError("member_id/member/mbr_id must be non-empty.")
    try:
        return resolve_member_id(raw)
    except Exception as exc:
        raise ClinicalAgentPipelineError(str(exc)) from exc


def _build_stage_a_input(payload: dict[str, object]) -> dict[str, object]:
    stage_a_input: dict[str, object] = {
        "prod_sk": _coerce_prod_sk(payload),
    }
    for key in ("drug_name",):
        if key in payload and payload.get(key) is not None:
            stage_a_input[key] = payload[key]
    return stage_a_input


def _build_stage_b_input(
    payload: dict[str, object],
    *,
    stage_a_output: dict[str, Any],
) -> dict[str, object]:
    original = stage_a_output.get("original", {}) if isinstance(stage_a_output, dict) else {}
    original_drug = payload.get("original_drug") or original.get("prod_name")

    return {
        "member": _coerce_member_id(payload),
        "original_drug": original_drug,
        "candidate_drug": payload.get("candidate_drug"),
    }


def _build_per_alternative_view(stage_b_output: dict[str, Any]) -> list[dict[str, object]]:
    stage_b_alternatives = stage_b_output.get("alternatives", []) if isinstance(stage_b_output, dict) else []
    stage_b_by_prod_id: dict[int, dict[str, Any]] = {}
    for alt in stage_b_alternatives:
        try:
            prod_id = int(alt.get("prod_id", -1))
        except (TypeError, ValueError):
            continue
        if prod_id > 0:
            stage_b_by_prod_id[prod_id] = alt

    alternatives = stage_b_output.get("from_stage_a", {}).get("alternatives", [])
    per_alternative: list[dict[str, object]] = []

    for alt in alternatives:
        stage_a_evidence = alt.get("evidence", {}) if isinstance(alt.get("evidence", {}), dict) else {}
        stage_a_view = {
            "evidence": dict(stage_a_evidence),
            "score": alt.get("score"),
            "status": alt.get("status"),
            "llm_required": alt.get("llm_required"),
            "reasoning": alt.get("reasoning", ""),
        }

        try:
            prod_id = int(alt.get("prod_id", -1))
        except (TypeError, ValueError):
            prod_id = -1
        stage_b_alt = stage_b_by_prod_id.get(prod_id, {})
        stage_b_evidence = stage_b_alt.get("evidence", {}) if isinstance(stage_b_alt, dict) else {}

        stage_b_view = {
            "evidence": dict(stage_b_evidence) if isinstance(stage_b_evidence, dict) else {},
            "score": stage_b_alt.get("score", alt.get("patient_safety_score", alt.get("stage_b_score"))),
            "status": stage_b_alt.get("status", alt.get("stage_b_decision")),
            "llm_required": stage_b_alt.get("llm_required", alt.get("stage_b_llm_required")),
            "reasoning": str(stage_b_alt.get("reasoning", alt.get("stage_b_reasoning", ""))),
        }

        per_alternative.append(
            {
                "prod_id": alt.get("prod_id"),
                "prod_name": alt.get("prod_name"),
                "stage_a": stage_a_view,
                "stage_b": stage_b_view,
            }
        )

    return per_alternative


def _build_stage_c_view(
    stage_a_output: dict[str, Any],
    stage_b_output: dict[str, Any],
    *,
    member_id: str,
    trace_writer: TraceWriter | None = None,
) -> tuple[dict[str, object], dict[str, object]]:
    """Build the final Stage C payload plus a separate debug artifact."""

    def public_stage_b_view(stage_b_payload: dict[str, Any]) -> dict[str, Any]:
        summary_evidence = stage_b_payload.get("evidence", {})
        if not isinstance(summary_evidence, dict):
            summary_evidence = {}

        internal_evidence = stage_b_payload.get("stage_b_evidence", {})
        if isinstance(internal_evidence, dict):
            scores = internal_evidence.get("scores")
            if isinstance(scores, dict):
                summary_evidence = dict(scores)

        return {
            "evidence": dict(summary_evidence),
            "score": stage_b_payload.get("stage_b_score", stage_b_payload.get("score")),
            "status": stage_b_payload.get("stage_b_decision", stage_b_payload.get("status")),
            "llm_required": stage_b_payload.get(
                "stage_b_llm_required",
                stage_b_payload.get("llm_required"),
            ),
            "reasoning": str(
                stage_b_payload.get("stage_b_reasoning", stage_b_payload.get("reasoning", ""))
            ),
        }

    def public_eligible_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
        public_candidate = dict(candidate)
        stage_b_payload = candidate.get("stage_b")
        if isinstance(stage_b_payload, dict):
            public_candidate["stage_b"] = public_stage_b_view(stage_b_payload)
        return public_candidate

    def public_packaged_candidate(candidate_payload: dict[str, Any]) -> dict[str, Any]:
        public_candidate = dict(candidate_payload)
        public_candidate.pop("stage_c_flags", None)
        stage_b_evidence = candidate_payload.get("stage_b_evidence", {})
        if isinstance(stage_b_evidence, dict):
            public_candidate["stage_b_evidence"] = dict(stage_b_evidence)
        return public_candidate

    stage_c_started_at = time.perf_counter()
    selected_candidates = select_candidates(stage_a_output, stage_b_output)
    packaged_candidates = package_evidence(selected_candidates["eligible_candidates"])
    config = load_stage_c_config()
    patient = build_patient(member_id)
    patient_payload = patient.to_dict()
    patient_labs = load_stage_b_patient_labs(patient_payload)
    flagged_candidates = []
    for candidate in packaged_candidates:
        flags = evaluate_safety_flags(candidate, patient_payload, patient_labs, candidate.stage_b_evidence)
        flagged_candidates.append({
            "candidate_id": candidate.candidate_id,
            "flags": asdict(flags),
        })

    compute_composite_scores(packaged_candidates, config)
    composite_score_summary = " | ".join(
        f"{candidate.candidate_id} composite_score={candidate.composite_score} "
        f"stage_a={candidate.stage_a_score} stage_b={candidate.stage_b_score} "
        f"threshold={config.minimum_composite_score} passed={candidate.threshold_passed}"
        for candidate in packaged_candidates
    ) or "no eligible candidates"
    _trace_stage(trace_writer, "Stage C scores", composite_score_summary)
    passing_candidates = filter_passing_candidates(packaged_candidates, config)
    ranked_candidates = rank_candidates(passing_candidates)
    for candidate in ranked_candidates:
        build_clinical_rationale(candidate)

    original = stage_a_output.get("original", {}) if isinstance(stage_a_output, dict) else {}
    final_payload = build_final_payload(
        {
            "prod_id": original.get("prod_id"),
            "prod_name": original.get("prod_name"),
        },
        ranked_candidates,
    )
    flagged_count = sum(
        1
        for candidate in flagged_candidates
        if isinstance(candidate.get("flags"), dict) and any(bool(value) for value in candidate["flags"].values())
    )
    _trace_stage(
        trace_writer,
        "Stage C complete",
        "eligible_candidates="
        f"{len(selected_candidates['eligible_candidates'])}, passing_candidates={len(passing_candidates)}, "
        f"ranked_alternatives={len(final_payload.get('ranked_alternatives', []))}, "
        f"flagged_candidates={flagged_count}, elapsed={_format_elapsed_seconds(time.perf_counter() - stage_c_started_at)}",
    )

    debug_artifact = {
        "eligible_candidates": [
            public_eligible_candidate(candidate) for candidate in selected_candidates["eligible_candidates"]
        ],
        "packaged_candidates": [
            public_packaged_candidate(asdict(candidate)) for candidate in packaged_candidates
        ],
        "safety_flags": flagged_candidates,
        "passing_candidate_ids": [candidate.candidate_id for candidate in ranked_candidates],
        "per_alternative": _build_per_alternative_view(stage_b_output),
        "stage_b_summary": {
            "accepted": sum(
                1
                for item in stage_b_output.get("alternatives", [])
                if isinstance(item, dict) and item.get("status") == "accepted"
            ),
            "rejected": sum(
                1
                for item in stage_b_output.get("alternatives", [])
                if isinstance(item, dict) and item.get("status") == "rejected"
            ),
        },
    }
    return final_payload, debug_artifact


def run_clinical_agent_pipeline(
    consolidated_input: dict[str, object],
    *,
    debug: bool = False,
    ambiguity_resolver=None,
    trace: bool = False,
    trace_writer: TraceWriter | None = None,
) -> dict[str, object]:
    """Run Stage A, Stage B, then Stage C from one consolidated payload.

    Required input fields:
    - prod_sk (or product_id)
    - member_id (or member/mbr_id)

    Optional fields (passed through where relevant):
    - drug_name
    - original_drug, candidate_drug
    """
    payload = dict(consolidated_input)
    trace_sink = _build_trace_writer(trace, trace_writer)
    pipeline_started_at = time.perf_counter()
    _trace_stage(
        trace_sink,
        "Pipeline start",
        f"prod_sk={payload.get('prod_sk') or payload.get('product_id')}, member_id={payload.get('member_id') or payload.get('member') or payload.get('mbr_id')}",
    )
    if ambiguity_resolver is None:
        stage_a_resolver = build_default_stage_a_resolver(skill_version="default")
        stage_b_resolver = build_default_stage_b_resolver()
    else:
        stage_a_resolver = ambiguity_resolver
        stage_b_resolver = ambiguity_resolver

    stage_a_input = _build_stage_a_input(payload)
    _trace_stage(trace_sink, "Stage A", "matching clinical alternatives...")
    try:
        stage_a_started_at = time.perf_counter()
        stage_a_output = run_stage_a_pipeline(stage_a_input, ambiguity_resolver=stage_a_resolver)
        _trace_stage(
            trace_sink,
            "Stage A complete",
            f"original_prod_id={stage_a_output.get('original', {}).get('prod_id')}, alternatives={len(stage_a_output.get('alternatives', []))}, elapsed={_format_elapsed_seconds(time.perf_counter() - stage_a_started_at)}",
        )
    except StageAPipelineError as exc:
        raise ClinicalAgentPipelineError(str(exc)) from exc

    stage_b_input = _build_stage_b_input(payload, stage_a_output=stage_a_output)
    _trace_stage(trace_sink, "Stage B", "evaluating patient safety...")
    try:
        stage_b_started_at = time.perf_counter()
        stage_b_output = run_stage_b_sprint1_8(
            stage_b_input,
            stage_a_output=stage_a_output,
            ambiguity_resolver=stage_b_resolver,
        )
        accepted = sum(
            1
            for item in stage_b_output.get("alternatives", [])
            if isinstance(item, dict) and item.get("status") == "accepted"
        )
        rejected = sum(
            1
            for item in stage_b_output.get("alternatives", [])
            if isinstance(item, dict) and item.get("status") == "rejected"
        )
        _trace_stage(
            trace_sink,
            "Stage B complete",
            f"reviewed={len(stage_b_output.get('alternatives', []))}, accepted={accepted}, rejected={rejected}, elapsed={_format_elapsed_seconds(time.perf_counter() - stage_b_started_at)}",
        )
    except StageBPipelineError as exc:
        raise ClinicalAgentPipelineError(str(exc)) from exc

    _trace_stage(trace_sink, "Stage C", "combining scores, applying threshold, and ranking candidates...")
    final_payload, debug_artifact = _build_stage_c_view(
        stage_a_output,
        stage_b_output,
        member_id=_coerce_member_id(payload),
        trace_writer=trace_sink,
    )
    _trace_stage(
        trace_sink,
        "Pipeline complete",
        f"ranked_alternatives={len(final_payload.get('ranked_alternatives', []))}, total_elapsed={_format_elapsed_seconds(time.perf_counter() - pipeline_started_at)}",
    )
    if debug:
        output = dict(final_payload)
        output["_debug"] = debug_artifact
        return output
    return final_payload


DEFAULT_CONSOLIDATED_INPUT: dict[str, object] = {
    "prod_sk": 1013, "drug_name": "Sertraline 50mg", "member_id": "MBR0002004"
    # "prod_sk": 1034, "drug_name": "Sacubitril-Valsartan 24-26mg", "member_id": "MBR0002074"
    # "prod_sk": 1022, "drug_name": "Apixaban 5mg", "member_id": "MBR0002034"
    # "prod_sk": 1006, "drug_name": "Metformin 500mg", "member_id": "MBR0002012"
    # "prod_sk": 1035, "drug_name": "Amoxicillin 500mg", "member_id": "MBR0002012"
    # "prod_sk": 1025, "drug_name": "Aspirin 81mg", "member_id": "MBR0002005"
    # "prod_sk": 1026, "drug_name": "Gabapentin 300mg", "member_id": "MBR0002001"
    # "prod_sk": 1013, "drug_name": "Sertraline 50mg", "member_id": "MBR0002002"
    # "prod_sk": 1032, "drug_name": "Spironolactone 25mg", "member_id": "MBR0002074"
}



DEFAULT_OUTPUT_FILE = "clinical_agent_output.json"


def _split_debug_output(output: dict[str, object]) -> tuple[dict[str, object], dict[str, object] | None]:
    main_output = dict(output)
    debug_output = main_output.pop("_debug", None)
    if isinstance(debug_output, dict):
        return main_output, debug_output
    return main_output, None


def _debug_output_path(output_file: str) -> Path:
    path = Path(output_file).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return path.with_name(f"{path.stem}_debug{path.suffix or '.json'}")


def write_pipeline_output(output: dict[str, object], output_file: str) -> Path:
    main_output, _ = _split_debug_output(output)
    out_path = Path(output_file).expanduser()
    if not out_path.is_absolute():
        out_path = Path.cwd() / out_path
    out_path.write_text(json.dumps(main_output, indent=2), encoding="utf-8")
    return out_path


def write_debug_output(output: dict[str, object], output_file: str) -> Path | None:
    _, debug_output = _split_debug_output(output)
    if debug_output is None:
        return None

    out_path = _debug_output_path(output_file)
    out_path.write_text(json.dumps(debug_output, indent=2), encoding="utf-8")
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run consolidated clinical agent pipeline (Stage A, Stage B, then Stage C)."
    )
    parser.add_argument(
        "--input-json",
        type=str,
        default=None,
        help="Optional JSON string for consolidated input. If omitted, built-in default is used.",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Print a compact summary instead of full JSON output.",
    )
    parser.add_argument(
        "--output-file",
        type=str,
        default=DEFAULT_OUTPUT_FILE,
        help="Output JSON file path. Default: clinical_agent_output.json",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Also produce and write Stage C debug/intermediate artifacts.",
    )
    parser.add_argument(
        "--trace",
        action="store_true",
        default=True,
        help="Print a live end-to-end trace of Stage A, Stage B, and Stage C while the pipeline runs (default: enabled).",
    )
    parser.add_argument(
        "--no-trace",
        dest="trace",
        action="store_false",
        help="Disable terminal trace output and only write the JSON artifacts.",
    )
    args = parser.parse_args()

    if args.input_json:
        payload = json.loads(args.input_json)
    else:
        payload = dict(DEFAULT_CONSOLIDATED_INPUT)

    output = run_clinical_agent_pipeline(payload, debug=args.debug or args.pretty, trace=args.trace)
    output_path = write_pipeline_output(output, args.output_file)
    debug_output_path = write_debug_output(output, args.output_file) if args.debug else None
    main_output, debug_output = _split_debug_output(output)

    if args.pretty:
        ranked_alternatives = main_output.get("ranked_alternatives", []) if isinstance(main_output, dict) else []
        member_id = payload.get("member_id") or payload.get("member") or payload.get("mbr_id")
        if isinstance(debug_output, dict):
            accepted = int(debug_output.get("stage_b_summary", {}).get("accepted", 0))
            rejected = int(debug_output.get("stage_b_summary", {}).get("rejected", 0))
            stage_c_candidates = len(debug_output.get("packaged_candidates", []))
            print(
                "Clinical Agent ready for "
                f"member={member_id} "
                f"accepted={accepted} rejected={rejected} "
                f"stage_c_candidates={stage_c_candidates} "
                f"ranked_alternatives={len(ranked_alternatives)}"
            )
        else:
            print(
                "Clinical Agent ready for "
                f"member={member_id} "
                f"ranked_alternatives={len(ranked_alternatives)}"
            )
        print(f"Output written to: {output_path}")
        if debug_output_path is not None:
            print(f"Debug output written to: {debug_output_path}")
    else:
        print(f"Output written to: {output_path}")
        if debug_output_path is not None:
            print(f"Debug output written to: {debug_output_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
