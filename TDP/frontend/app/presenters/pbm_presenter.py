"""Builds the data context for the PBM Overview page.

Mirrors the provider overview layout — identical UI, PBM-scoped data.
"""
from datetime import date
from typing import List, Dict

from app.presenters.provider_presenter import (
    STATUS_META, WEEKDAYS, _build_prescriptions
)


def build_pbm_page_context(active_day=None, pbm_name='PBM Admin', pbm_id='PBM-001'):
    prescriptions = _build_prescriptions()

    pending_count = sum(1 for p in prescriptions if not p['is_completed'])
    completed_count = sum(1 for p in prescriptions if p['is_completed'])
    auto_approve_count = sum(1 for p in prescriptions if p['status_key'] == 'auto_approve')

    due_by_day = {day: [] for day in WEEKDAYS}
    overdue_count = 0
    
    today = date.today()
    for p in prescriptions:
        if not p['is_completed'] and p['weekday'] in WEEKDAYS:
            due_by_day[p['weekday']].append(p)
            # Count as overdue if due date is before today
            if p['due_date'] and p['due_date'] != '-':
                try:
                    due_date_obj = __import__('datetime').datetime.strptime(p['due_date'], '%Y-%m-%d').date()
                    if due_date_obj < today:
                        overdue_count += 1
                except ValueError:
                    pass

    today_idx = date.today().weekday()
    current_weekday = WEEKDAYS[today_idx] if today_idx < len(WEEKDAYS) else None
    if active_day not in WEEKDAYS:
        active_day = current_weekday or 'Mon'

    due_today_count = len(due_by_day.get(current_weekday, [])) if current_weekday else 0

    # Count only remaining workdays in the current week: today through Friday.
    due_this_week_count = 0
    if today.weekday() <= 4:
        friday_of_this_week = today + __import__('datetime').timedelta(days=4 - today.weekday())
        for p in prescriptions:
            if p['is_completed']:
                continue
            due_date_raw = p.get('due_date')
            if not due_date_raw or due_date_raw == '-':
                continue
            try:
                due_date_obj = __import__('datetime').datetime.strptime(due_date_raw, '%Y-%m-%d').date()
            except ValueError:
                continue
            if today <= due_date_obj <= friday_of_this_week:
                due_this_week_count += 1

    legend = [
        {'css': meta['css'], 'label': meta['label'], 'description': meta['legend']}
        for status_key, meta in STATUS_META.items()
        if status_key not in {'pending', 'in_progress', 'rejected'}
    ]

    # Calculate dates for today and each weekday
    from datetime import timedelta
    today = date.today()
    today_date_str = today.strftime('%m/%d/%Y')
    
    # Calculate dates for Mon-Fri of current week
    # today.weekday() returns 0=Monday, 6=Sunday
    day_dates = {}
    today_weekday = today.weekday()  # 0=Monday, ..., 4=Friday
    
    # Find Monday of this week
    days_to_monday = today_weekday
    monday_of_this_week = today - timedelta(days=days_to_monday)
    
    for i, day_name in enumerate(WEEKDAYS):
        # i is 0-4 for Mon-Fri
        target_date = monday_of_this_week + timedelta(days=i)
        day_dates[day_name] = target_date.strftime('%m/%d/%Y')

    return {
        'page_title': 'Prescription Overview | NextGen PBM',
        'css_version': '20260728-daw-status-fix',
        'script_version': '20260728-daw-status-fix',
        'pbm_user': {'name': pbm_name or 'PBM Admin', 'id': pbm_id or 'PBM-001'},
        'prescriptions': prescriptions,
        'pending_count': pending_count,
        'completed_count': completed_count,
        'auto_approve_count': auto_approve_count,
        'all_count': len(prescriptions),
        'due_today_count': due_today_count,
        'due_this_week_count': due_this_week_count,
        'due_by_day': due_by_day,
        'active_day': active_day,
        'legend': legend,
        'today_date': today_date_str,
        'day_dates': day_dates,
        'overdue_count': overdue_count,
    }
