"""Stage A orchestration for Sprints 1-4 with a single JSON output entry point."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from stage_a.normalization.drug_builder import PRODUCT_DF, build_drug
from stage_a.normalization.rxnorm_mapper import REFERENCE_SERVICE
from stage_a.normalization.rxnorm_mapper import normalize_drug
from stage_a.retrieval.formulary_service import get_alternatives
from stage_a.evidence import evaluate_evidence
from stage_a.scoring import (
    compute_weighted_similarity_score,
    confidence_engine,
    get_default_ahp_weights,
)
from stage_a.scoring.confidence import LLM_REVIEW_MIN_THRESHOLD

try:
    from stage_a.llm.ambiguity_resolver import AmbiguityResolver
except Exception:  # pragma: no cover - resolver is optional in offline test runs
    AmbiguityResolver = Any

logger = logging.getLogger(__name__)


class StageAPipelineError(Exception):
    """Raised when Stage A runtime pipeline cannot produce a valid response."""


def _run_async_blocking(coro: Any) -> Any:
    """Run a coroutine from sync code, even when an event loop is already running."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(asyncio.run, coro)
        return future.result()


def _coerce_stage_a_input(stage_a_input) -> tuple[int, dict[str, object]]:
    """
    Normalize Stage A input into a product_id and input metadata.

    Supported inputs:
    - int/str PROD_SK (legacy)
    - dict payload with key `prod_sk` (or `product_id` fallback)
    """
    if isinstance(stage_a_input, dict):
        payload = dict(stage_a_input)
        raw_prod_sk = payload.get("prod_sk", payload.get("product_id"))
        if raw_prod_sk is None:
            raise StageAPipelineError("Stage A input payload must include 'prod_sk'.")
        try:
            product_id = int(raw_prod_sk)
        except (TypeError, ValueError) as exc:
            raise StageAPipelineError(
                f"Invalid prod_sk '{raw_prod_sk}'. Expected an integer PROD_SK."
            ) from exc
        return product_id, payload

    try:
        product_id = int(stage_a_input)
    except (TypeError, ValueError) as exc:
        raise StageAPipelineError(
            f"Invalid prod_sk '{stage_a_input}'. Expected an integer PROD_SK."
        ) from exc
    return product_id, {"prod_sk": product_id}


def _existing_rxcui_for_product(product_id: int) -> str | None:
    rows = PRODUCT_DF[PRODUCT_DF["PROD_SK"] == int(product_id)]
    if rows.empty:
        return None
    raw = rows.iloc[0].get("RXCUI")
    if raw is None:
        return None
    raw_str = str(raw).strip()
    if raw_str == "" or raw_str.lower() == "nan":
        return None
    return raw_str


def _is_missing(value: object) -> bool:
    if value is None:
        return True
    text = str(value).strip().lower()
    return text in {"", "nan", "none"}


def _to_text(value: object) -> str | None:
    if _is_missing(value):
        return None
    return str(value).strip()


def _to_float(value: object) -> float | None:
    if _is_missing(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _split_semicolon_list(value: object) -> list[str]:
    text = _to_text(value)
    if text is None:
        return []
    parts = [part.strip() for part in text.split(";") if part.strip()]
    return parts


def _normalize_strength(drug, rxnorm_ref: dict[str, Any] | None) -> dict[str, object]:
    if isinstance(rxnorm_ref, dict):
        status = _to_text(rxnorm_ref.get("strength_normalization_status")) or "missing"
        if status not in {"converted", "unconvertible_unit", "missing"}:
            status = "missing"
        return {
            "value": _to_float(rxnorm_ref.get("normalized_strength_value")),
            "unit": _to_text(rxnorm_ref.get("normalized_strength_unit")) or "",
            "status": status,
        }

    strengths = list(getattr(drug, "strengths", []) or [])
    first = strengths[0] if strengths else {}
    return {
        "value": _to_float(first.get("strength")) if isinstance(first, dict) else None,
        "unit": _to_text(first.get("unit")) or "",
        "status": "missing",
    }


def _drug_payload(drug, rxnorm: dict[str, str | None]) -> dict[str, object]:
    rxnorm_ref = getattr(drug, "rxnorm_ref", None)
    ingredient = _to_text(rxnorm.get("ingredient")) or _to_text(getattr(drug, "generic_name", None)) or ""
    dose_form = _to_text(rxnorm.get("dose_form")) or _to_text(getattr(drug, "dosage_form", None)) or ""

    if isinstance(rxnorm_ref, dict):
        combo_raw = _to_text(rxnorm_ref.get("is_combination_product"))
        if combo_raw is None:
            is_combination_product = len(list(getattr(drug, "ingredients", []) or [])) > 1
        else:
            is_combination_product = combo_raw.lower() == "true"
        lookup_confidence = _to_text(rxnorm_ref.get("lookup_confidence")) or "missing"
        moa_lookup_confidence = _to_text(rxnorm_ref.get("moa_lookup_confidence")) or "missing"
    else:
        is_combination_product = len(list(getattr(drug, "ingredients", []) or [])) > 1
        lookup_confidence = "missing"
        moa_lookup_confidence = "missing"

    payload = {
        "product_id": int(getattr(drug, "product_id")),
        "product_name": _to_text(getattr(drug, "product_name", None)) or "",
        "ndc": _to_text(getattr(drug, "ndc", None)) or "",
        "ingredient": ingredient,
        "active_moiety": _to_text(rxnorm.get("active_moiety")),
        "route": _to_text(rxnorm.get("route")),
        "dose_form": dose_form,
        "therapeutic_class": _to_text(getattr(drug, "therapeutic_class", None)) or "",
        "strength": _normalize_strength(drug, rxnorm_ref),
        "is_combination_product": bool(is_combination_product),
        "moa_classes": _split_semicolon_list(
            rxnorm_ref.get("verified_moa_classes_normalized") if isinstance(rxnorm_ref, dict) else None
        ),
        "data_quality_flags": {
            "rxcui_in_verified": bool(
                REFERENCE_SERVICE.is_field_verified(rxnorm_ref, "verified_rxcui_in") if isinstance(rxnorm_ref, dict) else False
            ),
            "lookup_confidence": lookup_confidence,
            "moa_lookup_confidence": moa_lookup_confidence,
        },
    }
    return payload


def _minimal_drug_payload(drug) -> dict[str, object]:
    return {
        "prod_id": int(getattr(drug, "product_id")),
        "prod_name": _to_text(getattr(drug, "product_name", None)) or "",
    }


def _resolve_reasoning(
    ambiguity_resolver,
    *,
    original_payload: dict[str, object],
    candidate_payload: dict[str, object],
    evidence: dict[str, float],
    base_score: float,
    confidence_result: dict[str, object],
) -> str:
    if ambiguity_resolver is None:
        return ""

    try:
        resolve_fn = getattr(ambiguity_resolver, "resolve_sync", None)
        if callable(resolve_fn):
            response = resolve_fn(
                original_drug=original_payload,
                candidate_drug=candidate_payload,
                evidence=evidence,
                base_score=base_score,
                confidence_score=base_score,
                llm_required=bool(confidence_result["llm_required"]),
                confidence_level=str(confidence_result["confidence_level"]),
            )
            return str(response.get("reasoning", "") or "")

        async_fn = getattr(ambiguity_resolver, "resolve", None)
        if callable(async_fn):
            response = _run_async_blocking(
                async_fn(
                    original_drug=original_payload,
                    candidate_drug=candidate_payload,
                    evidence=evidence,
                    base_score=base_score,
                    confidence_score=base_score,
                    llm_required=bool(confidence_result["llm_required"]),
                    confidence_level=str(confidence_result["confidence_level"]),
                )
            )
            return str(response.get("reasoning", "") or "")
    except Exception as exc:
        logger.warning("Stage A ambiguity resolution failed: %s", exc)
    return ""


def run_stage_a_pipeline(stage_a_input, ambiguity_resolver: AmbiguityResolver | None = None) -> dict:
    """Run Stage A runtime pipeline using PROD_SK from a legacy value or payload dict."""
    product_id, _input_payload = _coerce_stage_a_input(stage_a_input)

    rows = PRODUCT_DF[PRODUCT_DF["PROD_SK"] == product_id]
    if rows.empty:
        raise StageAPipelineError(f"PROD_SK {product_id} was not found in v_d_product.csv.")

    original = build_drug(product_id)
    alternatives = get_alternatives(product_id)

    logger.info("Running Stage A pipeline for PROD_SK=%s with %s alternatives.", product_id, len(alternatives))

    original_rxcui = _existing_rxcui_for_product(original.product_id)
    original_norm = normalize_drug(
        original.ndc,
        existing_rxcui=original_rxcui,
        generic_name=original.generic_name,
        product_id=original.product_id,
    )

    output = {
        "original": _minimal_drug_payload(original),
        "alternatives": [],
    }

    ahp_weights = get_default_ahp_weights()

    seen_alternative_ids: set[int] = set()
    for alt in alternatives:
        if int(alt.product_id) in seen_alternative_ids:
            logger.info(
                "Skipping duplicate alternative PROD_SK=%s for original PROD_SK=%s.",
                alt.product_id,
                product_id,
            )
            continue
        seen_alternative_ids.add(int(alt.product_id))

        alt_rxcui = _existing_rxcui_for_product(alt.product_id)
        alt_norm = normalize_drug(
            alt.ndc,
            existing_rxcui=alt_rxcui,
            generic_name=alt.generic_name,
            product_id=alt.product_id,
        )
        evidence = evaluate_evidence(original, alt, original_norm, alt_norm)

        candidate_payload = _minimal_drug_payload(alt)
        criterion_scores = {
            "ingredient": float(evidence["ingredient"]),
            "moiety": float(evidence["moiety"]),
            "class": float(evidence["class"]),
            "moa": float(evidence["moa"]),
            "combo": float(evidence["combo"]),
            "route": float(evidence["route"]),
            "form": float(evidence["form"]),
            "strength": float(evidence["strength"]),
        }
        candidate_payload["evidence"] = criterion_scores
        base_score = round(
            compute_weighted_similarity_score(criterion_scores, ahp_weights),
            4,
        )
        candidate_payload["score"] = float(base_score)
        candidate_payload["status"] = "rejected" if float(base_score) < LLM_REVIEW_MIN_THRESHOLD else "accepted"
        confidence_result = confidence_engine(
            evidence=criterion_scores,
            base_similarity_score=float(base_score),
        )
        candidate_payload["llm_required"] = bool(confidence_result["llm_required"])
        if candidate_payload["llm_required"]:
            candidate_payload["reasoning"] = _resolve_reasoning(
                ambiguity_resolver,
                original_payload=output["original"],
                candidate_payload=candidate_payload,
                evidence=criterion_scores,
                base_score=float(base_score),
                confidence_result=confidence_result,
            )
        output["alternatives"].append(candidate_payload)

    return output


def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(level=level, format="%(levelname)s:%(name)s:%(message)s")


def _main() -> int:
    parser = argparse.ArgumentParser(description="Run Stage A Sprint 1-4 pipeline for a PROD_SK.")
    parser.add_argument("prod_sk", type=int, help="Product surrogate key (PROD_SK)")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose diagnostic logging")
    args = parser.parse_args()

    _configure_logging(args.verbose)
    result = run_stage_a_pipeline(args.prod_sk)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
