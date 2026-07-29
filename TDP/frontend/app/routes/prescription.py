from flask import Blueprint, request, jsonify, Response, stream_with_context, current_app
from datetime import datetime, date, timedelta
import json
import random
import importlib
import requests
import os
import csv
import re
import config as _config_module          # imported as module so we can reload it
from app.db import get_db_connection
from app.utils import token_required, role_required

prescription_bp = Blueprint('prescription', __name__)


class IntakeValidationError(Exception):
    def __init__(self, details):
        super().__init__("Validation failed")
        self.details = [str(item) for item in (details or []) if str(item).strip()]


def _calculate_due_date(date_written, is_completed, pbm_status='', decision_status=''):
    """Calculate due date for a prescription. Returns DONE if completed, otherwise a date string."""
    if is_completed:
        return 'DONE'
    
    # Parse the date_written or use today
    raw = str(date_written or '').strip()
    try:
        base = datetime.strptime(raw, '%Y-%m-%d').date() if raw else date.today()
    except ValueError:
        base = date.today()
    
    # Determine offset days based on pbm_status and decision_status
    pbm = str(pbm_status or '').strip().upper()
    decision = str(decision_status or '').strip().upper()
    
    offset_days = 2  # default for normal pending
    if pbm == 'ESCALATED':
        offset_days = 3
    elif pbm == 'IN_PROGRESS':
        offset_days = 1
    
    return (base + timedelta(days=offset_days)).strftime('%Y-%m-%d')


@prescription_bp.route('/progress/<trace_id>')
def stream_progress(trace_id):
    """Proxy Server-Sent Events from the FastAPI backend to the browser."""
    pbm_api_url = os.environ.get("PBM_ORCHESTRATOR_URL", "http://127.0.0.1:8000/api/orchestrate")
    backend_base = pbm_api_url.split('/api/')[0]
    sse_url = f"{backend_base}/progress/{trace_id}"

    def generate():
        try:
            with requests.get(sse_url, stream=True, timeout=120) as r:
                for line in r.iter_lines():
                    if line:
                        yield line.decode('utf-8') + '\n\n'
        except Exception as exc:
            current_app.logger.warning(
                "SSE proxy stream failed",
                extra={
                    "trace_id": trace_id,
                    "sse_url": sse_url,
                    "error": str(exc),
                },
            )

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )

_DIAGNOSIS_DATA = None
_DRUG_DATA = None
_REJECTION_REASON_DATA = None
_FORMULARY_ALT_DATA = None
_PRODUCT_NAME_BY_ID = None
_OVERALL_THRESHOLD_CACHE = None


def _get_overall_threshold():
    """Read overall_threshold from backend scoring_config.json with safe fallback."""
    global _OVERALL_THRESHOLD_CACHE
    if _OVERALL_THRESHOLD_CACHE is not None:
        return _OVERALL_THRESHOLD_CACHE

    config_path = os.path.join(
        os.path.dirname(__file__),
        '..', '..', '..', 'backend', 'app', 'config', 'scoring_config.json'
    )
    try:
        with open(config_path, encoding='utf-8') as f:
            config = json.load(f)
        _OVERALL_THRESHOLD_CACHE = float(config.get('overall_threshold', 0.80))
    except Exception:
        _OVERALL_THRESHOLD_CACHE = 0.80

    return _OVERALL_THRESHOLD_CACHE


def _load_formulary_alternative_data():
    """Load v_d_formulary_alternative.csv from the backend data directory."""
    global _FORMULARY_ALT_DATA
    if _FORMULARY_ALT_DATA is None:
        data_dir = os.environ.get(
            'PBM_DATA_DIR',
            os.path.join(os.path.dirname(__file__), '..', '..', '..', 'backend', 'data')
        )
        csv_path = os.path.join(data_dir, 'v_d_formulary_alternative.csv')
        _FORMULARY_ALT_DATA = []
        if os.path.exists(csv_path):
            with open(csv_path, newline='', encoding='utf-8') as f:
                for row in csv.DictReader(f):
                    _FORMULARY_ALT_DATA.append(row)
    return _FORMULARY_ALT_DATA


def _lookup_formulary_alternative(drug_name: str) -> str:
    """
    Find the best real formulary alternative for a drug name.
    Prefers COST_SAVINGS_FLG='Y'; falls back to first match by sequence.
    Returns the ALT_LBL_NM or empty string if nothing found.
    """
    rows = _load_formulary_alternative_data()
    if not rows:
        return ''
    drug_lower = drug_name.lower()
    # Match on first significant word of the target label (e.g. 'lisinopril')
    first_word = drug_lower.split()[0] if drug_lower else ''
    candidates = [
        r for r in rows
        if first_word and first_word in r.get('TRGT_LBL_NM', '').lower()
    ]
    if not candidates:
        return ''
    # Prefer cost-saving alternative, then lowest ALT_SEQ_NBR
    savings = [r for r in candidates if r.get('COST_SAVINGS_FLG', '').upper() == 'Y']
    pool = savings if savings else candidates
    pool.sort(key=lambda r: int(r.get('ALT_SEQ_NBR') or 99))
    return pool[0].get('ALT_LBL_NM', '').strip()


def _lookup_formulary_alt_label_by_ids(target_prod_sk: str, alt_prod_sk: str) -> str:
    """Resolve a target->alt pair to ALT_LBL_NM from formulary alternatives."""
    target = str(target_prod_sk or '').strip()
    alt = str(alt_prod_sk or '').strip()
    if not target or not alt:
        return ''

    rows = _load_formulary_alternative_data()
    matches = [
        r for r in rows
        if str(r.get('TRGT_PROD_SK') or '').strip() == target
        and str(r.get('ALT_PROD_SK') or '').strip() == alt
    ]
    if not matches:
        return ''

    # Prefer cost-saving mapping, otherwise earliest sequence.
    savings = [r for r in matches if str(r.get('COST_SAVINGS_FLG') or '').upper() == 'Y']
    pool = savings if savings else matches
    pool.sort(key=lambda r: int(r.get('ALT_SEQ_NBR') or 99))
    return str(pool[0].get('ALT_LBL_NM') or '').strip()


def _load_product_name_map():
    """Load PROD_SK -> PROD_NM map from backend v_d_product.csv for display labels."""
    global _PRODUCT_NAME_BY_ID
    if _PRODUCT_NAME_BY_ID is None:
        data_dir = os.environ.get(
            'PBM_DATA_DIR',
            os.path.join(os.path.dirname(__file__), '..', '..', '..', 'backend', 'data')
        )
        csv_path = os.path.join(data_dir, 'v_d_product.csv')
        _PRODUCT_NAME_BY_ID = {}
        if os.path.exists(csv_path):
            with open(csv_path, newline='', encoding='utf-8') as f:
                for row in csv.DictReader(f):
                    prod_sk = str(row.get('PROD_SK') or '').strip()
                    prod_nm = str(row.get('PROD_NM') or '').strip()
                    if prod_sk and prod_nm:
                        _PRODUCT_NAME_BY_ID[prod_sk] = prod_nm
    return _PRODUCT_NAME_BY_ID


def _render_drug_label(drug_identifier):
    value = str(drug_identifier or '').strip()
    if not value:
        return ''
    product_map = _load_product_name_map()
    return product_map.get(value, value)


def _select_display_candidate(summary, final_candidates):
    """Pick the orchestrator-intended candidate for storage/display.

    For doctor review, use the first review option rather than the highest-scoring
    candidate overall, because rejected candidates can still sort above the review
    candidate. For auto-approve, use the chosen drug. Fall back to the first
    candidate only when the summary does not identify a specific option.
    """
    if not final_candidates:
        return {}

    candidates_by_id = {
        str(candidate.get('drug_id') or '').strip(): candidate
        for candidate in final_candidates
        if str(candidate.get('drug_id') or '').strip()
    }

    preferred_ids = []
    decision = str((summary or {}).get('decision') or '').strip().lower()
    if decision == 'doctor_review':
        preferred_ids.extend(str(item or '').strip() for item in ((summary or {}).get('review_options') or []))

    preferred_ids.extend([
        str((summary or {}).get('chosen_drug') or '').strip(),
        str((summary or {}).get('recommended_drug') or '').strip(),
    ])

    for drug_id in preferred_ids:
        if drug_id and drug_id in candidates_by_id:
            return candidates_by_id[drug_id]

    return final_candidates[0]

def _load_diagnosis_data():
    global _DIAGNOSIS_DATA
    if _DIAGNOSIS_DATA is None:
        csv_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'structure_data.csv')
        _DIAGNOSIS_DATA = []
        with open(csv_path, newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                _DIAGNOSIS_DATA.append({
                    'code': row['code'].strip(),
                    'description': row['description'].strip()
                })
    return _DIAGNOSIS_DATA


def _load_drug_data():
    global _DRUG_DATA
    if _DRUG_DATA is None:
        csv_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'drug_dataset.csv')
        _DRUG_DATA = []
        with open(csv_path, newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                drug_name = (row.get('drug_name') or '').strip()
                if not drug_name:
                    continue
                _DRUG_DATA.append({
                    'rxcui': (row.get('rxcui') or '').strip(),
                    'drug_name': drug_name
                })
    return _DRUG_DATA


def _load_rejection_reason_data():
    global _REJECTION_REASON_DATA
    if _REJECTION_REASON_DATA is None:
        csv_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'medication_rejection_reasons.csv')
        _REJECTION_REASON_DATA = []
        with open(csv_path, newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                code = (row.get('reason_code') or '').strip().upper()
                label = (row.get('reason_chip') or '').strip()
                if not code or not label:
                    continue
                _REJECTION_REASON_DATA.append({
                    'code': code,
                    'label': label,
                })
    return _REJECTION_REASON_DATA


def _get_rejection_reason_map():
    return {item['code']: item['label'] for item in _load_rejection_reason_data()}


def _extract_diagnosis_code(value):
    raw = (value or '').strip()
    if not raw:
        return ''

    # Handles values like "A00.0 - Cholera..." or "A00.0 Cholera..."
    match = re.match(r'^([A-Z][0-9]{2}(?:\.[0-9A-Z]+)?)', raw, re.IGNORECASE)
    if match:
        return match.group(1).upper()

    return raw


def _resolve_diagnosis_fields(value):
    """Returns normalized diagnosis code/description/display values for UI rendering."""
    raw = (value or '').strip()
    code = _extract_diagnosis_code(raw)

    if not code:
        return {
            'code': '',
            'description': '',
            'display': raw,
        }

    description = ''
    for item in _load_diagnosis_data():
        if item['code'].upper() == code.upper():
            description = item['description']
            break

    display = f"{code} - {description}" if description else code
    return {
        'code': code,
        'description': description,
        'display': display,
    }


def _resolve_drug_fields(prod_nm, prod_rxcui):
    drug_name = (prod_nm or '').strip()
    rxcui = (prod_rxcui or '').strip()

    if drug_name and rxcui:
        return drug_name, rxcui

    data = _load_drug_data()
    if drug_name and not rxcui:
        for item in data:
            if item['drug_name'].lower() == drug_name.lower():
                return item['drug_name'], item['rxcui']
        return drug_name, ''

    if rxcui and not drug_name:
        for item in data:
            if item['rxcui'] == rxcui:
                return item['drug_name'], item['rxcui']
        return '', rxcui

    return '', ''

@prescription_bp.route('/diagnosis-search', methods=['GET'])
def diagnosis_search():
    query = request.args.get('q', '').strip().lower()
    if len(query) < 1:
        return jsonify([])
    data = _load_diagnosis_data()
    results = [
        item for item in data
        if query in item['code'].lower() or query in item['description'].lower()
    ]
    return jsonify(results[:20])


@prescription_bp.route('/drug-search', methods=['GET'])
def drug_search():
    query = request.args.get('q', '').strip().lower()
    if len(query) < 1:
        return jsonify([])

    data = _load_drug_data()
    results = [
        item for item in data
        if query in item['drug_name'].lower() or query in item['rxcui'].lower()
    ]
    return jsonify(results[:20])

PHASE_LABELS = {
    "DEDUCTIBLE": "Deductible Stage",
    "INITIAL_COVERAGE": "Standard Coverage",
    "CATASTROPHIC": "OOP Max Reached",
}


def _ensure_cost_comparison_columns(cursor):
    """Adds insurance context columns to existing DBs if they are missing."""
    cursor.execute("PRAGMA table_info(pbm_cost_comparison)")
    existing = {row[1] for row in cursor.fetchall()}

    required = {
        "insurance_phase": "TEXT",
        "ytd_oop": "REAL",
        "deductible_cap": "REAL",
        "oop_max_cap": "REAL",
        "deductible_remaining": "REAL",
        "oop_remaining": "REAL",
        "original_total_cost": "REAL",
        "alternative_total_cost": "REAL",
        "original_plan_paid": "REAL",
        "alternative_plan_paid": "REAL",
        "estimated_annual_savings": "REAL",
        "member_savings_percentage": "REAL",
        "deductible_met": "REAL",
        "oop_met": "REAL",
        "coinsurance_percentage": "REAL",
    }

    for column_name, column_type in required.items():
        if column_name not in existing:
            cursor.execute(f"ALTER TABLE pbm_cost_comparison ADD COLUMN {column_name} {column_type}")


def _ensure_financial_temp_table(cursor):
    """Creates a temporary financial snapshot table keyed by prescription."""
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS financial_temp_snapshot (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            rx_number            TEXT NOT NULL UNIQUE,
            original_tier        TEXT NOT NULL,
            original_price       REAL NOT NULL,
            original_copay       REAL NOT NULL,
            alternative_tier     TEXT NOT NULL,
            alternative_price    REAL NOT NULL,
            alternative_copay    REAL NOT NULL,
            savings              REAL NOT NULL,
            insurance_phase      TEXT,
            ytd_oop              REAL,
            deductible_cap       REAL,
            oop_max_cap          REAL,
            deductible_remaining REAL,
            oop_remaining        REAL,
            created_at           DATETIME NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (rx_number) REFERENCES prescription (rx_number)
        )
    """)


def _ensure_alternative_options_table(cursor):
    """Stores one rendered result payload per evaluated alternative."""
    cursor.execute("""
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
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_pbm_alternative_option_resp ON pbm_alternative_option (pbm_response_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_pbm_alternative_option_rx ON pbm_alternative_option (rx_number)")


def _candidate_review_status(decision, outcome, is_selected):
    outcome_value = str(outcome or '').strip().lower()
    decision_value = str(decision or '').strip().lower()

    if outcome_value == 'auto_approved':
        return 'APPROVED'
    if outcome_value == 'rejected':
        return 'REJECTED'
    if decision_value == 'keep_original':
        return 'KEEP_ORIGINAL' if is_selected else 'REJECTED'
    if decision_value == 'doctor_review' or is_selected:
        return 'ESCALATED'
    return 'PENDING_REVIEW'


def _build_alternative_payload(payload, medication, diagnosis, days_supply, summary, candidate, alternative_index, is_selected, original_tier_fallback=None, original_price_fallback=0.0):
    financial = candidate.get('financial', {}) or {}
    financial_summary = candidate.get('financial_summary', {}) or {}
    policy = candidate.get('policy', {}) or {}
    clinical_detail = candidate.get('clinical_detail', {}) or {}
    insurance_context = _normalize_insurance_context(financial.get('insurance_context'))

    original_drug_id = str(payload.get('drug_id') or '').strip()
    candidate_drug_id = str(candidate.get('drug_id') or '').strip()
    alternative_label = (
        _lookup_formulary_alt_label_by_ids(original_drug_id, candidate_drug_id)
        or _render_drug_label(candidate_drug_id)
        or candidate.get('drug_name')
        or f'Alternative {alternative_index + 1}'
    )

    estimated_savings = _to_float(
        financial_summary.get('estimated_savings'),
        _to_float(financial.get('estimated_savings'), 0.0)
    )
    original_final_cost_raw = financial.get('original_final_cost')
    decision_hint = str(financial_summary.get('decision') or '').strip().lower()
    pricing_note = str(financial.get('notes') or '').strip().lower()
    original_unpriceable = (
        original_final_cost_raw in (None, '', 'None')
        or decision_hint == 'fallback_original_unpriceable'
        or 'could not be priced' in pricing_note
    )

    original_total_cost = None if original_unpriceable else _to_float(original_final_cost_raw, 0.0)
    if original_total_cost is None and _to_float(original_price_fallback, 0.0) > 0:
        # Display a realistic original list price when adjudicated original pricing is unavailable.
        original_total_cost = _to_float(original_price_fallback, 0.0)
    alternative_total_cost = _to_float(financial.get('final_cost'), 0.0)
    original_copay = None
    if not original_unpriceable:
        original_copay = _to_float(
            (financial.get('insurance_context') or {}).get('original_fill_projection', {}).get('patient_pay'),
            financial_summary.get('original_patient_pay')
            or financial.get('original_patient_pay')
            or 0.0,
        )
    alternative_copay = _to_float(
        financial.get('estimated_patient_pay'),
        financial_summary.get('candidate_patient_pay')
        or financial.get('candidate_patient_pay')
        or 0.0,
    )

    if original_total_cost is not None and original_total_cost <= 0 and _to_float(original_price_fallback, 0.0) > 0:
        original_total_cost = _to_float(original_price_fallback, 0.0)
    if not alternative_total_cost:
        base_original = _to_float(original_total_cost, 0.0) if original_total_cost is not None else 0.0
        alternative_total_cost = max(base_original - estimated_savings, 0.0)
    if alternative_total_cost <= 0 and original_total_cost is not None and original_total_cost > 0:
        alternative_total_cost = original_total_cost

    if original_copay is None and original_total_cost is not None and original_total_cost > 0:
        original_copay = round(original_total_cost * 0.20, 2)
    if original_copay is not None and original_copay <= 0 and original_total_cost is not None and original_total_cost > 0:
        original_copay = round(original_total_cost * 0.20, 2)
    if alternative_copay <= 0 and alternative_total_cost > 0:
        alternative_copay = round(alternative_total_cost * 0.20, 2)

    computed_fill_savings = None
    if original_total_cost is not None:
        computed_fill_savings = max(original_total_cost - alternative_total_cost, 0.0)
    if estimated_savings <= 0 and computed_fill_savings is not None and computed_fill_savings > 0:
        estimated_savings = round(computed_fill_savings, 2)

    annual_savings = round(max(estimated_savings, 0.0) * 12, 2)
    savings_pct = (
        round((computed_fill_savings / original_total_cost) * 100, 2)
        if original_total_cost is not None and original_total_cost > 0 and computed_fill_savings is not None
        else None
    )
    original_plan_paid = None
    if original_total_cost is not None and original_copay is not None:
        original_plan_paid = round(max(_to_float(financial.get('original_final_cost'), original_total_cost) - original_copay, 0.0), 2)
    alternative_plan_paid = round(max(alternative_total_cost - alternative_copay, 0.0), 2)
    original_tier = _format_tier(
        _first_meaningful(
            financial.get('original_tier'),
            financial.get('original_drug_tier'),
            financial.get('original_tier_number'),
            original_tier_fallback,
        )
    )
    alternative_tier = _format_tier(
        _first_meaningful(
            financial.get('alternative_tier'),
            financial.get('tier'),
            policy.get('tier'),
            policy.get('formulary_tier'),
        )
    )
    coinsurance_percentage = _resolve_coinsurance_percentage(financial)

    outcome = candidate.get('outcome')
    review_status = _candidate_review_status(summary.get('decision'), outcome, is_selected)
    policy_reason = policy.get('notes') or (policy.get('summary') or {}).get('reason') or 'Review required'
    original_policy_reason = (
        policy.get('original_status')
        or (policy.get('summary') or {}).get('original_status')
        or 'Original prescription under plan review.'
    )
    if str((summary or {}).get('decision') or '').strip().lower() == 'keep_original':
        original_policy_reason = summary.get('reason') or 'Original prescription kept as written.'
    contraindications = clinical_detail.get('contraindications') or ('None detected' if clinical_detail.get('safe', True) else 'Contraindications detected')
    interactions = clinical_detail.get('interactions') or 'Minimal interactions'
    monitoring = clinical_detail.get('monitoring') or 'Standard monitoring'

    return {
        'index': alternative_index,
        'drug_id': candidate_drug_id,
        'label': alternative_label,
        'is_selected': bool(is_selected),
        'review_status': review_status,
        'combined_score': _to_float(candidate.get('combined_score'), summary.get('confidence_score') or 0.0),
        'score_basis': candidate.get('score_basis') or 'all_signals_considered',
        'outcome': outcome or ('selected' if is_selected else 'review'),
        'reason': candidate.get('reason') or summary.get('reason') or 'Review required',
        'prescribed_drug': medication,
        'diagnosis': diagnosis,
        'agent_breakdown': candidate.get('agent_breakdown') or candidate.get('scores') or {},
        'cost': {
            'original_tier': original_tier,
            'original_price': round(original_total_cost, 2) if original_total_cost is not None else None,
            'original_copay': round(original_copay, 2) if original_copay is not None else None,
            'alternative_tier': alternative_tier,
            'alternative_price': round(alternative_total_cost, 2),
            'alternative_copay': round(alternative_copay, 2),
            'savings': round(estimated_savings, 2),
            'insurance_phase': insurance_context.get('phase'),
            'ytd_oop': insurance_context.get('ytd_oop'),
            'deductible_cap': insurance_context.get('deductible_cap'),
            'oop_max_cap': insurance_context.get('oop_max_cap'),
            'deductible_remaining': insurance_context.get('deductible_remaining'),
            'oop_remaining': insurance_context.get('oop_remaining'),
            'original_total_cost': round(original_total_cost, 2) if original_total_cost is not None else None,
            'alternative_total_cost': round(alternative_total_cost, 2),
            'original_plan_paid': original_plan_paid,
            'alternative_plan_paid': alternative_plan_paid,
            'estimated_annual_savings': annual_savings,
            'member_savings_percentage': savings_pct,
            'deductible_met': round(max(insurance_context.get('deductible_cap', 0.0) - insurance_context.get('deductible_remaining', 0.0), 0.0), 2),
            'oop_met': round(insurance_context.get('ytd_oop', 0.0), 2),
            'coinsurance_percentage': coinsurance_percentage,
            'coverage_gap_status': 'Not in Coverage Gap' if insurance_context.get('ytd_oop', 0.0) < 2000 else 'In Coverage Gap',
            'catastrophic_coverage_status': 'Not Reached' if insurance_context.get('ytd_oop', 0.0) < insurance_context.get('oop_max_cap', 3000.0) else 'Reached',
            'days_supply': int(days_supply) if days_supply else 30,
        },
        'safety': {
            'summary': 'None detected' if clinical_detail.get('safe', True) else 'Contraindications detected',
            'contraindications': contraindications,
            'interactions': interactions,
            'monitoring': monitoring,
        },
        'policy': {
            'original_status': original_policy_reason,
            'alternative_status': policy_reason,
            'policy_state': policy.get('policy_state') or 'review',
        },
    }


def _persist_alternative_payloads(cursor, pbm_id, rx_number, alternative_payloads):
    _ensure_alternative_options_table(cursor)
    cursor.execute("DELETE FROM pbm_alternative_option WHERE rx_number = ?", (rx_number,))

    for item in alternative_payloads:
        cursor.execute("""
            INSERT INTO pbm_alternative_option (
                pbm_response_id, rx_number, alternative_index, drug_id,
                alternative_label, is_selected, result_payload
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            pbm_id,
            rx_number,
            int(item.get('index') or 0),
            item.get('drug_id'),
            item.get('label') or f"Alternative {(int(item.get('index') or 0) + 1)}",
            1 if item.get('is_selected') else 0,
            json.dumps(item),
        ))


def _build_legacy_alternative_payload(pbm_payload, cost, safety, policy):
    recommended_alt = str((pbm_payload or {}).get('recommended_alt') or '').strip() or 'No alternative recorded'
    return {
        'index': 0,
        'drug_id': '',
        'label': recommended_alt,
        'is_selected': True,
        'review_status': (pbm_payload or {}).get('status') or 'ESCALATED',
        'combined_score': _to_float((pbm_payload or {}).get('ai_confidence'), 0.0),
        'score_basis': 'legacy_single_result',
        'outcome': 'selected',
        'reason': (pbm_payload or {}).get('orchestrator_summary') or (policy or {}).get('original_status') or 'Legacy PBM result',
        'prescribed_drug': (pbm_payload or {}).get('prescribed_drug') or '',
        'diagnosis': (pbm_payload or {}).get('diagnosis') or '',
        'agent_breakdown': {},
        'cost': dict(cost) if cost else {},
        'safety': {
            'summary': (pbm_payload or {}).get('safety_summary') or 'Reviewed by AI',
            'contraindications': (safety or {}).get('contraindications') if safety else 'None',
            'interactions': (safety or {}).get('interactions') if safety else 'None',
            'monitoring': (safety or {}).get('monitoring') if safety else 'None',
        },
        'policy': {
            'original_status': (policy or {}).get('original_status') if policy else '—',
            'alternative_status': (policy or {}).get('alternative_status') if policy else '—',
            'policy_state': 'legacy',
        },
    }


def _ensure_doctor_decision_tables(cursor):
    """Migrates doctor decision tables to support decision comments and multi-select reject reasons."""
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS doctor_decision (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            rx_number   TEXT NOT NULL,
            status      TEXT NOT NULL CHECK (status IN ('ACCEPTED', 'REJECTED', 'MODIFIED')),
            reason      TEXT,
            created_at  DATETIME NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (rx_number) REFERENCES prescription (rx_number)
        )
    """)

    cursor.execute("PRAGMA table_info(doctor_decision)")
    columns = {row['name'] if hasattr(row, 'keys') else row[1] for row in cursor.fetchall()}

    if 'comment' not in columns:
        cursor.execute("ALTER TABLE doctor_decision RENAME TO doctor_decision_legacy")
        cursor.execute("""
            CREATE TABLE doctor_decision (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                rx_number   TEXT NOT NULL,
                status      TEXT NOT NULL CHECK (status IN ('ACCEPTED', 'REJECTED', 'MODIFIED')),
                reason      TEXT,
                comment     TEXT,
                created_at  DATETIME NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (rx_number) REFERENCES prescription (rx_number)
            )
        """)
        cursor.execute("""
            INSERT INTO doctor_decision (id, rx_number, status, reason, comment, created_at)
            SELECT id, rx_number, status, reason, NULL, created_at
            FROM doctor_decision_legacy
        """)
        cursor.execute("DROP TABLE doctor_decision_legacy")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS doctor_decision_reason (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            rx_number   TEXT NOT NULL,
            reason_code TEXT NOT NULL,
            reason_text TEXT NOT NULL,
            comment     TEXT,
            created_at  DATETIME NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (rx_number) REFERENCES prescription (rx_number)
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_doctor_decision_reason_rx ON doctor_decision_reason (rx_number)")


def _upsert_financial_snapshot(cursor, rx_number, cost_payload):
    """Stores the latest temporary financial output for a prescription."""
    _ensure_financial_temp_table(cursor)
    cursor.execute("""
        INSERT INTO financial_temp_snapshot (
            rx_number, original_tier, original_price, original_copay,
            alternative_tier, alternative_price, alternative_copay, savings,
            insurance_phase, ytd_oop, deductible_cap, oop_max_cap,
            deductible_remaining, oop_remaining
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(rx_number) DO UPDATE SET
            original_tier = excluded.original_tier,
            original_price = excluded.original_price,
            original_copay = excluded.original_copay,
            alternative_tier = excluded.alternative_tier,
            alternative_price = excluded.alternative_price,
            alternative_copay = excluded.alternative_copay,
            savings = excluded.savings,
            insurance_phase = excluded.insurance_phase,
            ytd_oop = excluded.ytd_oop,
            deductible_cap = excluded.deductible_cap,
            oop_max_cap = excluded.oop_max_cap,
            deductible_remaining = excluded.deductible_remaining,
            oop_remaining = excluded.oop_remaining,
            created_at = datetime('now')
    """, (
        rx_number,
        cost_payload.get("original_tier", "Tier 3"),
        _to_float(cost_payload.get("original_price"), 0.0),
        _to_float(cost_payload.get("original_copay"), 0.0),
        cost_payload.get("alternative_tier", "Tier 1"),
        _to_float(cost_payload.get("alternative_price"), 0.0),
        _to_float(cost_payload.get("alternative_copay"), 0.0),
        _to_float(cost_payload.get("savings"), 0.0),
        cost_payload.get("insurance_phase", "Standard Coverage"),
        _to_float(cost_payload.get("ytd_oop"), 0.0),
        _to_float(cost_payload.get("deductible_cap"), 750.0),
        _to_float(cost_payload.get("oop_max_cap"), 3000.0),
        _to_float(cost_payload.get("deductible_remaining"), 750.0),
        _to_float(cost_payload.get("oop_remaining"), 3000.0),
    ))


def _ensure_prescription_columns(cursor):
    """Adds newer prescription columns to older DBs if missing."""
    cursor.execute("PRAGMA table_info(prescription)")
    existing = {row[1] for row in cursor.fetchall()}
    if "member_id" not in existing:
        cursor.execute("ALTER TABLE prescription ADD COLUMN member_id TEXT")
    if "prescriber_npi" not in existing:
        cursor.execute("ALTER TABLE prescription ADD COLUMN prescriber_npi TEXT")
    if "medication" not in existing:
        cursor.execute("ALTER TABLE prescription ADD COLUMN medication TEXT")
    if "medication_rxcui" not in existing:
        cursor.execute("ALTER TABLE prescription ADD COLUMN medication_rxcui TEXT")
    if "strength" not in existing:
        cursor.execute("ALTER TABLE prescription ADD COLUMN strength TEXT")
    if "diagnosis_icd10" not in existing:
        cursor.execute("ALTER TABLE prescription ADD COLUMN diagnosis_icd10 TEXT")
    if "pharmacy_id" not in existing:
        cursor.execute("ALTER TABLE prescription ADD COLUMN pharmacy_id TEXT DEFAULT 'PHARM0001'")


def _get_table_columns(cursor, table_name):
    cursor.execute(f"PRAGMA table_info({table_name})")
    return {row[1] for row in cursor.fetchall()}


def _to_float(value, default):
    try:
        if value is None or value == "":
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _phase_label(phase):
    if not phase:
        return "Standard Coverage"
    return PHASE_LABELS.get(str(phase), str(phase).replace("_", " ").title())


def _normalize_insurance_context(raw_context):
    context = raw_context or {}
    ytd_oop = _to_float(context.get("ytd_oop"), 0.0)
    deductible_cap = _to_float(context.get("deductible_cap"), 750.0)
    oop_max_cap = _to_float(context.get("oop_max_cap"), 3000.0)
    deductible_remaining = _to_float(
        context.get("deductible_remaining"),
        max(deductible_cap - ytd_oop, 0.0),
    )
    oop_remaining = _to_float(
        context.get("oop_remaining"),
        max(oop_max_cap - ytd_oop, 0.0),
    )

    return {
        "phase": _phase_label(context.get("phase")),
        "ytd_oop": round(ytd_oop, 2),
        "deductible_cap": round(deductible_cap, 2),
        "oop_max_cap": round(oop_max_cap, 2),
        "deductible_remaining": round(deductible_remaining, 2),
        "oop_remaining": round(oop_remaining, 2),
    }


def _format_tier(value, default="Unknown"):
    raw = str(value or "").strip()
    if not raw:
        return default

    if raw.lower() in {"none", "null", "na", "n/a", "unknown"}:
        return default

    if raw.lower().startswith("tier"):
        return raw

    try:
        numeric = int(float(raw))
        return f"Tier {numeric}"
    except (TypeError, ValueError):
        return raw


def _resolve_coinsurance_percentage(financial):
    if not isinstance(financial, dict):
        return 0.0

    direct = financial.get("coinsurance_percentage")
    if direct not in (None, ""):
        return round(_to_float(direct, 0.0), 2)

    context = financial.get("insurance_context") or {}
    effective = (context.get("candidate_fill_projection") or {}).get("effective_coinsurance")
    if effective in (None, ""):
        return 0.0

    value = _to_float(effective, 0.0)
    if value <= 1:
        value *= 100
    return round(value, 2)


def _first_meaningful(*values):
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if not text:
            continue
        if text.lower() in {"none", "null", "na", "n/a", "unknown"}:
            continue
        return value
    return None


def _load_phase_results(path):
    phase_path = str(path or "").strip()
    if not phase_path or not os.path.exists(phase_path):
        return []

    try:
        with open(phase_path, encoding="utf-8") as fh:
            payload = json.load(fh) or {}
        return payload.get("phase_results") or []
    except Exception:
        return []


def _extract_selected_summary_cards(latest_output):
    """Extract summary cards for selected/first review alternative from latest orchestrator payload."""
    payload = latest_output or {}

    def _candidate_from_entries(entries):
        for entry in (entries or []):
            if not isinstance(entry, dict):
                continue
            summary = entry.get('summary') or {}
            cards = summary.get('summary_cards') or {}
            if isinstance(cards, dict) and cards:
                return entry, summary, cards
        return None, None, None

    selected = payload.get('selected_alternative') or {}
    summary = selected.get('summary') or {}
    cards = summary.get('summary_cards') or {}

    if not isinstance(cards, dict) or not cards:
        selected = ((payload.get('provider_packet') or {}).get('selected_alternative')
                    or (payload.get('pbm_packet') or {}).get('selected_alternative')
                    or (payload.get('pharmacist_packet') or {}).get('selected_alternative')
                    or {})
        summary = selected.get('summary') or {}
        cards = summary.get('summary_cards') or {}

    if not isinstance(cards, dict) or not cards:
        provider_entry, provider_summary, provider_cards = _candidate_from_entries((payload.get('provider_review_list') or []))
        if provider_cards:
            selected, summary, cards = provider_entry, provider_summary, provider_cards

    if not isinstance(cards, dict) or not cards:
        packet_lists = [
            ((payload.get('provider_packet') or {}).get('alternatives') or []),
            ((payload.get('pbm_packet') or {}).get('review_alternatives') or []),
            ((payload.get('pharmacist_packet') or {}).get('review_alternatives') or []),
        ]
        for entries in packet_lists:
            entry, entry_summary, entry_cards = _candidate_from_entries(entries)
            if entry_cards:
                selected, summary, cards = entry, entry_summary, entry_cards
                break

    if not isinstance(cards, dict) or not cards:
        return None, None

    meta = {
        'final_outcome': payload.get('final_outcome'),
        'final_status': selected.get('final_status'),
        'final_band': selected.get('final_band'),
        'adjusted_score': selected.get('adjusted_score'),
        'summary_generation_fail_safe': summary.get('summary_generation_fail_safe'),
    }
    return cards, meta


def _extract_summary_cards_by_alternative(latest_output):
    """Build a mapping of alternative_id -> {cards, meta} from latest orchestrator payload."""
    payload = latest_output or {}
    by_alt = {}

    def _store(entry):
        if not isinstance(entry, dict):
            return
        alt_id = str(entry.get('alternative_id') or '').strip()
        if not alt_id:
            return
        summary = entry.get('summary') or {}
        cards = summary.get('summary_cards') or {}
        if not isinstance(cards, dict) or not cards:
            return
        by_alt[alt_id] = {
            'cards': cards,
            'meta': {
                'final_outcome': payload.get('final_outcome'),
                'final_status': entry.get('final_status'),
                'final_band': entry.get('final_band') or summary.get('final_band'),
                'adjusted_score': entry.get('adjusted_score'),
                'summary_generation_fail_safe': summary.get('summary_generation_fail_safe'),
            }
        }

    _store(payload.get('selected_alternative') or {})
    _store((payload.get('provider_packet') or {}).get('selected_alternative') or {})
    _store((payload.get('pbm_packet') or {}).get('selected_alternative') or {})
    _store((payload.get('pharmacist_packet') or {}).get('selected_alternative') or {})

    list_sources = [
        payload.get('provider_review_list') or [],
        (payload.get('provider_packet') or {}).get('alternatives') or [],
        (payload.get('pbm_packet') or {}).get('review_alternatives') or [],
        (payload.get('pharmacist_packet') or {}).get('review_alternatives') or [],
    ]
    for entries in list_sources:
        for entry in entries:
            _store(entry)

    return by_alt


def _extract_clinical_confidence_from_lines(lines):
    for line in (lines or []):
        text = str(line or '').strip()
        if not text:
            continue
        match = re.search(r'clinical\s+composite\s+score\s*:\s*([0-9]*\.?[0-9]+)', text, flags=re.IGNORECASE)
        if not match:
            continue
        value = _to_float(match.group(1), 0.0)
        if value <= 1:
            value *= 100
        return max(0.0, min(100.0, value))
    return None


def _derive_agent_confidence_from_summary_cards(cards):
    cards = cards or {}

    clinical_card = cards.get('clinical_agent') or {}
    policy_card = cards.get('policy_agent') or {}
    financial_card = cards.get('financial_agent') or {}
    past_card = cards.get('past_decision_agent') or {}

    # Clinical: parse composite score from summary text, fallback to status-based rule
    clinical_conf = _extract_clinical_confidence_from_lines(clinical_card.get('clinical_summary') or [])
    if clinical_conf is None:
        clinical_status = str(clinical_card.get('status') or '').upper()
        clinical_conf = 82.0 if 'ACCEPTABLE' in clinical_status or 'PASS' in clinical_status else 45.0

    # Policy: read score directly from policy_agent card (written from trace by orchestrator)
    raw_policy_score = _to_float(policy_card.get('score'), None)
    if raw_policy_score is not None:
        policy_conf = min(100.0, round(raw_policy_score * 100.0, 1))
    elif policy_card.get('policy_checks_passed') is True:
        policy_conf = 95.0
    elif str(policy_card.get('coverage_status') or '').strip().lower() == 'covered':
        policy_conf = 80.0
    elif str(policy_card.get('alternative_status') or '').strip().lower() == 'pass':
        policy_conf = 85.0
    else:
        policy_conf = 45.0

    # Financial / Cost Analysis: read score directly from financial_agent card
    raw_financial_score = _to_float(financial_card.get('score'), None)
    if raw_financial_score is not None:
        financial_conf = min(100.0, round(raw_financial_score * 100.0, 1))
    else:
        financial_status = str(financial_card.get('status') or '').strip().upper()
        if 'SAVING' in financial_status or 'FAVORABLE' in financial_status:
            financial_conf = 90.0
        elif 'NEUTRAL' in financial_status:
            financial_conf = 75.0
        elif financial_status:
            financial_conf = 55.0
        else:
            financial_conf = 50.0

    # Past Decision: read score directly from past_decision_agent card
    raw_past_score = _to_float(past_card.get('score'), None)
    if raw_past_score is not None:
        past_conf = min(100.0, round(raw_past_score * 100.0, 1))
    else:
        hist_conf = str(past_card.get('historical_confidence') or '').strip().lower()
        if hist_conf == 'high':
            past_conf = 90.0
        elif hist_conf == 'medium':
            past_conf = 70.0
        elif hist_conf == 'low':
            past_conf = 45.0
        elif past_card.get('recommendation_supported') is True:
            past_conf = 85.0
        else:
            past_conf = 50.0

    # Coverage Details: use financial agent score (reflects insurance/cost outcomes)
    coverage_conf = financial_conf

    return {
        'clinical': round(clinical_conf, 1),
        'policy': round(policy_conf, 1),
        'financial': round(financial_conf, 1),
        'past': round(past_conf, 1),
        'coverage': round(coverage_conf, 1),
    }


def _apply_summary_cards_to_alternative_payload(payload, cards, meta):
    """Overlay orchestrator summary card values into the selected alternative payload."""
    if not isinstance(payload, dict) or not isinstance(cards, dict):
        return

    financial = cards.get('financial_agent') or {}
    insurance = cards.get('insurance_context') or {}
    clinical = cards.get('clinical_agent') or {}
    policy = cards.get('policy_agent') or {}
    past = cards.get('past_decision_agent') or {}

    payload['orchestrator_summary_cards'] = cards
    payload['orchestrator_meta'] = meta or {}
    payload['agent_confidence'] = _derive_agent_confidence_from_summary_cards(cards)

    cost = dict(payload.get('cost') or {})
    policy_payload = dict(payload.get('policy') or {})
    safety_payload = dict(payload.get('safety') or {})

    cost['original_tier'] = _first_meaningful(financial.get('original_tier'), cost.get('original_tier'))
    cost['alternative_tier'] = _first_meaningful(financial.get('alternative_tier'), cost.get('alternative_tier'))
    cost['original_total_cost'] = _first_meaningful(financial.get('original_total_price'), cost.get('original_total_cost'))
    cost['alternative_total_cost'] = _first_meaningful(financial.get('alternative_total_price'), cost.get('alternative_total_cost'))
    cost['original_copay'] = _first_meaningful(financial.get('original_copay'), cost.get('original_copay'))
    cost['alternative_copay'] = _first_meaningful(financial.get('alternative_copay'), cost.get('alternative_copay'))
    cost['original_plan_paid'] = _first_meaningful(financial.get('original_plan_paid'), cost.get('original_plan_paid'))
    cost['alternative_plan_paid'] = _first_meaningful(financial.get('alternative_plan_paid'), cost.get('alternative_plan_paid'))
    cost['estimated_annual_savings'] = _first_meaningful(financial.get('annual_savings'), cost.get('estimated_annual_savings'))
    cost['member_savings_percentage'] = _first_meaningful(financial.get('savings_percent'), cost.get('member_savings_percentage'))

    cost['insurance_phase'] = _first_meaningful(insurance.get('insurance_phase'), cost.get('insurance_phase'))
    cost['ytd_oop'] = _first_meaningful(insurance.get('ytd_oop'), cost.get('ytd_oop'))
    cost['coinsurance_percentage'] = _first_meaningful(insurance.get('coinsurance'), cost.get('coinsurance_percentage'))
    cost['deductible_cap'] = _first_meaningful(insurance.get('deductible_limit'), cost.get('deductible_cap'))
    cost['deductible_remaining'] = _first_meaningful(insurance.get('deductible_remaining'), cost.get('deductible_remaining'))
    cost['oop_max_cap'] = _first_meaningful(insurance.get('oop_max'), cost.get('oop_max_cap'))
    cost['oop_remaining'] = _first_meaningful(insurance.get('oop_remaining'), cost.get('oop_remaining'))

    policy_payload['original_status'] = _first_meaningful(policy.get('original_status'), policy_payload.get('original_status'))
    policy_payload['alternative_status'] = _first_meaningful(policy.get('alternative_status'), policy_payload.get('alternative_status'))
    policy_payload['policy_state'] = _first_meaningful(policy.get('status'), policy_payload.get('policy_state'))
    policy_payload['policy_notes'] = _first_meaningful(policy.get('policy_notes'), policy_payload.get('policy_notes'))
    policy_payload['formulary_preference'] = _first_meaningful(policy.get('formulary_preference'), policy_payload.get('formulary_preference'))
    policy_payload['coverage_status'] = _first_meaningful(policy.get('coverage_status'), policy_payload.get('coverage_status'))
    policy_payload['key_findings'] = policy.get('key_findings') or policy_payload.get('key_findings') or []

    clinical_summary_lines = clinical.get('clinical_summary') or []
    safety_summary_lines = clinical.get('safety_summary') or []
    safety_payload['summary'] = _first_meaningful(clinical.get('status'), safety_payload.get('summary'))

    payload['cost'] = cost
    payload['policy'] = policy_payload
    payload['safety'] = safety_payload
    payload['clinical_summary_lines'] = clinical_summary_lines
    payload['safety_summary_lines'] = safety_summary_lines
    payload['past_decision_summary'] = _first_meaningful(past.get('summary'), payload.get('past_decision_summary'))
    payload['reason'] = _first_meaningful(past.get('summary'), policy.get('policy_notes'), financial.get('summary'), payload.get('reason'))

    if payload.get('agent_breakdown') in (None, {}):
        conf = payload.get('agent_confidence') or {}
        payload['agent_breakdown'] = {
            'clinical': _to_float(conf.get('clinical'), 0.0) / 100.0,
            'policy': _to_float(conf.get('policy'), 0.0) / 100.0,
            'financial': _to_float(conf.get('financial'), 0.0) / 100.0,
            'past': _to_float(conf.get('past'), 0.0) / 100.0,
        }


def _coerce_orchestrator_shape(orch_result):
    """Translate newer orchestrator output into legacy summary/final_candidates fields."""
    summary = dict((orch_result or {}).get("summary") or {})
    final_candidates = list((orch_result or {}).get("final_candidates") or [])

    if final_candidates:
        return summary, final_candidates

    evaluated = list((orch_result or {}).get("evaluated_alternatives") or [])
    if not evaluated:
        return summary, final_candidates

    phase_results = _load_phase_results((orch_result or {}).get("phase_results_path"))
    downstream = next(
        (item for item in phase_results if str(item.get("name") or "") == "phase_03_downstream_agents"),
        None,
    )
    evaluations = ((downstream or {}).get("data") or {}).get("alternative_evaluations") or []
    eval_by_id = {
        str(item.get("alternative_id") or "").strip(): item
        for item in evaluations
        if str(item.get("alternative_id") or "").strip()
    }

    translated = []
    for idx, alt in enumerate(evaluated):
        alt_id = str(alt.get("alternative_id") or "").strip()
        eval_item = eval_by_id.get(alt_id) or {}
        policy_response = ((eval_item.get("policy_agent") or {}).get("response") or {})
        financial_response = ((eval_item.get("financial_agent") or {}).get("response") or {})
        past_response = ((eval_item.get("past_decision_agent") or {}).get("response") or {})
        clinical_result = eval_item.get("clinical_agent_result") or {}

        score = _to_float(alt.get("adjusted_score"), 0.0)
        final_status = str(alt.get("final_status") or "").strip().upper()
        if final_status in {"AUTO_APPROVE", "APPROVED"}:
            outcome = "auto_approved"
        elif final_status in {"DISPENSE_AS_WRITTEN", "DENIED", "REJECTED"}:
            outcome = "rejected"
        else:
            outcome = "review"

        translated.append({
            "drug_id": alt_id,
            "drug_name": alt.get("alternative_name"),
            "combined_score": score,
            "outcome": outcome,
            "reason": (
                financial_response.get("notes")
                or policy_response.get("notes")
                or past_response.get("final_statement")
                or final_status.replace("_", " ").title()
            ),
            "agent_breakdown": {
                "policy": _to_float(policy_response.get("score"), 0.0),
                "financial": _to_float(financial_response.get("score"), 0.0),
                "past": _to_float(past_response.get("final_score"), 0.0),
                "clinical": _to_float(((clinical_result.get("stage_c") or {}).get("composite_score")), 0.0),
            },
            "policy": policy_response,
            "financial": financial_response,
            "financial_summary": financial_response.get("summary") or {},
            "clinical_detail": {
                "safe": str(clinical_result.get("overall_status") or "PASS").upper() == "PASS",
                "contraindications": "None detected",
                "interactions": "Minimal interactions",
                "monitoring": "Standard monitoring",
            },
            "score_basis": "layered_orchestrator_adjusted_score",
            "rank": alt.get("rank") if alt.get("rank") is not None else (idx + 1),
            "final_status": final_status,
        })

    translated.sort(key=lambda item: _to_float(item.get("combined_score"), 0.0), reverse=True)

    final_outcome = str((orch_result or {}).get("final_outcome") or "").strip().upper()
    if final_outcome in {"AUTO_APPROVE", "AUTO_ACCEPT_SELECTED"}:
        summary.setdefault("decision", "auto_approve")
    elif final_outcome in {"PROVIDER_REVIEW", "PENDING_REVIEW", "PROVIDER_REVIEW_SELECTION_PENDING", "PROVIDER_SELECTED"}:
        summary.setdefault("decision", "doctor_review")
    else:
        summary.setdefault("decision", "keep_original")

    summary.setdefault("confidence_score", _to_float((translated[0] or {}).get("combined_score"), 0.0))
    summary.setdefault("reason", final_outcome.replace("_", " ").title() if final_outcome else "No reason provided")
    summary.setdefault("chosen_drug", str(((orch_result or {}).get("selected_alternative") or {}).get("alternative_id") or ""))
    if summary.get("decision") == "doctor_review":
        summary.setdefault("review_options", [str(item.get("drug_id") or "") for item in translated[:3]])

    return summary, translated


def _resolve_intake_url(orchestrate_url):
    marker = "/api/orchestrate"
    if marker in orchestrate_url:
        return orchestrate_url.replace(marker, "/resolve-intake")
    return orchestrate_url.rstrip("/") + "/resolve-intake"


def _resolve_backend_base_url(orchestrate_url):
    api_marker = "/api/"
    if api_marker in orchestrate_url:
        return orchestrate_url.split(api_marker)[0].rstrip("/")
    return orchestrate_url.rstrip("/")


def _build_intake_validation_details(missing_keys, notes):
    details = []
    key_messages = {
        "member_id": "member_id not found",
        "plan_id": "plan_id could not be resolved",
        "drug_id": "medication could not be resolved",
    }
    for key in (missing_keys or []):
        details.append(key_messages.get(key, f"{key} could not be resolved"))

    for note in (notes or []):
        note_text = str(note or "").strip()
        if not note_text:
            continue
        lowered = note_text.lower()
        if "member" in lowered or "patient account" in lowered:
            normalized = "member_id not found"
        elif "plan" in lowered:
            normalized = "plan_id could not be resolved"
        elif "pharmacy" in lowered:
            normalized = "pharmacy_id not found"
        elif "drug" in lowered or "product" in lowered or "rxcui" in lowered:
            normalized = "medication could not be resolved"
        else:
            normalized = note_text

        if normalized not in details:
            details.append(normalized)

    return details


def _row_value(row, *keys):
    if not row:
        return None
    try:
        available = set(row.keys())
    except Exception:
        available = set()

    for key in keys:
        if key in available:
            value = row[key]
            if value not in (None, ""):
                return value
    return None


def _sync_backend_doctor_feedback(status, prescription_row, selected_payload, reason_summary=None, comment=None):
    """Best-effort sync of provider decisions to backend feedback endpoints."""
    pbm_api_url = os.environ.get("PBM_ORCHESTRATOR_URL", "http://127.0.0.1:8000/api/orchestrate")
    backend_base = _resolve_backend_base_url(pbm_api_url)
    resolve_url = _resolve_intake_url(pbm_api_url)
    timeout_seconds = float(os.environ.get("PBM_FEEDBACK_TIMEOUT_SECONDS", "20"))

    member_id = str(_row_value(prescription_row, 'member_id', 'patient_account_id') or '').strip()
    prescriber_npi = str(_row_value(prescription_row, 'prescriber_npi', 'npi_number') or '').strip()
    medication = str(_row_value(prescription_row, 'medication', 'prod_nm') or '').strip()
    diagnosis = str(_row_value(prescription_row, 'diagnosis_icd10', 'diagnosis') or '').strip()
    pharmacy_id = str(_row_value(prescription_row, 'pharmacy_id', 'phr_id') or '').strip()
    days_supply_raw = _row_value(prescription_row, 'days_supply')

    try:
        days_supply = int(days_supply_raw) if days_supply_raw not in (None, '') else 30
    except (TypeError, ValueError):
        days_supply = 30

    intake_payload = {
        "member_id": member_id,
        "provider_npi_number": prescriber_npi,
        "drug_name": medication,
        "diagnosis": diagnosis,
        "days_supply": days_supply,
        "pharmacy_id": pharmacy_id,
        "fill_date": datetime.now().strftime("%Y-%m-%d"),
    }

    normalized_payload = {}
    try:
        resolve_resp = requests.post(resolve_url, json=intake_payload, timeout=timeout_seconds)
        resolve_resp.raise_for_status()
        normalized_payload = (resolve_resp.json() or {}).get("normalized_payload") or {}
    except Exception as e:
        print(f"Backend feedback resolve-intake failed: {e}")

    selected = selected_payload or {}
    original_drug_id = str(normalized_payload.get("drug_id") or '').strip()
    plan_id = str(normalized_payload.get("plan_id") or '').strip()
    recommended_drug_id = str(selected.get('drug_id') or '').strip()

    if not recommended_drug_id:
        recommended_drug_id = original_drug_id or "UNKNOWN_DRUG"

    decision_payload = {
        "member_id": member_id or "UNKNOWN_MEMBER",
        "plan_id": plan_id or "UNKNOWN_PLAN",
        "original_drug_id": original_drug_id or "UNKNOWN_DRUG",
        "recommended_drug_id": recommended_drug_id,
        "diagnosis": diagnosis or None,
        "doctor_id": str((request.user or {}).get('id') or (request.user or {}).get('username') or "FRONTEND_PROVIDER"),
        "npi_number": prescriber_npi or None,
        "confidence_score": _to_float(selected.get('combined_score'), 0.0),
        "policy_score": _to_float(((selected.get('agent_breakdown') or {}).get('policy')), 0.0),
        "clinical_score": _to_float(((selected.get('agent_breakdown') or {}).get('clinical')), 0.0),
        "financial_score": _to_float(((selected.get('agent_breakdown') or {}).get('financial')), 0.0),
        "past_score": _to_float(((selected.get('agent_breakdown') or {}).get('past')), 0.0),
    }

    endpoint = "/api/claim/accept"
    if status == 'REJECTED':
        endpoint = "/api/claim/reject"
        decision_payload["rejection_reason"] = reason_summary or comment or "Rejected by provider"

    try:
        sync_resp = requests.post(
            f"{backend_base}{endpoint}",
            json=decision_payload,
            timeout=timeout_seconds,
        )
        sync_resp.raise_for_status()
        return {"synced": True, "endpoint": endpoint}
    except Exception as e:
        print(f"Backend feedback sync failed: {e}")
        return {"synced": False, "endpoint": endpoint, "error": str(e)}


def _can_access_prescription_record(user, prescription_row):
    if not prescription_row:
        return False

    role = (user or {}).get('role')
    record = dict(prescription_row)

    if role == 'pharmacist':
        user_pharmacist_id = str((user or {}).get('pharmacist_id') or '').strip().upper()
        record_pharmacy_id = str(record.get('pharmacy_id') or record.get('phr_id') or '').strip().upper()
        return (not user_pharmacist_id) or (record_pharmacy_id == user_pharmacist_id)

    if role == 'provider':
        return True

    return True

# 1. Submit Prescription
@prescription_bp.route('/prescription', methods=['POST'])
@token_required
@role_required(['pharmacist'])
def submit_prescription():
    data = request.json or {}
    
    # Extract fields
    member_id = (data.get('patient_account_id') or data.get('member_id') or '').strip()
    prescriber_npi = (data.get('npi_number') or data.get('prescriber_npi') or '').strip()
    pharmacy_id = (data.get('phr_id') or data.get('pharmacy_id') or 'PHARM0001').strip().upper()
    user_pharmacist_id = str((request.user or {}).get('pharmacist_id') or '').strip().upper()
    if user_pharmacist_id:
        pharmacy_id = user_pharmacist_id
    medication, medication_rxcui = _resolve_drug_fields(data.get('prod_nm') or data.get('medication'), data.get('prod_rxcui') or data.get('medication_rxcui'))
    strength = data.get('dosage_size') or data.get('strength')
    frequency = data.get('frequency')
    days_supply = data.get('days_supply')
    diagnosis_icd10 = _extract_diagnosis_code(data.get('diagnosis') or data.get('diagnosis_icd10'))
    
    # Auto-generate current date for date_written
    date_written = datetime.now().strftime('%Y-%m-%d')

    # Basic validation. RXCUI is optional because some UI paths only capture free-text medication.
    if not all([member_id, prescriber_npi, pharmacy_id, medication, strength, frequency, days_supply, diagnosis_icd10]):
        return jsonify({'error': 'Missing required fields.'}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        _ensure_prescription_columns(cursor)
        _ensure_financial_temp_table(cursor)
        prescription_columns = _get_table_columns(cursor, 'prescription')
        patient_columns = _get_table_columns(cursor, 'patient')
        provider_columns = _get_table_columns(cursor, 'provider')

        using_legacy_prescription_schema = {
            'patient_account_id', 'npi_number', 'prod_nm', 'prod_rxcui',
            'dosage_size', 'diagnosis', 'phr_id'
        }.issubset(prescription_columns)

        # Generate unique RX Number
        cursor.execute("SELECT COUNT(*) FROM prescription")
        count = cursor.fetchone()[0] + 1
        date_str = datetime.now().strftime('%Y%m%d')
        rx_number = f"RX-{date_str}-{count:05d}"

        # Ensure patient exists
        patient_id_column = 'member_id' if 'member_id' in patient_columns else 'patient_account_id'
        cursor.execute(f"INSERT OR IGNORE INTO patient ({patient_id_column}) VALUES (?)", (member_id,))
        
        # Ensure provider exists
        provider_npi_column = 'prescriber_npi' if 'prescriber_npi' in provider_columns else 'npi_number'
        cursor.execute(f"INSERT OR IGNORE INTO provider ({provider_npi_column}) VALUES (?)", (prescriber_npi,))

        # Insert Prescription
        if using_legacy_prescription_schema:
            cursor.execute("""
                INSERT INTO prescription (rx_number, patient_account_id, npi_number, prod_nm, prod_rxcui, dosage_size, frequency, days_supply, diagnosis, rx_status, date_written, phr_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'Submitted', ?, ?)
            """, (rx_number, member_id, prescriber_npi, medication, medication_rxcui, strength, frequency, days_supply, diagnosis_icd10, date_written, pharmacy_id))
        else:
            cursor.execute("""
                INSERT INTO prescription (rx_number, member_id, prescriber_npi, medication, medication_rxcui, strength, frequency, days_supply, diagnosis_icd10, rx_status, date_written, pharmacy_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'Submitted', ?, ?)
            """, (rx_number, member_id, prescriber_npi, medication, medication_rxcui, strength, frequency, days_supply, diagnosis_icd10, date_written, pharmacy_id))

        # No separate RX tracking table — rely on prescription.rx_status and pbm_response/doctor_decision

        # Call the PBM orchestrator API to process the claim
        trace_id = data.get('trace_id') or None
        call_orchestrator_api(
            member_id=member_id,
            prescriber_npi=prescriber_npi,
            pharmacy_id=pharmacy_id,
            medication=medication,
            medication_rxcui=medication_rxcui,
            strength=strength,
            frequency=frequency,
            diagnosis_icd10=diagnosis_icd10,
            days_supply=days_supply,
            rx_number=rx_number,
            cursor=cursor,
            trace_id=trace_id,
        )

        conn.commit()
        return jsonify({'rx_number': rx_number, 'message': 'Prescription submitted successfully'})

    except IntakeValidationError as e:
        conn.rollback()
        return jsonify({
            'error': 'Validation failed',
            'details': e.details or ['Invalid prescription request'],
        }), 400
    except Exception as e:
        conn.rollback()
        current_app.logger.exception("Prescription submit failed")
        return jsonify({'error': 'Internal server error'}), 500
    finally:
        conn.close()




def call_orchestrator_api(
    member_id,
    prescriber_npi,
    pharmacy_id,
    medication,
    medication_rxcui,
    strength,
    frequency,
    diagnosis_icd10,
    days_supply,
    rx_number,
    cursor,
    trace_id=None,
):
    """
    Call the PBM orchestrator API to process the prescription claim.
    Falls back to random decision if API is unavailable.
    
    Args:
    member_id: Member identifier
    prescriber_npi: Prescriber NPI
    pharmacy_id: Pharmacy identifier
    medication: Medication name
    medication_rxcui: Medication RXCUI value
    strength: Dose form/size
    frequency: Frequency string
    diagnosis_icd10: Diagnosis code/description
        days_supply: Days supply for quantity calculation
        rx_number: Prescription number
        cursor: Database cursor for updating tables
    """
    pbm_api_url = os.environ.get("PBM_ORCHESTRATOR_URL", "http://127.0.0.1:8000/api/orchestrate")
    resolve_timeout_seconds = float(os.environ.get("PBM_RESOLVE_TIMEOUT_SECONDS", "30"))
    orchestrator_timeout_seconds = float(os.environ.get("PBM_ORCHESTRATOR_TIMEOUT_SECONDS", "90"))
    
    try:
        fill_date = datetime.now().strftime("%Y-%m-%d")
        canonical_member_id = member_id
        if str(member_id or "").strip().upper().startswith("PAT"):
            # Let resolver map patient account -> canonical member id (MBR_SK).
            canonical_member_id = ""

        intake_payload = {
        "patient_account_id": member_id,
        "member_id": canonical_member_id,
        "provider_npi_number": prescriber_npi,
        "drug_name": medication,
        "drug_rxcui": medication_rxcui,
        "dosage": strength,
            "frequency": frequency,
            "days_supply": days_supply,
        "diagnosis": diagnosis_icd10,
            "fill_date": fill_date,
        "pharmacy_id": pharmacy_id,
        }
        if trace_id:
            intake_payload["trace_id"] = trace_id

        resolve_resp = requests.post(
            _resolve_intake_url(pbm_api_url),
            json=intake_payload,
            timeout=resolve_timeout_seconds,
        )
        if resolve_resp.status_code >= 400 and resolve_resp.status_code < 500:
            details = [f"resolve-intake rejected request ({resolve_resp.status_code})"]
            try:
                err_payload = resolve_resp.json() or {}
                detail_value = err_payload.get("detail")
                if isinstance(detail_value, list):
                    details = [str(item) for item in detail_value if str(item).strip()]
                elif detail_value:
                    details = [str(detail_value)]
            except Exception:
                pass
            raise IntakeValidationError(details)

        resolve_resp.raise_for_status()
        resolved = resolve_resp.json()
        normalized = resolved.get("normalized_payload") or {}
        resolved_formulary_tier = ((resolved.get("formulary") or {}).get("FORMULARY_TIER"))
        resolved_pricing_final_cost = _to_float((resolved.get("pricing") or {}).get("FINAL_COST"), 0.0)

        payload = {
            "drug_id": normalized.get("drug_id"),
            "member_id": normalized.get("member_id"),
            "plan_id": normalized.get("plan_id"),
            "pharmacy_id": normalized.get("pharmacy_id") or pharmacy_id,
            "quantity": normalized.get("quantity") or (int(days_supply) if days_supply else 30),
            "fill_date": normalized.get("fill_date") or fill_date,
            "diagnosis": normalized.get("diagnosis") or diagnosis_icd10,
            "provider_npi_number": normalized.get("provider_npi_number") or prescriber_npi,
            "frequency": frequency,
            "days_supply": int(days_supply) if days_supply else 30,
        }
        if trace_id:
            payload["trace_id"] = trace_id

        missing_keys = [k for k in ("drug_id", "member_id", "plan_id") if not payload.get(k)]
        if missing_keys:
            raise IntakeValidationError(
                _build_intake_validation_details(missing_keys, resolved.get("notes") or [])
            )
        
        response = requests.post(
            pbm_api_url,
            json=payload,
            timeout=orchestrator_timeout_seconds,
        )
        response.raise_for_status()
        orch_result = response.json()

        summary, final_candidates = _coerce_orchestrator_shape(orch_result)
        top_candidate = _select_display_candidate(summary, final_candidates)
        top_financial = top_candidate.get("financial", {})
        top_financial_summary = top_candidate.get("financial_summary", {})
        top_policy = top_candidate.get("policy", {})
        
        # Extract decision from orchestrator response
        orchestrator_decision = summary.get("decision")
        is_keep_original = orchestrator_decision == "keep_original"
        decision_map = {
            "auto_approve": "APPROVED",
            "doctor_review": "ESCALATED",
            # Clinical agent found no suitable alternatives → escalate to doctor for DAW confirmation
            "keep_original": "ESCALATED",
        }
        status = decision_map.get(orchestrator_decision, "ESCALATED")
        
        # Extract confidence from combined score or use a default
        ai_confidence = _to_float(summary.get("confidence_score"), _to_float(top_candidate.get("combined_score"), 0.0))
        
        # Get chosen drug (alternative) or original
        chosen_drug = _render_drug_label(summary.get("chosen_drug") or summary.get("recommended_drug")) or medication
        reason = summary.get("reason", "No reason provided")

        # Extract financial info from final_candidates.
        # Prefer formulary ALT_LBL_NM (TRGT_PROD_SK -> ALT_PROD_SK mapping), then fall back.
        original_drug_id = str(payload.get("drug_id") or "")
        candidate_drug_id = str(top_candidate.get("drug_id") or summary.get("chosen_drug") or summary.get("recommended_drug") or "")
        recommended_alt = (
            _lookup_formulary_alt_label_by_ids(original_drug_id, candidate_drug_id)
            or _render_drug_label(candidate_drug_id)
            or _lookup_formulary_alternative(medication)
        )
        estimated_savings = _to_float(
            top_financial_summary.get("estimated_savings"),
            _to_float(top_financial.get("estimated_savings"), 0.0)
        )
        insurance_context = _normalize_insurance_context(top_financial.get("insurance_context"))

        original_final_cost_raw = top_financial.get("original_final_cost")
        top_decision_hint = str(top_financial_summary.get("decision") or '').strip().lower()
        top_pricing_note = str(top_financial.get("notes") or '').strip().lower()
        original_unpriceable = (
            original_final_cost_raw in (None, '', 'None')
            or top_decision_hint == 'fallback_original_unpriceable'
            or 'could not be priced' in top_pricing_note
        )

        original_total_cost = None if original_unpriceable else _to_float(original_final_cost_raw, 0.0)
        if original_total_cost is None and resolved_pricing_final_cost > 0:
            # Preserve both-column UX by surfacing fallback list pricing for original drug.
            original_total_cost = resolved_pricing_final_cost
        alternative_total_cost = _to_float(top_financial.get("final_cost"), 0.0)
        original_copay = None
        if not original_unpriceable:
            original_copay = _to_float(
                (top_financial.get("insurance_context") or {}).get("original_fill_projection", {}).get("patient_pay"),
                top_financial_summary.get("original_patient_pay")
                or top_financial.get("original_patient_pay")
                or 0.0,
            )
        alternative_copay = _to_float(
            top_financial.get("estimated_patient_pay"),
            top_financial_summary.get("candidate_patient_pay")
            or top_financial.get("candidate_patient_pay")
            or 0.0,
        )

        if original_total_cost is not None and original_total_cost <= 0 and resolved_pricing_final_cost > 0:
            original_total_cost = resolved_pricing_final_cost
        if not alternative_total_cost:
            base_original = _to_float(original_total_cost, 0.0) if original_total_cost is not None else 0.0
            alternative_total_cost = max(base_original - estimated_savings, 0)
        if alternative_total_cost <= 0 and original_total_cost is not None and original_total_cost > 0:
            alternative_total_cost = original_total_cost

        if original_copay is None and original_total_cost is not None and original_total_cost > 0:
            original_copay = round(original_total_cost * 0.20, 2)
        if original_copay is not None and original_copay <= 0 and original_total_cost is not None and original_total_cost > 0:
            original_copay = round(original_total_cost * 0.20, 2)
        if alternative_copay <= 0 and alternative_total_cost > 0:
            alternative_copay = round(alternative_total_cost * 0.20, 2)

        computed_fill_savings = None
        if original_total_cost is not None:
            computed_fill_savings = max(original_total_cost - alternative_total_cost, 0.0)
        if estimated_savings <= 0 and computed_fill_savings is not None and computed_fill_savings > 0:
            estimated_savings = round(computed_fill_savings, 2)
        annual_savings = round(max(estimated_savings, 0) * 12, 2)
        savings_pct = (
            round((computed_fill_savings / original_total_cost) * 100, 2)
            if original_total_cost is not None and original_total_cost > 0 and computed_fill_savings is not None
            else 0.0
        )

        original_tier = _format_tier(
            _first_meaningful(
                top_financial.get("original_tier"),
                top_financial.get("original_drug_tier"),
                top_financial.get("original_tier_number"),
                resolved_formulary_tier,
            )
        )
        alternative_tier = _format_tier(
            _first_meaningful(
                top_financial.get("alternative_tier"),
                top_financial.get("tier"),
                top_policy.get("tier"),
                top_policy.get("formulary_tier"),
            )
        )
        policy_reason = top_policy.get("notes") or (top_policy.get("summary") or {}).get("reason") or "Review required"
        original_policy_reason = (
            top_policy.get("original_status")
            or (top_policy.get("summary") or {}).get("original_status")
            or "Original prescription under plan review."
        )
        alternative_policy_reason = top_policy.get("alternative_status") or policy_reason
        coinsurance_percentage = _resolve_coinsurance_percentage(top_financial)

        if is_keep_original:
            recommended_alt = None
            alternative_tier = "—"
            alternative_total_cost = 0.0
            alternative_copay = 0.0
            estimated_savings = 0.0
            annual_savings = 0.0
            savings_pct = 0.0
            original_policy_reason = reason or "Original prescription kept as written."
            alternative_policy_reason = "No alternative cleared gate thresholds."

        _ensure_cost_comparison_columns(cursor)
        
        # ── Insert PBM Response ──────────────────────────────────────────────
        cursor.execute("""
            INSERT INTO pbm_response 
            (rx_number, status, ai_confidence, prescribed_drug, diagnosis, recommended_alt, cost_impact, safety_summary, policy_compliance)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            rx_number,
            status,
            ai_confidence,
            medication,
            diagnosis_icd10,
            recommended_alt,
            estimated_savings,
            top_candidate.get("reason") or summary.get("reason") or "Reviewed by multi-agent AI",
            policy_reason
        ))
        
        pbm_id = cursor.lastrowid

        outcome_by_drug_id = {
            str(item.get('drug_id') or '').strip(): item
            for item in (summary.get('candidate_outcomes') or [])
            if str(item.get('drug_id') or '').strip()
        }
        selected_drug_id = str(candidate_drug_id or '').strip()
        alternative_payloads = []
        display_index = 0
        for candidate in final_candidates:
            candidate_copy = dict(candidate)
            candidate_id = str(candidate_copy.get('drug_id') or '').strip()
            outcome_info = outcome_by_drug_id.get(candidate_id) or {}
            if outcome_info:
                candidate_copy.setdefault('outcome', outcome_info.get('outcome'))
                candidate_copy.setdefault('reason', outcome_info.get('reason'))
                candidate_copy.setdefault('rejection_reason', outcome_info.get('rejection_reason'))
                candidate_copy.setdefault('escalation_reason', outcome_info.get('escalation_reason'))

            alternative_payloads.append(
                _build_alternative_payload(
                    payload,
                    medication,
                    diagnosis_icd10,
                    days_supply,
                    summary,
                    candidate_copy,
                    display_index,
                    candidate_id == selected_drug_id,
                    original_tier_fallback=resolved_formulary_tier,
                    original_price_fallback=resolved_pricing_final_cost,
                )
            )
            display_index += 1

        # ── Apply orchestrator summary cards at write-time and save to DB ──
        cards_by_alternative = _extract_summary_cards_by_alternative(orch_result)
        if cards_by_alternative:
            for alt_payload in alternative_payloads:
                alt_id = str(alt_payload.get('drug_id') or '').strip()
                mapped = cards_by_alternative.get(alt_id)
                if not mapped:
                    continue
                _apply_summary_cards_to_alternative_payload(
                    alt_payload,
                    mapped.get('cards') or {},
                    mapped.get('meta') or {},
                )

        selected_cards, selected_meta = _extract_selected_summary_cards(orch_result)
        if selected_cards:
            selected_payload = next((item for item in alternative_payloads if item.get('is_selected')), None)
            if selected_payload is None and alternative_payloads:
                selected_payload = alternative_payloads[0]
            if selected_payload is not None and not selected_payload.get('orchestrator_summary_cards'):
                _apply_summary_cards_to_alternative_payload(selected_payload, selected_cards, selected_meta)

        if alternative_payloads:
            _persist_alternative_payloads(cursor, pbm_id, rx_number, alternative_payloads)
        
        # ── Cost Comparison ──────────────────────────────────────────────────
        original_total_for_db = _to_float(original_total_cost, 0.0)
        original_copay_for_db = _to_float(original_copay, 0.0)
        original_plan_paid = round(max(_to_float(top_financial.get("original_final_cost"), original_total_for_db) - original_copay_for_db, 0), 2)
        alternative_plan_paid = round(max(alternative_total_cost - alternative_copay, 0), 2)
        ytd_oop = insurance_context.get("ytd_oop")
        deductible_cap = insurance_context.get("deductible_cap")
        oop_max_cap = insurance_context.get("oop_max_cap")
        cursor.execute("""
            INSERT INTO pbm_cost_comparison 
            (rx_number, original_tier, original_price, original_copay, alternative_tier, alternative_price, alternative_copay, savings,
             insurance_phase, ytd_oop, deductible_cap, oop_max_cap, deductible_remaining, oop_remaining,
             drug_name, generic_name, dosage, quantity, days_supply, formulary_status,
             prior_authorization_required, step_therapy_required, original_total_cost, alternative_total_cost,
             original_plan_paid, alternative_plan_paid, estimated_annual_savings, member_savings_percentage,
             deductible_met, oop_met, coinsurance_percentage, coverage_gap_status, catastrophic_coverage_status,
             pbm_name, policy_id, formulary_version, effective_date, expiration_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            rx_number,
            original_tier,
            original_total_for_db,
            original_copay_for_db,
            alternative_tier,
            alternative_total_cost,
            alternative_copay,
            estimated_savings,
            insurance_context.get("phase"),
            insurance_context.get("ytd_oop"),
            insurance_context.get("deductible_cap"),
            insurance_context.get("oop_max_cap"),
            insurance_context.get("deductible_remaining"),
            insurance_context.get("oop_remaining"),
            medication,
            medication,
            f"{days_supply} day fill" if days_supply else "30 day fill",
            int(days_supply) if days_supply else 30,
            int(days_supply) if days_supply else 30,
            "Preferred" if status == "APPROVED" else "Non-Preferred",
            0 if status == "APPROVED" else 1,
            0 if status == "APPROVED" else 1,
            original_total_for_db,
            alternative_total_cost,
            original_plan_paid,
            alternative_plan_paid,
            annual_savings,
            savings_pct,
            round(max((deductible_cap or 0) - (insurance_context.get("deductible_remaining") or 0), 0), 2),
            round(ytd_oop or 0, 2),
            coinsurance_percentage,
            "Not in Coverage Gap" if (ytd_oop or 0) < 2000 else "In Coverage Gap",
            "Not Reached" if (ytd_oop or 0) < (oop_max_cap or 3000) else "Reached",
            "Default PBM",
            "POL-DEFAULT-2026",
            "v2026.07",
            datetime.now().strftime('%Y-%m-%d'),
            "2027-12-31",
        ))

        _upsert_financial_snapshot(cursor, rx_number, {
            "original_tier": original_tier,
            "original_price": original_total_for_db,
            "original_copay": original_copay_for_db,
            "alternative_tier": alternative_tier,
            "alternative_price": alternative_total_cost,
            "alternative_copay": alternative_copay,
            "savings": estimated_savings,
            "insurance_phase": insurance_context.get("phase"),
            "ytd_oop": insurance_context.get("ytd_oop"),
            "deductible_cap": insurance_context.get("deductible_cap"),
            "oop_max_cap": insurance_context.get("oop_max_cap"),
            "deductible_remaining": insurance_context.get("deductible_remaining"),
            "oop_remaining": insurance_context.get("oop_remaining"),
        })
        
        # ── Safety ──────────────────────────────────────────────────────────
        clinical_detail = top_candidate.get("clinical_detail", {})
        safety_info = "None detected" if clinical_detail.get("safe", True) else "Contraindications detected"
        cursor.execute("""
            INSERT INTO pbm_safety (pbm_response_id, contraindications, interactions, monitoring)
            VALUES (?, ?, ?, ?)
        """, (pbm_id, safety_info, "Minimal interactions", "Standard monitoring"))
        
        # ── Policy ──────────────────────────────────────────────────────────
        cursor.execute("""
            INSERT INTO pbm_policy (pbm_response_id, original_status, alternative_status)
            VALUES (?, ?, ?)
        """, (pbm_id, original_policy_reason, alternative_policy_reason))
        
        # ── Auto-approve decision ────────────────────────────────────────────
        if status == "APPROVED":
            _ensure_doctor_decision_tables(cursor)
            cursor.execute("""
                INSERT INTO doctor_decision (rx_number, status, reason)
                VALUES (?, ?, ?)
            """, (rx_number, "ACCEPTED", reason))
            cursor.execute("""
                UPDATE prescription SET rx_status = 'Approved' WHERE rx_number = ?
            """, (rx_number,))
        else:
            cursor.execute("""
                UPDATE prescription SET rx_status = 'Pending' WHERE rx_number = ?
            """, (rx_number,))
    
    except IntakeValidationError:
        raise
    except requests.exceptions.ConnectionError as e:
        print(f"Orchestrator API call failed: {e}")
        raise RuntimeError("Backend not running") from e
    except requests.exceptions.RequestException as e:
        print(f"Orchestrator API call failed: {e}")
        raise RuntimeError("API error") from e
    except Exception as e:
        print(f"Error processing orchestrator response: {e}")
        raise


def fallback_pbm_processing(cursor, rx_number, drug, diagnosis):
    """
    Fallback two-outcome PBM decision logic when orchestrator is unavailable.
    Used when the orchestrator API is unreachable.
    """
    importlib.reload(_config_module)
    threshold = _config_module.Config.AUTO_APPROVE_THRESHOLD
    ai_conf = round(random.uniform(0.20, 0.97), 2)
    auto_approved = ai_conf >= threshold

    if auto_approved:
        status = 'APPROVED'
        alt = None
        savings = 0
        policy = 'Fully covered'
        alt_policy = 'Fully covered'
    else:
        status = 'ESCALATED'
        alt = _lookup_formulary_alternative(drug) or f"Preferred alternative for {drug}"
        savings = random.randint(100, 2500)
        policy = 'Prior auth required'
        alt_policy = 'Covered with copay'

    cursor.execute("""
        INSERT INTO pbm_response 
        (rx_number, status, ai_confidence, prescribed_drug, diagnosis, recommended_alt, cost_impact, safety_summary, policy_compliance)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'Reviewed by AI', 'Checked against formulary')
    """, (rx_number, status, ai_conf, drug, diagnosis, alt, savings))

    pbm_id = cursor.lastrowid

    _ensure_cost_comparison_columns(cursor)

    orig_price = random.randint(100, 3000)
    alt_price = max(0, orig_price - savings)
    original_total_cost = round(orig_price, 2)
    alternative_total_cost = round(alt_price, 2)
    original_plan_paid = round(max(original_total_cost - (orig_price * 0.2), 0), 2)
    alternative_plan_paid = round(max(alternative_total_cost - (alt_price * 0.1), 0), 2)
    annual_savings = round(max(savings, 0) * 12, 2)
    savings_pct = round((savings / orig_price) * 100, 2) if orig_price else 0.0
    cursor.execute("""
        INSERT INTO pbm_cost_comparison 
        (rx_number, original_tier, original_price, original_copay, alternative_tier, alternative_price, alternative_copay, savings,
         insurance_phase, ytd_oop, deductible_cap, oop_max_cap, deductible_remaining, oop_remaining,
         drug_name, generic_name, dosage, quantity, days_supply, formulary_status,
         prior_authorization_required, step_therapy_required, original_total_cost, alternative_total_cost,
         original_plan_paid, alternative_plan_paid, estimated_annual_savings, member_savings_percentage,
         deductible_met, oop_met, coinsurance_percentage, coverage_gap_status, catastrophic_coverage_status,
         pbm_name, policy_id, formulary_version, effective_date, expiration_date)
        VALUES (?, 'Tier 3', ?, ?, 'Tier 1', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (rx_number, orig_price, orig_price * 0.2, alt_price, alt_price * 0.1, savings,
            "Standard Coverage", 120.0, 750.0, 3000.0, 630.0, 2880.0,
            drug, drug, "30 day fill", 30, 30, "Preferred" if auto_approved else "Non-Preferred",
            0 if auto_approved else 1, 0 if auto_approved else 1,
            original_total_cost, alternative_total_cost, original_plan_paid, alternative_plan_paid,
            annual_savings, savings_pct, 120.0, 120.0, 20.0,
            "Not in Coverage Gap", "Not Reached", "Default PBM", "POL-FALLBACK-2026", "v2026.07",
            datetime.now().strftime('%Y-%m-%d'), "2027-12-31"))

    _upsert_financial_snapshot(cursor, rx_number, {
        "original_tier": "Tier 3",
        "original_price": orig_price,
        "original_copay": orig_price * 0.2,
        "alternative_tier": "Tier 1",
        "alternative_price": alt_price,
        "alternative_copay": alt_price * 0.1,
        "savings": savings,
        "insurance_phase": "Standard Coverage",
        "ytd_oop": 0.0,
        "deductible_cap": 750.0,
        "oop_max_cap": 3000.0,
        "deductible_remaining": 750.0,
        "oop_remaining": 3000.0,
    })

    cursor.execute("""
        INSERT INTO pbm_safety (pbm_response_id, contraindications, interactions, monitoring)
        VALUES (?, 'None detected', 'Minimal interactions', 'Standard monitoring')
    """, (pbm_id,))

    cursor.execute("""
        INSERT INTO pbm_policy (pbm_response_id, original_status, alternative_status)
        VALUES (?, ?, ?)
    """, (pbm_id, policy, alt_policy))

    alternative_payloads = []
    if alt:
        alternative_payloads.append({
            'index': 0,
            'drug_id': '',
            'label': alt,
            'is_selected': not auto_approved,
            'review_status': 'APPROVED' if auto_approved else 'ESCALATED',
            'combined_score': ai_conf,
            'score_basis': 'fallback_randomized',
            'outcome': 'auto_approved' if auto_approved else 'review',
            'reason': policy,
            'prescribed_drug': drug,
            'diagnosis': diagnosis,
            'agent_breakdown': {},
            'cost': {
                'original_tier': 'Tier 3',
                'original_price': round(orig_price, 2),
                'original_copay': round(orig_price * 0.2, 2),
                'alternative_tier': 'Tier 1',
                'alternative_price': round(alt_price, 2),
                'alternative_copay': round(alt_price * 0.1, 2),
                'savings': round(savings, 2),
                'insurance_phase': 'Standard Coverage',
                'ytd_oop': 120.0,
                'deductible_cap': 750.0,
                'oop_max_cap': 3000.0,
                'deductible_remaining': 630.0,
                'oop_remaining': 2880.0,
                'original_total_cost': original_total_cost,
                'alternative_total_cost': alternative_total_cost,
                'original_plan_paid': original_plan_paid,
                'alternative_plan_paid': alternative_plan_paid,
                'estimated_annual_savings': annual_savings,
                'member_savings_percentage': savings_pct,
                'deductible_met': 120.0,
                'oop_met': 120.0,
                'coinsurance_percentage': 20.0,
                'coverage_gap_status': 'Not in Coverage Gap',
                'catastrophic_coverage_status': 'Not Reached',
                'days_supply': 30,
            },
            'safety': {
                'summary': 'None detected',
                'contraindications': 'None detected',
                'interactions': 'Minimal interactions',
                'monitoring': 'Standard monitoring',
            },
            'policy': {
                'original_status': policy,
                'alternative_status': alt_policy,
                'policy_state': 'fallback',
            },
        })

    if alternative_payloads:
        _persist_alternative_payloads(cursor, pbm_id, rx_number, alternative_payloads)

    if auto_approved:
        _ensure_doctor_decision_tables(cursor)
        cursor.execute("""
            INSERT INTO doctor_decision (rx_number, status, reason)
            VALUES (?, 'ACCEPTED', NULL)
        """, (rx_number,))
        cursor.execute("""
            UPDATE prescription SET rx_status = 'Approved' WHERE rx_number = ?
        """, (rx_number,))
    else:
        cursor.execute("""
            UPDATE prescription SET rx_status = 'Pending' WHERE rx_number = ?
        """, (rx_number,))



# 2. Track Status
@prescription_bp.route('/prescription/<rx_number>/status', methods=['GET'])
@token_required
def get_status(rx_number):
    conn = get_db_connection()
    cursor = conn.cursor()
    _ensure_doctor_decision_tables(cursor)
    # Return simplified status composed from prescription, PBM response and doctor decision
    cursor.execute("SELECT * FROM prescription WHERE rx_number = ?", (rx_number,))
    pres = cursor.fetchone()

    if not pres:
        conn.close()
        return jsonify({'error': 'Prescription not found'}), 404

    if not _can_access_prescription_record(request.user, pres):
        conn.close()
        return jsonify({'error': 'Forbidden'}), 403

    # PBM Response
    cursor.execute("SELECT status AS pbm_status, ai_confidence, created_at FROM pbm_response WHERE rx_number = ?", (rx_number,))
    pbm = cursor.fetchone()

    # Doctor Decision
    cursor.execute("SELECT status AS decision_status, reason, comment, created_at FROM doctor_decision WHERE rx_number = ?", (rx_number,))
    decision = cursor.fetchone()

    decision_reasons = []
    if decision:
        cursor.execute("SELECT reason_code, reason_text FROM doctor_decision_reason WHERE rx_number = ? ORDER BY id", (rx_number,))
        decision_reasons = [dict(row) for row in cursor.fetchall()]

    conn.close()

    # Derive a simple pipeline-style status to keep UI compatibility
    if not pbm:
        status = 'PROCESSING'
        agents_done = []
        agents_pending = ['clinical','financial','pbm']
        estimated_wait_s = 10
        created_at = pres['date_written']
    else:
        if pbm['pbm_status'] == 'ESCALATED' or (decision and not decision['decision_status']):
            status = 'ESCALATED'
            agents_done = ['clinical','financial','pbm']
            agents_pending = ['provider']
        else:
            status = 'COMPLETED'
            agents_done = ['clinical','financial','pbm']
            agents_pending = []
        estimated_wait_s = 0
        created_at = pbm['created_at']

    response = {
        'rx_number': pres['rx_number'],
        'status': status,
        'prescription_status': pres['rx_status'],
        'date_written': pres['date_written'],
        'agents_done': agents_done,
        'agents_pending': agents_pending,
        'estimated_wait_s': estimated_wait_s,
        'created_at': created_at,
        'pbm_status': pbm['pbm_status'] if pbm else None,
        'ai_confidence': pbm['ai_confidence'] if pbm else None,
        'pbm_created_at': pbm['created_at'] if pbm else None,
        'doctor_decision': ({**dict(decision), 'reasons': decision_reasons} if decision else None)
    }

    return jsonify(response)


# 3. Get PBM Results
@prescription_bp.route('/prescription/<rx_number>/result', methods=['GET'])
@token_required
def get_results(rx_number):
    conn = get_db_connection()
    cursor = conn.cursor()
    _ensure_doctor_decision_tables(cursor)

    cursor.execute("SELECT * FROM prescription WHERE rx_number = ?", (rx_number,))
    pres = cursor.fetchone()
    if not pres:
        conn.close()
        return jsonify({'error': 'Prescription not found'}), 404

    if not _can_access_prescription_record(request.user, pres):
        conn.close()
        return jsonify({'error': 'Forbidden'}), 403
    
    # PBM Response
    cursor.execute("SELECT * FROM pbm_response WHERE rx_number = ?", (rx_number,))
    pbm = cursor.fetchone()
    
    if not pbm:
        conn.close()
        return jsonify({'pbm': None}) # Not ready yet
        
    pbm_id = pbm['id']

    _ensure_financial_temp_table(cursor)
    
    # Sub-objects
    # Merge cost by rx_number: prefer financial snapshot values when present,
    # and fall back to pbm_cost_comparison for any missing fields.
    cursor.execute("""
        SELECT
            COALESCE(f.rx_number, c.rx_number) AS rx_number,
            COALESCE(f.original_tier, c.original_tier) AS original_tier,
            COALESCE(f.original_price, c.original_price) AS original_price,
            COALESCE(f.original_copay, c.original_copay) AS original_copay,
            COALESCE(f.alternative_tier, c.alternative_tier) AS alternative_tier,
            COALESCE(f.alternative_price, c.alternative_price) AS alternative_price,
            COALESCE(f.alternative_copay, c.alternative_copay) AS alternative_copay,
            COALESCE(f.savings, c.savings) AS savings,
            COALESCE(f.insurance_phase, c.insurance_phase) AS insurance_phase,
            COALESCE(f.ytd_oop, c.ytd_oop) AS ytd_oop,
            COALESCE(f.deductible_cap, c.deductible_cap) AS deductible_cap,
            COALESCE(f.oop_max_cap, c.oop_max_cap) AS oop_max_cap,
            COALESCE(f.deductible_remaining, c.deductible_remaining) AS deductible_remaining,
            COALESCE(f.oop_remaining, c.oop_remaining) AS oop_remaining,
            c.drug_name AS drug_name,
            c.generic_name AS generic_name,
            c.dosage AS dosage,
            c.quantity AS quantity,
            c.days_supply AS days_supply,
            c.formulary_status AS formulary_status,
            c.prior_authorization_required AS prior_authorization_required,
            c.step_therapy_required AS step_therapy_required,
            c.original_total_cost AS original_total_cost,
            c.alternative_total_cost AS alternative_total_cost,
            c.original_plan_paid AS original_plan_paid,
            c.alternative_plan_paid AS alternative_plan_paid,
            c.estimated_annual_savings AS estimated_annual_savings,
            c.member_savings_percentage AS member_savings_percentage,
            c.deductible_met AS deductible_met,
            c.oop_met AS oop_met,
            c.coinsurance_percentage AS coinsurance_percentage,
            c.coverage_gap_status AS coverage_gap_status,
            c.catastrophic_coverage_status AS catastrophic_coverage_status,
            c.pbm_name AS pbm_name,
            c.policy_id AS policy_id,
            c.formulary_version AS formulary_version,
            c.effective_date AS effective_date,
            c.expiration_date AS expiration_date
        FROM pbm_cost_comparison c
        LEFT JOIN financial_temp_snapshot f ON f.rx_number = c.rx_number
        WHERE c.rx_number = ?
    """, (rx_number,))
    cost = cursor.fetchone()
    if not cost:
        cursor.execute("SELECT * FROM financial_temp_snapshot WHERE rx_number = ?", (rx_number,))
        cost = cursor.fetchone()
    
    cursor.execute("SELECT * FROM pbm_safety WHERE pbm_response_id = ?", (pbm_id,))
    safety = cursor.fetchone()
    
    cursor.execute("SELECT * FROM pbm_policy WHERE pbm_response_id = ?", (pbm_id,))
    policy = cursor.fetchone()

    _ensure_alternative_options_table(cursor)
    cursor.execute("SELECT * FROM pbm_alternative_option WHERE rx_number = ? ORDER BY alternative_index ASC, id ASC", (rx_number,))
    alternative_rows = cursor.fetchall()

    # Doctor Decision
    cursor.execute("SELECT * FROM doctor_decision WHERE rx_number = ?", (rx_number,))
    decision = cursor.fetchone()

    decision_payload = None
    if decision:
        cursor.execute("SELECT reason_code, reason_text FROM doctor_decision_reason WHERE rx_number = ? ORDER BY id", (rx_number,))
        decision_payload = dict(decision)
        decision_payload['reasons'] = [dict(row) for row in cursor.fetchall()]

    pbm_payload = dict(pbm)
    member_id_value = str((pres['member_id'] if 'member_id' in pres.keys() else '') or (pres['patient_account_id'] if 'patient_account_id' in pres.keys() else '') or '').strip()
    if member_id_value:
        if not str(pbm_payload.get('member_id') or '').strip():
            pbm_payload['member_id'] = member_id_value
        if not str(pbm_payload.get('patient_account_id') or '').strip():
            pbm_payload['patient_account_id'] = member_id_value
    diagnosis_fields = _resolve_diagnosis_fields(pbm_payload.get('diagnosis'))
    pbm_payload['diagnosis_code'] = diagnosis_fields['code']
    pbm_payload['diagnosis_description'] = diagnosis_fields['description']
    pbm_payload['diagnosis_display'] = diagnosis_fields['display']

    alternative_payloads = []
    for row in alternative_rows:
        try:
            payload = json.loads(row['result_payload'])
        except (TypeError, ValueError, json.JSONDecodeError):
            payload = {}

        payload.setdefault('index', row['alternative_index'])
        payload.setdefault('drug_id', row['drug_id'])
        payload.setdefault('label', row['alternative_label'])
        payload.setdefault('is_selected', bool(row['is_selected']))
        alternative_payloads.append(payload)

    if not alternative_payloads:
        alternative_payloads.append(
            _build_legacy_alternative_payload(
                pbm_payload,
                dict(cost) if cost else None,
                dict(safety) if safety else None,
                dict(policy) if policy else None,
            )
        )

    # Collect rejected alternatives with stored per-alternative reasons.
    # Fall back to RX-level decision reason when per-alternative reason is absent (legacy rejections).
    rx_level_reason = None
    rx_level_comment = None
    if decision_payload:
        rx_level_reason = decision_payload.get('reason') or None
        rx_level_comment = decision_payload.get('comment') or None

    rejected_alternatives = []
    for row in alternative_rows:
        try:
            rp = json.loads(row['result_payload']) if row['result_payload'] else {}
        except (TypeError, ValueError, json.JSONDecodeError):
            rp = {}
        review_status = str((rp or {}).get('review_status') or '').strip().upper()
        outcome = str((rp or {}).get('outcome') or '').strip().lower()
        policy_state = str((((rp or {}).get('policy') or {}).get('policy_state') or '')).strip().lower()
        is_rej = review_status == 'REJECTED' or outcome == 'rejected' or policy_state == 'deny'
        if is_rej:
            per_alt_reason = rp.get('rejection_reason') or rp.get('reason') or None
            per_alt_comment = rp.get('rejection_comment') or rp.get('comment') or None
            rejected_alternatives.append({
                'label': row['alternative_label'] or rp.get('label') or f'Alternative {row["alternative_index"] + 1}',
                'drug_id': row['drug_id'],
                'index': row['alternative_index'],
                'rejection_reason': per_alt_reason or rx_level_reason,
                'rejection_reason_codes': rp.get('rejection_reason_codes') or [],
                'rejection_comment': per_alt_comment or rx_level_comment,
            })

    # Build pharmacist-facing past agent summary from same member + medication history.
    prescription_columns = _get_table_columns(cursor, 'prescription')
    if {'patient_account_id', 'prod_nm'}.issubset(prescription_columns):
        member_col = 'patient_account_id'
        medication_col = 'prod_nm'
    else:
        member_col = 'member_id'
        medication_col = 'medication'

    member_value = str((pres[member_col] if member_col in pres.keys() else '') or '').strip()
    medication_value = str((pres[medication_col] if medication_col in pres.keys() else '') or '').strip()

    past_entries = []
    if member_value and medication_value:
        cursor.execute(
            f"""
            SELECT
                p.rx_number,
                p.date_written,
                pb.status AS pbm_status,
                pb.recommended_alt,
                pb.policy_compliance,
                pb.safety_summary,
                pb.created_at AS pbm_created_at,
                d.status AS decision_status,
                d.comment AS decision_comment,
                d.created_at AS decision_created_at,
                c.estimated_annual_savings,
                c.savings,
                c.insurance_phase
            FROM prescription p
            LEFT JOIN pbm_response pb ON pb.rx_number = p.rx_number
            LEFT JOIN doctor_decision d ON d.rx_number = p.rx_number
            LEFT JOIN pbm_cost_comparison c ON c.rx_number = p.rx_number
            WHERE p.{member_col} = ? AND p.{medication_col} = ?
            ORDER BY COALESCE(d.created_at, pb.created_at, p.date_written) DESC, p.rx_number DESC
            LIMIT 5
            """,
            (member_value, medication_value),
        )
        history_rows = cursor.fetchall()

        for h in history_rows:
            decision_status = str((h['decision_status'] or '')).upper()
            pbm_status = str((h['pbm_status'] or '')).upper()
            savings_value = h['estimated_annual_savings']
            if savings_value is None:
                savings_value = h['savings']
            try:
                savings_value = float(savings_value) if savings_value is not None else 0.0
            except (TypeError, ValueError):
                savings_value = 0.0

            if pbm_status == 'ESCALATED':
                agent_type = 'AI Clinical Review'
            elif str(h['insurance_phase'] or '').strip():
                agent_type = 'Coverage Review'
            elif savings_value > 0:
                agent_type = 'Cost Optimization'
            else:
                agent_type = 'PBM Analysis'

            if decision_status == 'ACCEPTED':
                outcome = 'Accepted'
            elif decision_status == 'REJECTED':
                outcome = 'Rejected'
            elif decision_status == 'MODIFIED':
                outcome = 'Modified'
            else:
                outcome = 'Modified' if pbm_status == 'APPROVED' else 'Pending'

            recommendation = str((h['recommended_alt'] or '')).strip() or 'Original medication retained'
            reasoning_summary = (
                str((h['decision_comment'] or '')).strip()
                or str((h['policy_compliance'] or '')).strip()
                or str((h['safety_summary'] or '')).strip()
                or 'Based on prior outcomes and agent checks.'
            )

            date_time = h['decision_created_at'] or h['pbm_created_at'] or h['date_written']
            past_entries.append({
                'rx_number': h['rx_number'],
                'date_time': date_time,
                'agent_type': agent_type,
                'recommendation': recommendation,
                'reasoning_summary': reasoning_summary,
                'outcome': outcome,
                'savings_impact': round(savings_value, 2),
            })

    finalized_outcomes = [e for e in past_entries if e['outcome'] in ('Accepted', 'Rejected', 'Modified')]
    accepted_outcomes = [e for e in finalized_outcomes if e['outcome'] == 'Accepted']
    acceptance_rate = round((len(accepted_outcomes) / len(finalized_outcomes) * 100.0), 1) if finalized_outcomes else 0.0
    total_saved = round(sum(max(0.0, float(e.get('savings_impact') or 0.0)) for e in past_entries), 2)
    last_review_date = past_entries[0]['date_time'] if past_entries else None

    past_agent_summary = {
        'metrics': {
            'total_reviews': len(past_entries),
            'acceptance_rate': acceptance_rate,
            'total_cost_saved': total_saved,
            'last_review_date': last_review_date,
        },
        'entries': past_entries,
    }

    conn.close()
    
    return jsonify({
        'pbm': pbm_payload,
        'cost': dict(cost) if cost else None,
        'safety': dict(safety) if safety else None,
        'policy': dict(policy) if policy else None,
        'alternatives': alternative_payloads,
        'rejected_alternatives': rejected_alternatives,
        'doctor_decision': decision_payload,
        'past_agent_summary': past_agent_summary,
        'overall_threshold': _get_overall_threshold(),
    })


@prescription_bp.route('/decision-reasons', methods=['GET'])
@token_required
@role_required(['provider'])
def search_decision_reasons():
    query = (request.args.get('q') or '').strip().lower()
    items = _load_rejection_reason_data()

    if query:
        terms = query.split()
        items = [
            item for item in items
            if all(term in f"{item['code']} {item['label']}".lower() for term in terms)
        ]

    return jsonify(items[:25])


# 4. Submit Final Decision
@prescription_bp.route('/prescription/<rx_number>/decision', methods=['POST'])
@token_required
@role_required(['provider'])
def submit_decision(rx_number):
    data = request.json or {}
    status = (data.get('status') or '').strip().upper()
    comment = (data.get('comment') or '').strip()
    comment_value = comment or None
    reason_codes = data.get('reason_codes') or []
    alt_index_raw = data.get('alternative_index')

    if status not in ['ACCEPTED', 'REJECTED']:
        return jsonify({'error': 'Invalid status'}), 400

    alternative_index = None
    if alt_index_raw is not None and alt_index_raw != '':
        try:
            alternative_index = int(alt_index_raw)
        except (TypeError, ValueError):
            return jsonify({'error': 'Invalid alternative_index'}), 400

    reason_map = _get_rejection_reason_map()
    normalized_codes = []
    if status == 'REJECTED':
        if not isinstance(reason_codes, list):
            return jsonify({'error': 'Reason list must be an array'}), 400

        seen = set()
        for raw_code in reason_codes:
            code = (raw_code or '').strip().upper()
            if not code:
                continue
            if code not in reason_map:
                return jsonify({'error': f'Invalid rejection reason: {code}'}), 400
            if code not in seen:
                normalized_codes.append(code)
                seen.add(code)

        if not normalized_codes:
            return jsonify({'error': 'At least one rejection reason is required'}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    _ensure_doctor_decision_tables(cursor)
    backend_feedback_sync = None

    try:
        cursor.execute("SELECT * FROM prescription WHERE rx_number = ?", (rx_number,))
        pres = cursor.fetchone()
        if not pres:
            return jsonify({'error': 'Prescription not found'}), 404

        if not _can_access_prescription_record(request.user, pres):
            return jsonify({'error': 'Forbidden'}), 403

        cursor.execute("SELECT status FROM pbm_response WHERE rx_number = ?", (rx_number,))
        pbm_row = cursor.fetchone()
        pbm_status_value = str((pbm_row['status'] if pbm_row else '') or '').strip().upper()
        if pbm_status_value == 'APPROVED':
            return jsonify({'error': 'This prescription was auto-approved by the AI system and does not require provider review.'}), 409

        cursor.execute("SELECT status FROM doctor_decision WHERE rx_number = ?", (rx_number,))
        prior_decision_row = cursor.fetchone()
        if prior_decision_row and str(prior_decision_row['status'] or '').strip().upper() in ('ACCEPTED', 'REJECTED'):
            return jsonify({'error': 'A decision has already been recorded for this prescription.'}), 409

        _ensure_alternative_options_table(cursor)
        cursor.execute("SELECT id, alternative_index, is_selected, result_payload FROM pbm_alternative_option WHERE rx_number = ? ORDER BY alternative_index ASC, id ASC", (rx_number,))
        alt_rows = cursor.fetchall()

        alt_payloads = []
        for row in alt_rows:
            try:
                payload = json.loads(row['result_payload']) if row['result_payload'] else {}
            except (TypeError, ValueError, json.JSONDecodeError):
                payload = {}
            alt_payloads.append((row, payload))

        def is_rejected_payload(payload):
            review_status = str((payload or {}).get('review_status') or '').strip().upper()
            outcome = str((payload or {}).get('outcome') or '').strip().lower()
            policy_state = str((((payload or {}).get('policy') or {}).get('policy_state') or '')).strip().lower()
            return review_status == 'REJECTED' or outcome == 'rejected' or policy_state == 'deny'

        active_rows = [(row, payload) for row, payload in alt_payloads if not is_rejected_payload(payload)]

        target_row = None
        if alternative_index is not None:
            for row, payload in active_rows:
                if int(row['alternative_index']) == alternative_index:
                    target_row = (row, payload)
                    break
        if target_row is None:
            for row, payload in active_rows:
                if bool(row['is_selected']) or bool((payload or {}).get('is_selected')):
                    target_row = (row, payload)
                    break
        if target_row is None and active_rows:
            target_row = active_rows[0]

        reason_summary = None
        if normalized_codes:
            reason_summary = ', '.join(reason_map[code] for code in normalized_codes)

        cursor.execute("SELECT id FROM doctor_decision WHERE rx_number = ?", (rx_number,))
        existing_decision = cursor.fetchone()
        if existing_decision:
            cursor.execute("""
                UPDATE doctor_decision
                SET status = ?, reason = ?, comment = ?, created_at = datetime('now')
                WHERE rx_number = ?
            """, (status, reason_summary, comment_value, rx_number))
        else:
            cursor.execute("""
                INSERT INTO doctor_decision (rx_number, status, reason, comment)
                VALUES (?, ?, ?, ?)
            """, (rx_number, status, reason_summary, comment_value))

        cursor.execute("DELETE FROM doctor_decision_reason WHERE rx_number = ?", (rx_number,))

        if normalized_codes:
            cursor.executemany("""
                INSERT INTO doctor_decision_reason (rx_number, reason_code, reason_text, comment)
                VALUES (?, ?, ?, ?)
            """, [
                (rx_number, code, reason_map[code], comment_value)
                for code in normalized_codes
            ])

        if target_row is not None:
            row, payload = target_row
            if status == 'REJECTED':
                payload['review_status'] = 'REJECTED'
                payload['outcome'] = 'rejected'
                payload['is_selected'] = False
                payload['rejection_reason'] = reason_summary
                payload['rejection_reason_codes'] = normalized_codes
                payload['rejection_comment'] = comment_value
                cursor.execute(
                    "UPDATE pbm_alternative_option SET is_selected = 0, result_payload = ? WHERE id = ?",
                    (json.dumps(payload), row['id'])
                )

                remaining_active = 0
                for alt_row, alt_payload in alt_payloads:
                    if int(alt_row['id']) == int(row['id']):
                        continue
                    if not is_rejected_payload(alt_payload):
                        remaining_active += 1

                if remaining_active == 0:
                    cursor.execute("UPDATE pbm_response SET status = 'ESCALATED' WHERE rx_number = ?", (rx_number,))
                else:
                    cursor.execute("UPDATE pbm_response SET status = 'ESCALATED' WHERE rx_number = ?", (rx_number,))

            elif status == 'ACCEPTED':
                for alt_row, alt_payload in alt_payloads:
                    is_target = int(alt_row['id']) == int(row['id'])
                    if is_target:
                        alt_payload['review_status'] = 'ACCEPTED'
                        alt_payload['outcome'] = 'selected'
                        alt_payload['is_selected'] = True
                    else:
                        alt_payload['is_selected'] = False
                        if str(alt_payload.get('review_status') or '').upper() == 'ACCEPTED':
                            alt_payload['review_status'] = 'NOT_SELECTED'
                    cursor.execute(
                        "UPDATE pbm_alternative_option SET is_selected = ?, result_payload = ? WHERE id = ?",
                        (1 if alt_payload.get('is_selected') else 0, json.dumps(alt_payload), alt_row['id'])
                    )

                cursor.execute("UPDATE pbm_response SET status = 'ACCEPTED' WHERE rx_number = ?", (rx_number,))

        if status == 'ACCEPTED':
            cursor.execute("UPDATE pbm_response SET status = 'ACCEPTED' WHERE rx_number = ?", (rx_number,))

        selected_payload = target_row[1] if target_row is not None else {}
        backend_feedback_sync = _sync_backend_doctor_feedback(
            status=status,
            prescription_row=pres,
            selected_payload=selected_payload,
            reason_summary=reason_summary,
            comment=comment_value,
        )
        
        conn.commit()
        return jsonify({
            'message': 'Decision saved successfully',
            'backend_feedback_sync': backend_feedback_sync,
        })
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


# 5. Dashboard - All Prescriptions
@prescription_bp.route('/prescriptions', methods=['GET'])
@token_required
@role_required(['pharmacist', 'pbm', 'provider'])
def list_prescriptions():
    conn = get_db_connection()
    cursor = conn.cursor()

    prescription_columns = _get_table_columns(cursor, 'prescription')
    if {'patient_account_id', 'prod_nm'}.issubset(prescription_columns):
        patient_col = 'p.patient_account_id'
        drug_col = 'p.prod_nm'
        pharmacy_col = 'p.phr_id'
        provider_col = 'p.npi_number'
    else:
        patient_col = 'p.member_id'
        drug_col = 'p.medication'
        pharmacy_col = 'p.pharmacy_id'
        provider_col = 'p.prescriber_npi'

    where_clauses = []
    query_params = []
    user_role = (request.user or {}).get('role')
    if user_role == 'pharmacist':
        user_pharmacist_id = str((request.user or {}).get('pharmacist_id') or '').strip().upper()
        if user_pharmacist_id:
            where_clauses.append(f"UPPER({pharmacy_col}) = ?")
            query_params.append(user_pharmacist_id)

    where_sql = ''
    if where_clauses:
        where_sql = 'WHERE ' + ' AND '.join(where_clauses)

    cursor.execute(f"""
        SELECT p.rx_number,
               {patient_col} AS member_id,
               {drug_col} AS medication,
               {patient_col} AS patient_account_id,
               {drug_col} AS prod_nm,
               p.date_written,
               p.rx_status AS tracking_status,
               d.status   AS decision_status,
               pb.status  AS pbm_status,
             pb.ai_confidence AS ai_confidence,
               c.insurance_phase,
               c.ytd_oop
        FROM prescription p
        LEFT JOIN doctor_decision    d  ON p.rx_number = d.rx_number
        LEFT JOIN pbm_response       pb ON p.rx_number = pb.rx_number
        LEFT JOIN pbm_cost_comparison c ON p.rx_number = c.rx_number
        {where_sql}
        ORDER BY p.date_written DESC, p.rx_number DESC
    """, query_params)

    rows = cursor.fetchall()

    _ensure_alternative_options_table(cursor)
    rx_numbers = [str(row['rx_number']) for row in rows if row['rx_number']]
    alt_counts = {rx: {'total': 0, 'active': 0} for rx in rx_numbers}

    if rx_numbers:
        placeholders = ','.join(['?'] * len(rx_numbers))
        cursor.execute(
            f"SELECT rx_number, result_payload FROM pbm_alternative_option WHERE rx_number IN ({placeholders}) ORDER BY alternative_index ASC, id ASC",
            rx_numbers
        )

        for alt_row in cursor.fetchall():
            rx = str(alt_row['rx_number'])
            payload_text = alt_row['result_payload'] or '{}'
            try:
                payload = json.loads(payload_text)
            except (TypeError, ValueError, json.JSONDecodeError):
                payload = {}

            review_status = str((payload or {}).get('review_status') or '').strip().upper()
            outcome = str((payload or {}).get('outcome') or '').strip().lower()
            policy_state = str((((payload or {}).get('policy') or {}).get('policy_state') or '')).strip().lower()
            is_rejected = review_status == 'REJECTED' or outcome == 'rejected' or policy_state == 'deny'

            entry = alt_counts.setdefault(rx, {'total': 0, 'active': 0})
            entry['total'] += 1
            if not is_rejected:
                entry['active'] += 1

    conn.close()

    threshold = _get_overall_threshold()
    payload = []
    for row in rows:
        item = dict(row)
        pbm_status = str(item.get('pbm_status') or '').strip().upper()
        decision_status = str(item.get('decision_status') or '').strip().upper()
        date_written = str(item.get('date_written') or '').strip()
        
        # Determine completion status using same logic as presenter
        # COMPLETED_STATUSES = {'auto_approve', 'daw', 'accept', 'rejected'}
        is_completed = (
            pbm_status == 'APPROVED' or  # → auto_approve
            decision_status == 'ACCEPTED' or  # → accept
            decision_status == 'REJECTED' or  # → daw
            decision_status == 'MODIFIED' or  # → daw
            pbm_status == 'KEEP_ORIGINAL'  # → daw
        )
        
        if pbm_status == 'APPROVED':
            item['decision_status'] = None
        item['overall_threshold'] = threshold
        counts = alt_counts.get(str(item.get('rx_number') or ''), {'total': 0, 'active': 0})
        item['total_alternatives_count'] = counts['total']
        item['active_alternatives_count'] = counts['active']
        
        # Calculate due_date: show ✓ when completed, otherwise calculate based on date_written
        item['due_date'] = _calculate_due_date(date_written, is_completed, pbm_status, decision_status)
        
        payload.append(item)

    return jsonify(payload)
