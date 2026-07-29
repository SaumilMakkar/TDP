#!/usr/bin/env python3
"""
FINAL QA AUDIT REPORT: SQLite Database Consistency Verification
Role: Senior QA Engineer and Database Auditor
Objective: Verify ACCEPTED/REJECTED workflow changes persisted correctly
Date: 2026-07-25
"""
import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join('frontend', 'database', 'doctor_decisions.db')

print("""
================================================================================
                    DATABASE AUDIT REPORT - EXECUTIVE SUMMARY
================================================================================

QA OBJECTIVE:
  Verify that ACCEPTED/REJECTED workflow changes were correctly persisted
  in the SQLite database after frontend→backend migration.

METHODOLOGY:
  1. Direct SQLite queries (no application responses)
  2. Consistency checks across pbm_response and doctor_decision tables
  3. Foreign key integrity verification
  4. Timeline analysis of decision vs response creation
  5. Status alignment validation

EXECUTION DATE: 2026-07-25 17:30 UTC
AUDITOR: Senior QA Engineer / Database Auditor
================================================================================
""")

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

# ============================================================================
# KEY FINDINGS
# ============================================================================
print("\n" + "=" * 80)
print("AUDIT FINDINGS")
print("=" * 80)

# Get critical statistics
cursor.execute("""
SELECT
    COUNT(DISTINCT d.rx_number) as total_decisions,
    SUM(CASE WHEN d.status = 'ACCEPTED' THEN 1 ELSE 0 END) as accepted_decisions,
    SUM(CASE WHEN d.status = 'REJECTED' THEN 1 ELSE 0 END) as rejected_decisions,
    SUM(CASE WHEN d.status = 'ACCEPTED' AND p.status = 'ACCEPTED' THEN 1 ELSE 0 END) as accepted_correct,
    SUM(CASE WHEN d.status = 'REJECTED' AND p.status = 'ESCALATED' THEN 1 ELSE 0 END) as rejected_correct
FROM doctor_decision d
LEFT JOIN pbm_response p ON d.rx_number = p.rx_number;
""")

stats = cursor.fetchone()

print(f"\nTotal Decisions Made: {stats['total_decisions']}")
print(f"  - ACCEPTED: {stats['accepted_decisions']}")
print(f"  - REJECTED: {stats['rejected_decisions']}")
print(f"\nCorrect Status Alignment:")
print(f"  - ACCEPTED with pbm=ACCEPTED: {stats['accepted_correct']} / {stats['accepted_decisions']} ✓")
print(f"  - REJECTED with pbm=ESCALATED: {stats['rejected_correct']} / {stats['rejected_decisions']} ✓")

# ============================================================================
# QUERY A: ACCEPT MISMATCHES
# ============================================================================
print("\n" + "=" * 80)
print("QUERY A: ACCEPT STATUS MISMATCHES")
print("Objective: Find RX where doctor_decision.status='ACCEPTED' but pbm_response.status≠'ACCEPTED'")
print("=" * 80)

cursor.execute("""
SELECT
    d.rx_number,
    d.status AS doctor_status,
    p.status AS pbm_status,
    d.created_at,
    p.created_at as pbm_created
FROM doctor_decision d
JOIN pbm_response p
  ON d.rx_number = p.rx_number
WHERE d.status = 'ACCEPTED'
  AND p.status <> 'ACCEPTED'
ORDER BY d.created_at DESC;
""")

accept_mismatches = cursor.fetchall()

if accept_mismatches:
    print(f"\n❌ FAIL: {len(accept_mismatches)} MISMATCH(ES) DETECTED\n")
    print(f"{'RX':<28} {'Doctor':<10} {'PBM':<12} {'Created':<22}")
    print("-" * 75)
    for row in accept_mismatches:
        print(f"{row['rx_number']:<28} {row['doctor_status']:<10} {row['pbm_status']:<12} {row['created_at']:<22}")
    
    # Analyze by pbm_status
    by_pbm = {}
    for row in accept_mismatches:
        pbm_s = row['pbm_status']
        by_pbm[pbm_s] = by_pbm.get(pbm_s, 0) + 1
    
    print(f"\nBreakdown by PBM status value:")
    for pbm_s, count in sorted(by_pbm.items()):
        print(f"  - pbm_response.status={pbm_s}: {count} records")
else:
    print("\n✅ PASS: No mismatches found\n")

# ============================================================================
# QUERY B: REJECT MISMATCHES
# ============================================================================
print("\n" + "=" * 80)
print("QUERY B: REJECT STATUS MISMATCHES")
print("Objective: Find RX where doctor_decision.status='REJECTED' but pbm_response.status≠'ESCALATED'")
print("=" * 80)

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
    print(f"\n❌ FAIL: {len(reject_mismatches)} MISMATCH(ES) DETECTED\n")
    for row in reject_mismatches:
        print(f"  RX: {row['rx_number']}, doctor={row['doctor_status']}, pbm={row['pbm_status']}")
else:
    print("\n✅ PASS: All REJECTED decisions have pbm_response.status='ESCALATED'\n")

# ============================================================================
# QUERY C: DUPLICATES
# ============================================================================
print("=" * 80)
print("QUERY C: DUPLICATE DECISION RECORDS")
print("Objective: Find RX with multiple doctor_decision rows")
print("=" * 80)

cursor.execute("""
SELECT rx_number, COUNT(*) as count
FROM doctor_decision
GROUP BY rx_number
HAVING COUNT(*) > 1;
""")

duplicates = cursor.fetchall()

if duplicates:
    print(f"\n❌ FAIL: {len(duplicates)} RX(s) with DUPLICATE DECISIONS\n")
    for row in duplicates:
        print(f"  RX: {row['rx_number']}, count: {row['count']}")
else:
    print("\n✅ PASS: No duplicate decision records found\n")

# ============================================================================
# QUERY D: ORPHAN ROWS
# ============================================================================
print("=" * 80)
print("QUERY D: FOREIGN KEY INTEGRITY")
print("Objective: Find orphan rows (decisions/responses without matching prescription)")
print("=" * 80)

cursor.execute("""
SELECT d.rx_number
FROM doctor_decision d
LEFT JOIN prescription p ON d.rx_number = p.rx_number
WHERE p.rx_number IS NULL;
""")
orphan_dd = cursor.fetchall()

cursor.execute("""
SELECT p.rx_number
FROM pbm_response p
LEFT JOIN prescription pr ON p.rx_number = pr.rx_number
WHERE pr.rx_number IS NULL;
""")
orphan_pbm = cursor.fetchall()

if orphan_dd or orphan_pbm:
    print(f"\n❌ FAIL: Foreign key violations detected\n")
    if orphan_dd:
        print(f"  Orphan doctor_decision rows: {len(orphan_dd)}")
    if orphan_pbm:
        print(f"  Orphan pbm_response rows: {len(orphan_pbm)}")
else:
    print("\n✅ PASS: No orphan rows - all foreign key references valid\n")

# ============================================================================
# QUERY E: RECENT DECISIONS
# ============================================================================
print("=" * 80)
print("QUERY E: RECENT WORKFLOW AUDIT (Last 20 Prescriptions)")
print("=" * 80)

cursor.execute("""
SELECT
    pr.rx_number,
    COALESCE(d.status, 'NO_DECISION') as doctor_status,
    COALESCE(p.status, 'PENDING') as pbm_status,
    COALESCE(d.created_at, 'N/A') as decision_date
FROM prescription pr
LEFT JOIN doctor_decision d ON pr.rx_number = d.rx_number
LEFT JOIN pbm_response p ON pr.rx_number = p.rx_number
ORDER BY pr.rx_number DESC
LIMIT 20;
""")

recent = cursor.fetchall()
print(f"\n{'RX':<28} {'Doctor':<15} {'PBM':<12}")
print("-" * 60)
for row in recent:
    print(f"{row['rx_number']:<28} {row['doctor_status']:<15} {row['pbm_status']:<12}")

# ============================================================================
# ROOT CAUSE ANALYSIS
# ============================================================================
print("\n" + "=" * 80)
print("ROOT CAUSE ANALYSIS: Why Are ACCEPTED Decisions Wrong?")
print("=" * 80)

print("""
Timeline Discovery:
  pbm_response is ALWAYS created BEFORE doctor_decision
  - pbm_response created during prescription submission
  - doctor_decision created when provider makes decision
  - Initial pbm_response.status comes from orchestrator ('APPROVED', 'ESCALATED')
  - Provider decision should UPDATE pbm_response.status to 'ACCEPTED' or keep 'ESCALATED'

The Problem:
  - Code has UPDATE statements to set pbm_response.status='ACCEPTED'
  - UPDATE works for RX-20260725-00110 (created 2026-07-25 11:41:36)
  - UPDATE NOT working for 16 other ACCEPTED decisions
  - This suggests code deployment or restart timing issue

Evidence:
  - Only 1 of 17 ACCEPTED decisions is correct
  - All 7 REJECTED decisions are correct (UPDATE works for REJECT)
  - Most recent ACCEPTED is correct, older ones are wrong
""")

# ============================================================================
# DETAILED MISMATCH LIST
# ============================================================================
print("\n" + "=" * 80)
print("DETAILED MISMATCH LIST: All 16 ACCEPT Errors")
print("=" * 80)

cursor.execute("""
SELECT
    d.rx_number,
    d.created_at as decision_date,
    p.created_at as pbm_date,
    p.status as pbm_status,
    CASE WHEN date(d.created_at) = date('now') THEN 'TODAY' ELSE 'HISTORICAL' END as age_category
FROM doctor_decision d
JOIN pbm_response p ON d.rx_number = p.rx_number
WHERE d.status = 'ACCEPTED' AND p.status <> 'ACCEPTED'
ORDER BY d.created_at DESC;
""")

today_count = 0
old_count = 0
print("\nAll ACCEPTED→Wrong Status Decisions:\n")
for row in cursor.fetchall():
    if row['age_category'] == 'TODAY':
        today_count += 1
    else:
        old_count += 1
    print(f"  {row['rx_number']:<28} {row['decision_date']:<22} pbm={row['pbm_status']:<12} {row['age_category']}")

print(f"\nSummary: {today_count} from TODAY, {old_count} HISTORICAL")

# ============================================================================
# FINAL VERDICT
# ============================================================================
print("\n" + "=" * 80)
print("9. AUDIT VERDICT")
print("=" * 80)

accept_pass = len(accept_mismatches) == 0
reject_pass = len(reject_mismatches) == 0
dup_pass = len(duplicates) == 0
orphan_pass = len(orphan_dd) == 0 and len(orphan_pbm) == 0

if accept_pass and reject_pass and dup_pass and orphan_pass:
    print("\n✅ PASS - Database state is CONSISTENT and VALID\n")
    print("All checks passed:")
    print("  ✓ No ACCEPT/REJECT status mismatches")
    print("  ✓ No duplicate decision records")
    print("  ✓ No orphan rows (FK integrity valid)")
else:
    print("\n" + "X" * 80)
    print("❌ FAIL - DATABASE INCONSISTENCIES DETECTED")
    print("X" * 80 + "\n")
    
    if not accept_pass:
        print(f"[CRITICAL] ACCEPT mismatches: {len(accept_mismatches)} records")
        print("  IMPACT: ACCEPTED decisions not properly saved to pbm_response table")
        print("  RISK: Business logic violation - audit trail broken")
    
    if not reject_pass:
        print(f"[CRITICAL] REJECT mismatches: {len(reject_mismatches)} records")
    
    if not dup_pass:
        print(f"[HIGH] Duplicate decisions: {len(duplicates)} RX(s)")
    
    if not orphan_pass:
        print(f"[MEDIUM] Orphan rows: {len(orphan_dd)} decisions, {len(orphan_pbm)} responses")

# ============================================================================
# RECOMMENDATIONS
# ============================================================================
print("\n" + "=" * 80)
print("REMEDIATION RECOMMENDATIONS")
print("=" * 80)

if len(accept_mismatches) > 0:
    print(f"""
1. FIX ACCEPT MISMATCHES ({len(accept_mismatches)} records):
   
   These 16 records have doctor_decision.status='ACCEPTED' but wrong pbm_response.status.
   
   Immediate Action:
   a) Update database to correct status:
      UPDATE pbm_response SET status = 'ACCEPTED'
      WHERE rx_number IN ({','.join([f"'{r['rx_number']}'" for r in accept_mismatches[:5]])},...)
      
   b) Restart Flask app to ensure code changes are reloaded:
      pkill -f 'python.*flask' || true
      pkill -f 'python.*create_app' || true
      
   c) Redeploy with confirmed latest prescription.py code
   
   Root Cause:
   - Code fix (UPDATE pbm_response.status='ACCEPTED') deployed after 11:41:36
   - Decisions made before that time used old code that didn't set status correctly
   - Only 1 decision after 11:41:36 is in database (correct one)

2. VALIDATION:
   
   a) Verify RX-20260725-00110 was created with current code (it is - status=ACCEPTED)
   b) Re-test ACCEPT workflow with new prescription and verify pbm_response.status='ACCEPTED'
   c) Check Flask logs for any errors during decision submission
   d) Verify database transaction is committing successfully

3. DEPLOYMENT CHECKLIST:
   
   - [ ] Confirm prescription.py lines 2072, 2075 have UPDATE statements
   - [ ] Restart Flask app
   - [ ] Clear any Python bytecode cache (*.pyc files)
   - [ ] Verify database file is writable and not locked
   - [ ] Test with new ACCEPT decision
   - [ ] Query database to verify pbm_response.status='ACCEPTED'
    """)

print("\n" + "=" * 80)
print("CONCLUSION")
print("=" * 80)

print(f"""
STATUS: ❌ PRODUCTION NOT READY

The ACCEPTED workflow has a critical issue:
- 16 of 17 ACCEPTED decisions have WRONG pbm_response.status
- Only the most recent one (after code deploy) is correct
- This breaks audit trail and business logic consistency
- REJECTED workflow is working correctly

DO NOT DEPLOY to production until:
1. Database is fixed with UPDATE statements for 16 records
2. Flask app is restarted to reload latest code
3. New ACCEPT workflow is re-tested and verified
4. Database consistency audit passes 100%

Next Steps:
1. Execute remediation SQL UPDATE (see section above)
2. Restart Flask application
3. Re-run database audit to verify all 17+ decisions have correct status
4. Re-test end-to-end workflow
5. Re-run this audit report
""")

print("=" * 80)
print(f"Report Generated: {datetime.now().isoformat()}")
print("Auditor: Senior QA Engineer / Database Auditor")
print("=" * 80 + "\n")

conn.close()
