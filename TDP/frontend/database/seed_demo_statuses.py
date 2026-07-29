import sqlite3

DB_PATH = r"frontend/database/doctor_decisions.db"
RXS = [
    "RX-20260722-90001",
    "RX-20260722-90002",
    "RX-20260722-90003",
    "RX-20260722-90004",
]

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

for table in [
    "doctor_decision_reason",
    "doctor_decision",
    "pbm_response",
    "pbm_cost_comparison",
    "prescription",
]:
    cursor.executemany(f"DELETE FROM {table} WHERE rx_number = ?", [(rx,) for rx in RXS])

prescriptions = [
    ("RX-20260722-90001", "P901", "1234567890", "Rosuvastatin", "387458", "10 mg", "QD", 30, "E78.5", "Submitted", "2026-07-22", "PHARMA001"),
    ("RX-20260722-90002", "P902", "1234567890", "Levothyroxine", "966248", "50 mcg", "QD", 30, "E03.9", "Submitted", "2026-07-22", "PHARMA001"),
    ("RX-20260722-90003", "P903", "1234567890", "Losartan", "979482", "50 mg", "QD", 30, "I10", "Submitted", "2026-07-22", "PHARMA001"),
    ("RX-20260722-90004", "P904", "1234567890", "Metformin ER", "861007", "500 mg", "BID", 90, "E11.9", "Submitted", "2026-07-22", "PHARMA001"),
]

cursor.executemany(
    """
    INSERT INTO prescription (
        rx_number, member_id, prescriber_npi, medication, medication_rxcui,
        strength, frequency, days_supply, diagnosis_icd10, rx_status,
        date_written, pharmacy_id
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    prescriptions,
)

pbm_rows = [
    ("RX-20260722-90001", "ESCALATED", 0.74, "Rosuvastatin 10mg", "Hyperlipidemia", "Atorvastatin 20mg", 14.5, "Needs clinician choice among alternatives.", "Step therapy requires review."),
    ("RX-20260722-90002", "ESCALATED", 0.79, "Levothyroxine 50mcg", "Hypothyroidism", None, 0.0, "Alternative options did not satisfy safety/policy checks.", "Original medication retained after review."),
    ("RX-20260722-90003", "ESCALATED", 0.86, "Losartan 50mg", "Hypertension", "Valsartan 80mg", 18.0, "Clinician reviewed and accepted alternative.", "Escalated for review then accepted."),
    ("RX-20260722-90004", "APPROVED", 0.96, "Metformin ER 500mg", "Type 2 diabetes mellitus", None, 0.0, "Auto-approved by AI threshold.", "Formulary preferred, no edits required."),
]

cursor.executemany(
    """
    INSERT INTO pbm_response (
        rx_number, status, ai_confidence, prescribed_drug, diagnosis,
        recommended_alt, cost_impact, safety_summary, policy_compliance
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    pbm_rows,
)

cost_rows = [
    ("RX-20260722-90001", "Tier 2", 145.0, 32.0, "Tier 1", 98.0, 18.0, 14.5, "Standard Coverage", 120.0),
    ("RX-20260722-90002", "Tier 1", 120.0, 20.0, "Tier 1", 120.0, 20.0, 0.0, "Standard Coverage", 120.0),
    ("RX-20260722-90003", "Tier 2", 132.0, 28.0, "Tier 1", 96.0, 16.0, 18.0, "Standard Coverage", 120.0),
    ("RX-20260722-90004", "Tier 1", 110.0, 15.0, "Tier 1", 110.0, 15.0, 0.0, "Standard Coverage", 120.0),
]

cursor.executemany(
    """
    INSERT INTO pbm_cost_comparison (
        rx_number, original_tier, original_price, original_copay,
        alternative_tier, alternative_price, alternative_copay, savings,
        insurance_phase, ytd_oop
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    cost_rows,
)

doctor_rows = [
    ("RX-20260722-90002", "REJECTED", "All alternatives rejected; dispense as written.", "DAW outcome"),
    ("RX-20260722-90003", "ACCEPTED", None, "Accepted after clinician review"),
    ("RX-20260722-90004", "ACCEPTED", None, "Auto accepted"),
]

cursor.executemany(
    "INSERT INTO doctor_decision (rx_number, status, reason, comment) VALUES (?, ?, ?, ?)",
    doctor_rows,
)

# DAW representation in UI: all alternatives rejected for this RX.
pbm_response_id = cursor.execute(
    "SELECT id FROM pbm_response WHERE rx_number = ?",
    ("RX-20260722-90002",),
).fetchone()
if pbm_response_id:
    rejected_payload = (
        '{"index":0,"label":"Alternative A","is_selected":false,'
        '"review_status":"REJECTED","outcome":"rejected",'
        '"policy":{"policy_state":"deny"}}'
    )
    rejected_payload_b = (
        '{"index":1,"label":"Alternative B","is_selected":false,'
        '"review_status":"REJECTED","outcome":"rejected",'
        '"policy":{"policy_state":"deny"}}'
    )
    cursor.executemany(
        """
        INSERT INTO pbm_alternative_option (
            pbm_response_id, rx_number, alternative_index, drug_id,
            alternative_label, is_selected, result_payload
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (pbm_response_id[0], "RX-20260722-90002", 0, "DAW-A", "Alternative A", 0, rejected_payload),
            (pbm_response_id[0], "RX-20260722-90002", 1, "DAW-B", "Alternative B", 0, rejected_payload_b),
        ],
    )

conn.commit()

rows = cursor.execute(
    """
    SELECT
      p.rx_number,
      p.member_id,
      p.medication,
      p.date_written,
      COALESCE(c.insurance_phase, '—') AS insurance_phase,
      COALESCE(c.ytd_oop, 0) AS ytd_oop,
      COALESCE(pb.status, '') AS pbm_status,
      COALESCE(d.status, '') AS decision_status
    FROM prescription p
    LEFT JOIN pbm_response pb ON p.rx_number = pb.rx_number
    LEFT JOIN doctor_decision d ON p.rx_number = d.rx_number
    LEFT JOIN pbm_cost_comparison c ON p.rx_number = c.rx_number
    WHERE p.rx_number LIKE 'RX-20260722-9000%'
    ORDER BY p.rx_number
    """
).fetchall()

print("INSERTED_ROWS", rows)
conn.close()
