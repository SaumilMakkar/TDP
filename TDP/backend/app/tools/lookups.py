"""Lookup helpers for turning frontend prescription intake into PBM-ready data.

The frontend can submit human-friendly fields such as patient account id,
provider NPI, drug name, dosage, frequency, days supply, and diagnosis. This
module resolves those values against the CSV-backed PBM reference tables and
returns the normalized identifiers and reference data the agents need.
"""

from __future__ import annotations

import csv
import os
import re
from collections import defaultdict
from datetime import date, datetime
from functools import lru_cache
from typing import Any, Dict, List, Optional

DATA_DIR = os.environ.get(
    "PBM_DATA_DIR",
    os.path.join(os.path.dirname(__file__), "..", "..", "data"),
)


def _read_csv(name: str) -> List[Dict[str, Any]]:
    path = os.path.join(DATA_DIR, name)
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _parse_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


def _date_in_range(check_date: str, from_s: Optional[str], thru_s: Optional[str]) -> bool:
    current = _parse_date(check_date)
    start = _parse_date(from_s)
    end = _parse_date(thru_s)
    if current is None:
        return False
    if start and current < start:
        return False
    if end and current > end:
        return False
    return True


def _normalize_text(value: Optional[str]) -> str:
    if not value:
        return ""
    cleaned = re.sub(r"[^a-z0-9]+", " ", value.lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def _normalize_icd10(value: Optional[str]) -> Optional[str]:
    raw = (value or "").strip()
    if not raw:
        return None
    match = re.match(r"^([A-Z][0-9]{2}(?:\.[0-9A-Z]+)?)", raw, re.IGNORECASE)
    if match:
        return match.group(1).upper()
    return raw


@lru_cache(maxsize=1)
def _members() -> List[Dict[str, Any]]:
    return _read_csv("v_d_member.csv")


@lru_cache(maxsize=1)
def _members_by_account() -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for row in _members():
        out[str(row.get("PATIENT_ACCOUNT_ID") or "")] = row
    return out


@lru_cache(maxsize=1)
def _members_by_id() -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for row in _members():
        out[str(row.get("MBR_SK") or "")] = row
        out[str(row.get("MBR_ID") or "")] = row
    return out


@lru_cache(maxsize=1)
def _products() -> List[Dict[str, Any]]:
    return _read_csv("v_d_product.csv")


@lru_cache(maxsize=1)
def _products_by_id() -> Dict[str, Dict[str, Any]]:
    return {str(row.get("PROD_SK") or ""): row for row in _products()}


@lru_cache(maxsize=1)
def _products_by_prod_id() -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for row in _products():
        prod_id = str(row.get("PROD_ID") or "").strip()
        if prod_id:
            out[prod_id.upper()] = row
    return out


@lru_cache(maxsize=1)
def _pharmacies_by_key() -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for row in _read_csv("v_d_pharmacy.csv"):
        phr_sk = str(row.get("PHR_SK") or "").strip()
        phr_id = str(row.get("PHR_ID") or "").strip()
        if phr_sk:
            out[phr_sk] = row
        if phr_id:
            out[phr_id.upper()] = row
    return out


@lru_cache(maxsize=1)
def _plans() -> Dict[str, Dict[str, Any]]:
    return {str(row.get("PLN_SK") or ""): row for row in _read_csv("v_d_plan.csv")}


@lru_cache(maxsize=1)
def _plan_drug_status() -> Dict[tuple, Dict[str, Any]]:
    return {(str(row.get("PLN_SK") or ""), str(row.get("PROD_SK") or "")): row for row in _read_csv("v_d_plan_drug_status.csv")}


@lru_cache(maxsize=1)
def _pricing_by_drug() -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in _read_csv("v_d_drug_pricing.csv"):
        out[str(row.get("PROD_SK") or "")].append(row)
    return dict(out)


@lru_cache(maxsize=1)
def _claims_by_member() -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in _read_csv("F_CLM_TRANSACTION.csv"):
        out[str(row.get("MBR_SK") or "")].append(row)
    return dict(out)


def resolve_member(patient_account_id: Optional[str] = None, member_id: Optional[str] = None) -> Dict[str, Any]:
    if patient_account_id:
        row = _members_by_account().get(str(patient_account_id))
        if row:
            return {"found": True, "source": "patient_account_id", "member": row}

    if member_id:
        row = _members_by_id().get(str(member_id))
        if row:
            return {"found": True, "source": "member_id", "member": row}

    return {"found": False, "source": None, "member": None}


def resolve_drug(drug_name: Optional[str], drug_rxcui: Optional[str] = None) -> Dict[str, Any]:
    normalized_rxcui = (drug_rxcui or "").strip()
    if normalized_rxcui:
        # In this dataset we treat numeric RXCUI as a best-effort candidate key:
        # - exact PROD_SK match when present
        # - PROD_ID match for IDs like PROD1234
        row = _products_by_id().get(normalized_rxcui)
        if row:
            return {"found": True, "drug": row, "matches": [row], "source": "rxcui_prod_sk"}

        row = _products_by_prod_id().get(normalized_rxcui.upper())
        if row:
            return {"found": True, "drug": row, "matches": [row], "source": "rxcui_prod_id"}

    normalized_query = _normalize_text(drug_name)
    if not normalized_query:
        return {"found": False, "drug": None, "matches": [], "source": None}

    exact_matches: List[Dict[str, Any]] = []
    partial_matches: List[Dict[str, Any]] = []

    for row in _products():
        prod_name = _normalize_text(row.get("PROD_NM"))
        generic_name = _normalize_text(row.get("GNRC_NM"))
        if normalized_query == prod_name or normalized_query == generic_name:
            exact_matches.append(row)
        elif normalized_query in prod_name or normalized_query in generic_name or prod_name in normalized_query or generic_name in normalized_query:
            partial_matches.append(row)

    if exact_matches:
        chosen = exact_matches[0]
        return {
            "found": True,
            "drug": chosen,
            "matches": exact_matches,
            "source": "exact",
        }

    if partial_matches:
        chosen = partial_matches[0]
        return {
            "found": True,
            "drug": chosen,
            "matches": partial_matches,
            "source": "partial",
        }

    return {"found": False, "drug": None, "matches": [], "source": None}


def resolve_pharmacy(pharmacy_id: Optional[str]) -> Dict[str, Any]:
    key = str(pharmacy_id or "").strip()
    if not key:
        return {"found": False, "pharmacy": None, "source": None}

    row = _pharmacies_by_key().get(key) or _pharmacies_by_key().get(key.upper())
    if not row:
        return {"found": False, "pharmacy": None, "source": None}

    source = "PHR_SK" if str(row.get("PHR_SK") or "").strip() == key else "PHR_ID"
    return {"found": True, "pharmacy": row, "source": source}


def resolve_plan(member_row: Optional[Dict[str, Any]] = None, plan_id: Optional[str] = None) -> Dict[str, Any]:
    if plan_id:
        plan = _plans().get(str(plan_id))
        if plan:
            return {"found": True, "plan": plan, "source": "plan_id"}

    if member_row:
        member_plan_id = str(member_row.get("PLN_SK") or "")
        plan = _plans().get(member_plan_id)
        if plan:
            return {"found": True, "plan": plan, "source": "member_plan"}

    return {"found": False, "plan": None, "source": None}


def resolve_formulary(plan_id: Optional[str], drug_id: Optional[str], fill_date: Optional[str] = None) -> Dict[str, Any]:
    if not plan_id or not drug_id:
        return {"found": False, "status": None}

    status = _plan_drug_status().get((str(plan_id), str(drug_id)))
    if status is None:
        return {"found": False, "status": None}

    if fill_date and not _date_in_range(fill_date, status.get("EFF_DT"), status.get("TERM_DT")):
        return {"found": False, "status": status, "reason": "formulary row not active for fill date"}

    return {"found": True, "status": status}


def resolve_pricing(drug_id: Optional[str], fill_date: Optional[str] = None) -> Dict[str, Any]:
    if not drug_id:
        return {"found": False, "pricing": None}

    candidates = _pricing_by_drug().get(str(drug_id), [])
    if not candidates:
        return {"found": False, "pricing": None}

    as_of = fill_date or date.today().isoformat()
    valid_rows = [row for row in candidates if _date_in_range(as_of, row.get("PRICE_EFF_FROM_DT"), row.get("PRICE_EFF_THRU_DT"))]
    pool = valid_rows or candidates
    chosen = sorted(pool, key=lambda row: row.get("PRICE_EFF_FROM_DT") or "")[-1]
    return {"found": True, "pricing": chosen}


def resolve_eligibility(member_row: Optional[Dict[str, Any]], plan_row: Optional[Dict[str, Any]], fill_date: Optional[str]) -> Dict[str, Any]:
    fill_value = fill_date or date.today().isoformat()
    issues: List[str] = []

    if member_row is None:
        issues.append("member not found")
    if plan_row is None:
        issues.append("plan not found")

    member_active = False
    plan_active = False

    if member_row is not None:
        member_active = _date_in_range(fill_value, member_row.get("MBR_EFF_DT"), member_row.get("MBR_TERM_DT"))
        if not member_active:
            issues.append("member coverage inactive on fill date")

    if plan_row is not None:
        plan_active = _date_in_range(fill_value, plan_row.get("PLN_EFF_DT"), plan_row.get("PLN_TERM_DT"))
        if not plan_active:
            issues.append("plan inactive on fill date")

    return {
        "eligible": not issues,
        "member_active": member_active,
        "plan_active": plan_active,
        "issues": issues,
    }


def resolve_claim_history(member_id: Optional[str], plan_id: Optional[str], fill_date: Optional[str]) -> Dict[str, Any]:
    if not member_id:
        return {
            "found": False,
            "claims": [],
            "ytd_oop": None,
            "claim_count": 0,
            "pa_evidence": False,
            "step_therapy_evidence": False,
        }

    fill_value = fill_date or date.today().isoformat()
    year = fill_value[:4]
    claims = []
    ytd_oop = 0.0
    pa_evidence = False

    for row in _claims_by_member().get(str(member_id), []):
        if plan_id and str(row.get("PLN_SK") or "") != str(plan_id):
            continue
        if (row.get("FILLED_DT") or "")[:4] != year:
            continue
        if row.get("CLAIM_STAT_ID") not in ("PAID", "ADJUDICATED"):
            continue
        claims.append(row)
        try:
            ytd_oop += float(row.get("OOP_APPLIED_AMT") or 0)
        except (TypeError, ValueError):
            pass
        if row.get("PA_APPROVED_FLG") == "Y":
            pa_evidence = True

    claims.sort(key=lambda row: row.get("FILLED_DT") or "")

    return {
        "found": True,
        "claims": claims[-10:],
        "ytd_oop": round(ytd_oop, 2),
        "claim_count": len(claims),
        "pa_evidence": pa_evidence,
        "step_therapy_evidence": len(claims) > 0,
    }


def resolve_quantity(dosage: Optional[str], frequency: Optional[str], days_supply: Optional[str]) -> Dict[str, Any]:
    days = None
    try:
        if days_supply not in (None, ""):
            days = int(float(days_supply))
    except (TypeError, ValueError):
        days = None

    if days is None:
        return {"found": False, "quantity": None, "method": None, "notes": ["days supply missing or invalid"]}

    freq_text = _normalize_text(frequency)
    multiplier = 1.0
    method = "days_supply_only"

    if any(token in freq_text for token in ["once daily", "qd", "daily", "q day"]):
        multiplier = 1.0
        method = "daily_frequency"
    elif any(token in freq_text for token in ["bid", "twice daily", "2 times", "two times"]):
        multiplier = 2.0
        method = "bid_frequency"
    elif any(token in freq_text for token in ["tid", "three times", "3 times"]):
        multiplier = 3.0
        method = "tid_frequency"
    elif any(token in freq_text for token in ["qid", "four times", "4 times"]):
        multiplier = 4.0
        method = "qid_frequency"

    quantity = int(round(days * multiplier))
    notes = [f"estimated from {days} day supply and frequency '{frequency or ''}'"]
    if dosage:
        notes.append(f"dosage preserved as input '{dosage}'")

    return {"found": True, "quantity": quantity, "method": method, "notes": notes}


def lookup_pbm_context(intake: Dict[str, Any]) -> Dict[str, Any]:
    def _pick(*keys: str):
        for k in keys:
            if k in intake and intake.get(k) not in (None, ""):
                return intake.get(k)
        return None

    patient_account_id = _pick("patient_account_id", "patientAccountId", "Patient Account ID")
    member_id = _pick("member_id", "memberId", "Member ID")
    plan_id = _pick("plan_id", "planId", "Plan ID")
    drug_name = _pick("drug_name", "drugName", "Drug Name", "prod_nm")
    drug_rxcui = _pick("drug_rxcui", "drugRxcui", "prod_rxcui", "Drug RXCUI")
    dosage = _pick("dosage", "Dosage")
    frequency = _pick("frequency", "frequencey", "Frequency")
    days_supply = _pick("days_supply", "daysSupply", "Days Supply")
    diagnosis = _normalize_icd10(_pick("diagnosis", "Diagnosis"))
    fill_date = _pick("fill_date", "fillDate", "Fill Date") or date.today().isoformat()
    provider_npi = _pick(
        "provider_npi_number",
        "providerNpiNumber",
        "provider_npi",
        "npi_number",
        "Prescriber NPI Number",
    )
    pharmacy_id = _pick("pharmacy_id", "pharmacyId", "phr_id", "Dispensing Pharmacy ID")

    member_lookup = resolve_member(patient_account_id=patient_account_id, member_id=member_id)
    member_row = member_lookup.get("member")
    if member_row and not member_id:
        member_id = str(member_row.get("MBR_SK") or "")

    plan_lookup = resolve_plan(member_row=member_row, plan_id=plan_id)
    plan_row = plan_lookup.get("plan")
    resolved_plan_id = str(plan_row.get("PLN_SK") or plan_id or "") if plan_row else str(plan_id or "")

    drug_lookup = resolve_drug(drug_name, drug_rxcui=drug_rxcui)
    drug_row = drug_lookup.get("drug")
    resolved_drug_id = str(drug_row.get("PROD_SK") or "") if drug_row else None

    pharmacy_lookup = resolve_pharmacy(pharmacy_id)
    pharmacy_row = pharmacy_lookup.get("pharmacy")
    resolved_pharmacy_id = None
    if pharmacy_row:
        resolved_pharmacy_id = str(pharmacy_row.get("PHR_SK") or pharmacy_row.get("PHR_ID") or "")

    quantity_lookup = resolve_quantity(dosage=dosage, frequency=frequency, days_supply=days_supply)
    formulary_lookup = resolve_formulary(resolved_plan_id or plan_id, resolved_drug_id, fill_date)
    pricing_lookup = resolve_pricing(resolved_drug_id, fill_date)
    eligibility_lookup = resolve_eligibility(member_row, plan_row, fill_date)
    claim_history = resolve_claim_history(member_id or (str(member_row.get("MBR_SK") or "") if member_row else None), resolved_plan_id or plan_id, fill_date)

    normalized_payload = {
        "member_id": member_id or (str(member_row.get("MBR_SK") or "") if member_row else None),
        "plan_id": resolved_plan_id or plan_id,
        "drug_id": resolved_drug_id,
        "drug_rxcui": drug_rxcui,
        "pharmacy_id": resolved_pharmacy_id or pharmacy_id,
        "quantity": quantity_lookup.get("quantity"),
        "fill_date": fill_date,
        "diagnosis": diagnosis,
        "original_drug_id": resolved_drug_id,
        "provider_npi_number": provider_npi,
    }

    accumulators = None
    if member_row and plan_row:
        try:
            deductible = float(plan_row.get("DEDUCTIBLE_AMT") or 0)
        except (TypeError, ValueError):
            deductible = 0.0
        try:
            oop_max = float(plan_row.get("MAX_OOP_AMT") or 0)
        except (TypeError, ValueError):
            oop_max = 0.0
        ytd_oop = claim_history.get("ytd_oop")
        if ytd_oop is not None:
            deductible_remaining = max(0.0, round(deductible - ytd_oop, 2))
            oop_remaining = max(0.0, round(oop_max - ytd_oop, 2))
            if oop_max and ytd_oop >= oop_max:
                phase = "CATASTROPHIC"
            elif deductible and ytd_oop < deductible:
                phase = "DEDUCTIBLE"
            else:
                phase = "INITIAL_COVERAGE"
            accumulators = {
                "phase": phase,
                "ytd_oop": ytd_oop,
                "deductible_cap": deductible,
                "oop_max_cap": oop_max,
                "deductible_remaining": deductible_remaining,
                "oop_remaining": oop_remaining,
            }

    return {
        "input": intake,
        "member": member_row,
        "plan": plan_row,
        "drug": drug_row,
        "pharmacy": pharmacy_row,
        "formulary": formulary_lookup.get("status"),
        "pricing": pricing_lookup.get("pricing"),
        "eligibility": eligibility_lookup,
        "claim_history": claim_history,
        "accumulators": accumulators,
        "quantity_lookup": quantity_lookup,
        "normalized_payload": normalized_payload,
        "matches": {
            "patient_account_id": member_lookup,
            "plan": plan_lookup,
            "drug": drug_lookup,
            "pharmacy": pharmacy_lookup,
        },
        "notes": [
            note for note in [
                None if member_lookup.get("found") else "patient account id not resolved to a member",
                None if plan_row else "plan id not resolved from member or request",
                None if drug_lookup.get("found") else "drug name/rxcui not resolved to a product id",
                None if pharmacy_lookup.get("found") else "pharmacy id not resolved",
                None if quantity_lookup.get("found") else "quantity was not reliably derived",
            ] if note
        ],
    }
