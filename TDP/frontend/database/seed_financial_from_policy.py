import json
import sqlite3
from pathlib import Path

DB_PATH = Path("policy_agent.db")
SCHEMA_PATH = Path("financial_agent_schema_sqlite.sql")


def tier_rank(tier: str | None) -> int:
    mapping = {"1": 1, "2": 2, "3": 3, "4": 4, "5": 5}
    if tier is None:
        return 5
    return mapping.get(str(tier), 5)


def make_dummy_money(candidate_drug_id: str, base_rank: int):
    seed = int(candidate_drug_id) % 17
    original_price = round(18 + (base_rank * 8) + seed * 1.7, 2)
    original_copay = round(5 + (base_rank * 2) + (seed % 4), 2)

    alt_price = round(max(original_price * 0.82, 6.0), 2)
    alt_copay = round(max(original_copay * 0.75, 2.0), 2)

    original_total = original_price
    alt_total = alt_price

    original_plan_paid = round(max(original_total - original_copay, 0.0), 2)
    alt_plan_paid = round(max(alt_total - alt_copay, 0.0), 2)

    savings = round(max(original_total - alt_total, 0.0), 2)
    annual = round(savings * 12, 2)
    member_pct = round((savings / original_total) * 100, 2) if original_total else 0.0

    return {
        "original_price": original_price,
        "original_copay": original_copay,
        "alternative_price": alt_price,
        "alternative_copay": alt_copay,
        "original_total_cost": original_total,
        "alternative_total_cost": alt_total,
        "original_plan_paid": original_plan_paid,
        "alternative_plan_paid": alt_plan_paid,
        "savings": savings,
        "estimated_annual_savings": annual,
        "member_savings_percentage": member_pct,
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
            p.rx_number,
            p.candidate_drug_id,
            p.tier,
            p.formulary_preference,
            p.pa_required,
            p.step_therapy_required,
            c.drug_id,
            c.quantity,
            c.fill_date
        FROM drug_policy_evaluations p
        JOIN claims c ON c.rx_number = p.rx_number
        ORDER BY p.rx_number, p.candidate_drug_id
        """
    )
    rows = cur.fetchall()

    insert_original = """
        INSERT INTO financial_original_drug (
            rx_number, candidate_drug_id, original_drug_id,
            original_drug_name, original_generic_name, original_dosage,
            original_quantity, original_days_supply,
            original_tier, original_price, original_copay,
            original_total_cost, original_plan_paid,
            insurance_phase, ytd_oop, deductible_cap, oop_max_cap,
            deductible_remaining, oop_remaining, deductible_met, oop_met,
            coinsurance_percentage, formulary_status,
            prior_authorization_required, step_therapy_required,
            pbm_name, policy_id, formulary_version,
            effective_date, expiration_date, raw_response
        ) VALUES (
            :rx_number, :candidate_drug_id, :original_drug_id,
            :original_drug_name, :original_generic_name, :original_dosage,
            :original_quantity, :original_days_supply,
            :original_tier, :original_price, :original_copay,
            :original_total_cost, :original_plan_paid,
            :insurance_phase, :ytd_oop, :deductible_cap, :oop_max_cap,
            :deductible_remaining, :oop_remaining, :deductible_met, :oop_met,
            :coinsurance_percentage, :formulary_status,
            :prior_authorization_required, :step_therapy_required,
            :pbm_name, :policy_id, :formulary_version,
            :effective_date, :expiration_date, :raw_response
        )
        ON CONFLICT(rx_number, candidate_drug_id) DO UPDATE SET
            original_drug_id = excluded.original_drug_id,
            original_drug_name = excluded.original_drug_name,
            original_generic_name = excluded.original_generic_name,
            original_dosage = excluded.original_dosage,
            original_quantity = excluded.original_quantity,
            original_days_supply = excluded.original_days_supply,
            original_tier = excluded.original_tier,
            original_price = excluded.original_price,
            original_copay = excluded.original_copay,
            original_total_cost = excluded.original_total_cost,
            original_plan_paid = excluded.original_plan_paid,
            insurance_phase = excluded.insurance_phase,
            ytd_oop = excluded.ytd_oop,
            deductible_cap = excluded.deductible_cap,
            oop_max_cap = excluded.oop_max_cap,
            deductible_remaining = excluded.deductible_remaining,
            oop_remaining = excluded.oop_remaining,
            deductible_met = excluded.deductible_met,
            oop_met = excluded.oop_met,
            coinsurance_percentage = excluded.coinsurance_percentage,
            formulary_status = excluded.formulary_status,
            prior_authorization_required = excluded.prior_authorization_required,
            step_therapy_required = excluded.step_therapy_required,
            pbm_name = excluded.pbm_name,
            policy_id = excluded.policy_id,
            formulary_version = excluded.formulary_version,
            effective_date = excluded.effective_date,
            expiration_date = excluded.expiration_date,
            raw_response = excluded.raw_response
    """

    insert_alternative = """
        INSERT INTO financial_alternative_drug (
            rx_number, candidate_drug_id, alternative_drug_id,
            alternative_drug_name, alternative_generic_name, alternative_dosage,
            alternative_quantity, alternative_days_supply,
            alternative_tier, alternative_price, alternative_copay,
            alternative_total_cost, alternative_plan_paid,
            savings, estimated_annual_savings, member_savings_percentage,
            insurance_phase, ytd_oop, deductible_cap, oop_max_cap,
            deductible_remaining, oop_remaining,
            formulary_status, prior_authorization_required, step_therapy_required,
            pbm_name, policy_id, formulary_version,
            effective_date, expiration_date, raw_response
        ) VALUES (
            :rx_number, :candidate_drug_id, :alternative_drug_id,
            :alternative_drug_name, :alternative_generic_name, :alternative_dosage,
            :alternative_quantity, :alternative_days_supply,
            :alternative_tier, :alternative_price, :alternative_copay,
            :alternative_total_cost, :alternative_plan_paid,
            :savings, :estimated_annual_savings, :member_savings_percentage,
            :insurance_phase, :ytd_oop, :deductible_cap, :oop_max_cap,
            :deductible_remaining, :oop_remaining,
            :formulary_status, :prior_authorization_required, :step_therapy_required,
            :pbm_name, :policy_id, :formulary_version,
            :effective_date, :expiration_date, :raw_response
        )
        ON CONFLICT(rx_number, candidate_drug_id) DO UPDATE SET
            alternative_drug_id = excluded.alternative_drug_id,
            alternative_drug_name = excluded.alternative_drug_name,
            alternative_generic_name = excluded.alternative_generic_name,
            alternative_dosage = excluded.alternative_dosage,
            alternative_quantity = excluded.alternative_quantity,
            alternative_days_supply = excluded.alternative_days_supply,
            alternative_tier = excluded.alternative_tier,
            alternative_price = excluded.alternative_price,
            alternative_copay = excluded.alternative_copay,
            alternative_total_cost = excluded.alternative_total_cost,
            alternative_plan_paid = excluded.alternative_plan_paid,
            savings = excluded.savings,
            estimated_annual_savings = excluded.estimated_annual_savings,
            member_savings_percentage = excluded.member_savings_percentage,
            insurance_phase = excluded.insurance_phase,
            ytd_oop = excluded.ytd_oop,
            deductible_cap = excluded.deductible_cap,
            oop_max_cap = excluded.oop_max_cap,
            deductible_remaining = excluded.deductible_remaining,
            oop_remaining = excluded.oop_remaining,
            formulary_status = excluded.formulary_status,
            prior_authorization_required = excluded.prior_authorization_required,
            step_therapy_required = excluded.step_therapy_required,
            pbm_name = excluded.pbm_name,
            policy_id = excluded.policy_id,
            formulary_version = excluded.formulary_version,
            effective_date = excluded.effective_date,
            expiration_date = excluded.expiration_date,
            raw_response = excluded.raw_response
    """

    original_payloads = []
    alternative_payloads = []

    for rx_number, candidate_drug_id, tier, formulary_pref, pa_req, step_req, original_drug_id, quantity, fill_date in rows:
        rank = tier_rank(tier)
        m = make_dummy_money(candidate_drug_id, rank)

        deductible_cap = 750.0
        oop_cap = 3000.0
        ytd_oop = round((int(candidate_drug_id) % 35) * 12.0, 2)
        deductible_remaining = round(max(deductible_cap - min(ytd_oop, deductible_cap), 0.0), 2)
        oop_remaining = round(max(oop_cap - ytd_oop, 0.0), 2)

        common = {
            "rx_number": rx_number,
            "candidate_drug_id": candidate_drug_id,
            "insurance_phase": "Standard Coverage",
            "ytd_oop": ytd_oop,
            "deductible_cap": deductible_cap,
            "oop_max_cap": oop_cap,
            "deductible_remaining": deductible_remaining,
            "oop_remaining": oop_remaining,
            "formulary_status": formulary_pref or "Non Preferred",
            "prior_authorization_required": int(pa_req or 0),
            "step_therapy_required": int(step_req or 0),
            "pbm_name": "Default PBM",
            "policy_id": f"FIN-{rx_number}-{candidate_drug_id}",
            "formulary_version": "v2026.07",
            "effective_date": fill_date,
            "expiration_date": "2027-12-31",
        }

        original_payload = {
            **common,
            "original_drug_id": original_drug_id,
            "original_drug_name": f"Drug {original_drug_id}",
            "original_generic_name": f"Generic {original_drug_id}",
            "original_dosage": "10 mg",
            "original_quantity": int(quantity),
            "original_days_supply": 30,
            "original_tier": f"Tier {rank}",
            "original_price": m["original_price"],
            "original_copay": m["original_copay"],
            "original_total_cost": m["original_total_cost"],
            "original_plan_paid": m["original_plan_paid"],
            "deductible_met": round(ytd_oop, 2),
            "oop_met": round(ytd_oop, 2),
            "coinsurance_percentage": 20.0,
            "raw_response": json.dumps(
                {
                    "side": "original",
                    "rx_number": rx_number,
                    "candidate_drug_id": candidate_drug_id,
                    "original_drug_id": original_drug_id,
                    "financials": {
                        "tier": f"Tier {rank}",
                        "price": m["original_price"],
                        "copay": m["original_copay"],
                        "total_cost": m["original_total_cost"],
                    },
                }
            ),
        }

        alt_rank = max(rank - 1, 1)
        alternative_payload = {
            **common,
            "alternative_drug_id": candidate_drug_id,
            "alternative_drug_name": f"Drug {candidate_drug_id}",
            "alternative_generic_name": f"Generic {candidate_drug_id}",
            "alternative_dosage": "10 mg",
            "alternative_quantity": int(quantity),
            "alternative_days_supply": 30,
            "alternative_tier": f"Tier {alt_rank}",
            "alternative_price": m["alternative_price"],
            "alternative_copay": m["alternative_copay"],
            "alternative_total_cost": m["alternative_total_cost"],
            "alternative_plan_paid": m["alternative_plan_paid"],
            "savings": m["savings"],
            "estimated_annual_savings": m["estimated_annual_savings"],
            "member_savings_percentage": m["member_savings_percentage"],
            "raw_response": json.dumps(
                {
                    "side": "alternative",
                    "rx_number": rx_number,
                    "candidate_drug_id": candidate_drug_id,
                    "alternative_drug_id": candidate_drug_id,
                    "financials": {
                        "tier": f"Tier {alt_rank}",
                        "price": m["alternative_price"],
                        "copay": m["alternative_copay"],
                        "total_cost": m["alternative_total_cost"],
                        "savings": m["savings"],
                    },
                }
            ),
        }

        original_payloads.append(original_payload)
        alternative_payloads.append(alternative_payload)

    cur.executemany(insert_original, original_payloads)
    cur.executemany(insert_alternative, alternative_payloads)

    cur.execute("SELECT COUNT(1) FROM drug_policy_evaluations")
    policy_count = cur.fetchone()[0]

    cur.execute("SELECT COUNT(1) FROM financial_original_drug")
    orig_count = cur.fetchone()[0]

    cur.execute("SELECT COUNT(1) FROM financial_alternative_drug")
    alt_count = cur.fetchone()[0]

    cur.execute(
        """
        SELECT p.rx_number,
               COUNT(1) AS policy_n,
               COALESCE(o.original_n, 0) AS original_n,
               COALESCE(a.alternative_n, 0) AS alternative_n
        FROM drug_policy_evaluations p
        LEFT JOIN (
            SELECT rx_number, COUNT(1) AS original_n
            FROM financial_original_drug
            GROUP BY rx_number
        ) o ON o.rx_number = p.rx_number
        LEFT JOIN (
            SELECT rx_number, COUNT(1) AS alternative_n
            FROM financial_alternative_drug
            GROUP BY rx_number
        ) a ON a.rx_number = p.rx_number
        GROUP BY p.rx_number
        ORDER BY p.rx_number
        """
    )
    parity = cur.fetchall()

    conn.commit()
    conn.close()

    print(
        f"Policy rows={policy_count}, Original financial rows={orig_count}, Alternative financial rows={alt_count}"
    )
    for rx_number, policy_n, original_n, alternative_n in parity:
        print(
            f"{rx_number}: policy={policy_n}, original={original_n}, alternative={alternative_n}"
        )


if __name__ == "__main__":
    main()
