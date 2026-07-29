-- ============================================================
-- Policy Agent Output Storage Schema
-- ============================================================
-- Design:
--   1 claim_context  -> many candidate drug evaluations
--   rx_number is the synthetic key generated at ingestion time
--   (not present in source JSON) that links the two tables.
-- ============================================================

CREATE TABLE claims (
    rx_number        VARCHAR(50)  PRIMARY KEY,        -- generated at ingestion (UUID / Rx#)
    drug_id          VARCHAR(20)  NOT NULL,            -- the drug originally claimed
    plan_id          VARCHAR(20)  NOT NULL,
    member_id        VARCHAR(20)  NOT NULL,
    quantity         INTEGER      NOT NULL,
    fill_date        DATE         NOT NULL,
    created_at       TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE drug_policy_evaluations (
    evaluation_id        BIGSERIAL PRIMARY KEY,        -- surrogate PK, one row per candidate result
    rx_number             VARCHAR(50) NOT NULL,
    candidate_drug_id     VARCHAR(20) NOT NULL,

    covered               BOOLEAN,
    tier                  VARCHAR(10),
    pa_required           BOOLEAN,
    pa_met                BOOLEAN,
    step_therapy_required BOOLEAN,
    step_therapy_met      BOOLEAN,
    quantity_ok           BOOLEAN,
    formulary_preference  VARCHAR(50),

    -- variable-length arrays stored as JSONB (works for 0, 1, or many entries)
    violations            JSONB DEFAULT '[]'::jsonb,
    pending_reasons       JSONB DEFAULT '[]'::jsonb,

    policy_state          VARCHAR(20),   -- pass / pending / fail / etc.
    pending_type          VARCHAR(50),   -- doctor_review / null / ...
    review_recommendation TEXT,

    score                 NUMERIC(4,2),
    notes                 TEXT,          -- same as summary.reason in source JSON

    raw_response           JSONB,        -- optional: store the full original JSON blob as-is (audit/debug)

    created_at             TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_rx_number
        FOREIGN KEY (rx_number) REFERENCES claims(rx_number)
        ON DELETE CASCADE,

    CONSTRAINT uq_rx_candidate
        UNIQUE (rx_number, candidate_drug_id)   -- one evaluation per candidate per claim
);

-- Helpful indexes for common queries
CREATE INDEX idx_evaluations_rx_number     ON drug_policy_evaluations (rx_number);
CREATE INDEX idx_evaluations_candidate_id  ON drug_policy_evaluations (candidate_drug_id);
CREATE INDEX idx_evaluations_policy_state  ON drug_policy_evaluations (policy_state);
CREATE INDEX idx_claims_member_id          ON claims (member_id);
CREATE INDEX idx_claims_plan_id            ON claims (plan_id);

-- ============================================================
-- Sample inserts using your provided data
-- ============================================================

-- --------------------------------------------------------
-- 1) CLAIMS  (parent rows)
-- --------------------------------------------------------
INSERT INTO claims (rx_number, drug_id, plan_id, member_id, quantity, fill_date) VALUES
('10001',                '1018', '3001', '2001', 30,  '2025-01-05'),
('10002',                '1005', '3002', '2002', 60,  '2025-01-12'),
('10003',                '1022', '3003', '2003', 30,  '2025-02-01'),
('10004',                '1009', '3001', '2004', 90,  '2025-02-14'),
('10005',                '1014', '3004', '2005', 30,  '2025-03-03'),
('10006',                '1002', '3005', '2006', 60,  '2025-03-20'),
('10007',                '1030', '3002', '2007', 30,  '2025-04-02'),
('10008',                '1011', '3006', '2008', 90,  '2025-04-18'),
('10009',                '1027', '3001', '2009', 30,  '2025-05-05'),
('10010',                '1033', '3003', '2010', 60,  '2025-05-22'),
('RX-20260629-00011',    '1018', '3007', '2001', 30,  '2026-06-29'),
('RX-20260706-00012',    '1044', '3008', '2011', 30,  '2026-07-06'),
('RX-20260706-00013',    '1050', '3002', '2012', 90,  '2026-07-06'),
('RX-20260706-00014',    '1006', '3009', '2013', 60,  '2026-07-06'),
('RX-20260707-00015',    '1021', '3010', '2014', 30,  '2026-07-07');

-- --------------------------------------------------------
-- 2) DRUG POLICY EVALUATIONS  (child rows, variable count per claim)
-- --------------------------------------------------------

-- ---- 10001: 2 candidates, both pass, different tiers ----
INSERT INTO drug_policy_evaluations
(rx_number, candidate_drug_id, covered, tier, pa_required, pa_met, step_therapy_required, step_therapy_met, quantity_ok, formulary_preference, violations, policy_state, pending_type, pending_reasons, review_recommendation, score, notes) VALUES
('10001','1033', TRUE,'3', FALSE,TRUE, FALSE,TRUE, TRUE,'Non Preferred','[]'::jsonb,'pass',NULL,'[]'::jsonb,NULL,0.72,'Non Preferred formulary preference. All policy checks passed.'),
('10001','1040', TRUE,'1', FALSE,TRUE, FALSE,TRUE, TRUE,'Preferred','[]'::jsonb,'pass',NULL,'[]'::jsonb,NULL,0.95,'Preferred formulary preference. All policy checks passed.');

-- ---- 10002: 3 candidates, pass / PA pending / pass ----
INSERT INTO drug_policy_evaluations
(rx_number, candidate_drug_id, covered, tier, pa_required, pa_met, step_therapy_required, step_therapy_met, quantity_ok, formulary_preference, violations, policy_state, pending_type, pending_reasons, review_recommendation, score, notes) VALUES
('10002','1011', TRUE,'2', FALSE,TRUE, FALSE,TRUE, TRUE,'Preferred','[]'::jsonb,'pass',NULL,'[]'::jsonb,NULL,0.90,'Preferred formulary preference. All policy checks passed.'),
('10002','1008', TRUE,'4', TRUE,FALSE, FALSE,TRUE, TRUE,'Exception Only','["Prior authorization required and not yet evidenced."]'::jsonb,'pending','doctor_review','["Prior authorization required and not yet evidenced."]'::jsonb,'Doctor review required (accept/reject/modify).',0.32,'Prior authorization required and not yet evidenced.'),
('10002','1017', TRUE,'3', FALSE,TRUE, FALSE,TRUE, TRUE,'Non Preferred','[]'::jsonb,'pass',NULL,'[]'::jsonb,NULL,0.70,'Non Preferred formulary preference. All policy checks passed.');

-- ---- 10003: 1 candidate, fully rejected (not covered) ----
INSERT INTO drug_policy_evaluations
(rx_number, candidate_drug_id, covered, tier, pa_required, pa_met, step_therapy_required, step_therapy_met, quantity_ok, formulary_preference, violations, policy_state, pending_type, pending_reasons, review_recommendation, score, notes) VALUES
('10003','1022', FALSE,NULL, FALSE,TRUE, FALSE,TRUE, TRUE,'Not Covered','["Drug not covered under plan formulary."]'::jsonb,'fail',NULL,'[]'::jsonb,NULL,0.05,'Drug not covered under plan formulary.');

-- ---- 10004: 4 candidates, pass / PA pending / step-therapy pending / quantity fail ----
INSERT INTO drug_policy_evaluations
(rx_number, candidate_drug_id, covered, tier, pa_required, pa_met, step_therapy_required, step_therapy_met, quantity_ok, formulary_preference, violations, policy_state, pending_type, pending_reasons, review_recommendation, score, notes) VALUES
('10004','1009', TRUE,'2', FALSE,TRUE, FALSE,TRUE, TRUE,'Preferred','[]'::jsonb,'pass',NULL,'[]'::jsonb,NULL,0.88,'Preferred formulary preference. All policy checks passed.'),
('10004','1015', TRUE,'4', TRUE,FALSE, FALSE,TRUE, TRUE,'Exception Only','["Prior authorization required and not yet evidenced."]'::jsonb,'pending','doctor_review','["Prior authorization required and not yet evidenced."]'::jsonb,'Doctor review required (accept/reject/modify).',0.30,'Prior authorization required and not yet evidenced.'),
('10004','1028', TRUE,'3', FALSE,TRUE, TRUE,FALSE, TRUE,'Non Preferred','["Step therapy requirement not met."]'::jsonb,'pending','doctor_review','["Step therapy requirement not met."]'::jsonb,'Doctor review required (accept/reject/modify).',0.35,'Step therapy requirement not met.'),
('10004','1041', TRUE,'3', FALSE,TRUE, FALSE,TRUE, FALSE,'Non Preferred','["Requested quantity exceeds plan limit."]'::jsonb,'fail',NULL,'[]'::jsonb,NULL,0.20,'Requested quantity exceeds plan limit.');

-- ---- 10005: 2 candidates, pass / not covered ----
INSERT INTO drug_policy_evaluations
(rx_number, candidate_drug_id, covered, tier, pa_required, pa_met, step_therapy_required, step_therapy_met, quantity_ok, formulary_preference, violations, policy_state, pending_type, pending_reasons, review_recommendation, score, notes) VALUES
('10005','1014', TRUE,'2', FALSE,TRUE, FALSE,TRUE, TRUE,'Preferred','[]'::jsonb,'pass',NULL,'[]'::jsonb,NULL,0.91,'Preferred formulary preference. All policy checks passed.'),
('10005','1035', FALSE,NULL, FALSE,TRUE, FALSE,TRUE, TRUE,'Not Covered','["Drug not covered under plan formulary."]'::jsonb,'fail',NULL,'[]'::jsonb,NULL,0.05,'Drug not covered under plan formulary.');

-- ---- 10006: 5 candidates - broad mix (pass x2, PA pending, step-therapy pending, quantity fail) ----
INSERT INTO drug_policy_evaluations
(rx_number, candidate_drug_id, covered, tier, pa_required, pa_met, step_therapy_required, step_therapy_met, quantity_ok, formulary_preference, violations, policy_state, pending_type, pending_reasons, review_recommendation, score, notes) VALUES
('10006','1002', TRUE,'1', FALSE,TRUE, FALSE,TRUE, TRUE,'Preferred','[]'::jsonb,'pass',NULL,'[]'::jsonb,NULL,0.97,'Preferred formulary preference. All policy checks passed.'),
('10006','1019', TRUE,'3', FALSE,TRUE, FALSE,TRUE, TRUE,'Non Preferred','[]'::jsonb,'pass',NULL,'[]'::jsonb,NULL,0.75,'Non Preferred formulary preference. All policy checks passed.'),
('10006','1023', TRUE,'5', TRUE,FALSE, TRUE,FALSE, TRUE,'Exception Only','["Prior authorization required and not yet evidenced.","Step therapy requirement not met."]'::jsonb,'pending','doctor_review','["Prior authorization required and not yet evidenced.","Step therapy requirement not met."]'::jsonb,'Doctor review required (accept/reject/modify).',0.18,'Prior authorization required and not yet evidenced. Step therapy requirement not met.'),
('10006','1031', TRUE,'4', TRUE,TRUE, FALSE,TRUE, TRUE,'Exception Only','[]'::jsonb,'pass',NULL,'[]'::jsonb,NULL,0.60,'Exception Only formulary preference. All policy checks passed.'),
('10006','1046', TRUE,'2', FALSE,TRUE, FALSE,TRUE, FALSE,'Preferred','["Requested quantity exceeds plan limit."]'::jsonb,'fail',NULL,'[]'::jsonb,NULL,0.25,'Requested quantity exceeds plan limit.');

-- ---- 10007: 1 candidate, step-therapy pending ----
INSERT INTO drug_policy_evaluations
(rx_number, candidate_drug_id, covered, tier, pa_required, pa_met, step_therapy_required, step_therapy_met, quantity_ok, formulary_preference, violations, policy_state, pending_type, pending_reasons, review_recommendation, score, notes) VALUES
('10007','1030', TRUE,'3', FALSE,TRUE, TRUE,FALSE, TRUE,'Non Preferred','["Step therapy requirement not met."]'::jsonb,'pending','doctor_review','["Step therapy requirement not met."]'::jsonb,'Doctor review required (accept/reject/modify).',0.34,'Step therapy requirement not met.');

-- ---- 10008: 3 candidates, all pass (different tiers) ----
INSERT INTO drug_policy_evaluations
(rx_number, candidate_drug_id, covered, tier, pa_required, pa_met, step_therapy_required, step_therapy_met, quantity_ok, formulary_preference, violations, policy_state, pending_type, pending_reasons, review_recommendation, score, notes) VALUES
('10008','1011', TRUE,'1', FALSE,TRUE, FALSE,TRUE, TRUE,'Preferred','[]'::jsonb,'pass',NULL,'[]'::jsonb,NULL,0.96,'Preferred formulary preference. All policy checks passed.'),
('10008','1024', TRUE,'2', FALSE,TRUE, FALSE,TRUE, TRUE,'Preferred','[]'::jsonb,'pass',NULL,'[]'::jsonb,NULL,0.89,'Preferred formulary preference. All policy checks passed.'),
('10008','1037', TRUE,'3', FALSE,TRUE, FALSE,TRUE, TRUE,'Non Preferred','[]'::jsonb,'pass',NULL,'[]'::jsonb,NULL,0.71,'Non Preferred formulary preference. All policy checks passed.');

-- ---- 10009: 2 candidates, both pending (PA / step therapy) ----
INSERT INTO drug_policy_evaluations
(rx_number, candidate_drug_id, covered, tier, pa_required, pa_met, step_therapy_required, step_therapy_met, quantity_ok, formulary_preference, violations, policy_state, pending_type, pending_reasons, review_recommendation, score, notes) VALUES
('10009','1027', TRUE,'4', TRUE,FALSE, FALSE,TRUE, TRUE,'Exception Only','["Prior authorization required and not yet evidenced."]'::jsonb,'pending','doctor_review','["Prior authorization required and not yet evidenced."]'::jsonb,'Doctor review required (accept/reject/modify).',0.31,'Prior authorization required and not yet evidenced.'),
('10009','1039', TRUE,'3', FALSE,TRUE, TRUE,FALSE, TRUE,'Non Preferred','["Step therapy requirement not met."]'::jsonb,'pending','doctor_review','["Step therapy requirement not met."]'::jsonb,'Doctor review required (accept/reject/modify).',0.33,'Step therapy requirement not met.');

-- ---- 10010: 4 candidates, pass / fail / pending / pass ----
INSERT INTO drug_policy_evaluations
(rx_number, candidate_drug_id, covered, tier, pa_required, pa_met, step_therapy_required, step_therapy_met, quantity_ok, formulary_preference, violations, policy_state, pending_type, pending_reasons, review_recommendation, score, notes) VALUES
('10010','1033', TRUE,'3', FALSE,TRUE, FALSE,TRUE, TRUE,'Non Preferred','[]'::jsonb,'pass',NULL,'[]'::jsonb,NULL,0.72,'Non Preferred formulary preference. All policy checks passed.'),
('10010','1048', FALSE,NULL, FALSE,TRUE, FALSE,TRUE, TRUE,'Not Covered','["Drug not covered under plan formulary."]'::jsonb,'fail',NULL,'[]'::jsonb,NULL,0.04,'Drug not covered under plan formulary.'),
('10010','1052', TRUE,'5', TRUE,FALSE, FALSE,TRUE, TRUE,'Exception Only','["Prior authorization required and not yet evidenced."]'::jsonb,'pending','doctor_review','["Prior authorization required and not yet evidenced."]'::jsonb,'Doctor review required (accept/reject/modify).',0.28,'Prior authorization required and not yet evidenced.'),
('10010','1013', TRUE,'2', FALSE,TRUE, FALSE,TRUE, TRUE,'Preferred','[]'::jsonb,'pass',NULL,'[]'::jsonb,NULL,0.93,'Preferred formulary preference. All policy checks passed.');

-- ---- RX-20260629-00011: 2 candidates, pass / quantity fail ----
INSERT INTO drug_policy_evaluations
(rx_number, candidate_drug_id, covered, tier, pa_required, pa_met, step_therapy_required, step_therapy_met, quantity_ok, formulary_preference, violations, policy_state, pending_type, pending_reasons, review_recommendation, score, notes) VALUES
('RX-20260629-00011','1018', TRUE,'3', FALSE,TRUE, FALSE,TRUE, TRUE,'Non Preferred','[]'::jsonb,'pass',NULL,'[]'::jsonb,NULL,0.72,'Non Preferred formulary preference. All policy checks passed.'),
('RX-20260629-00011','1042', TRUE,'2', FALSE,TRUE, FALSE,TRUE, FALSE,'Preferred','["Requested quantity exceeds plan limit."]'::jsonb,'fail',NULL,'[]'::jsonb,NULL,0.22,'Requested quantity exceeds plan limit.');

-- ---- RX-20260706-00012: 3 candidates, pass / pending (PA) / pass ----
INSERT INTO drug_policy_evaluations
(rx_number, candidate_drug_id, covered, tier, pa_required, pa_met, step_therapy_required, step_therapy_met, quantity_ok, formulary_preference, violations, policy_state, pending_type, pending_reasons, review_recommendation, score, notes) VALUES
('RX-20260706-00012','1044', TRUE,'1', FALSE,TRUE, FALSE,TRUE, TRUE,'Preferred','[]'::jsonb,'pass',NULL,'[]'::jsonb,NULL,0.94,'Preferred formulary preference. All policy checks passed.'),
('RX-20260706-00012','1007', TRUE,'4', TRUE,FALSE, FALSE,TRUE, TRUE,'Exception Only','["Prior authorization required and not yet evidenced."]'::jsonb,'pending','doctor_review','["Prior authorization required and not yet evidenced."]'::jsonb,'Doctor review required (accept/reject/modify).',0.29,'Prior authorization required and not yet evidenced.'),
('RX-20260706-00012','1016', TRUE,'3', FALSE,TRUE, FALSE,TRUE, TRUE,'Non Preferred','[]'::jsonb,'pass',NULL,'[]'::jsonb,NULL,0.68,'Non Preferred formulary preference. All policy checks passed.');

-- ---- RX-20260706-00013: 1 candidate, not covered ----
INSERT INTO drug_policy_evaluations
(rx_number, candidate_drug_id, covered, tier, pa_required, pa_met, step_therapy_required, step_therapy_met, quantity_ok, formulary_preference, violations, policy_state, pending_type, pending_reasons, review_recommendation, score, notes) VALUES
('RX-20260706-00013','1050', FALSE,NULL, FALSE,TRUE, FALSE,TRUE, TRUE,'Not Covered','["Drug not covered under plan formulary."]'::jsonb,'fail',NULL,'[]'::jsonb,NULL,0.03,'Drug not covered under plan formulary.');

-- ---- RX-20260706-00014: 4 candidates, pass / pending(step) / pending(PA) / pass ----
INSERT INTO drug_policy_evaluations
(rx_number, candidate_drug_id, covered, tier, pa_required, pa_met, step_therapy_required, step_therapy_met, quantity_ok, formulary_preference, violations, policy_state, pending_type, pending_reasons, review_recommendation, score, notes) VALUES
('RX-20260706-00014','1006', TRUE,'2', FALSE,TRUE, FALSE,TRUE, TRUE,'Preferred','[]'::jsonb,'pass',NULL,'[]'::jsonb,NULL,0.90,'Preferred formulary preference. All policy checks passed.'),
('RX-20260706-00014','1025', TRUE,'3', FALSE,TRUE, TRUE,FALSE, TRUE,'Non Preferred','["Step therapy requirement not met."]'::jsonb,'pending','doctor_review','["Step therapy requirement not met."]'::jsonb,'Doctor review required (accept/reject/modify).',0.36,'Step therapy requirement not met.'),
('RX-20260706-00014','1034', TRUE,'4', TRUE,FALSE, FALSE,TRUE, TRUE,'Exception Only','["Prior authorization required and not yet evidenced."]'::jsonb,'pending','doctor_review','["Prior authorization required and not yet evidenced."]'::jsonb,'Doctor review required (accept/reject/modify).',0.27,'Prior authorization required and not yet evidenced.'),
('RX-20260706-00014','1049', TRUE,'3', FALSE,TRUE, FALSE,TRUE, TRUE,'Non Preferred','[]'::jsonb,'pass',NULL,'[]'::jsonb,NULL,0.73,'Non Preferred formulary preference. All policy checks passed.');

-- ---- RX-20260707-00015: 2 candidates, pass / pending (both PA+step not met) ----
INSERT INTO drug_policy_evaluations
(rx_number, candidate_drug_id, covered, tier, pa_required, pa_met, step_therapy_required, step_therapy_met, quantity_ok, formulary_preference, violations, policy_state, pending_type, pending_reasons, review_recommendation, score, notes) VALUES
('RX-20260707-00015','1021', TRUE,'2', FALSE,TRUE, FALSE,TRUE, TRUE,'Preferred','[]'::jsonb,'pass',NULL,'[]'::jsonb,NULL,0.92,'Preferred formulary preference. All policy checks passed.'),
('RX-20260707-00015','1029', TRUE,'5', TRUE,FALSE, TRUE,FALSE, TRUE,'Exception Only','["Prior authorization required and not yet evidenced.","Step therapy requirement not met."]'::jsonb,'pending','doctor_review','["Prior authorization required and not yet evidenced.","Step therapy requirement not met."]'::jsonb,'Doctor review required (accept/reject/modify).',0.15,'Prior authorization required and not yet evidenced. Step therapy requirement not met.');

-- ============================================================
-- Sanity check queries
-- ============================================================
-- SELECT rx_number, COUNT(*) AS candidate_count
-- FROM drug_policy_evaluations
-- GROUP BY rx_number
-- ORDER BY rx_number;

-- SELECT policy_state, COUNT(*) FROM drug_policy_evaluations GROUP BY policy_state;
