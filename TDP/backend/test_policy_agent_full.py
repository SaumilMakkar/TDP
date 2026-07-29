import asyncio
import csv
import tempfile
import unittest
from pathlib import Path

from app.agents import policy_agent as policy_module


def _write_csv(path: Path, headers, rows):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _clear_policy_caches():
    policy_module._products.cache_clear()
    policy_module._plans.cache_clear()
    policy_module._plan_drug_status.cache_clear()
    policy_module._formulary_alternatives.cache_clear()
    policy_module._claims_by_member.cache_clear()


def _product(prod_sk: str, active: str = "Y", term_dt: str = "2029-12-31"):
    return {
        "PROD_SK": prod_sk,
        "PROD_ID": f"PROD{prod_sk}",
        "PROD_NM": f"Drug {prod_sk}",
        "GNRC_NM": f"generic{prod_sk}",
        "THRPC_CLASS_NM": "Class",
        "DISE_CAT_NM": "Condition",
        "DRG_DOSAG_FRM_NM": "Tablet",
        "NDC": f"{int(prod_sk):011d}",
        "GPI": "111",
        "DRG_DRG_INTRCTN_DESC": "",
        "BASE_PRICE": "10.0",
        "BRAND_IND": "N",
        "CONTROLLED_SUB_FLG": "N",
        "NARROW_THRPTC_IDX_FLG": "N",
        "PROD_ACTV_FLG": active,
        "PROD_EFF_DT": "2020-01-01",
        "PROD_TERM_DT": term_dt,
        "GPI_NO": "",
        "DRG_CLASS_NM": "",
        "DRG_SUB_CLASS_NM": "",
        "DRG_FDA_THRPC_EQVLC_CD": "AB",
    }


class TestPolicyAgentFull(unittest.TestCase):
    def _call(self, **overrides):
        payload = {
            "drug_id": "1001",
            "plan_id": "3010",
            "member_id": "2001",
            "fill_date": "2025-06-01",
            "quantity": 30,
        }
        payload.update(overrides)
        return asyncio.run(policy_module.policy_agent(payload))

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        data_dir = Path(self.tmp.name)

        _write_csv(
            data_dir / "v_d_product.csv",
            [
                "PROD_SK", "PROD_ID", "PROD_NM", "GNRC_NM", "THRPC_CLASS_NM", "DISE_CAT_NM",
                "DRG_DOSAG_FRM_NM", "NDC", "GPI", "DRG_DRG_INTRCTN_DESC", "BASE_PRICE", "BRAND_IND",
                "CONTROLLED_SUB_FLG", "NARROW_THRPTC_IDX_FLG", "PROD_ACTV_FLG", "PROD_EFF_DT", "PROD_TERM_DT",
                "GPI_NO", "DRG_CLASS_NM", "DRG_SUB_CLASS_NM", "DRG_FDA_THRPC_EQVLC_CD",
            ],
            [
                _product("1001"), _product("1002"), _product("1003"), _product("1004"), _product("1005"),
                _product("1006"), _product("1007"), _product("1008"), _product("1010"), _product("1011"), _product("1012"),
                _product("1999", active="N", term_dt="2020-12-31"),
            ],
        )

        _write_csv(
            data_dir / "v_d_plan.csv",
            ["PLN_SK", "PLN_DFLT_DRG_STAT", "PLN_EFF_DT", "PLN_TERM_DT"],
            [
                {"PLN_SK": "3010", "PLN_DFLT_DRG_STAT": "COV", "PLN_EFF_DT": "2020-01-01", "PLN_TERM_DT": "2030-12-31"},
                {"PLN_SK": "3999", "PLN_DFLT_DRG_STAT": "NC", "PLN_EFF_DT": "2020-01-01", "PLN_TERM_DT": "2030-12-31"},
                {"PLN_SK": "3555", "PLN_DFLT_DRG_STAT": "COV", "PLN_EFF_DT": "2010-01-01", "PLN_TERM_DT": "2020-12-31"},
            ],
        )

        _write_csv(
            data_dir / "v_d_plan_drug_status.csv",
            [
                "PLN_DRG_STAT_SK", "PLN_SK", "PROD_SK", "PLN_DRG_STAT_CD", "PLN_DRG_STAT_DESC", "PLN_DRG_STAT_GRP_CD",
                "PLN_DRG_STAT_GRP_DESC", "FORMULARY_TIER", "PA_REQUIRED_FLG", "STEP_THERAPY_FLG", "QUANTITY_LIMIT",
                "EFF_DT", "TERM_DT",
            ],
            [
                {"PLN_DRG_STAT_SK": "1", "PLN_SK": "3010", "PROD_SK": "1001", "PLN_DRG_STAT_CD": "COV", "PLN_DRG_STAT_DESC": "Covered", "PLN_DRG_STAT_GRP_CD": "ACTIVE", "PLN_DRG_STAT_GRP_DESC": "Covered", "FORMULARY_TIER": "1", "PA_REQUIRED_FLG": "N", "STEP_THERAPY_FLG": "N", "QUANTITY_LIMIT": "", "EFF_DT": "2023-01-01", "TERM_DT": "2029-12-31"},
                {"PLN_DRG_STAT_SK": "2", "PLN_SK": "3010", "PROD_SK": "1002", "PLN_DRG_STAT_CD": "PA", "PLN_DRG_STAT_DESC": "Prior Auth", "PLN_DRG_STAT_GRP_CD": "RESTRICTED", "PLN_DRG_STAT_GRP_DESC": "PA", "FORMULARY_TIER": "2", "PA_REQUIRED_FLG": "Y", "STEP_THERAPY_FLG": "N", "QUANTITY_LIMIT": "", "EFF_DT": "2023-01-01", "TERM_DT": "2029-12-31"},
                {"PLN_DRG_STAT_SK": "3", "PLN_SK": "3010", "PROD_SK": "1003", "PLN_DRG_STAT_CD": "ST", "PLN_DRG_STAT_DESC": "Step Therapy", "PLN_DRG_STAT_GRP_CD": "RESTRICTED", "PLN_DRG_STAT_GRP_DESC": "ST", "FORMULARY_TIER": "2", "PA_REQUIRED_FLG": "N", "STEP_THERAPY_FLG": "Y", "QUANTITY_LIMIT": "", "EFF_DT": "2023-01-01", "TERM_DT": "2029-12-31"},
                {"PLN_DRG_STAT_SK": "4", "PLN_SK": "3010", "PROD_SK": "1004", "PLN_DRG_STAT_CD": "QL", "PLN_DRG_STAT_DESC": "Quantity Limit", "PLN_DRG_STAT_GRP_CD": "RESTRICTED", "PLN_DRG_STAT_GRP_DESC": "QL", "FORMULARY_TIER": "3", "PA_REQUIRED_FLG": "N", "STEP_THERAPY_FLG": "N", "QUANTITY_LIMIT": "30", "EFF_DT": "2023-01-01", "TERM_DT": "2029-12-31"},
                {"PLN_DRG_STAT_SK": "5", "PLN_SK": "3010", "PROD_SK": "1005", "PLN_DRG_STAT_CD": "NF", "PLN_DRG_STAT_DESC": "Non Formulary", "PLN_DRG_STAT_GRP_CD": "RESTRICTED", "PLN_DRG_STAT_GRP_DESC": "NF", "FORMULARY_TIER": "4", "PA_REQUIRED_FLG": "N", "STEP_THERAPY_FLG": "N", "QUANTITY_LIMIT": "", "EFF_DT": "2023-01-01", "TERM_DT": "2029-12-31"},
                {"PLN_DRG_STAT_SK": "6", "PLN_SK": "3010", "PROD_SK": "1006", "PLN_DRG_STAT_CD": "EX", "PLN_DRG_STAT_DESC": "Excluded", "PLN_DRG_STAT_GRP_CD": "INACTIVE", "PLN_DRG_STAT_GRP_DESC": "Inactive", "FORMULARY_TIER": "4", "PA_REQUIRED_FLG": "N", "STEP_THERAPY_FLG": "N", "QUANTITY_LIMIT": "", "EFF_DT": "2023-01-01", "TERM_DT": "2029-12-31"},
                {"PLN_DRG_STAT_SK": "7", "PLN_SK": "3010", "PROD_SK": "1007", "PLN_DRG_STAT_CD": "NC", "PLN_DRG_STAT_DESC": "Not Covered", "PLN_DRG_STAT_GRP_CD": "INACTIVE", "PLN_DRG_STAT_GRP_DESC": "Inactive", "FORMULARY_TIER": "4", "PA_REQUIRED_FLG": "N", "STEP_THERAPY_FLG": "N", "QUANTITY_LIMIT": "", "EFF_DT": "2023-01-01", "TERM_DT": "2029-12-31"},
                {"PLN_DRG_STAT_SK": "8", "PLN_SK": "3010", "PROD_SK": "1008", "PLN_DRG_STAT_CD": "COV", "PLN_DRG_STAT_DESC": "Covered", "PLN_DRG_STAT_GRP_CD": "ACTIVE", "PLN_DRG_STAT_GRP_DESC": "Covered", "FORMULARY_TIER": "2", "PA_REQUIRED_FLG": "N", "STEP_THERAPY_FLG": "N", "QUANTITY_LIMIT": "", "EFF_DT": "2023-01-01", "TERM_DT": "2029-12-31"},
                {"PLN_DRG_STAT_SK": "9", "PLN_SK": "3010", "PROD_SK": "1010", "PLN_DRG_STAT_CD": "COV", "PLN_DRG_STAT_DESC": "Covered", "PLN_DRG_STAT_GRP_CD": "ACTIVE", "PLN_DRG_STAT_GRP_DESC": "Covered", "FORMULARY_TIER": "2", "PA_REQUIRED_FLG": "N", "STEP_THERAPY_FLG": "N", "QUANTITY_LIMIT": "", "EFF_DT": "2023-01-01", "TERM_DT": "2029-12-31"},
                {"PLN_DRG_STAT_SK": "10", "PLN_SK": "3010", "PROD_SK": "1012", "PLN_DRG_STAT_CD": "COV", "PLN_DRG_STAT_DESC": "Covered", "PLN_DRG_STAT_GRP_CD": "ACTIVE", "PLN_DRG_STAT_GRP_DESC": "Covered", "FORMULARY_TIER": "2", "PA_REQUIRED_FLG": "N", "STEP_THERAPY_FLG": "N", "QUANTITY_LIMIT": "", "EFF_DT": "2023-01-01", "TERM_DT": "2029-12-31"},
            ],
        )

        _write_csv(
            data_dir / "v_d_formulary_alternative.csv",
            ["TRGT_PROD_SK", "ALT_PROD_SK", "ALT_SEQ_NBR"],
            [{"TRGT_PROD_SK": "1003", "ALT_PROD_SK": "1010", "ALT_SEQ_NBR": "1"}],
        )

        _write_csv(
            data_dir / "F_CLM_TRANSACTION.csv",
            ["MBR_SK", "PROD_SK", "PLN_SK", "PA_APPROVED_FLG"],
            [
                {"MBR_SK": "2002", "PROD_SK": "1002", "PLN_SK": "3010", "PA_APPROVED_FLG": "Y"},
                {"MBR_SK": "2003", "PROD_SK": "1010", "PLN_SK": "3010", "PA_APPROVED_FLG": "N"},
            ],
        )

        self.prev_data_dir = policy_module.DATA_DIR
        policy_module.DATA_DIR = str(data_dir)
        _clear_policy_caches()

    def tearDown(self):
        policy_module.DATA_DIR = self.prev_data_dir
        _clear_policy_caches()
        self.tmp.cleanup()

    # Core invalid/valid entities
    def test_unknown_drug_denied(self):
        r = self._call(drug_id="9999")
        self.assertEqual(r["summary"]["decision"], "deny")

    def test_unknown_plan_denied(self):
        r = self._call(plan_id="9999")
        self.assertEqual(r["summary"]["decision"], "deny")

    def test_inactive_drug_denied(self):
        r = self._call(drug_id="1999")
        self.assertEqual(r["summary"]["decision"], "deny")

    def test_inactive_plan_denied(self):
        r = self._call(plan_id="3555")
        self.assertEqual(r["summary"]["decision"], "deny")

    # Default coverage branches
    def test_no_status_uses_plan_default_covered(self):
        r = self._call(drug_id="1011")
        self.assertEqual(r["summary"]["decision"], "pass")
        self.assertAlmostEqual(r["score"], 0.80, places=2)

    def test_no_status_uses_plan_default_noncovered(self):
        r = self._call(plan_id="3999", drug_id="1011")
        self.assertEqual(r["summary"]["decision"], "deny")

    # Status code denies
    def test_non_formulary_denied(self):
        r = self._call(drug_id="1005")
        self.assertEqual(r["summary"]["decision"], "deny")

    def test_excluded_denied(self):
        r = self._call(drug_id="1006")
        self.assertEqual(r["summary"]["decision"], "deny")

    def test_not_covered_denied(self):
        r = self._call(drug_id="1007")
        self.assertEqual(r["summary"]["decision"], "deny")

    # PA / ST / QL
    def test_pa_unmet_pending(self):
        r = self._call(drug_id="1002", member_id="2001")
        self.assertEqual(r["summary"]["decision"], "pending")
        self.assertEqual(r["policy_state"], "pending")
        self.assertEqual(r["pending_type"], "doctor_review")
        self.assertFalse(r["pa_met"])

    def test_pa_met_pass(self):
        r = self._call(drug_id="1002", member_id="2002")
        self.assertEqual(r["summary"]["decision"], "pass")
        self.assertTrue(r["pa_met"])

    def test_st_unmet_pending(self):
        r = self._call(drug_id="1003", member_id="2001")
        self.assertEqual(r["summary"]["decision"], "pending")
        self.assertEqual(r["pending_type"], "doctor_review")
        self.assertFalse(r["step_therapy_met"])

    def test_st_met_pass(self):
        r = self._call(drug_id="1003", member_id="2003")
        self.assertEqual(r["summary"]["decision"], "pass")
        self.assertTrue(r["step_therapy_met"])

    def test_ql_exceeded_pending(self):
        r = self._call(drug_id="1004", quantity=31)
        self.assertEqual(r["summary"]["decision"], "pending")
        self.assertEqual(r["pending_type"], "doctor_review")
        self.assertFalse(r["quantity_ok"])

    def test_ql_within_pass(self):
        r = self._call(drug_id="1004", quantity=20)
        self.assertEqual(r["summary"]["decision"], "pass")
        self.assertTrue(r["quantity_ok"])

    # Pharmacy checks - removed; pharmacy operational checks are not the policy agent's concern

    # Mixed pending
if __name__ == "__main__":
    unittest.main(verbosity=2)
