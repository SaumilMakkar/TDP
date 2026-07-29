import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / 'doctor_decisions.db'
SCHEMA_PATH = BASE_DIR / 'schema.sql'
SEED_PATH = BASE_DIR / 'seed_data.sql'

# Remove old DB so we start fresh
if DB_PATH.exists():
    DB_PATH.unlink()

conn = sqlite3.connect(DB_PATH)
conn.execute("PRAGMA foreign_keys = ON")  # Enable FK enforcement
cursor = conn.cursor()

# Read and execute schema
with open(SCHEMA_PATH, 'r') as f:
    cursor.executescript(f.read())

# Re-enable FK after executescript (it resets pragmas)
conn.execute("PRAGMA foreign_keys = ON")

# Read and execute seed data
with open(SEED_PATH, 'r') as f:
    cursor.executescript(f.read())

conn.commit()

# --- Display Members ---
print("=" * 30)
print("MEMBERS")
print("=" * 30)
cursor.execute("SELECT * FROM patient")
for row in cursor.fetchall():
    print(f"  {row[0]}")

# --- Display Prescribers ---
print(f"\n{'=' * 30}")
print("PRESCRIBERS")
print("=" * 30)
cursor.execute("SELECT * FROM provider")
for row in cursor.fetchall():
    print(f"  {row[0]}")

# --- Display Prescriptions ---
print(f"\n{'=' * 110}")
print("PRESCRIPTIONS")
print("=" * 110)
print(f"{'RX#':<18} {'Member ID':<12} {'Prescriber NPI':<16} {'Medication':<20} {'Strength':<12} {'Freq':<6} {'Days':<6} {'Status':<12} {'Date Written':<12} {'Pharmacy ID'}")
print("-" * 110)
cursor.execute("""
    SELECT rx_number, member_id, prescriber_npi, medication,
           strength, frequency, days_supply, rx_status,
           date_written, pharmacy_id
    FROM prescription
""")
for row in cursor.fetchall():
    print(f"{row[0]:<18} {row[1]:<10} {row[2]:<14} {row[3]:<20} {row[4]:<10} {row[5]:<6} {row[6]:<6} {row[7]:<12} {row[8]:<12} {row[9]}")

# --- Display Doctor Decisions ---
print(f"\n{'=' * 110}")
print("DOCTOR DECISIONS")
print("=" * 110)
print(f"{'ID':<4} {'RX#':<8} {'Status':<12} {'Reason':<55} {'Created At'}")
print("-" * 110)
cursor.execute("SELECT * FROM doctor_decision")
for row in cursor.fetchall():
    reason = row[3] if row[3] else "—"
    print(f"{row[0]:<4} {row[1]:<8} {row[2]:<12} {reason:<55} {row[4]}")

# --- Joined View ---
print(f"\n{'=' * 110}")
print("JOINED VIEW: Prescription + Doctor Decision")
print("=" * 110)
print(f"{'RX#':<8} {'Medication':<16} {'Member ID':<10} {'Decision':<12} {'Reason'}")
print("-" * 110)
cursor.execute("""
    SELECT p.rx_number, p.medication, p.member_id, d.status, d.reason
    FROM prescription p
    JOIN doctor_decision d ON p.rx_number = d.rx_number
""")
for row in cursor.fetchall():
    reason = row[4] if row[4] else "—"
    print(f"{row[0]:<8} {row[1]:<16} {row[2]:<10} {row[3]:<12} {reason}")

# --- RX Status Tracking removed (simplified flow) ---
print(f"\n{'=' * 40}")
print("RX STATUS TRACKING REMOVED")
print("RX status now derived from `prescription`, `pbm_response`, and `doctor_decision`")

# --- Full Joined View (simplified) ---
print(f"\n{'=' * 140}")
print("FULL VIEW: Prescription + PBM Response + Decision")
print("=" * 140)
print(f"{'RX#':<8} {'Medication':<16} {'Member ID':<10} {'PBM Status':<14} {'Decision':<12} {'Savings':<8}")
print("-" * 140)
cursor.execute("""
    SELECT p.rx_number, p.medication, p.member_id,
           pbm.status AS pbm_status, d.status AS decision, pbm.cost_impact
    FROM prescription p
    LEFT JOIN pbm_response pbm ON p.rx_number = pbm.rx_number
    LEFT JOIN doctor_decision d ON p.rx_number = d.rx_number
""")
for row in cursor.fetchall():
    print(f"{row[0]:<8} {row[1]:<16} {row[2]:<10} {row[3] or '-':<14} {row[4] or '-':<12} {row[5] or 0}")

# --- Display PBM Response ---
print(f"\n{'=' * 140}")
print("PBM RESPONSE (with AI Confidence)")
print("=" * 140)
print(f"{'ID':<4} {'RX#':<8} {'Status':<16} {'AI Conf':<9} {'Medication':<22} {'Diagnosis / ICD-10':<25} {'Alt':<22} {'Savings':<9} {'Safety Summary'}")
print("-" * 140)
cursor.execute("SELECT * FROM pbm_response")
for row in cursor.fetchall():
    alt = row[6] if row[6] else "—"
    print(f"{row[0]:<4} {row[1]:<8} {row[2]:<16} {row[3]:<9.2f} {row[4]:<22} {row[5]:<25} {alt:<22} {row[7]:<9.0f} {row[8]}")

# --- Display PBM Cost Comparison ---
print(f"\n{'=' * 120}")
print("PBM COST COMPARISON")
print("=" * 120)
print(f"{'RX#':<18} {'Orig Tier':<12} {'Orig Price':<12} {'Orig Copay':<12} {'Alt Tier':<12} {'Alt Price':<12} {'Alt Copay':<12} {'Savings'}")
print("-" * 120)
cursor.execute("""
    SELECT rx_number, original_tier, original_price, original_copay,
           alternative_tier, alternative_price, alternative_copay, savings
    FROM pbm_cost_comparison
""")
for row in cursor.fetchall():
    print(f"{row[0]:<18} {row[1]:<12} {row[2]:<12.0f} {row[3]:<12.0f} {row[4]:<12} {row[5]:<12.0f} {row[6]:<12.0f} {row[7]:.0f}")

# --- Display PBM Safety ---
print(f"\n{'=' * 100}")
print("PBM SAFETY")
print("=" * 100)
print(f"{'ID':<4} {'Resp#':<7} {'Contraindications':<25} {'Interactions':<25} {'Monitoring'}")
print("-" * 100)
cursor.execute("SELECT * FROM pbm_safety")
for row in cursor.fetchall():
    print(f"{row[0]:<4} {row[1]:<7} {row[2]:<25} {row[3]:<25} {row[4]}")

# --- Display PBM Policy ---
print(f"\n{'=' * 80}")
print("PBM POLICY")
print("=" * 80)
print(f"{'ID':<4} {'Resp#':<7} {'Original Status':<25} {'Alternative Status'}")
print("-" * 80)
cursor.execute("SELECT * FROM pbm_policy")
for row in cursor.fetchall():
    print(f"{row[0]:<4} {row[1]:<7} {row[2]:<25} {row[3]}")

# --- Complete Pipeline View ---
print(f"\n{'=' * 150}")
print("COMPLETE PIPELINE: Prescription -> PBM -> Decision (simplified)")
print("=" * 150)
print(f"{'RX#':<8} {'Medication':<18} {'Member ID':<8} {'PBM Status':<16} {'AI Conf':<9} {'Decision':<12} {'Savings'}")
print("-" * 150)
cursor.execute("""
    SELECT p.rx_number, p.medication, p.member_id,
           pbm.status AS pbm_status, pbm.ai_confidence,
           d.status AS decision, pbm.cost_impact
    FROM prescription p
    LEFT JOIN pbm_response pbm ON p.rx_number = pbm.rx_number
    LEFT JOIN doctor_decision d ON p.rx_number = d.rx_number
""")
for row in cursor.fetchall():
    print(f"{row[0]:<8} {row[1]:<18} {row[2]:<8} {row[3] or '-':<16} {row[4] or 0:<9.2f} {row[5] or '-':<12} {row[6] or 0}")

conn.close()
