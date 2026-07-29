-- ============================================================
-- Clinical Agent Output Storage Schema (SQLite)
-- ============================================================
-- Design:
--   1 claim (rx_number) -> many clinical candidate evaluations
--   Each clinical row is tied to an existing policy alternative via
--   (rx_number, candidate_drug_id), so counts stay aligned by design.
-- ============================================================

CREATE TABLE IF NOT EXISTS clinical_evaluations (
    clinical_evaluation_id      INTEGER PRIMARY KEY AUTOINCREMENT,

    rx_number                   TEXT NOT NULL,
    candidate_drug_id           TEXT NOT NULL,
    candidate_name              TEXT,

    overall_status              TEXT NOT NULL,

    stage_a_status              TEXT,
    stage_a_similarity_score    REAL,
    stage_a_evidence_json       TEXT DEFAULT '{}',
    stage_a_llm_review_required INTEGER,

    stage_b_status              TEXT,
    stage_b_hard_gates_json     TEXT DEFAULT '{}',
    stage_b_soft_safety_json    TEXT DEFAULT '{}',
    stage_b_safety_score        REAL,

    stage_c_status              TEXT,
    stage_c_clinical_rationale  TEXT DEFAULT '[]',
    stage_c_recommendation      TEXT,

    assessment_similarity_score REAL,
    assessment_safety_score     REAL,
    assessment_clinical_score   REAL,

    raw_response                TEXT,
    created_at                  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT uq_clinical_rx_candidate
        UNIQUE (rx_number, candidate_drug_id),

    CONSTRAINT fk_clinical_rx
        FOREIGN KEY (rx_number) REFERENCES claims(rx_number)
        ON DELETE CASCADE,

    CONSTRAINT fk_clinical_policy_pair
        FOREIGN KEY (rx_number, candidate_drug_id)
        REFERENCES drug_policy_evaluations(rx_number, candidate_drug_id)
        ON DELETE CASCADE,

    CONSTRAINT ck_overall_status
        CHECK (overall_status IN ('PASS', 'REVIEW', 'FAIL')),

    CONSTRAINT ck_stage_a_status
        CHECK (stage_a_status IN ('PASS', 'REVIEW', 'FAIL')),

    CONSTRAINT ck_stage_b_status
        CHECK (stage_b_status IN ('PASS', 'REVIEW', 'FAIL')),

    CONSTRAINT ck_stage_c_status
        CHECK (stage_c_status IN ('PASS', 'REVIEW', 'FAIL'))
);

CREATE INDEX IF NOT EXISTS idx_clinical_rx_number
    ON clinical_evaluations (rx_number);

CREATE INDEX IF NOT EXISTS idx_clinical_candidate_id
    ON clinical_evaluations (candidate_drug_id);

CREATE INDEX IF NOT EXISTS idx_clinical_overall_status
    ON clinical_evaluations (overall_status);
