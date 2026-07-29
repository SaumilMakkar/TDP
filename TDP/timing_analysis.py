#!/usr/bin/env python3
"""
Analyze relationship between pbm_response creation and doctor_decision creation
"""
import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join('frontend', 'database', 'doctor_decisions.db')
conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

print("=" * 100)
print("INVESTIGATING: Timing of pbm_response vs doctor_decision Creation")
print("=" * 100)

# For all ACCEPTED decisions, check if pbm_response was created BEFORE or AFTER
cursor.execute("""
SELECT
    d.rx_number,
    d.created_at as decision_created,
    p.created_at as pbm_created,
    d.status as doctor_status,
    p.status as pbm_status,
    CASE 
        WHEN p.created_at < d.created_at THEN 'PBM FIRST (pre-decision)'
        WHEN p.created_at = d.created_at THEN 'SIMULTANEOUS'
        ELSE 'DECISION FIRST'
    END as timing,
    CASE 
        WHEN d.status = 'ACCEPTED' AND p.status = 'ACCEPTED' THEN '✓ CORRECT'
        ELSE '✗ WRONG'
    END as alignment
FROM doctor_decision d
JOIN pbm_response p ON d.rx_number = p.rx_number
WHERE d.status = 'ACCEPTED'
ORDER BY d.created_at DESC;
""")

rows = cursor.fetchall()
print(f"\nAll ACCEPTED decisions with timing analysis:\n")
print(f"{'RX':<28} {'Timing':<25} {'PBM Status':<12} {'Alignment':<12}")
print("-" * 80)

for row in rows:
    print(f"{row['rx_number']:<28} {row['timing']:<25} {row['pbm_status']:<12} {row['alignment']:<12}")

# Analyze pattern
print("\n" + "=" * 100)
print("PATTERN ANALYSIS")
print("=" * 100)

pbm_first = len([r for r in rows if 'PBM FIRST' in r['timing']])
simultaneous = len([r for r in rows if 'SIMULTANEOUS' in r['timing']])
decision_first = len([r for r in rows if 'DECISION FIRST' in r['timing']])

print(f"\nTiming patterns:")
print(f"  PBM created BEFORE decision: {pbm_first}")
print(f"  PBM created SIMULTANEOUS with decision: {simultaneous}")
print(f"  PBM created AFTER decision: {decision_first}")

# Check recent ones specifically
print(f"\nLast 3 ACCEPTED decisions:")
for i, row in enumerate(rows[:3], 1):
    print(f"  {i}. RX {row['rx_number']}")
    print(f"     Decision: {row['decision_created']}")
    print(f"     PBM:      {row['pbm_created']}")
    print(f"     Timing:   {row['timing']}")
    print(f"     Status:   {row['alignment']}")

conn.close()
