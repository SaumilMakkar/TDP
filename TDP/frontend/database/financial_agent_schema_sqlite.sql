-- ============================================================
-- Financial Agent Output Storage Schema (SQLite)
-- ============================================================
-- Design:
--   Two tables split financial output into original and alternative drug views.
--   Both tables are anchored to policy alternatives by (rx_number, candidate_drug_id)
--   so every policy candidate can have matching financial original+alternative rows.
-- ============================================================

CREATE TABLE IF NOT EXISTS financial_original_drug (
    financial_original_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    rx_number                    TEXT NOT NULL,
    candidate_drug_id            TEXT NOT NULL,

    original_drug_id             TEXT NOT NULL,
    original_drug_name           TEXT,
    original_generic_name        TEXT,
    original_dosage              TEXT,
    original_quantity            INTEGER,
    original_days_supply         INTEGER,

    original_tier                TEXT,
    original_price               REAL,
    original_copay               REAL,
    original_total_cost          REAL,
    original_plan_paid           REAL,

    insurance_phase              TEXT,
    ytd_oop                      REAL,
    deductible_cap               REAL,
    oop_max_cap                  REAL,
    deductible_remaining         REAL,
    oop_remaining                REAL,
    deductible_met               REAL,
    oop_met                      REAL,
    coinsurance_percentage       REAL,

    formulary_status             TEXT,
    prior_authorization_required INTEGER,
    step_therapy_required        INTEGER,

    pbm_name                     TEXT,
    policy_id                    TEXT,
    formulary_version            TEXT,
    effective_date               DATE,
    expiration_date              DATE,

    raw_response                 TEXT,
    created_at                   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT uq_financial_original_rx_candidate
        UNIQUE (rx_number, candidate_drug_id),

    CONSTRAINT fk_fin_orig_claim
        FOREIGN KEY (rx_number) REFERENCES claims(rx_number)
        ON DELETE CASCADE,

    CONSTRAINT fk_fin_orig_policy_pair
        FOREIGN KEY (rx_number, candidate_drug_id)
        REFERENCES drug_policy_evaluations(rx_number, candidate_drug_id)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS financial_alternative_drug (
    financial_alternative_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    rx_number                    TEXT NOT NULL,
    candidate_drug_id            TEXT NOT NULL,

    alternative_drug_id          TEXT NOT NULL,
    alternative_drug_name        TEXT,
    alternative_generic_name     TEXT,
    alternative_dosage           TEXT,
    alternative_quantity         INTEGER,
    alternative_days_supply      INTEGER,

    alternative_tier             TEXT,
    alternative_price            REAL,
    alternative_copay            REAL,
    alternative_total_cost       REAL,
    alternative_plan_paid        REAL,

    savings                      REAL,
    estimated_annual_savings     REAL,
    member_savings_percentage    REAL,

    insurance_phase              TEXT,
    ytd_oop                      REAL,
    deductible_cap               REAL,
    oop_max_cap                  REAL,
    deductible_remaining         REAL,
    oop_remaining                REAL,

    formulary_status             TEXT,
    prior_authorization_required INTEGER,
    step_therapy_required        INTEGER,

    pbm_name                     TEXT,
    policy_id                    TEXT,
    formulary_version            TEXT,
    effective_date               DATE,
    expiration_date              DATE,

    raw_response                 TEXT,
    created_at                   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT uq_financial_alt_rx_candidate
        UNIQUE (rx_number, candidate_drug_id),

    CONSTRAINT fk_fin_alt_claim
        FOREIGN KEY (rx_number) REFERENCES claims(rx_number)
        ON DELETE CASCADE,

    CONSTRAINT fk_fin_alt_policy_pair
        FOREIGN KEY (rx_number, candidate_drug_id)
        REFERENCES drug_policy_evaluations(rx_number, candidate_drug_id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_fin_orig_rx
    ON financial_original_drug (rx_number);

CREATE INDEX IF NOT EXISTS idx_fin_orig_candidate
    ON financial_original_drug (candidate_drug_id);

CREATE INDEX IF NOT EXISTS idx_fin_alt_rx
    ON financial_alternative_drug (rx_number);

CREATE INDEX IF NOT EXISTS idx_fin_alt_candidate
    ON financial_alternative_drug (candidate_drug_id);
