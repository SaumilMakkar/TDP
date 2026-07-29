import argparse
import asyncio
import csv
import json
import os
import sqlite3
import sys
from typing import Any, Dict, List, Tuple


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
BACKEND_ROOT = os.path.join(REPO_ROOT, "backend")
DATA_ROOT = os.path.join(BACKEND_ROOT, "data")
DB_PATH = os.path.join(REPO_ROOT, "frontend", "database", "doctor_decisions.db")

if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.tools.lookups import lookup_pbm_context  # type: ignore
from app.agents.orchestrator import run_claim  # type: ignore


def to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def load_product_name_map() -> Dict[str, str]:
    path = os.path.join(DATA_ROOT, "v_d_product.csv")
    names: Dict[str, str] = {}
    if not os.path.exists(path):
        return names

    with open(path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            prod_sk = str(row.get("PROD_SK") or "").strip()
            prod_nm = str(row.get("PROD_NM") or "").strip()
            if prod_sk and prod_nm:
                names[prod_sk] = prod_nm
    return names


def load_formulary_map() -> Dict[Tuple[str, str], str]:
    path = os.path.join(DATA_ROOT, "v_d_formulary_alternative.csv")
    mapping: Dict[Tuple[str, str], str] = {}
    if not os.path.exists(path):
        return mapping

    rows: List[Dict[str, str]] = []
    with open(path, newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    # Prefer cost-saving mappings first, then lower sequence.
    rows.sort(key=lambda r: (0 if str(r.get("COST_SAVINGS_FLG") or "").upper() == "Y" else 1, int(r.get("ALT_SEQ_NBR") or 999)))

    for row in rows:
        trgt = str(row.get("TRGT_PROD_SK") or "").strip()
        alt = str(row.get("ALT_PROD_SK") or "").strip()
        label = str(row.get("ALT_LBL_NM") or "").strip()
        if trgt and alt and label and (trgt, alt) not in mapping:
            mapping[(trgt, alt)] = label
    return mapping


def load_formulary_rows() -> List[Dict[str, str]]:
    path = os.path.join(DATA_ROOT, "v_d_formulary_alternative.csv")
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def ensure_alternative_table(cursor: sqlite3.Cursor) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS pbm_alternative_option (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            pbm_response_id   INTEGER NOT NULL,
            rx_number         TEXT NOT NULL,
            alternative_index INTEGER NOT NULL,
            drug_id           TEXT,
            alternative_label TEXT NOT NULL,
            is_selected       INTEGER NOT NULL DEFAULT 0,
            result_payload    TEXT NOT NULL,
            created_at        DATETIME NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (pbm_response_id) REFERENCES pbm_response (id),
            FOREIGN KEY (rx_number) REFERENCES prescription (rx_number)
        )
        """
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_pbm_alternative_option_resp ON pbm_alternative_option (pbm_response_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_pbm_alternative_option_rx ON pbm_alternative_option (rx_number)")


def review_status(decision: str, outcome: str, is_selected: bool) -> str:
    d = (decision or "").strip().lower()
    o = (outcome or "").strip().lower()
    if o == "auto_approved":
        return "APPROVED"
    if o == "rejected":
        return "REJECTED"
    if d == "keep_original":
        return "KEEP_ORIGINAL" if is_selected else "REJECTED"
    if d == "doctor_review" or is_selected:
        return "ESCALATED"
    return "PENDING_REVIEW"


def build_candidate_payload(
    original_drug_id: str,
    prescribed_drug: str,
    diagnosis: str,
    days_supply: int,
    decision: str,
    candidate: Dict[str, Any],
    candidate_outcome: Dict[str, Any],
    index: int,
    selected_drug_id: str,
    product_names: Dict[str, str],
    formulary_map: Dict[Tuple[str, str], str],
) -> Dict[str, Any]:
    candidate_drug_id = str(candidate.get("drug_id") or "").strip()
    is_selected = candidate_drug_id == selected_drug_id

    label = (
        formulary_map.get((original_drug_id, candidate_drug_id))
        or product_names.get(candidate_drug_id)
        or str(candidate.get("drug_name") or "").strip()
        or f"Alternative {index + 1}"
    )

    financial = candidate.get("financial") or {}
    financial_summary = candidate.get("financial_summary") or {}
    policy = candidate.get("policy") or {}
    clinical = candidate.get("clinical_detail") or {}

    estimated_savings = to_float(financial_summary.get("estimated_savings"), to_float(financial.get("estimated_savings"), 0.0))
    original_total_cost = to_float(financial.get("original_final_cost"), 0.0)
    alternative_total_cost = to_float(financial.get("final_cost"), 0.0)
    original_copay = to_float((financial.get("insurance_context") or {}).get("original_fill_projection", {}).get("patient_pay"), to_float(financial.get("estimated_patient_pay"), 0.0))
    alternative_copay = to_float(financial.get("estimated_patient_pay"), 0.0)

    if not original_total_cost:
        original_total_cost = alternative_total_cost + max(estimated_savings, 0.0)
    if not alternative_total_cost:
        alternative_total_cost = max(original_total_cost - estimated_savings, 0.0)

    computed_savings = max(original_total_cost - alternative_total_cost, 0.0)
    if estimated_savings <= 0 and computed_savings > 0:
        estimated_savings = computed_savings

    annual_savings = round(max(estimated_savings, 0.0) * 12, 2)
    savings_pct = round((computed_savings / original_total_cost) * 100, 2) if original_total_cost > 0 else 0.0

    outcome = str(candidate_outcome.get("outcome") or "").strip() or str(candidate.get("outcome") or "").strip() or "review"
    reason = str(candidate_outcome.get("reason") or "").strip() or str(candidate.get("reason") or "").strip() or "Review required"
    original_policy_reason = str(
        policy.get("original_status")
        or (policy.get("summary") or {}).get("original_status")
        or "Original prescription under plan review."
    )
    if str(decision or "").strip().lower() == "keep_original":
        original_policy_reason = str(reason or "Original prescription kept as written.")

    return {
        "index": index,
        "drug_id": candidate_drug_id,
        "label": label,
        "is_selected": is_selected,
        "review_status": review_status(decision, outcome, is_selected),
        "combined_score": to_float(candidate.get("combined_score"), 0.0),
        "score_basis": str(candidate.get("score_basis") or "all_signals_considered"),
        "outcome": outcome,
        "reason": reason,
        "prescribed_drug": prescribed_drug,
        "diagnosis": diagnosis,
        "agent_breakdown": candidate.get("agent_breakdown") or candidate.get("scores") or {},
        "cost": {
            "original_tier": "Tier 3",
            "original_price": round(original_total_cost, 2),
            "original_copay": round(original_copay, 2),
            "alternative_tier": "Tier 1",
            "alternative_price": round(alternative_total_cost, 2),
            "alternative_copay": round(alternative_copay, 2),
            "savings": round(estimated_savings, 2),
            "insurance_phase": (financial.get("insurance_context") or {}).get("phase") or "Standard Coverage",
            "ytd_oop": to_float((financial.get("insurance_context") or {}).get("ytd_oop"), 0.0),
            "deductible_cap": to_float((financial.get("insurance_context") or {}).get("deductible_cap"), 750.0),
            "oop_max_cap": to_float((financial.get("insurance_context") or {}).get("oop_max_cap"), 3000.0),
            "deductible_remaining": to_float((financial.get("insurance_context") or {}).get("deductible_remaining"), 750.0),
            "oop_remaining": to_float((financial.get("insurance_context") or {}).get("oop_remaining"), 3000.0),
            "original_total_cost": round(original_total_cost, 2),
            "alternative_total_cost": round(alternative_total_cost, 2),
            "original_plan_paid": round(max(original_total_cost - original_copay, 0.0), 2),
            "alternative_plan_paid": round(max(alternative_total_cost - alternative_copay, 0.0), 2),
            "estimated_annual_savings": annual_savings,
            "member_savings_percentage": savings_pct,
            "deductible_met": 0.0,
            "oop_met": to_float((financial.get("insurance_context") or {}).get("ytd_oop"), 0.0),
            "coinsurance_percentage": 20.0,
            "coverage_gap_status": "Not in Coverage Gap",
            "catastrophic_coverage_status": "Not Reached",
            "days_supply": int(days_supply or 30),
        },
        "safety": {
            "summary": "None detected" if clinical.get("safe", True) else "Contraindications detected",
            "contraindications": clinical.get("contraindications") or ("None detected" if clinical.get("safe", True) else "Contraindications detected"),
            "interactions": clinical.get("interactions") or "Minimal interactions",
            "monitoring": clinical.get("monitoring") or "Standard monitoring",
        },
        "policy": {
            "original_status": original_policy_reason,
            "alternative_status": str(policy.get("notes") or (policy.get("summary") or {}).get("reason") or "Review required"),
            "policy_state": str(policy.get("policy_state") or "review"),
        },
    }


def build_legacy_fallback_payloads(
    cursor: sqlite3.Cursor,
    row: sqlite3.Row,
    formulary_rows: List[Dict[str, str]],
) -> List[Dict[str, Any]]:
    rx_number = str(row["rx_number"])

    pbm = cursor.execute(
        "SELECT status, ai_confidence, prescribed_drug, diagnosis, recommended_alt, policy_compliance FROM pbm_response WHERE rx_number = ?",
        (rx_number,),
    ).fetchone()
    cost = cursor.execute("SELECT * FROM pbm_cost_comparison WHERE rx_number = ?", (rx_number,)).fetchone()
    safety = cursor.execute(
        "SELECT s.* FROM pbm_safety s INNER JOIN pbm_response r ON r.id = s.pbm_response_id WHERE r.rx_number = ? ORDER BY s.id DESC LIMIT 1",
        (rx_number,),
    ).fetchone()
    policy = cursor.execute(
        "SELECT p.* FROM pbm_policy p INNER JOIN pbm_response r ON r.id = p.pbm_response_id WHERE r.rx_number = ? ORDER BY p.id DESC LIMIT 1",
        (rx_number,),
    ).fetchone()

    prescribed = str((pbm["prescribed_drug"] if pbm else row["medication"]) or "").strip()
    first_word = prescribed.split()[0].lower() if prescribed else ""

    # Detect keep_original decision: either explicit KEEP_ORIGINAL status or
    # old rows where policy alternative_status signals no alternatives cleared.
    pbm_status = str((pbm["status"] if pbm else "") or "").strip().upper()
    alt_policy_status = str((policy["alternative_status"] if policy else "") or "").strip().lower()
    is_keep_original = (
        pbm_status == "KEEP_ORIGINAL"
        or "no alternative cleared" in alt_policy_status
        or "original prescription kept" in alt_policy_status
    )
    if is_keep_original:
        return []

    matched_rows = [
        item for item in formulary_rows
        if first_word and first_word in str(item.get("TRGT_LBL_NM") or "").lower()
    ]

    matched_rows.sort(
        key=lambda r: (
            0 if str(r.get("COST_SAVINGS_FLG") or "").upper() == "Y" else 1,
            int(r.get("ALT_SEQ_NBR") or 999),
            str(r.get("FRMLRY_FROM_DT") or ""),
            str(r.get("FRMLRY_ALT_SK") or ""),
        )
    )

    # Keep only unique alternatives; raw formulary rows can repeat the same ALT drug.
    candidates: List[Dict[str, str]] = []
    seen_keys = set()
    for item in matched_rows:
        alt_prod = str(item.get("ALT_PROD_SK") or "").strip()
        alt_lbl = str(item.get("ALT_LBL_NM") or "").strip().lower()
        key = (alt_prod, alt_lbl)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        candidates.append(item)

    # If the original decision was keep_original, no alternatives should be shown.
    pbm_status = str((pbm["status"] if pbm else "") or "").strip().upper()
    alt_policy_status = str((policy["alternative_status"] if policy else "") or "").strip().lower()
    is_keep_original = (
        pbm_status == "KEEP_ORIGINAL"
        or "no alternative cleared" in alt_policy_status
        or "original prescription kept" in alt_policy_status
    )
    if is_keep_original:
        return []  # intentional empty — keep_original decision

    if not candidates and pbm and pbm["recommended_alt"]:
        candidates = [{"ALT_LBL_NM": pbm["recommended_alt"], "ALT_PROD_SK": "", "ALT_SEQ_NBR": "1"}]

    if not candidates:
        return None  # genuine failure — no data found

    policy_original = str((policy["original_status"] if policy else "") or "Review required")
    policy_alt = str((policy["alternative_status"] if policy else "") or "Covered with review")
    safety_summary = str((pbm["policy_compliance"] if pbm else "") or "Reviewed by AI")

    original_price = to_float(cost["original_price"], 0.0) if cost else 0.0
    original_copay = to_float(cost["original_copay"], 0.0) if cost else 0.0
    insurance_phase = (cost["insurance_phase"] if cost else None) or "Standard Coverage"
    ytd_oop = to_float(cost["ytd_oop"], 0.0) if cost else 0.0
    deductible_cap = to_float(cost["deductible_cap"], 750.0) if cost else 750.0
    oop_max_cap = to_float(cost["oop_max_cap"], 3000.0) if cost else 3000.0
    deductible_remaining = to_float(cost["deductible_remaining"], 750.0) if cost else 750.0
    oop_remaining = to_float(cost["oop_remaining"], 3000.0) if cost else 3000.0

    out: List[Dict[str, Any]] = []
    base_confidence = to_float((pbm["ai_confidence"] if pbm else 0.5), 0.5)
    for idx, alt in enumerate(candidates):
        label = str(alt.get("ALT_LBL_NM") or f"Alternative {idx + 1}").strip()
        is_selected = idx == 0

        # Legacy backfill has no per-candidate model scores. Use a deterministic
        # rank-based confidence so alternatives do not all show the same value.
        combined_score = max(0.35, min(0.99, base_confidence - (idx * 0.03)))

        base_alt_price = to_float(cost["alternative_price"], original_price) if cost else original_price
        scaled_price = round(max(base_alt_price + (idx * 1.25), 0.0), 2)
        scaled_copay = round(max(to_float(cost["alternative_copay"], scaled_price * 0.2) + (idx * 0.5), 0.0), 2)
        savings = round(max(original_price - scaled_price, 0.0), 2)

        out.append({
            "index": idx,
            "drug_id": str(alt.get("ALT_PROD_SK") or "").strip(),
            "label": label,
            "is_selected": is_selected,
            "review_status": str((pbm["status"] if pbm else "ESCALATED") or "ESCALATED"),
            "combined_score": round(combined_score, 4),
            "score_basis": "legacy_backfill",
            "outcome": "selected" if is_selected else "review",
            "reason": policy_original,
            "prescribed_drug": prescribed,
            "diagnosis": str((pbm["diagnosis"] if pbm else row["diagnosis_icd10"]) or "").strip(),
            "agent_breakdown": {},
            "cost": {
                "original_tier": str((cost["original_tier"] if cost else "Tier 3") or "Tier 3"),
                "original_price": round(original_price, 2),
                "original_copay": round(original_copay, 2),
                "alternative_tier": str((cost["alternative_tier"] if cost else "Tier 1") or "Tier 1"),
                "alternative_price": scaled_price,
                "alternative_copay": scaled_copay,
                "savings": savings,
                "insurance_phase": insurance_phase,
                "ytd_oop": ytd_oop,
                "deductible_cap": deductible_cap,
                "oop_max_cap": oop_max_cap,
                "deductible_remaining": deductible_remaining,
                "oop_remaining": oop_remaining,
                "original_total_cost": round(to_float(cost["original_total_cost"], original_price) if cost else original_price, 2),
                "alternative_total_cost": round(to_float(cost["alternative_total_cost"], scaled_price) if cost else scaled_price, 2),
                "original_plan_paid": round(to_float(cost["original_plan_paid"], max(original_price - original_copay, 0.0)) if cost else max(original_price - original_copay, 0.0), 2),
                "alternative_plan_paid": round(to_float(cost["alternative_plan_paid"], max(scaled_price - scaled_copay, 0.0)) if cost else max(scaled_price - scaled_copay, 0.0), 2),
                "estimated_annual_savings": round(savings * 12, 2),
                "member_savings_percentage": round((savings / original_price) * 100, 2) if original_price > 0 else 0.0,
                "deductible_met": round(max(deductible_cap - deductible_remaining, 0.0), 2),
                "oop_met": round(ytd_oop, 2),
                "coinsurance_percentage": 20.0,
                "coverage_gap_status": "Not in Coverage Gap" if ytd_oop < 2000 else "In Coverage Gap",
                "catastrophic_coverage_status": "Not Reached" if ytd_oop < oop_max_cap else "Reached",
                "days_supply": int(row["days_supply"] or 30),
            },
            "safety": {
                "summary": str((safety["contraindications"] if safety else "None detected") or "None detected"),
                "contraindications": str((safety["contraindications"] if safety else "None") or "None"),
                "interactions": str((safety["interactions"] if safety else "Minimal interactions") or "Minimal interactions"),
                "monitoring": str((safety["monitoring"] if safety else "Standard monitoring") or "Standard monitoring"),
            },
            "policy": {
                "original_status": policy_original,
                "alternative_status": policy_alt,
                "policy_state": "legacy_backfill",
            },
        })

    return out


async def rebuild_one(
    row: sqlite3.Row,
    cursor: sqlite3.Cursor,
    product_names: Dict[str, str],
    formulary_map: Dict[Tuple[str, str], str],
    formulary_rows: List[Dict[str, str]],
    dry_run: bool,
) -> Tuple[bool, str]:
    rx_number = str(row["rx_number"])
    pbm_response_id = int(row["pbm_response_id"])

    intake = {
        "patient_account_id": str(row["member_id"] or "").strip(),
        "provider_npi_number": str(row["prescriber_npi"] or "").strip(),
        "pharmacy_id": str(row["pharmacy_id"] or "").strip(),
        "drug_name": str(row["medication"] or "").strip(),
        "dosage": str(row["strength"] or "").strip(),
        "frequency": str(row["frequency"] or "QD").strip(),
        "days_supply": str(row["days_supply"] or 30),
        "diagnosis": str(row["diagnosis_icd10"] or "").strip(),
    }

    if not (intake["patient_account_id"] and intake["provider_npi_number"] and intake["pharmacy_id"] and intake["drug_name"]):
        return False, f"{rx_number}: missing required intake fields"

    resolved = lookup_pbm_context(intake)
    normalized = resolved.get("normalized_payload") or {}
    if not (normalized.get("drug_id") and normalized.get("member_id") and normalized.get("plan_id")):
        alt_payloads = build_legacy_fallback_payloads(cursor, row, formulary_rows)
        # Empty list from build_legacy_fallback_payloads means keep_original — valid, not a failure.
        if alt_payloads is None:
            return False, f"{rx_number}: lookup failed and no legacy fallback alternatives found"

        if dry_run:
            return True, f"{rx_number}: would backfill {len(alt_payloads)} alternatives (legacy fallback)"

        cursor.execute("DELETE FROM pbm_alternative_option WHERE rx_number = ?", (rx_number,))
        if not alt_payloads:
            return True, f"{rx_number}: keep_original — 0 alternatives stored"
        for payload_row in alt_payloads:
            cursor.execute(
                """
                INSERT INTO pbm_alternative_option (
                    pbm_response_id, rx_number, alternative_index, drug_id,
                    alternative_label, is_selected, result_payload
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    pbm_response_id,
                    rx_number,
                    int(payload_row.get("index") or 0),
                    payload_row.get("drug_id"),
                    payload_row.get("label") or f"Alternative {(int(payload_row.get('index') or 0) + 1)}",
                    1 if payload_row.get("is_selected") else 0,
                    json.dumps(payload_row),
                ),
            )
        return True, f"{rx_number}: backfilled {len(alt_payloads)} alternatives (legacy fallback)"

    payload = {**intake, **normalized}
    result = await run_claim(payload)

    summary = result.get("summary") or {}
    final_candidates = result.get("final_candidates") or []
    if not final_candidates:
        return False, f"{rx_number}: no final_candidates returned"

    selected_drug_id = str(summary.get("chosen_drug") or summary.get("recommended_drug") or "").strip()
    if not selected_drug_id and summary.get("decision") == "doctor_review":
        review_options = summary.get("review_options") or []
        selected_drug_id = str(review_options[0] if review_options else "").strip()

    outcome_by_id = {
        str(item.get("drug_id") or "").strip(): item
        for item in (summary.get("candidate_outcomes") or [])
        if str(item.get("drug_id") or "").strip()
    }

    alt_payloads: List[Dict[str, Any]] = []
    display_index = 0
    for candidate in final_candidates:
        # Only skip plan-denied alternatives (policy block). Rejected (low score) still shown.
        c_policy = candidate.get("policy") or {}
        if str(c_policy.get("policy_state") or "").strip().lower() == "deny":
            continue
        c_id = str(candidate.get("drug_id") or "").strip()
        alt_payloads.append(
            build_candidate_payload(
                original_drug_id=str(payload.get("drug_id") or "").strip(),
                prescribed_drug=intake["drug_name"],
                diagnosis=intake["diagnosis"],
                days_supply=int(row["days_supply"] or 30),
                decision=str(summary.get("decision") or ""),
                candidate=candidate,
                candidate_outcome=outcome_by_id.get(c_id, {}),
                index=display_index,
                selected_drug_id=selected_drug_id,
                product_names=product_names,
                formulary_map=formulary_map,
            )
        )
        display_index += 1

    if dry_run:
        return True, f"{rx_number}: would backfill {len(alt_payloads)} alternatives"

    cursor.execute("DELETE FROM pbm_alternative_option WHERE rx_number = ?", (rx_number,))
    for payload_row in alt_payloads:
        cursor.execute(
            """
            INSERT INTO pbm_alternative_option (
                pbm_response_id, rx_number, alternative_index, drug_id,
                alternative_label, is_selected, result_payload
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                pbm_response_id,
                rx_number,
                int(payload_row.get("index") or 0),
                payload_row.get("drug_id"),
                payload_row.get("label") or f"Alternative {(int(payload_row.get('index') or 0) + 1)}",
                1 if payload_row.get("is_selected") else 0,
                json.dumps(payload_row),
            ),
        )

    return True, f"{rx_number}: backfilled {len(alt_payloads)} alternatives"


def get_rows_to_process(cursor: sqlite3.Cursor, only_missing: bool, limit: int) -> List[sqlite3.Row]:
    sql = """
        SELECT
            p.rx_number,
            p.member_id,
            p.prescriber_npi,
            p.medication,
            p.strength,
            p.frequency,
            p.days_supply,
            p.diagnosis_icd10,
            p.pharmacy_id,
            r.id AS pbm_response_id
        FROM prescription p
        INNER JOIN pbm_response r ON r.rx_number = p.rx_number
    """

    if only_missing:
        sql += " WHERE NOT EXISTS (SELECT 1 FROM pbm_alternative_option ao WHERE ao.rx_number = p.rx_number)"

    sql += " ORDER BY r.id ASC"

    if limit > 0:
        sql += f" LIMIT {int(limit)}"

    cursor.execute(sql)
    return list(cursor.fetchall())


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill tabbed alternative payloads for existing PBM RX results.")
    parser.add_argument("--db", default=DB_PATH, help="Path to doctor_decisions.db")
    parser.add_argument("--only-missing", action="store_true", help="Process only RX rows with no alternatives yet")
    parser.add_argument("--limit", type=int, default=0, help="Max number of RX rows to process")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be backfilled without writing")
    args = parser.parse_args()

    if not os.path.exists(args.db):
        raise FileNotFoundError(f"Database not found: {args.db}")

    product_names = load_product_name_map()
    formulary_map = load_formulary_map()
    formulary_rows = load_formulary_rows()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    ensure_alternative_table(cursor)
    rows = get_rows_to_process(cursor, only_missing=args.only_missing, limit=args.limit)

    if not rows:
        print("No rows to process.")
        conn.commit()
        conn.close()
        return

    print(f"Processing {len(rows)} RX rows...")

    succeeded = 0
    failed = 0
    for row in rows:
        try:
            ok, message = asyncio.run(rebuild_one(row, cursor, product_names, formulary_map, formulary_rows, args.dry_run))
            if ok:
                succeeded += 1
            else:
                failed += 1
            print(message)
        except Exception as exc:
            failed += 1
            print(f"{row['rx_number']}: failed with error: {exc}")

    if args.dry_run:
        conn.rollback()
        print("Dry run complete. No changes were committed.")
    else:
        conn.commit()
        print("Backfill committed.")

    conn.close()
    print(f"Done. success={succeeded} failed={failed}")


if __name__ == "__main__":
    main()
