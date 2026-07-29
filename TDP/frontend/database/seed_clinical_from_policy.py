import json
import sqlite3
from pathlib import Path

DB_PATH = Path("policy_agent.db")
SCHEMA_PATH = Path("clinical_agent_schema_sqlite.sql")


def score_by_policy_state(policy_state: str, covered: int, tier: str | None, quantity_ok: int):
    if policy_state == "pass":
        similarity = {"1": 0.96, "2": 0.93, "3": 0.90, "4": 0.87, "5": 0.84}.get(str(tier), 0.88)
        safety = 0.93 if quantity_ok else 0.78
        overall = "PASS"
        recommendation = "CLINICALLY_ACCEPTABLE"
    elif policy_state == "pending":
        similarity = {"1": 0.86, "2": 0.83, "3": 0.80, "4": 0.76, "5": 0.72}.get(str(tier), 0.75)
        safety = 0.70 if covered else 0.45
        overall = "REVIEW"
        recommendation = "REQUIRES_CLINICAL_REVIEW"
    else:
        similarity = 0.38 if covered else 0.22
        safety = 0.42 if quantity_ok else 0.30
        overall = "FAIL"
        recommendation = "NOT_CLINICALLY_ACCEPTABLE"

    clinical = round((similarity + safety) / 2, 3)
    return similarity, safety, clinical, overall, recommendation


def build_payload(row):
    (
        rx_number,
        candidate_drug_id,
        covered,
        tier,
        pa_required,
        pa_met,
        step_required,
        step_met,
        quantity_ok,
        policy_state,
        violations,
    ) = row

    similarity, safety, clinical, overall, recommendation = score_by_policy_state(
        policy_state, covered, tier, quantity_ok
    )

    stage_a_status = "PASS" if similarity >= 0.85 else ("REVIEW" if similarity >= 0.65 else "FAIL")
    stage_b_status = "PASS" if safety >= 0.85 else ("REVIEW" if safety >= 0.60 else "FAIL")
    stage_c_status = "PASS" if overall == "PASS" else ("REVIEW" if overall == "REVIEW" else "FAIL")

    evidence = {
        "ingredient": round(max(similarity - 0.16, 0.0), 2),
        "moiety": round(max(similarity - 0.08, 0.0), 2),
        "class": round(min(similarity + 0.07, 1.0), 2),
        "moa": round(min(similarity + 0.06, 1.0), 2),
        "combo": 1.0,
        "route": 1.0,
        "form": 1.0,
        "strength": round(max(similarity - 0.12, 0.0), 2),
    }

    hard_gates = {
        "allergy": "PASS",
        "cross_reactivity": "PASS",
        "contraindication": "PASS" if covered else "FAIL",
        "duplicate_therapy": "REVIEW" if policy_state == "pending" else "PASS",
        "major_interaction": "PASS",
        "renal_contraindication": "PASS",
        "hepatic_contraindication": "PASS",
    }

    soft_safety = {
        "interaction": {"severity": "NONE", "score": 1.0},
        "renal": {"severity": "NONE", "score": 1.0},
        "hepatic": {
            "severity": "MILD" if policy_state != "fail" else "MODERATE",
            "score": 0.9 if policy_state != "fail" else 0.7,
        },
        "geriatric": {"severity": "LOW", "score": 1.0},
        "duplicate_therapy": {
            "severity": "SAME_CLASS" if policy_state == "pending" else "LOW",
            "score": 0.8 if policy_state == "pending" else 0.95,
        },
    }

    rationale = [
        "Same indication" if covered else "Coverage mismatch observed",
        "Same therapeutic class",
        "No major interaction identified",
        "No allergy conflict identified",
    ]

    if quantity_ok:
        rationale.append("Dose quantity within expected threshold")
    else:
        rationale.append("Quantity concern flagged")

    if violations and violations != "[]":
        rationale.append("Policy violations require additional review")

    raw_response = {
        "candidate_id": int(candidate_drug_id),
        "candidate_name": f"Drug {candidate_drug_id}",
        "overall_status": overall,
        "stage_a": {
            "status": stage_a_status,
            "similarity_score": similarity,
            "evidence": evidence,
            "llm_review_required": overall != "PASS",
        },
        "stage_b": {
            "status": stage_b_status,
            "hard_gates": hard_gates,
            "soft_safety": soft_safety,
            "safety_score": safety,
        },
        "stage_c": {
            "status": stage_c_status,
            "clinical_rationale": rationale,
            "recommendation": recommendation,
        },
        "clinical_assessment": {
            "similarity_score": similarity,
            "safety_score": safety,
            "clinical_score": clinical,
        },
    }

    return {
        "rx_number": rx_number,
        "candidate_drug_id": candidate_drug_id,
        "candidate_name": f"Drug {candidate_drug_id}",
        "overall_status": overall,
        "stage_a_status": stage_a_status,
        "stage_a_similarity_score": similarity,
        "stage_a_evidence_json": json.dumps(evidence),
        "stage_a_llm_review_required": 0 if overall == "PASS" else 1,
        "stage_b_status": stage_b_status,
        "stage_b_hard_gates_json": json.dumps(hard_gates),
        "stage_b_soft_safety_json": json.dumps(soft_safety),
        "stage_b_safety_score": safety,
        "stage_c_status": stage_c_status,
        "stage_c_clinical_rationale": json.dumps(rationale),
        "stage_c_recommendation": recommendation,
        "assessment_similarity_score": similarity,
        "assessment_safety_score": safety,
        "assessment_clinical_score": clinical,
        "raw_response": json.dumps(raw_response),
    }


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")

    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    conn.executescript(schema_sql)

    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            rx_number,
            candidate_drug_id,
            covered,
            tier,
            pa_required,
            pa_met,
            step_therapy_required,
            step_therapy_met,
            quantity_ok,
            policy_state,
            violations
        FROM drug_policy_evaluations
        ORDER BY rx_number, candidate_drug_id
        """
    )
    policy_rows = cur.fetchall()

    insert_sql = """
        INSERT INTO clinical_evaluations (
            rx_number,
            candidate_drug_id,
            candidate_name,
            overall_status,
            stage_a_status,
            stage_a_similarity_score,
            stage_a_evidence_json,
            stage_a_llm_review_required,
            stage_b_status,
            stage_b_hard_gates_json,
            stage_b_soft_safety_json,
            stage_b_safety_score,
            stage_c_status,
            stage_c_clinical_rationale,
            stage_c_recommendation,
            assessment_similarity_score,
            assessment_safety_score,
            assessment_clinical_score,
            raw_response
        ) VALUES (
            :rx_number,
            :candidate_drug_id,
            :candidate_name,
            :overall_status,
            :stage_a_status,
            :stage_a_similarity_score,
            :stage_a_evidence_json,
            :stage_a_llm_review_required,
            :stage_b_status,
            :stage_b_hard_gates_json,
            :stage_b_soft_safety_json,
            :stage_b_safety_score,
            :stage_c_status,
            :stage_c_clinical_rationale,
            :stage_c_recommendation,
            :assessment_similarity_score,
            :assessment_safety_score,
            :assessment_clinical_score,
            :raw_response
        )
        ON CONFLICT(rx_number, candidate_drug_id) DO UPDATE SET
            candidate_name = excluded.candidate_name,
            overall_status = excluded.overall_status,
            stage_a_status = excluded.stage_a_status,
            stage_a_similarity_score = excluded.stage_a_similarity_score,
            stage_a_evidence_json = excluded.stage_a_evidence_json,
            stage_a_llm_review_required = excluded.stage_a_llm_review_required,
            stage_b_status = excluded.stage_b_status,
            stage_b_hard_gates_json = excluded.stage_b_hard_gates_json,
            stage_b_soft_safety_json = excluded.stage_b_soft_safety_json,
            stage_b_safety_score = excluded.stage_b_safety_score,
            stage_c_status = excluded.stage_c_status,
            stage_c_clinical_rationale = excluded.stage_c_clinical_rationale,
            stage_c_recommendation = excluded.stage_c_recommendation,
            assessment_similarity_score = excluded.assessment_similarity_score,
            assessment_safety_score = excluded.assessment_safety_score,
            assessment_clinical_score = excluded.assessment_clinical_score,
            raw_response = excluded.raw_response
    """

    payloads = [build_payload(r) for r in policy_rows]
    cur.executemany(insert_sql, payloads)

    cur.execute("SELECT COUNT(1) FROM drug_policy_evaluations")
    policy_count = cur.fetchone()[0]

    cur.execute("SELECT COUNT(1) FROM clinical_evaluations")
    clinical_count = cur.fetchone()[0]

    cur.execute(
        """
        SELECT p.rx_number, COUNT(1) AS policy_n,
               COALESCE(c.clinical_n, 0) AS clinical_n
        FROM drug_policy_evaluations p
        LEFT JOIN (
            SELECT rx_number, COUNT(1) AS clinical_n
            FROM clinical_evaluations
            GROUP BY rx_number
        ) c ON c.rx_number = p.rx_number
        GROUP BY p.rx_number
        ORDER BY p.rx_number
        """
    )
    per_rx = cur.fetchall()

    conn.commit()
    conn.close()

    print(f"Policy rows={policy_count}, Clinical rows={clinical_count}")
    for rx, policy_n, clinical_n in per_rx:
        print(f"{rx}: policy={policy_n}, clinical={clinical_n}")


if __name__ == "__main__":
    main()
