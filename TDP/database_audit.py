#!/usr/bin/env python3
"""
QA/Database Auditor: SQLite Workflow Consistency Verification
Objective: Verify ACCEPTED/REJECTED workflow changes persisted correctly
"""
import sqlite3
import json
from datetime import datetime
import os

DB_PATH = os.path.join('frontend', 'database', 'doctor_decisions.db')

# Connect to database
conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

sep = "=" * 80

print(sep)
print("SQLITE DATABASE AUDIT REPORT")
print(sep)
print(f"\nDatabase: {DB_PATH}")
print(f"Timestamp: {datetime.now().isoformat()}")

# ============================================================================
# STEP 1: Database Schema Observations
# ============================================================================
print("\n" + sep)
print("1. DATABASE SCHEMA OBSERVATIONS")
print(sep)

# List all tables
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;")
tables = cursor.fetchall()
print(f"\nTables found ({len(tables)}):")
for table in tables:
    cursor.execute(f"PRAGMA table_info({table['name']});")
    cols = cursor.fetchall()
    print(f"  TABLE: {table['name']} ({len(cols)} columns)")

# ============================================================================
# STEP 2: Query A - ACCEPT Mismatches
# ============================================================================
print("\n" + sep)
print("2. QUERY A: ACCEPT MISMATCHES")
print("Objective: Find RX where doctor_decision.status=ACCEPTED but pbm_response.status!=ACCEPTED")
print(sep)

cursor.execute("""
SELECT
    d.rx_number,
    d.status AS doctor_status,
    p.status AS pbm_status
FROM doctor_decision d
JOIN pbm_response p
  ON d.rx_number = p.rx_number
WHERE d.status = 'ACCEPTED'
  AND p.status <> 'ACCEPTED';
""")
accept_mismatches = cursor.fetchall()
if accept_mismatches:
    print(f"\nFAIL: {len(accept_mismatches)} MISMATCH(ES) FOUND")
    for row in accept_mismatches:
        print(f"  RX: {row['rx_number']}, doctor={row['doctor_status']}, pbm={row['pbm_status']}")
else:
    print("\nPASS: All ACCEPTED decisions have pbm_response.status = ACCEPTED")

# ============================================================================
# STEP 3: Query B - REJECT Mismatches
# ============================================================================
print("\n" + sep)
print("3. QUERY B: REJECT MISMATCHES")
print("Objective: Find RX where doctor_decision.status=REJECTED but pbm_response.status!=ESCALATED")
print(sep)

cursor.execute("""
SELECT
    d.rx_number,
    d.status AS doctor_status,
    p.status AS pbm_status
FROM doctor_decision d
JOIN pbm_response p
  ON d.rx_number = p.rx_number
WHERE d.status = 'REJECTED'
  AND p.status <> 'ESCALATED';
""")
reject_mismatches = cursor.fetchall()
if reject_mismatches:
    print(f"\nFAIL: {len(reject_mismatches)} MISMATCH(ES) FOUND")
    for row in reject_mismatches:
        print(f"  RX: {row['rx_number']}, doctor={row['doctor_status']}, pbm={row['pbm_status']}")
else:
    print("\nPASS: All REJECTED decisions have pbm_response.status = ESCALATED")

# ============================================================================
# STEP 4: Query C - Duplicate Decision Records
# ============================================================================
print("\n" + sep)
print("4. QUERY C: DUPLICATE DECISION RECORDS")
print("Objective: Find RX with multiple doctor_decision rows")
print(sep)

cursor.execute("""
SELECT
    rx_number,
    COUNT(*) as decision_count
FROM doctor_decision
GROUP BY rx_number
HAVING COUNT(*) > 1;
""")
duplicates = cursor.fetchall()
if duplicates:
    print(f"\nFAIL: {len(duplicates)} RX(s) with MULTIPLE DECISIONS")
    for row in duplicates:
        print(f"  RX: {row['rx_number']}, count: {row['decision_count']}")
        # Show details
        cursor.execute("""
            SELECT id, status, provider_npi, created_at
            FROM doctor_decision
            WHERE rx_number = ?
            ORDER BY created_at DESC
        """, (row['rx_number'],))
        for detail in cursor.fetchall():
            print(f"    - ID: {detail['id']}, status: {detail['status']}, provider: {detail['provider_npi']}, created: {detail['created_at']}")
else:
    print("\nPASS: Each RX has exactly one doctor_decision record")

# ============================================================================
# STEP 5: Query D - Orphan Rows
# ============================================================================
print("\n" + sep)
print("5. QUERY D: ORPHAN ROWS")
print("Objective: Find FK violations - decisions/responses without matching prescription")
print(sep)

cursor.execute("""
SELECT d.rx_number
FROM doctor_decision d
LEFT JOIN prescription p
  ON d.rx_number = p.rx_number
WHERE p.rx_number IS NULL;
""")
orphan_decisions = cursor.fetchall()

cursor.execute("""
SELECT p.rx_number
FROM pbm_response p
LEFT JOIN prescription pr
  ON p.rx_number = pr.rx_number
WHERE pr.rx_number IS NULL;
""")
orphan_pbm = cursor.fetchall()

if orphan_decisions or orphan_pbm:
    print(f"\nFAIL: Orphan rows detected")
    if orphan_decisions:
        print(f"  Orphan doctor_decision: {len(orphan_decisions)}")
        for row in orphan_decisions:
            print(f"    - rx_number: {row['rx_number']}")
    if orphan_pbm:
        print(f"  Orphan pbm_response: {len(orphan_pbm)}")
        for row in orphan_pbm:
            print(f"    - rx_number: {row['rx_number']}")
else:
    print("\nPASS: No orphan rows - all FK references valid")

# ============================================================================
# STEP 6: Recent Workflow Audit
# ============================================================================
print("\n" + sep)
print("6. RECENT PRESCRIPTIONS (Last 20)")
print("Objective: Show rx_number, doctor status, pbm status, provider for recent RXs")
print(sep)

cursor.execute("""
SELECT
    pr.rx_number,
    COALESCE(d.status, 'NO_DECISION') as doctor_status,
    COALESCE(d.created_at, 'N/A') as decision_created,
    COALESCE(p.status, 'PENDING') as pbm_status,
    COALESCE(p.created_at, 'N/A') as pbm_created
FROM prescription pr
LEFT JOIN doctor_decision d ON pr.rx_number = d.rx_number
LEFT JOIN pbm_response p ON pr.rx_number = p.rx_number
ORDER BY pr.rx_number DESC
LIMIT 20;
""")

recent = cursor.fetchall()
print(f"\nTotal: {len(recent)} recent prescriptions\n")
print(f"{'RX':<28} {'Doctor':<15} {'PBM':<12} {'Decision Created':<20}")
print("-" * 80)
for row in recent:
    rx = row['rx_number']
    doc = row['doctor_status']
    pbm = row['pbm_status']
    created = row['decision_created'][:10] if row['decision_created'] and row['decision_created'] != 'N/A' else 'No Decision'
    print(f"{rx:<28} {doc:<15} {pbm:<12} {created:<20}")

# ============================================================================
# STEP 7: Database Statistics
# ============================================================================
print("\n" + sep)
print("7. DATABASE STATISTICS")
print(sep)

cursor.execute("SELECT COUNT(*) as count FROM prescription;")
rx_total = cursor.fetchone()['count']

cursor.execute("SELECT COUNT(*) as count FROM doctor_decision;")
dd_total = cursor.fetchone()['count']

cursor.execute("SELECT COUNT(*) as count FROM pbm_response;")
pbm_total = cursor.fetchone()['count']

cursor.execute("""
SELECT
    SUM(CASE WHEN status = 'ACCEPTED' THEN 1 ELSE 0 END) as accepted,
    SUM(CASE WHEN status = 'REJECTED' THEN 1 ELSE 0 END) as rejected
FROM doctor_decision;
""")
dd_summary = cursor.fetchone()

cursor.execute("""
SELECT
    SUM(CASE WHEN status = 'ACCEPTED' THEN 1 ELSE 0 END) as accepted,
    SUM(CASE WHEN status = 'ESCALATED' THEN 1 ELSE 0 END) as escalated,
    SUM(CASE WHEN status = 'APPROVED' THEN 1 ELSE 0 END) as approved,
    SUM(CASE WHEN status = 'PENDING' THEN 1 ELSE 0 END) as pending
FROM pbm_response;
""")
pbm_summary = cursor.fetchone()

print(f"\nPrescriptions Total: {rx_total}")
print(f"\nDoctor Decisions: {dd_total}")
print(f"  - ACCEPTED: {dd_summary['accepted'] or 0}")
print(f"  - REJECTED: {dd_summary['rejected'] or 0}")
print(f"\nPBM Responses: {pbm_total}")
print(f"  - ACCEPTED: {pbm_summary['accepted'] or 0}")
print(f"  - ESCALATED: {pbm_summary['escalated'] or 0}")
print(f"  - APPROVED: {pbm_summary['approved'] or 0}")
print(f"  - PENDING: {pbm_summary['pending'] or 0}")

# ============================================================================
# STEP 8: Status Alignment Check
# ============================================================================
print("\n" + sep)
print("8. STATUS ALIGNMENT CHECK")
print("Verify doctor_decision.status aligns with pbm_response.status")
print(sep)

cursor.execute("""
SELECT
    d.rx_number,
    d.status as doc_status,
    p.status as pbm_status
FROM doctor_decision d
JOIN pbm_response p ON d.rx_number = p.rx_number
ORDER BY d.rx_number;
""")

aligned_rows = cursor.fetchall()
alignment_pass = True
accept_count = 0
reject_count = 0
mismatch_list = []

for row in aligned_rows:
    if row['doc_status'] == 'ACCEPTED':
        if row['pbm_status'] != 'ACCEPTED':
            alignment_pass = False
            mismatch_list.append((row['rx_number'], row['doc_status'], row['pbm_status']))
        else:
            accept_count += 1
    elif row['doc_status'] == 'REJECTED':
        if row['pbm_status'] != 'ESCALATED':
            alignment_pass = False
            mismatch_list.append((row['rx_number'], row['doc_status'], row['pbm_status']))
        else:
            reject_count += 1

if alignment_pass:
    print(f"\nPASS: Status alignment verified")
    print(f"  - {accept_count} ACCEPTED: doctor=ACCEPTED, pbm=ACCEPTED")
    print(f"  - {reject_count} REJECTED: doctor=REJECTED, pbm=ESCALATED")
else:
    print(f"\nFAIL: {len(mismatch_list)} status alignment issues found")
    for rx, doc, pbm in mismatch_list:
        print(f"  - RX: {rx}, doctor={doc}, pbm={pbm}")

# ============================================================================
# FINAL VERDICT
# ============================================================================
print("\n" + sep)
print("9. FINAL AUDIT VERDICT")
print(sep)

all_pass = (
    len(accept_mismatches) == 0 and
    len(reject_mismatches) == 0 and
    len(duplicates) == 0 and
    len(orphan_decisions) == 0 and
    len(orphan_pbm) == 0 and
    alignment_pass
)

if all_pass:
    print("\nVERDICT: PASS - Database state is CONSISTENT and VALID")
    print("\nAll audit checks passed:")
    print("  [✓] No ACCEPT/REJECT status mismatches")
    print("  [✓] No duplicate decision records")
    print("  [✓] No orphan rows (FK integrity valid)")
    print("  [✓] Status alignment: doctor_decision.status matches pbm_response.status")
    print("  [✓] Workflow changes correctly persisted to database")
    print("\nConclusion: ACCEPTED/REJECTED workflow changes have been successfully")
    print("and consistently applied throughout the database.")
else:
    print("\nVERDICT: FAIL - Database INCONSISTENCIES DETECTED")
    print("\nFailed checks:")
    if accept_mismatches:
        print(f"  [✗] ACCEPT mismatches: {len(accept_mismatches)}")
    if reject_mismatches:
        print(f"  [✗] REJECT mismatches: {len(reject_mismatches)}")
    if duplicates:
        print(f"  [✗] Duplicate decisions: {len(duplicates)}")
    if orphan_decisions:
        print(f"  [✗] Orphan decisions: {len(orphan_decisions)}")
    if orphan_pbm:
        print(f"  [✗] Orphan PBM: {len(orphan_pbm)}")
    if not alignment_pass:
        print(f"  [✗] Status alignment issues: {len(mismatch_list)}")

print("\n" + sep + "\n")

conn.close()
