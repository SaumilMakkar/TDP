from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.llm.llm_client import LLMConfigError, call_llm_json
from backend.app.agents.past_decisions_agent_final import AgentConfig, DatasetPaths, PastDecisionsAgent


DEFAULT_PAYLOAD: Dict[str, Any] = {
    "original_drug": "Lisinopril",
    "patient_id": "100245",
    "claim_id": "9001123",
    "diagnosis": "I10",
}

DEFAULT_CLINICAL_OUTPUT: Dict[str, Any] = {
    "recommended_drug": "Losartan",
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Post-process Past Decisions Agent output into averaged scores and consolidated reasoning."
    )
    parser.add_argument(
        "--input-file",
        type=Path,
        help="Path to a JSON file containing the raw output returned by PastDecisionsAgent.run().",
    )
    parser.add_argument(
        "--skip-llm",
        action="store_true",
        help="Skip LLM reasoning generation and use deterministic reasoning only.",
    )
    parser.add_argument(
        "--from-test-runner",
        action="store_true",
        help="Run run_past_decisions_agent_test.py and auto-extract the final JSON result.",
    )
    parser.add_argument(
        "--run-agent",
        action="store_true",
        help="Run PastDecisionsAgent directly using payload/clinical JSON, then post-process output.",
    )
    parser.add_argument(
        "--payload-json",
        type=str,
        help="JSON string for agent payload. If omitted in --run-agent mode, built-in sample payload is used.",
    )
    parser.add_argument(
        "--clinical-json",
        type=str,
        help="JSON string for clinical output. If omitted in --run-agent mode, built-in sample clinical output is used.",
    )
    parser.add_argument(
        "--agent-similarity-threshold",
        type=float,
        default=0.30,
        help="Similarity threshold for direct agent run mode.",
    )
    parser.add_argument(
        "--agent-top-k",
        type=int,
        default=5,
        help="Top K matches for direct agent run mode.",
    )
    parser.add_argument(
        "--enable-agent-llm-adjustment",
        action="store_true",
        help="Enable the PastDecisionsAgent internal LLM adjustment during --run-agent mode.",
    )
    return parser.parse_args()


def _parse_json_arg(raw: Optional[str], fallback: Dict[str, Any]) -> Dict[str, Any]:
    if raw is None or not raw.strip():
        return dict(fallback)
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("JSON argument must parse to an object.")
    return parsed


def _run_agent_direct(args: argparse.Namespace) -> Dict[str, Any]:
    payload = _parse_json_arg(args.payload_json, DEFAULT_PAYLOAD)
    clinical_output = _parse_json_arg(args.clinical_json, DEFAULT_CLINICAL_OUTPUT)

    dataset_paths = DatasetPaths(
        doctor_responses="data/doctor_responses.csv",
        claims="data/F_CLM_TRANSACTION.csv",
        product="data/v_d_product.csv",
        prescription="data/v_xxiris_om_prescription.csv",
        member="data/v_d_member.csv",
        patient_history="data/patient_history.csv",
    )

    config = AgentConfig(
        similarity_threshold=args.agent_similarity_threshold,
        top_k=args.agent_top_k,
        enable_llm_patient_adjustment=args.enable_agent_llm_adjustment,
        patient_rule_weight=0.50,
        patient_llm_weight=0.50,
        debug=False,
    )

    agent = PastDecisionsAgent(
        dataset_paths=dataset_paths,
        config=config,
    )

    return agent.run(payload, clinical_output)


def _extract_json_objects(text: str) -> List[Dict[str, Any]]:
    decoder = json.JSONDecoder()
    objects: List[Dict[str, Any]] = []
    idx = 0
    length = len(text)

    while idx < length:
        brace = text.find("{", idx)
        if brace == -1:
            break
        try:
            value, end = decoder.raw_decode(text, brace)
            if isinstance(value, dict):
                objects.append(value)
            idx = end
        except json.JSONDecodeError:
            idx = brace + 1

    return objects


def _extract_agent_output_from_text(text: str) -> Optional[Dict[str, Any]]:
    objects = _extract_json_objects(text)
    for obj in reversed(objects):
        if "top_cases" in obj and "final_score" in obj:
            return obj
    return None


def _load_from_test_runner() -> Dict[str, Any]:
    script = ROOT / "run_past_decisions_agent_test.py"
    if not script.exists():
        raise ValueError(
            "run_past_decisions_agent_test.py was not found. "
            "Provide input via --input-file or pipe JSON to stdin."
        )

    completed = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )

    combined_output = (completed.stdout or "") + "\n" + (completed.stderr or "")
    parsed = _extract_agent_output_from_text(combined_output)
    if parsed is not None:
        return parsed

    raise ValueError(
        "Could not parse Past Decisions JSON from run_past_decisions_agent_test.py output. "
        "Provide input via --input-file or pipe JSON to stdin."
    )


def _load_input(input_file: Optional[Path], from_test_runner: bool) -> Dict[str, Any]:
    if input_file is not None:
        return json.loads(input_file.read_text(encoding="utf-8"))

    if not sys.stdin.isatty():
        raw = sys.stdin.read().strip()
        if raw:
            parsed = _extract_agent_output_from_text(raw)
            if parsed is not None:
                return parsed
            return json.loads(raw)

    if from_test_runner:
        return _load_from_test_runner()

    # Convenience default: if no explicit input is given, try running the local
    # test runner and extracting the final JSON result.
    try:
        return _load_from_test_runner()
    except ValueError:
        pass

    raise ValueError(
        "No input provided. Use one of: "
        "--input-file <path>, pipe JSON to stdin, or --from-test-runner."
    )


def _safe_float(value: Any) -> Optional[float]:
    if value in (None, "", "nan"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round_or_none(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return round(value, 4)


def _average(values: List[Optional[float]]) -> Optional[float]:
    numeric = [value for value in values if value is not None]
    if not numeric:
        return None
    return mean(numeric)


def _build_rank_records(top_cases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []

    for case in top_cases:
        records.append(
            {
                "rank": case.get("rank"),
                "case_id": case.get("case_id"),
                "claim_id": case.get("claim_id"),
                "date": case.get("date"),
                "decision": case.get("decision"),
                "original_drug": case.get("original_drug"),
                "recommended_drug": case.get("recommended_drug"),
                "diagnosis": case.get("diagnosis"),
                "structured_similarity_score": case.get("structured_similarity_score"),
                "modified_score_after_time_decay_and_decision_weight": case.get(
                    "modified_score_after_time_decay_and_decision_weight"
                ),
                "rule_adjustment_score": case.get("rule_adjustment_score"),
                "llm_adjustment_score": case.get("llm_adjustment_score"),
                "combined_patient_adjustment_score": case.get("combined_patient_adjustment_score"),
                "final_score_after_patient_adjustment": case.get("final_score_after_patient_adjustment"),
                "reasoning": case.get("reasoning", []),
            }
        )

    return records


def _build_deterministic_reasoning(summary_input: Dict[str, Any]) -> Dict[str, Any]:
    top_records = summary_input.get("records_used_for_reasoning", [])
    if not top_records:
        return {
            "summary_reasoning": "No ranked historical cases were available, so no additional reasoning could be generated.",
            "case_pattern_summary": [],
            "confidence_statement": "Confidence is based only on the agent-level score because no ranked case list was present.",
        }

    best_case = top_records[0]
    acceptance_count = sum(1 for record in top_records if str(record.get("decision", "")).upper() == "ACCEPTED")
    score_text = summary_input.get("average_rank_final_score")

    pattern_summary = [
        f"Processed {len(top_records)} ranked historical cases.",
        f"{acceptance_count} of those ranked cases were ACCEPTED.",
        f"Top supporting case is {best_case.get('case_id')} with final_score_after_patient_adjustment={best_case.get('final_score_after_patient_adjustment')}.",
    ]

    return {
        "summary_reasoning": (
            "The consolidated score is driven by strongly similar historical cases, mostly accepted decisions, "
            "and positive patient-level alignment across the ranked matches."
        ),
        "case_pattern_summary": pattern_summary,
        "confidence_statement": (
            f"Average final score across the ranked list is {score_text}, which indicates the recommendation is consistently supported "
            "across the matched historical records."
        ),
    }


def _generate_llm_reasoning(summary_input: Dict[str, Any]) -> Dict[str, Any]:
    system_prompt = (
        "You are a reasoning-only summarizer for Past Decisions Agent results. "
        "You must not invent scores, alter scores, or make new clinical recommendations. "
        "Treat current_input as the active request. Historical records are supporting context only. "
        "If historical drugs differ from current_input drugs, explicitly label them as historical examples. "
        "Keep summary_reasoning detailed, but keep case_pattern_summary very simple and short. "
        "Each case_pattern_summary item must be plain English and maximum 12 words. "
        "Use only the provided records and produce JSON with this exact shape: "
        "{\"summary_reasoning\": \"...\", \"case_pattern_summary\": [\"...\"], \"confidence_statement\": \"...\"}."
    )

    user_prompt = json.dumps(summary_input, indent=2, default=str)
    return call_llm_json(system_prompt, user_prompt)


def summarize_past_decisions_output(
    agent_output: Dict[str, Any],
    skip_llm: bool = False,
    current_input: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    top_cases = agent_output.get("top_cases") or []
    rank_records = _build_rank_records(top_cases)

    rank_final_scores = [_safe_float(case.get("final_score_after_patient_adjustment")) for case in top_cases]
    rank_rule_scores = [_safe_float(case.get("rule_adjustment_score")) for case in top_cases]
    rank_llm_scores = [_safe_float(case.get("llm_adjustment_score")) for case in top_cases]
    rank_combined_adjustments = [_safe_float(case.get("combined_patient_adjustment_score")) for case in top_cases]

    summary: Dict[str, Any] = {
        "agent_final_score": _round_or_none(_safe_float(agent_output.get("final_score"))),
        "historical_score": _round_or_none(_safe_float(agent_output.get("historical_score"))),
        "agent_combined_patient_adjustment_score": _round_or_none(
            _safe_float(agent_output.get("combined_patient_adjustment_score", agent_output.get("adjustment_score")))
        ),
        "average_rank_final_score": _round_or_none(_average(rank_final_scores)),
        "average_rank_rule_adjustment_score": _round_or_none(_average(rank_rule_scores)),
        "average_rank_llm_adjustment_score": _round_or_none(_average(rank_llm_scores)),
        "average_rank_combined_patient_adjustment_score": _round_or_none(_average(rank_combined_adjustments)),
        "rank_count": len(top_cases),
        "all_rank_records": rank_records,
    }

    reasoning_input = {
        "current_input": current_input or {},
        "agent_final_score": summary["agent_final_score"],
        "historical_score": summary["historical_score"],
        "average_rank_final_score": summary["average_rank_final_score"],
        "average_rank_rule_adjustment_score": summary["average_rank_rule_adjustment_score"],
        "average_rank_llm_adjustment_score": summary["average_rank_llm_adjustment_score"],
        "average_rank_combined_patient_adjustment_score": summary[
            "average_rank_combined_patient_adjustment_score"
        ],
        "rank_count": summary["rank_count"],
        "records_used_for_reasoning": rank_records,
    }

    if skip_llm:
        summary["reasoning_summary"] = _build_deterministic_reasoning(reasoning_input)
        summary["reasoning_summary_source"] = "deterministic"
        return summary

    try:
        summary["reasoning_summary"] = _generate_llm_reasoning(reasoning_input)
        summary["reasoning_summary_source"] = "llm"
    except LLMConfigError as exc:
        summary["reasoning_summary"] = _build_deterministic_reasoning(reasoning_input)
        summary["reasoning_summary_source"] = "deterministic_fallback"
        summary["reasoning_summary_error"] = str(exc)

    _normalize_reasoning_points(summary)
    return summary


def run_agent_and_summarize_for_ori(
    payload: Dict[str, Any],
    clinical_output: Dict[str, Any],
    similarity_threshold: float = 0.30,
    top_k: int = 5,
    enable_agent_llm_adjustment: bool = False,
    skip_llm: bool = False,
) -> Dict[str, Any]:
    data_dir = ROOT / "data"

    dataset_paths = DatasetPaths(
        doctor_responses=str(data_dir / "doctor_responses.csv"),
        claims=str(data_dir / "F_CLM_TRANSACTION.csv"),
        product=str(data_dir / "v_d_product.csv"),
        prescription=str(data_dir / "v_xxiris_om_prescription.csv"),
        member=str(data_dir / "v_d_member.csv"),
        patient_history=str(data_dir / "patient_history.csv"),
    )

    config = AgentConfig(
        similarity_threshold=similarity_threshold,
        top_k=top_k,
        enable_llm_patient_adjustment=enable_agent_llm_adjustment,
        patient_rule_weight=0.50,
        patient_llm_weight=0.50,
        debug=False,
    )

    agent = PastDecisionsAgent(
        dataset_paths=dataset_paths,
        config=config,
    )

    agent_output = agent.run(payload, clinical_output)
    postprocessed = summarize_past_decisions_output(
        agent_output,
        skip_llm=skip_llm,
        current_input={
            "original_drug": payload.get("original_drug") or payload.get("drug"),
            "recommended_drug": clinical_output.get("recommended_drug") or clinical_output.get("recommended"),
            "diagnosis": payload.get("diagnosis"),
            "claim_id": payload.get("claim_id") or payload.get("CLAIM_NBR"),
            "patient_id": payload.get("patient_id"),
            "member_key": payload.get("member_key") or payload.get("mbr_sk") or payload.get("MBR_SK"),
        },
    )

    reasoning_summary = postprocessed.get("reasoning_summary") or {}
    return {
        "input_medicines": {
            "original_drug": payload.get("original_drug") or payload.get("drug"),
            "recommended_drug": clinical_output.get("recommended_drug") or clinical_output.get("recommended"),
        },
        "final_score": agent_output.get("final_score"),
        "reasoning": {
            "summary_reasoning": reasoning_summary.get("summary_reasoning"),
            "reasoning_points": reasoning_summary.get("case_pattern_summary", []),
            "confidence_statement": reasoning_summary.get("confidence_statement"),
        },
    }


def _simplify_point(text: Any, max_words: int = 12) -> str:
    if text is None:
        return ""

    clean = str(text)
    clean = re.sub(r"\([^)]*\)", "", clean)
    clean = re.sub(r"\s+", " ", clean).strip(" .;:-")

    # Keep only the first sentence-like segment for brevity without
    # breaking decimal numbers like 0.5906.
    parts = re.split(r"[.;]\s+", clean)
    base = parts[0].strip() if parts else clean

    words = base.split()
    if len(words) > max_words:
        base = " ".join(words[:max_words]).rstrip(",")

    return base


def _normalize_reasoning_points(summary: Dict[str, Any]) -> None:
    reasoning = summary.get("reasoning_summary")
    if not isinstance(reasoning, dict):
        return

    points = reasoning.get("case_pattern_summary")
    if not isinstance(points, list):
        return

    simple_points: List[str] = []
    for point in points:
        simple = _simplify_point(point)
        if simple:
            simple_points.append(simple)

    reasoning["case_pattern_summary"] = simple_points


def main() -> None:
    load_dotenv(override=True)
    args = _parse_args()
    try:
        if args.run_agent:
            agent_output = _run_agent_direct(args)
        else:
            agent_output = _load_input(args.input_file, args.from_test_runner)
        result = summarize_past_decisions_output(agent_output, skip_llm=args.skip_llm)
        print(json.dumps(result, indent=2, default=str))
    except ValueError as exc:
        print(f"Input error: {exc}", file=sys.stderr)
        print(
            "Examples:\n"
            "  python run_past_decisions_postprocess.py --run-agent --skip-llm\n"
            "  python run_past_decisions_postprocess.py --from-test-runner\n"
            "  python run_past_decisions_postprocess.py --input-file result.json\n"
            "  type result.json | python run_past_decisions_postprocess.py",
            file=sys.stderr,
        )
        sys.exit(2)


if __name__ == "__main__":
    main()