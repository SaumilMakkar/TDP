#!/usr/bin/env python3
"""
Check if recent ACCEPTED decisions are now being saved correctly
"""
import sqlite3
import os
from datetime import datetime, timedelta

DB_PATH = os.path.join('frontend', 'database', 'doctor_decisions.db')
conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

print("=" * 90)
print("ROOT CAUSE ANALYSIS: When Did ACCEPTED Decisions Break?")
print("=" * 90)

# Get ALL ACCEPTED decisions (correct and incorrect)
cursor.execute("""
SELECT
    d.rx_number,
    d.created_at,
    d.status as doctor_status,
    p.status as pbm_status,
    CASE WHEN d.status = 'ACCEPTED' AND p.status = 'ACCEPTED' THEN 'CORRECT' ELSE 'WRONG' END as alignment
FROM doctor_decision d
JOIN pbm_response p ON d.rx_number = p.rx_number
WHERE d.status = 'ACCEPTED'
ORDER BY d.created_at DESC;
""")

all_accepted = cursor.fetchall()
print(f"\nAll ACCEPTED decisions (correct and wrong):\n")
print(f"{'RX':<28} {'Created':<22} {'Doctor':<10} {'PBM':<12} {'Status':<10}")
print("-" * 85)

for row in all_accepted:
    print(f"{row['rx_number']:<28} {row['created_at']:<22} {row['doctor_status']:<10} {row['pbm_status']:<12} {row['alignment']:<10}")

# Summary
correct = len([r for r in all_accepted if r['alignment'] == 'CORRECT'])
wrong = len([r for r in all_accepted if r['alignment'] == 'WRONG'])

print(f"\n{'=' * 90}")
print(f"SUMMARY: {correct} CORRECT, {wrong} WRONG out of {len(all_accepted)} ACCEPTED decisions")
print(f"{'=' * 90}")

# Check the last 3 decisions created
print(f"\nMost Recent 3 ACCEPTED Decisions:")
for i, row in enumerate(all_accepted[:3], 1):
    alignment = "✓" if row['alignment'] == 'CORRECT' else "✗"
    print(f"  {i}. {row['rx_number']}: {row['created_at']} - doctor={row['doctor_status']}, pbm={row['pbm_status']} {alignment}")

conn.close()
