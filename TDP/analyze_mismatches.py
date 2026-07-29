#!/usr/bin/env python3
"""
Detailed analysis of ACCEPT mismatches by timestamp
"""
import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join('frontend', 'database', 'doctor_decisions.db')
conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

print("=" * 90)
print("DETAILED MISMATCH ANALYSIS: ACCEPTED Decisions with Wrong PBM Status")
print("=" * 90)

# Get all ACCEPTED mismatches with timestamps
cursor.execute("""
SELECT
    d.rx_number,
    d.status as doctor_status,
    d.created_at as decision_created,
    p.status as pbm_status,
    p.created_at as pbm_created
FROM doctor_decision d
JOIN pbm_response p ON d.rx_number = p.rx_number
WHERE d.status = 'ACCEPTED'
  AND p.status <> 'ACCEPTED'
ORDER BY d.created_at DESC;
""")

rows = cursor.fetchall()
print(f"\nFound {len(rows)} ACCEPT mismatches:\n")
print(f"{'RX':<28} {'Doctor Created':<22} {'PBM Status':<12} {'PBM Created':<22} {'Age (hours)':<12}")
print("-" * 100)

now = datetime.now()
for row in rows:
    rx = row['rx_number']
    doc_created = row['decision_created']
    pbm_status = row['pbm_status']
    pbm_created = row['pbm_created']
    
    # Calculate age in hours
    if doc_created:
        try:
            doc_dt = datetime.fromisoformat(doc_created)
            age_hours = (now - doc_dt).total_seconds() / 3600
        except:
            age_hours = None
    else:
        age_hours = None
    
    age_str = f"{age_hours:.1f}h" if age_hours is not None else "N/A"
    
    print(f"{rx:<28} {doc_created:<22} {pbm_status:<12} {pbm_created:<22} {age_str:<12}")

print("\n" + "=" * 90)
print("DETAILED ANALYSIS")
print("=" * 90)

# Analyze by PBM status value
cursor.execute("""
SELECT
    p.status as pbm_status,
    COUNT(*) as mismatch_count
FROM doctor_decision d
JOIN pbm_response p ON d.rx_number = p.rx_number
WHERE d.status = 'ACCEPTED'
  AND p.status <> 'ACCEPTED'
GROUP BY p.status;
""")

print("\nMismatches grouped by PBM status:")
for row in cursor.fetchall():
    print(f"  {row['pbm_status']}: {row['mismatch_count']} records")

# Check if they're all from before a specific time
cursor.execute("""
SELECT
    COUNT(CASE WHEN date(d.created_at) = date('now') THEN 1 END) as today_count,
    COUNT(CASE WHEN date(d.created_at) < date('now') THEN 1 END) as old_count
FROM doctor_decision d
JOIN pbm_response p ON d.rx_number = p.rx_number
WHERE d.status = 'ACCEPTED'
  AND p.status <> 'ACCEPTED';
""")

summary = cursor.fetchone()
print(f"\nMismatch timeline:")
print(f"  From today: {summary['today_count']}")
print(f"  From before today: {summary['old_count']}")

print("\n" + "=" * 90)
print("INVESTIGATING: Are new ACCEPTED decisions now being set correctly?")
print("=" * 90)

# Get the most recent ACCEPTED decision that IS correct
cursor.execute("""
SELECT
    d.rx_number,
    d.created_at,
    p.status
FROM doctor_decision d
JOIN pbm_response p ON d.rx_number = p.rx_number
WHERE d.status = 'ACCEPTED'
  AND p.status = 'ACCEPTED'
ORDER BY d.created_at DESC
LIMIT 1;
""")

correct = cursor.fetchone()
if correct:
    print(f"\nMost recent CORRECT ACCEPTED decision:")
    print(f"  RX: {correct['rx_number']}")
    print(f"  Created: {correct['created_at']}")
    print(f"  PBM Status: {correct['pbm_status']}")

# Get the most recent ACCEPTED decision that is WRONG
cursor.execute("""
SELECT
    d.rx_number,
    d.created_at,
    p.status
FROM doctor_decision d
JOIN pbm_response p ON d.rx_number = p.rx_number
WHERE d.status = 'ACCEPTED'
  AND p.status <> 'ACCEPTED'
ORDER BY d.created_at DESC
LIMIT 1;
""")

wrong = cursor.fetchone()
if wrong:
    print(f"\nMost recent INCORRECT ACCEPTED decision:")
    print(f"  RX: {wrong['rx_number']}")
    print(f"  Created: {wrong['created_at']}")
    print(f"  PBM Status: {wrong['pbm_status']}")

print("\n" + "=" * 90)
conn.close()
