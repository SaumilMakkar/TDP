-- ============================================
-- Seed Data
-- ============================================

-- Patients (6 patients)
INSERT INTO patient (member_id) VALUES
    ('P001'), ('P002'), ('P003'), ('P004'), ('P005'), ('P006');

-- Providers (4 providers)
INSERT INTO provider (prescriber_npi) VALUES
    ('1234567890'), ('2345678901'), ('3456789012'), ('4567890123');

-- Prescriptions (14 records)
INSERT INTO prescription (rx_number, member_id, prescriber_npi, medication, strength, frequency, days_supply, diagnosis_icd10, rx_status, date_written, pharmacy_id) VALUES
    ('10001', 'P001', '1234567890', 'Metformin ER',          '500 mg',  'BID',  90, 'E11.9',  'Submitted', '2026-06-20', 'PHARMA001'),
    ('10002', 'P002', '2345678901', 'Apixaban',              '5 mg',    'BID',  30, 'I48.91', 'Submitted', '2026-06-19', 'PHARMA001'),
    ('10003', 'P003', '1234567890', 'Semaglutide',           '0.5 mg',  'QD',   28, 'E11.69', 'Submitted', '2026-06-18', 'PHARMA001'),
    ('10004', 'P001', '3456789012', 'Lisinopril',            '20 mg',   'QD',   90, 'I10',    'Submitted', '2026-06-17', 'PHARMA001'),
    ('10005', 'P004', '2345678901', 'Adalimumab',            '40 mg',   'BID',  28, 'M06.9',  'Submitted', '2026-06-16', 'PHARMA001'),
    ('10006', 'P005', '4567890123', 'Rosuvastatin',          '20 mg',   'QD',   90, 'E78.2',  'Submitted', '2026-06-15', 'PHARMA001'),
    ('10007', 'P002', '1234567890', 'Omeprazole',            '20 mg',   'QD',   30, 'K21.9',  'Submitted', '2026-06-14', 'PHARMA001'),
    ('10008', 'P006', '3456789012', 'Ibuprofen',             '800 mg',  'TID',  14, 'M54.50', 'Submitted', '2026-06-13', 'PHARMA001'),
    ('10009', 'P003', '4567890123', 'Azithromycin',          '500 mg',  'QD',   5,  'J20.9',  'Submitted', '2026-06-12', 'PHARMA001'),
    ('10010', 'P004', '2345678901', 'Amoxicillin Suspension','400 mg',  'BID',  10, 'H66.90', 'Submitted', '2026-06-11', 'PHARMA001'),
    ('RX-20260629-00011', 'P001', '1234567890', 'Atorvastatin',        '20 mg',  'QD',  30, 'E78.5',  'Submitted', '2026-06-29', 'PHARMA001'),
    ('RX-20260706-00012', 'P002', '2345678901', 'Losartan',            '50 mg',  'QD',  30, 'I10',    'Submitted', '2026-07-06', 'PHARMA001'),
    ('RX-20260706-00013', 'P003', '3456789012', 'Metoprolol Succinate','25 mg',  'QD',  30, 'I48.91', 'Submitted', '2026-07-06', 'PHARMA001'),
    ('RX-20260706-00014', 'P004', '4567890123', 'Levothyroxine',       '75 mcg', 'QD',  30, 'E03.9',  'Submitted', '2026-07-06', 'PHARMA001');

-- Doctor Decisions (8 records — escalated cases include accepted/modified/rejected plus pending in dashboard)
INSERT INTO doctor_decision (rx_number, status, reason) VALUES
    ('10001', 'ACCEPTED',  NULL),
    ('10003', 'MODIFIED',  'Adjusted to formulary-preferred GLP-1 with equivalent glycemic efficacy and lower member cost share.'),
    ('10004', 'ACCEPTED',  NULL),
    ('10005', 'REJECTED',  'Biologic request does not meet step-therapy criteria; methotrexate trial not documented.'),
    ('10006', 'ACCEPTED',  NULL),
    ('10007', 'ACCEPTED',  NULL),
    ('10008', 'MODIFIED',  'Converted to short-course NSAID with GI prophylaxis due to ulcer risk profile.'),
    ('10010', 'MODIFIED',  'Dose and formulation adjusted to guideline-based pediatric otitis media regimen.');

-- RX status tracking removed — simplified flow uses `prescription`, `pbm_response` and `doctor_decision`

-- PBM Response (10 records with ai_confidence — rx_numbers match prescriptions)
INSERT INTO pbm_response (rx_number, status, ai_confidence, prescribed_drug, diagnosis, recommended_alt, cost_impact, safety_summary, policy_compliance) VALUES
('10001', 'APPROVED',  0.94, 'Metformin ER 500mg',           'Type 2 diabetes mellitus',     NULL,                           0,    'No major safety signal; renal function acceptable.',         'Formulary preferred, no PA or step edits.'),
('10002', 'ESCALATED', 0.67, 'Apixaban 5mg',                'Atrial fibrillation',          'Rivaroxaban 20mg',              95,   'Concomitant antiplatelet therapy increases bleed risk.',      'Prior authorization required for this line of therapy.'),
('10003', 'ESCALATED', 0.62, 'Semaglutide 0.5mg',           'Type 2 diabetes with obesity', 'Liraglutide 1.8mg',              210,  'Monitor GI intolerance and pancreatitis warning criteria.',    'Step therapy not satisfied per current claims history.'),
('10004', 'APPROVED',  0.96, 'Lisinopril 20mg',             'Essential hypertension',       NULL,                           0,    'No contraindications noted in profile.',                      'Covered as Tier 1 preferred generic.'),
('10005', 'ESCALATED', 0.51, 'Adalimumab 40mg',             'Rheumatoid arthritis',         'Etanercept 50mg',               580,  'Biologic therapy requires infection screening verification.',  'Non-preferred biologic; PA and step-therapy criteria open.'),
('10006', 'APPROVED',  0.92, 'Rosuvastatin 20mg',           'Mixed hyperlipidemia',         NULL,                           0,    'Monitor liver enzymes per statin protocol.',                 'Covered with standard quantity limit.'),
('10007', 'APPROVED',  0.91, 'Omeprazole 20mg',             'GERD',                         NULL,                           0,    'No major interaction risk with active meds.',                'Preferred PPI on formulary.'),
('10008', 'ESCALATED', 0.58, 'Ibuprofen 800mg',             'Chronic low back pain',        'Naproxen 500mg',                34,   'High-dose NSAID raises GI/renal risk in this profile.',       'Quantity and duration exceed plan soft limits.'),
('10009', 'ESCALATED', 0.74, 'Azithromycin 500mg',          'Acute bronchitis',             'Doxycycline 100mg',             42,   'QT interval caution; evaluate indication appropriateness.',    'Antibiotic stewardship edit triggered for diagnosis coding.'),
('10010', 'ESCALATED', 0.65, 'Amoxicillin Suspension 400mg','Acute otitis media (peds)',    'Amoxicillin-clavulanate ES',    18,   'Weight-based dosing check required for pediatric regimen.',    'Formulary covered after pediatric dosing validation.');

-- PBM Cost Comparison (1 per prescription rx_number, keyed by rx_number FK)
INSERT INTO pbm_cost_comparison (
    rx_number, original_tier, original_price, original_copay,
    alternative_tier, alternative_price, alternative_copay, savings,
    insurance_phase, ytd_oop, deductible_cap, oop_max_cap, deductible_remaining, oop_remaining,
    drug_name, generic_name, dosage, quantity, days_supply, formulary_status,
    prior_authorization_required, step_therapy_required, original_total_cost, alternative_total_cost,
    original_plan_paid, alternative_plan_paid, estimated_annual_savings, member_savings_percentage,
    deductible_met, oop_met, coinsurance_percentage, coverage_gap_status, catastrophic_coverage_status,
    pbm_name, policy_id, formulary_version, effective_date, expiration_date
) VALUES
    ('10001', 'Tier 1',  28.00,   8.00,  'Tier 1',  28.00,   8.00,   0.00, 'Standard Coverage', 120.00, 750.00, 3000.00, 630.00, 2880.00, 'Metformin ER', 'Metformin', '500 mg', 90, 90, 'Preferred', 0, 0, 28.00, 28.00, 20.00, 20.00, 0.00, 0.00, 120.00, 120.00, 20.00, 'Not in Coverage Gap', 'Not Reached', 'Default PBM', 'POL-10001', 'v2026.07', '2026-01-01', '2027-12-31'),
    ('10002', 'Tier 3',  612.00, 120.00, 'Tier 2',  517.00,  95.00, 95.00, 'Standard Coverage', 120.00, 750.00, 3000.00, 630.00, 2880.00, 'Apixaban', 'Apixaban', '5 mg', 30, 30, 'Non-Preferred', 1, 1, 612.00, 517.00, 492.00, 422.00, 1140.00, 15.52, 120.00, 120.00, 20.00, 'Not in Coverage Gap', 'Not Reached', 'Default PBM', 'POL-10002', 'v2026.07', '2026-01-01', '2027-12-31'),
    ('10003', 'Tier 3',  985.00, 180.00, 'Tier 2',  775.00, 135.00, 210.00, 'Standard Coverage', 120.00, 750.00, 3000.00, 630.00, 2880.00, 'Semaglutide', 'Semaglutide', '0.5 mg', 28, 28, 'Non-Preferred', 1, 1, 985.00, 775.00, 805.00, 640.00, 2520.00, 21.32, 120.00, 120.00, 20.00, 'Not in Coverage Gap', 'Not Reached', 'Default PBM', 'POL-10003', 'v2026.07', '2026-01-01', '2027-12-31'),
    ('10004', 'Tier 1',  14.00,   4.00,  'Tier 1',  14.00,   4.00,   0.00, 'Standard Coverage', 120.00, 750.00, 3000.00, 630.00, 2880.00, 'Lisinopril', 'Lisinopril', '20 mg', 90, 90, 'Preferred', 0, 0, 14.00, 14.00, 10.00, 10.00, 0.00, 0.00, 120.00, 120.00, 20.00, 'Not in Coverage Gap', 'Not Reached', 'Default PBM', 'POL-10004', 'v2026.07', '2026-01-01', '2027-12-31'),
    ('10005', 'Tier 4',  3540.00, 620.00,'Tier 3', 2960.00, 520.00, 580.00, 'Standard Coverage', 120.00, 750.00, 3000.00, 630.00, 2880.00, 'Adalimumab', 'Adalimumab', '40 mg', 28, 28, 'Non-Preferred', 1, 1, 3540.00, 2960.00, 2920.00, 2440.00, 6960.00, 16.38, 120.00, 120.00, 20.00, 'Not in Coverage Gap', 'Not Reached', 'Default PBM', 'POL-10005', 'v2026.07', '2026-01-01', '2027-12-31'),
    ('10006', 'Tier 1',  24.00,   7.00,  'Tier 1',  24.00,   7.00,   0.00, 'Standard Coverage', 120.00, 750.00, 3000.00, 630.00, 2880.00, 'Rosuvastatin', 'Rosuvastatin', '20 mg', 90, 90, 'Preferred', 0, 0, 24.00, 24.00, 17.00, 17.00, 0.00, 0.00, 120.00, 120.00, 20.00, 'Not in Coverage Gap', 'Not Reached', 'Default PBM', 'POL-10006', 'v2026.07', '2026-01-01', '2027-12-31'),
    ('10007', 'Tier 1',  18.00,   5.00,  'Tier 1',  18.00,   5.00,   0.00, 'Standard Coverage', 120.00, 750.00, 3000.00, 630.00, 2880.00, 'Omeprazole', 'Omeprazole', '20 mg', 30, 30, 'Preferred', 0, 0, 18.00, 18.00, 13.00, 13.00, 0.00, 0.00, 120.00, 120.00, 20.00, 'Not in Coverage Gap', 'Not Reached', 'Default PBM', 'POL-10007', 'v2026.07', '2026-01-01', '2027-12-31'),
    ('10008', 'Tier 2',  26.00,  10.00,  'Tier 1',   9.00,   6.00,  17.00, 'Standard Coverage', 120.00, 750.00, 3000.00, 630.00, 2880.00, 'Ibuprofen', 'Ibuprofen', '800 mg', 14, 14, 'Non-Preferred', 1, 1, 26.00, 9.00, 16.00, 3.00, 204.00, 65.38, 120.00, 120.00, 20.00, 'Not in Coverage Gap', 'Not Reached', 'Default PBM', 'POL-10008', 'v2026.07', '2026-01-01', '2027-12-31'),
    ('10009', 'Tier 2',  32.00,  11.00,  'Tier 1',  14.00,   7.00,  18.00, 'Standard Coverage', 120.00, 750.00, 3000.00, 630.00, 2880.00, 'Azithromycin', 'Azithromycin', '500 mg', 5, 5, 'Non-Preferred', 1, 1, 32.00, 14.00, 21.00, 7.00, 216.00, 56.25, 120.00, 120.00, 20.00, 'Not in Coverage Gap', 'Not Reached', 'Default PBM', 'POL-10009', 'v2026.07', '2026-01-01', '2027-12-31'),
    ('10010', 'Tier 2',  22.00,   9.00,  'Tier 2',  18.00,   8.00,   4.00, 'Standard Coverage', 120.00, 750.00, 3000.00, 630.00, 2880.00, 'Amoxicillin Suspension', 'Amoxicillin', '400 mg', 10, 10, 'Non-Preferred', 1, 1, 22.00, 18.00, 13.00, 10.00, 48.00, 18.18, 120.00, 120.00, 20.00, 'Not in Coverage Gap', 'Not Reached', 'Default PBM', 'POL-10010', 'v2026.07', '2026-01-01', '2027-12-31'),
    ('RX-20260629-00011', 'Tier 2',  46.00,  12.00, 'Tier 1',  24.00,   8.00,  22.00, 'Standard Coverage', 120.00, 750.00, 3000.00, 630.00, 2880.00, 'Atorvastatin', 'Atorvastatin', '20 mg', 30, 30, 'Non-Preferred', 1, 0, 46.00, 24.00, 34.00, 16.00, 264.00, 47.83, 120.00, 120.00, 20.00, 'Not in Coverage Gap', 'Not Reached', 'Default PBM', 'POL-00011', 'v2026.07', '2026-01-01', '2027-12-31'),
    ('RX-20260706-00012', 'Tier 1',  20.00,   6.00, 'Tier 1',  20.00,   6.00,   0.00, 'Standard Coverage', 120.00, 750.00, 3000.00, 630.00, 2880.00, 'Losartan', 'Losartan', '50 mg', 30, 30, 'Preferred', 0, 0, 20.00, 20.00, 14.00, 14.00, 0.00, 0.00, 120.00, 120.00, 20.00, 'Not in Coverage Gap', 'Not Reached', 'Default PBM', 'POL-00012', 'v2026.07', '2026-01-01', '2027-12-31'),
    ('RX-20260706-00013', 'Tier 2',  38.00,  10.00, 'Tier 1',  19.00,   7.00,  19.00, 'Standard Coverage', 120.00, 750.00, 3000.00, 630.00, 2880.00, 'Metoprolol Succinate', 'Metoprolol', '25 mg', 30, 30, 'Non-Preferred', 1, 0, 38.00, 19.00, 28.00, 12.00, 228.00, 50.00, 120.00, 120.00, 20.00, 'Not in Coverage Gap', 'Not Reached', 'Default PBM', 'POL-00013', 'v2026.07', '2026-01-01', '2027-12-31'),
    ('RX-20260706-00014', 'Tier 1',  16.00,   5.00, 'Tier 1',  16.00,   5.00,   0.00, 'Standard Coverage', 120.00, 750.00, 3000.00, 630.00, 2880.00, 'Levothyroxine', 'Levothyroxine', '75 mcg', 30, 30, 'Preferred', 0, 0, 16.00, 16.00, 11.00, 11.00, 0.00, 0.00, 120.00, 120.00, 20.00, 'Not in Coverage Gap', 'Not Reached', 'Default PBM', 'POL-00014', 'v2026.07', '2026-01-01', '2027-12-31');

-- Financial Temp Snapshot (dummy cost-analysis output keyed by valid prescriptions)
INSERT INTO financial_temp_snapshot (
    rx_number, original_tier, original_price, original_copay,
    alternative_tier, alternative_price, alternative_copay, savings,
    insurance_phase, ytd_oop, deductible_cap, oop_max_cap,
    deductible_remaining, oop_remaining
) VALUES
    ('10001', 'Tier 1', 28.00,   8.00,  'Tier 1', 28.00,   8.00,   0.00, 'Standard Coverage', 120.00, 750.00, 3000.00, 630.00, 2880.00),
    ('10002', 'Tier 3', 612.00, 120.00, 'Tier 2', 517.00, 95.00,  95.00, 'Standard Coverage', 0.00,   750.00, 3000.00, 750.00, 3000.00),
    ('10003', 'Tier 3', 985.00, 180.00, 'Tier 2', 775.00, 135.00, 210.00, 'Deductible Stage', 245.00, 750.00, 3000.00, 505.00, 2755.00),
    ('10004', 'Tier 1', 14.00,   4.00,  'Tier 1', 14.00,   4.00,   0.00, 'Standard Coverage', 80.00,  750.00, 3000.00, 670.00, 2920.00),
    ('10005', 'Tier 4', 3540.00,620.00, 'Tier 3',2960.00,520.00, 580.00, 'Standard Coverage', 0.00,   750.00, 3000.00, 750.00, 3000.00),
    ('10006', 'Tier 1', 24.00,   7.00,  'Tier 1', 24.00,   7.00,   0.00, 'Standard Coverage', 310.00, 750.00, 3000.00, 440.00, 2690.00),
    ('10007', 'Tier 1', 18.00,   5.00,  'Tier 1', 18.00,   5.00,   0.00, 'Standard Coverage', 200.00, 750.00, 3000.00, 550.00, 2800.00),
    ('10008', 'Tier 2', 26.00,  10.00,  'Tier 1',  9.00,   6.00,  17.00, 'Standard Coverage', 460.00, 750.00, 3000.00, 290.00, 2540.00),
    ('10009', 'Tier 2', 32.00,  11.00,  'Tier 1', 14.00,   7.00,  18.00, 'Standard Coverage', 510.00, 750.00, 3000.00, 240.00, 2490.00),
    ('10010','Tier 2', 22.00,   9.00,  'Tier 2', 18.00,   8.00,   4.00, 'Standard Coverage', 150.00, 750.00, 3000.00, 600.00, 2850.00),
    ('RX-20260629-00011', 'Tier 1', 45.00, 11.00, 'Tier 1', 45.00, 11.00, 0.00, 'Standard Coverage', 180.00, 750.00, 3000.00, 570.00, 2820.00),
    ('RX-20260706-00012', 'Tier 1', 38.00, 10.00, 'Tier 1', 30.00,  8.00, 8.00, 'Standard Coverage', 260.00, 750.00, 3000.00, 490.00, 2740.00),
    ('RX-20260706-00013', 'Tier 2', 72.00, 18.00, 'Tier 1', 49.00, 12.00, 23.00, 'Standard Coverage', 320.00, 750.00, 3000.00, 430.00, 2680.00),
    ('RX-20260706-00014', 'Tier 2', 61.00, 16.00, 'Tier 1', 42.00, 10.00, 19.00, 'Standard Coverage', 205.00, 750.00, 3000.00, 545.00, 2795.00);

-- PBM Safety (1 per PBM response)
INSERT INTO pbm_safety (pbm_response_id, contraindications, interactions, monitoring) VALUES
    (1,  'No major contraindication',        'No clinically significant interaction', 'A1c every 3 months, renal panel annually'),
    (2,  'Active major bleed risk to assess','Dual antithrombotic regimen',           'CBC and bleeding surveillance'),
    (3,  'History review for pancreatitis',  'No severe interaction identified',      'GI tolerance and weight trend'),
    (4,  'Pregnancy contraindication check', 'No major interaction',                  'Serum creatinine and potassium'),
    (5,  'Active infection must be excluded', 'Immunosuppressant additive risk',      'TB/HBV screen and infection monitoring'),
    (6,  'Hepatic disease caution',          'No major interaction',                   'Lipid panel and ALT/AST'),
    (7,  'Long-term PPI risk if chronic use','No major interaction',                   'Symptom control and duration review'),
    (8,  'Peptic ulcer and CKD risk factors','Concomitant NSAID exposure',             'Renal function and GI adverse effects'),
    (9,  'Macrolide QT-risk screening',      'Potential QT-prolonging co-therapy',    'ECG only if cardiac risk present'),
    (10, 'Penicillin allergy screening',     'No major interaction',                   'Weight-based dosing confirmation');

-- PBM Policy (1 per PBM response)
INSERT INTO pbm_policy (pbm_response_id, original_status, alternative_status) VALUES
    (1,  'Preferred generic (Tier 1)',                 'Preferred generic (Tier 1)'),
    (2,  'PA required for non-preferred anticoagulant', 'Preferred alternative covered'),
    (3,  'Step therapy required before GLP-1 coverage', 'Preferred GLP-1 covered with criteria'),
    (4,  'Preferred ACE inhibitor (Tier 1)',           'Preferred ACE inhibitor (Tier 1)'),
    (5,  'Non-preferred biologic; PA + step edit',     'Preferred biologic covered with PA'),
    (6,  'Preferred statin with standard quantity edit','Preferred statin with standard quantity edit'),
    (7,  'Preferred PPI (Tier 1)',                     'Preferred PPI (Tier 1)'),
    (8,  'Quantity/day-supply limit exceeded',          'Preferred NSAID covered within limits'),
    (9,  'Stewardship edit: diagnosis/antibiotic mismatch', 'Alternative covered for coded indication'),
    (10, 'Pediatric dosing validation required',        'Covered after dose/formulation correction');

-- Users (10 records)
-- pharmacist_id maps to prescription.phr_id / pharmacy_id for scoped visibility
-- provider_npi maps to prescription.npi_number / prescriber_npi for scoped visibility
-- All seed passwords use the demo fallback: password123
INSERT INTO users (username, full_name, password_hash, role, pharmacist_id, provider_npi, is_active) VALUES
    ('provider_1234567890', 'Dr. Sarah Mitchell',  'pbkdf2:sha256:1000000$salt001$hash001', 'provider', NULL, '1234567890', 1),
    ('provider_2345678901', 'Dr. James Okafor',    'pbkdf2:sha256:1000000$salt002$hash002', 'provider', NULL, '2345678901', 1),
    ('provider_3456789012', 'Dr. Linda Nguyen',    'pbkdf2:sha256:1000000$salt003$hash003', 'provider', NULL, '3456789012', 1),
    ('provider_4567890123', 'Dr. Robert Chen',     'pbkdf2:sha256:1000000$salt004$hash004', 'provider', NULL, '4567890123', 0),
    ('pharmacist_PHARMA001', 'Alex Rivera',        'pbkdf2:sha256:1000000$salt005$hash005', 'pharmacist', 'PHARMA001', NULL, 1),
    ('pharmacist_PHARMA002', 'Priya Sharma',       'pbkdf2:sha256:1000000$salt006$hash006', 'pharmacist', 'PHARMA002', NULL, 1),
    ('pharmacist_PHARMA003', 'Marcus Webb',        'pbkdf2:sha256:1000000$salt007$hash007', 'pharmacist', 'PHARMA003', NULL, 1),
    ('pharmacist_PHARMA004', 'Dana Kowalski',      'pbkdf2:sha256:1000000$salt008$hash008', 'pharmacist', 'PHARMA004', NULL, 0),
    ('pbm1',                 'PBM Reviewer 1',    'pbkdf2:sha256:1000000$salt009$hash009', 'pbm',        NULL,         NULL, 1),
    ('pbm2',                 'PBM Reviewer 2',    'pbkdf2:sha256:1000000$salt010$hash010', 'pbm',        NULL,         NULL, 1);