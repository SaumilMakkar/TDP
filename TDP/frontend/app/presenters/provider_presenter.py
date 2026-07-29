"""Builds DB-backed data context for Provider/PBM overview pages."""
from datetime import date, datetime, timedelta
from dataclasses import dataclass, asdict
from typing import List, Dict, Optional

from app.db import get_db_connection

# Workflow status -> display config (color + legend copy) taken from the mock.
STATUS_META = {
    'pending': {
        'label': 'Pending',
        'css': 'status-pending',
        'legend': 'Awaiting AI evaluation.',
    },
    'in_progress': {
        'label': 'In Progress',
        'css': 'status-in-progress',
        'legend': 'Submitted for AI analysis.',
    },
    'under_review': {
        'label': 'Under Review',
        'css': 'status-under-review',
        'legend': 'Referred for clinical review due to low confidence.',
    },
    'auto_approve': {
        'label': 'Auto Approve',
        'css': 'status-auto-approve',
        'legend': 'Automatically approved due to high confidence.',
    },
    'daw': {
        'label': 'DAW',
        'css': 'status-daw',
        'legend': 'Original medication retained after clinical review.',
    },
    'accept': {
        'label': 'Accept',
        'css': 'status-accept',
        'legend': 'Alternative medication approved by clinician.',
    },
    'rejected': {
        'label': 'DAW',
        'css': 'status-daw',
        'legend': 'Original medication retained after clinical review.',
    },
}

PENDING_DISPLAY_STATUSES = {'pending', 'in_progress', 'under_review'}
COMPLETED_STATUSES = {'auto_approve', 'daw', 'accept', 'rejected'}

WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']


def _weekday_from_due_date(due_date: str) -> str | None:
    raw = str(due_date or '').strip()
    if not raw or raw == '-':
        return None

    try:
        parsed = datetime.strptime(raw, '%Y-%m-%d').date()
    except ValueError:
        return None

    weekday_index = parsed.weekday()
    if weekday_index >= len(WEEKDAYS):
        return None
    return WEEKDAYS[weekday_index]


@dataclass(frozen=True)
class ProviderContext:
    page_title: str
    css_version: str
    script_version: str
    provider: Dict
    prescriptions: List[Dict]
    pending_count: int
    completed_count: int
    all_count: int
    due_today_count: int
    due_this_week_count: int
    due_by_day: Dict[str, List[Dict]]
    active_day: str
    legend: List[Dict]
    today_date: str
    day_dates: Dict[str, str]


def _get_table_columns(cursor, table_name):
    cursor.execute(f"PRAGMA table_info({table_name})")
    return {row[1] for row in cursor.fetchall()}


def _table_exists(cursor, table_name):
    cursor.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
    return cursor.fetchone() is not None


def _derive_status_key(decision_status, pbm_status):
    decision = str(decision_status or '').upper()
    pbm = str(pbm_status or '').upper()

    if pbm == 'APPROVED':
        return 'auto_approve'
    if decision == 'ACCEPTED':
        return 'accept'
    if decision == 'REJECTED':
        return 'daw'
    if decision == 'MODIFIED':
        return 'daw'
    if pbm == 'KEEP_ORIGINAL':
        return 'daw'
    if pbm == 'ESCALATED':
        return 'under_review'
    if pbm == 'IN_PROGRESS':
        return 'in_progress'
    return 'pending'


def _derive_due_date(date_written, status_key):
    if status_key in COMPLETED_STATUSES:
        return '-'

    raw = str(date_written or '').strip()
    try:
        base = datetime.strptime(raw, '%Y-%m-%d').date() if raw else date.today()
    except ValueError:
        base = date.today()

    offset_days = 2
    if status_key == 'under_review':
        offset_days = 3
    elif status_key == 'in_progress':
        offset_days = 1

    return (base + timedelta(days=offset_days)).strftime('%Y-%m-%d')


def _format_currency(value):
    if value in (None, ''):
        return '$0.00'
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        text = str(value).strip()
        return text if text.startswith('$') else f"${text}"


def _build_prescriptions(provider_npi: Optional[str] = None) -> List[Dict]:
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        prescription_columns = _get_table_columns(cursor, 'prescription')

        if {'patient_account_id', 'prod_nm'}.issubset(prescription_columns):
            patient_col = 'p.patient_account_id'
            drug_col = 'p.prod_nm'
            provider_col = 'p.npi_number'
        else:
            patient_col = 'p.member_id'
            drug_col = 'p.medication'
            provider_col = 'p.prescriber_npi'

        join_decision = "LEFT JOIN doctor_decision d ON p.rx_number = d.rx_number" if _table_exists(cursor, 'doctor_decision') else ""
        join_pbm = "LEFT JOIN pbm_response pb ON p.rx_number = pb.rx_number" if _table_exists(cursor, 'pbm_response') else ""
        join_cost = "LEFT JOIN pbm_cost_comparison c ON p.rx_number = c.rx_number" if _table_exists(cursor, 'pbm_cost_comparison') else ""

        where_sql = ""
        params = []
        normalized_npi = str(provider_npi or '').strip()
        if normalized_npi:
            where_sql = f"WHERE {provider_col} = ?"
            params.append(normalized_npi)

        query = f"""
            SELECT
                p.rx_number,
                {patient_col} AS member_id,
                {drug_col} AS medication,
                p.date_written,
                d.status  AS decision_status,
                pb.status AS pbm_status,
                c.insurance_phase,
                c.ytd_oop
            FROM prescription p
            {join_decision}
            {join_pbm}
            {join_cost}
            {where_sql}
            ORDER BY p.date_written DESC, p.rx_number DESC
        """

        cursor.execute(query, params)
        rows = cursor.fetchall()
    except Exception:
        rows = []
    finally:
        conn.close()

    prescriptions = []
    for row in rows:
        status_key = _derive_status_key(row['decision_status'], row['pbm_status'])
        meta = STATUS_META[status_key]
        is_completed = status_key in COMPLETED_STATUSES
        due_date = _derive_due_date(row['date_written'], status_key)

        prescriptions.append({
            'rx_number': str(row['rx_number'] or ''),
            'member_id': str(row['member_id'] or '-'),
            'medication': str(row['medication'] or '-'),
            'date_written': str(row['date_written'] or '-'),
            'insurance_phase': str(row['insurance_phase'] or 'Standard Coverage'),
            'ytd_oop': _format_currency(row['ytd_oop']),
            'due_date': 'DONE' if is_completed else due_date,
            'status_key': status_key,
            'display_status_key': 'completed' if is_completed else 'pending',
            'status_label': meta['label'],
            'status_css': meta['css'],
            'is_completed': is_completed,
            'weekday': _weekday_from_due_date(due_date) if not is_completed else None,
        })

    return prescriptions


def build_provider_page_context(active_day: str | None = None, provider_name: str = 'Provider', provider_npi: Optional[str] = None) -> dict:
    prescriptions = _build_prescriptions()

    pending_count = sum(1 for p in prescriptions if not p['is_completed'])
    completed_count = sum(1 for p in prescriptions if p['is_completed'])

    due_by_day: Dict[str, List[Dict]] = {day: [] for day in WEEKDAYS}
    overdue_count = 0
    
    today = date.today()
    for p in prescriptions:
        if not p['is_completed'] and p['weekday'] in WEEKDAYS:
            due_by_day[p['weekday']].append(p)
            # Count as overdue if due date is before today
            if p['due_date'] and p['due_date'] != '-':
                try:
                    due_date_obj = datetime.strptime(p['due_date'], '%Y-%m-%d').date()
                    if due_date_obj < today:
                        overdue_count += 1
                except ValueError:
                    pass

    current_weekday = WEEKDAYS[date.today().weekday()] if date.today().weekday() < len(WEEKDAYS) else None
    if active_day not in WEEKDAYS:
        active_day = current_weekday or 'Mon'

    due_today_count = len(due_by_day.get(current_weekday, [])) if current_weekday else 0

    # Count only remaining workdays in the current week: today through Friday.
    due_this_week_count = 0
    if today.weekday() <= 4:
        friday_of_this_week = today + timedelta(days=4 - today.weekday())
        for p in prescriptions:
            if p['is_completed']:
                continue
            due_date_raw = p.get('due_date')
            if not due_date_raw or due_date_raw == '-':
                continue
            try:
                due_date_obj = datetime.strptime(due_date_raw, '%Y-%m-%d').date()
            except ValueError:
                continue
            if today <= due_date_obj <= friday_of_this_week:
                due_this_week_count += 1

    legend = [
        {'css': meta['css'], 'label': meta['label'], 'description': meta['legend']}
        for status_key, meta in STATUS_META.items()
        if status_key not in {'pending', 'in_progress', 'rejected'}
    ]

    today = date.today()
    today_date_str = today.strftime('%m/%d/%Y')

    day_dates = {}
    monday_of_this_week = today - timedelta(days=today.weekday())

    for i, day_name in enumerate(WEEKDAYS):
        target_date = monday_of_this_week + timedelta(days=i)
        day_dates[day_name] = target_date.strftime('%m/%d/%Y')

    context = ProviderContext(
        page_title='Prescription Overview | NextGen PBM',
        css_version='20260728-daw-status-fix',
        script_version='20260728-daw-status-fix',
        provider={
            'name': provider_name or 'Provider',
            'npi': provider_npi or '—',
        },
        prescriptions=prescriptions,
        pending_count=pending_count,
        completed_count=completed_count,
        all_count=len(prescriptions),
        due_today_count=due_today_count,
        due_this_week_count=due_this_week_count,
        due_by_day=due_by_day,
        active_day=active_day,
        legend=legend,
        today_date=today_date_str,
        day_dates=day_dates,
    )
    context_dict = asdict(context)
    context_dict['overdue_count'] = overdue_count
    return context_dict
