"""Stage B deterministic renal/hepatic suitability checks."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from stage_b.config import STAGE_B_DATA_DIR
from stage_b.evidence.common import best_semantic_similarity, candidate_drug_context, normalize_text


RENAL_DOSING_CSV = STAGE_B_DATA_DIR / "renal_dosing_reference.csv"
HEPATIC_DOSING_CSV = STAGE_B_DATA_DIR / "hepatic_dosing_reference.csv"
PATIENT_LABS_CSV = STAGE_B_DATA_DIR / "patient_labs.csv"


def _load_csv(path: Path, columns: list[str]) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=columns)
    return pd.read_csv(path, low_memory=False)


RENAL_REF_DF = _load_csv(RENAL_DOSING_CSV, ["ingredient", "egfr_min", "adjustment_level"])
HEPATIC_REF_DF = _load_csv(HEPATIC_DOSING_CSV, ["ingredient", "child_pugh", "adjustment_level"])
PATIENT_LABS_DF = _load_csv(
    PATIENT_LABS_CSV,
    ["MBR_SK", "eGFR", "CrCl", "Creatinine", "AST", "ALT", "Bilirubin", "Child_Pugh", "Lab_Date"],
)


_CHILD_PUGH_RANK = {"A": 1, "B": 2, "C": 3}


def _is_null(value: object) -> bool:
    return value is None or pd.isna(value) or str(value).strip() == ""


def _to_float(value: object) -> float | None:
    if _is_null(value):
        return None
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _adjustment_to_score(adjustment_level: str) -> tuple[float, str]:
    text = normalize_text(adjustment_level)
    if "contraindicated" in text:
        return (0.0, "CONTRAINDICATED")
    if "avoid" in text and "severe" in text:
        return (0.0, "CONTRAINDICATED")
    if "reduce" in text or "dose review" in text or "lower dose" in text:
        return (0.5, "MODERATE")
    if "monitor" in text:
        return (0.75, "MINOR")
    if "no adjustment" in text:
        return (1.0, "NONE")
    return (0.75, "MINOR")


def _find_patient_labs(mbr_sk: int) -> dict[str, object] | None:
    if mbr_sk <= 0 or PATIENT_LABS_DF.empty:
        return None
    matches = PATIENT_LABS_DF[PATIENT_LABS_DF["MBR_SK"].astype("Int64") == int(mbr_sk)]
    if matches.empty:
        return None
    row = matches.iloc[0]
    return {
        "egfr": _to_float(row.get("eGFR")),
        "crcl": _to_float(row.get("CrCl")),
        "child_pugh": str(row.get("Child_Pugh", "") or "").strip().upper() or None,
        "lab_date": str(row.get("Lab_Date", "") or "").strip() or None,
    }


def evaluate_renal_hepatic_suitability(
    *,
    mbr_sk: int,
    candidate_prod_id: int,
    candidate_context: dict[str, object] | None = None,
) -> dict[str, object]:
    """Return deterministic PASS/FAIL and soft score for renal/hepatic safety."""
    candidate = (
        dict(candidate_context)
        if isinstance(candidate_context, dict)
        else candidate_drug_context(candidate_prod_id)
    )
    candidate_tokens = set(candidate["tokens"])
    candidate_ingredients = set(candidate["ingredients"])
    labs = _find_patient_labs(mbr_sk)

    renal_result: dict[str, object] = {
        "status": "PASS",
        "severity": "NONE",
        "score": 1.0,
        "matched_ingredient": None,
        "adjustment_level": None,
        "egfr": labs.get("egfr") if labs else None,
    }
    hepatic_result: dict[str, object] = {
        "status": "PASS",
        "severity": "NONE",
        "score": 1.0,
        "matched_ingredient": None,
        "adjustment_level": None,
        "child_pugh": labs.get("child_pugh") if labs else None,
    }

    data_complete = labs is not None and labs.get("egfr") is not None and labs.get("child_pugh") is not None
    if labs is None:
        return {
            "status": "UNKNOWN",
            "severity": "UNKNOWN",
            "score": 0.0,
            "reason": "patient_labs_unavailable",
            "data_complete": False,
            "renal": renal_result,
            "hepatic": hepatic_result,
        }

    egfr = labs.get("egfr")
    if egfr is None:
        data_complete = False

    worst_renal_score = 1.0
    worst_renal_row: dict[str, object] | None = None
    drug_found_in_renal_data = False
    for _, row in RENAL_REF_DF.iterrows():
        ingredient = normalize_text(row.get("ingredient"))
        adjustment_level = str(row.get("adjustment_level", "") or "").strip()
        egfr_min = _to_float(row.get("egfr_min"))
        if not ingredient or egfr_min is None:
            continue

        ingredient_hit = best_semantic_similarity(ingredient, candidate_ingredients | candidate_tokens) >= 0.5
        if not ingredient_hit:
            continue
        
        # Drug found in reference data
        drug_found_in_renal_data = True

        if egfr is None:
            continue

        if float(egfr) < float(egfr_min):
            score, severity = _adjustment_to_score(adjustment_level)
            if score < worst_renal_score:
                worst_renal_score = score
                worst_renal_row = {
                    "severity": severity,
                    "score": score,
                    "ingredient": ingredient,
                    "adjustment_level": adjustment_level,
                }

    if worst_renal_row is not None:
        renal_result = {
            "status": "FAIL" if float(worst_renal_row["score"]) <= 0.0 else "PASS",
            "severity": str(worst_renal_row["severity"]),
            "score": float(worst_renal_row["score"]),
            "matched_ingredient": str(worst_renal_row["ingredient"]),
            "adjustment_level": str(worst_renal_row["adjustment_level"]),
            "egfr": egfr,
        }
    elif drug_found_in_renal_data and worst_renal_score == 1.0:
        # Drug found in reference data with "No Adjustment" -> keep 1.0
        renal_result["score"] = 1.0
        renal_result["reason"] = "renal_data_found_no_adjustment"
    elif not drug_found_in_renal_data and labs is not None:
        # Drug NOT in reference data but labs available -> conservative 0.0
        renal_result["score"] = 0.0
        renal_result["reason"] = "renal_data_not_found_conservative"
        renal_result["status"] = "UNKNOWN"

    patient_child_pugh = str(labs.get("child_pugh") or "").strip().upper()
    if patient_child_pugh not in _CHILD_PUGH_RANK:
        data_complete = False

    worst_hepatic_score = 1.0
    worst_hepatic_row: dict[str, object] | None = None
    drug_found_in_hepatic_data = False
    for _, row in HEPATIC_REF_DF.iterrows():
        ingredient = normalize_text(row.get("ingredient"))
        rule_child_pugh = str(row.get("child_pugh", "") or "").strip().upper()
        adjustment_level = str(row.get("adjustment_level", "") or "").strip()

        if not ingredient or rule_child_pugh not in _CHILD_PUGH_RANK:
            continue
        if patient_child_pugh not in _CHILD_PUGH_RANK:
            continue

        ingredient_hit = best_semantic_similarity(ingredient, candidate_ingredients | candidate_tokens) >= 0.5
        if not ingredient_hit:
            continue
        
        # Drug found in reference data
        drug_found_in_hepatic_data = True

        if _CHILD_PUGH_RANK[patient_child_pugh] >= _CHILD_PUGH_RANK[rule_child_pugh]:
            score, severity = _adjustment_to_score(adjustment_level)
            if score < worst_hepatic_score:
                worst_hepatic_score = score
                worst_hepatic_row = {
                    "severity": severity,
                    "score": score,
                    "ingredient": ingredient,
                    "adjustment_level": adjustment_level,
                }

    if worst_hepatic_row is not None:
        hepatic_result = {
            "status": "FAIL" if float(worst_hepatic_row["score"]) <= 0.0 else "PASS",
            "severity": str(worst_hepatic_row["severity"]),
            "score": float(worst_hepatic_row["score"]),
            "matched_ingredient": str(worst_hepatic_row["ingredient"]),
            "adjustment_level": str(worst_hepatic_row["adjustment_level"]),
            "child_pugh": patient_child_pugh,
        }
    elif drug_found_in_hepatic_data and worst_hepatic_score == 1.0:
        # Drug found in reference data with "No Adjustment" -> keep 1.0
        hepatic_result["score"] = 1.0
        hepatic_result["reason"] = "hepatic_data_found_no_adjustment"
    elif not drug_found_in_hepatic_data and labs is not None:
        # Drug NOT in reference data but labs available -> conservative 0.0
        hepatic_result["score"] = 0.0
        hepatic_result["reason"] = "hepatic_data_not_found_conservative"
        hepatic_result["status"] = "UNKNOWN"

    overall_score = min(float(renal_result["score"]), float(hepatic_result["score"]))
    overall_fail = bool(renal_result["status"] == "FAIL" or hepatic_result["status"] == "FAIL")

    if overall_fail:
        overall_status = "FAIL"
        overall_severity = "CONTRAINDICATED"
        reason = "renal_or_hepatic_contraindication"
    elif overall_score < 1.0:
        overall_status = "PASS"
        overall_severity = "MODERATE" if overall_score <= 0.7 else "MINOR"
        reason = "renal_or_hepatic_adjustment_recommended"
    else:
        overall_status = "PASS"
        overall_severity = "NONE"
        reason = "no_renal_or_hepatic_adjustment_needed"

    return {
        "status": overall_status,
        "severity": overall_severity,
        "score": float(overall_score),
        "reason": reason,
        "data_complete": bool(data_complete),
        "renal": renal_result,
        "hepatic": hepatic_result,
    }
