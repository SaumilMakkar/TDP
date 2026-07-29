-- ============================================
-- Full Schema (SQLite)
-- ============================================

-- 1. Patient table
CREATE TABLE IF NOT EXISTS patient (
    member_id  TEXT PRIMARY KEY
);

-- 2. Provider table
CREATE TABLE IF NOT EXISTS provider (
    prescriber_npi  TEXT PRIMARY KEY
);

-- 3. Prescription table
CREATE TABLE IF NOT EXISTS prescription (
    rx_number           TEXT PRIMARY KEY,
    member_id           TEXT NOT NULL,
    prescriber_npi      TEXT NOT NULL,
    medication          TEXT NOT NULL,
    medication_rxcui    TEXT,
    strength            TEXT NOT NULL,
    frequency           TEXT NOT NULL,
    days_supply         INTEGER NOT NULL,
    diagnosis_icd10     TEXT NOT NULL,
    rx_status           TEXT NOT NULL CHECK (rx_status IN ('Submitted', 'Approved', 'Denied', 'Pending')),
    date_written        DATE NOT NULL,
    pharmacy_id         TEXT NOT NULL DEFAULT 'PHARMA001',
    FOREIGN KEY (member_id) REFERENCES patient (member_id),
    FOREIGN KEY (prescriber_npi) REFERENCES provider (prescriber_npi)
);

-- 4. Doctor Decision table
CREATE TABLE IF NOT EXISTS doctor_decision (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    rx_number   TEXT NOT NULL,
    status      TEXT NOT NULL CHECK (status IN ('ACCEPTED', 'REJECTED', 'MODIFIED')),
    reason      TEXT,
    comment     TEXT,
    created_at  DATETIME NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (rx_number) REFERENCES prescription (rx_number)
);

CREATE TABLE IF NOT EXISTS doctor_decision_reason (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    rx_number   TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    reason_text TEXT NOT NULL,
    comment     TEXT,
    created_at  DATETIME NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (rx_number) REFERENCES prescription (rx_number)
);

-- 5. (Removed) RX Status Tracking: simplified flow uses prescription.rx_status, pbm_response and doctor_decision

-- 6. PBM Response table (root + clinical_snapshot fields flattened)
CREATE TABLE IF NOT EXISTS pbm_response (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    rx_number           TEXT NOT NULL,
    status              TEXT NOT NULL CHECK (status IN ('ESCALATED', 'APPROVED', 'ACCEPTED', 'DENIED', 'PENDING_REVIEW')),
    ai_confidence       REAL NOT NULL CHECK (ai_confidence >= 0.0 AND ai_confidence <= 1.0),  -- 0.0 to 1.0
    prescribed_drug     TEXT NOT NULL,
    diagnosis           TEXT NOT NULL,
    recommended_alt     TEXT,
    cost_impact         REAL NOT NULL DEFAULT 0,        -- savings amount
    safety_summary      TEXT NOT NULL,
    policy_compliance   TEXT NOT NULL,
    created_at          DATETIME NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (rx_number) REFERENCES prescription (rx_number)
);

-- 7. PBM Cost Comparison (nested sub-object of PBM Response)
CREATE TABLE IF NOT EXISTS pbm_cost_comparison (
    rx_number           TEXT PRIMARY KEY,
    original_tier       TEXT NOT NULL,
    original_price      REAL NOT NULL,
    original_copay      REAL NOT NULL,
    alternative_tier    TEXT NOT NULL,
    alternative_price   REAL NOT NULL,
    alternative_copay   REAL NOT NULL,
    savings             REAL NOT NULL,
    insurance_phase     TEXT,
    ytd_oop             REAL,
    deductible_cap      REAL,
    oop_max_cap         REAL,
    deductible_remaining REAL,
    oop_remaining       REAL,
    drug_name           TEXT,
    generic_name        TEXT,
    dosage              TEXT,
    quantity            INTEGER,
    days_supply         INTEGER,
    formulary_status    TEXT,
    prior_authorization_required INTEGER,
    step_therapy_required INTEGER,
    original_total_cost REAL,
    alternative_total_cost REAL,
    original_plan_paid  REAL,
    alternative_plan_paid REAL,
    estimated_annual_savings REAL,
    member_savings_percentage REAL,
    deductible_met      REAL,
    oop_met             REAL,
    coinsurance_percentage REAL,
    coverage_gap_status TEXT,
    catastrophic_coverage_status TEXT,
    pbm_name            TEXT,
    policy_id           TEXT,
    formulary_version   TEXT,
    effective_date      DATE,
    expiration_date     DATE,
    FOREIGN KEY (rx_number) REFERENCES prescription (rx_number)
);

-- 7b. Financial Temp Snapshot (temporary financial-agent output keyed by rx)
CREATE TABLE IF NOT EXISTS financial_temp_snapshot (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    rx_number            TEXT NOT NULL UNIQUE,
    original_tier        TEXT NOT NULL,
    original_price       REAL NOT NULL,
    original_copay       REAL NOT NULL,
    alternative_tier     TEXT NOT NULL,
    alternative_price    REAL NOT NULL,
    alternative_copay    REAL NOT NULL,
    savings              REAL NOT NULL,
    insurance_phase      TEXT,
    ytd_oop              REAL,
    deductible_cap       REAL,
    oop_max_cap          REAL,
    deductible_remaining REAL,
    oop_remaining        REAL,
    created_at           DATETIME NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (rx_number) REFERENCES prescription (rx_number)
);

-- 8. PBM Safety (nested sub-object of PBM Response)
CREATE TABLE IF NOT EXISTS pbm_safety (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    pbm_response_id     INTEGER NOT NULL,
    contraindications   TEXT NOT NULL,
    interactions        TEXT NOT NULL,
    monitoring          TEXT NOT NULL,
    FOREIGN KEY (pbm_response_id) REFERENCES pbm_response (id)
);

-- 9. PBM Policy (nested sub-object of PBM Response)
CREATE TABLE IF NOT EXISTS pbm_policy (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    pbm_response_id     INTEGER NOT NULL,
    original_status     TEXT NOT NULL,
    alternative_status  TEXT NOT NULL,
    FOREIGN KEY (pbm_response_id) REFERENCES pbm_response (id)
);

-- 9b. PBM Alternative Options (one rendered payload per evaluated alternative)
CREATE TABLE IF NOT EXISTS pbm_alternative_option (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    pbm_response_id   INTEGER NOT NULL,
    rx_number         TEXT NOT NULL,
    alternative_index INTEGER NOT NULL,
    drug_id           TEXT,
    alternative_label TEXT NOT NULL,
    is_selected       INTEGER NOT NULL DEFAULT 0,
    result_payload    TEXT NOT NULL,
    created_at        DATETIME NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (pbm_response_id) REFERENCES pbm_response (id),
    FOREIGN KEY (rx_number) REFERENCES prescription (rx_number)
);

-- 10. Users table
CREATE TABLE IF NOT EXISTS users (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    username       TEXT UNIQUE,
    full_name      TEXT,
    password_hash  TEXT NOT NULL,
    role           TEXT NOT NULL CHECK (role IN ('provider', 'pharmacist', 'pbm')),
    pharmacist_id  TEXT UNIQUE,
    provider_npi   TEXT UNIQUE,
    is_active      INTEGER NOT NULL DEFAULT 1,
    created_at     DATETIME NOT NULL DEFAULT (datetime('now'))
);


-- Indexes
CREATE INDEX IF NOT EXISTS idx_prescription_member ON prescription (member_id);
CREATE INDEX IF NOT EXISTS idx_prescription_prescriber ON prescription (prescriber_npi);
CREATE INDEX IF NOT EXISTS idx_doctor_decision_rx ON doctor_decision (rx_number);
CREATE INDEX IF NOT EXISTS idx_doctor_decision_reason_rx ON doctor_decision_reason (rx_number);
-- rx_status_tracking index removed
CREATE INDEX IF NOT EXISTS idx_pbm_response_rx ON pbm_response (rx_number);
CREATE INDEX IF NOT EXISTS idx_pbm_cost_comparison_rx ON pbm_cost_comparison (rx_number);
CREATE INDEX IF NOT EXISTS idx_financial_temp_snapshot_rx ON financial_temp_snapshot (rx_number);
CREATE INDEX IF NOT EXISTS idx_pbm_safety_resp ON pbm_safety (pbm_response_id);
CREATE INDEX IF NOT EXISTS idx_pbm_policy_resp ON pbm_policy (pbm_response_id);
CREATE INDEX IF NOT EXISTS idx_pbm_alternative_option_resp ON pbm_alternative_option (pbm_response_id);
CREATE INDEX IF NOT EXISTS idx_pbm_alternative_option_rx ON pbm_alternative_option (rx_number);







