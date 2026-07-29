from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any, Callable, Dict, List, Optional, Tuple
import asyncio
from functools import lru_cache

import pandas as pd

import json
import re
import httpx
import openai

# ============================================================
# Utility helpers
# ============================================================

def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    return str(value).strip().lower()


def string_similarity(a: Any, b: Any) -> float:
    a_n, b_n = normalize_text(a), normalize_text(b)
    if not a_n or not b_n:
        return 0.0
    return SequenceMatcher(None, a_n, b_n).ratio()


def split_tokens(value: Any) -> List[str]:
    text = normalize_text(value)
    if not text:
        return []
    raw = text.replace("|", ";").replace(",", ";").split(";")
    return [x.strip() for x in raw if x.strip() and x.strip() != "none documented"]


def jaccard_similarity(list_a: List[str], list_b: List[str]) -> float:
    set_a, set_b = set(list_a), set(list_b)
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


def parse_any_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None

    fmts = [
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d",
        "%m/%d/%Y",
        "%d-%m-%Y",
        "%Y-%m-%dT%H:%M:%S",
    ]
    for fmt in fmts:
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass

    try:
        ts = pd.to_datetime(text, utc=True, errors="coerce")
        if pd.isna(ts):
            return None
        return ts.to_pydatetime()
    except Exception:
        return None


def age_from_dob(dob: Any) -> Optional[int]:
    dt = parse_any_datetime(dob)
    if dt is None:
        return None
    now = datetime.now(timezone.utc)
    return max(0, now.year - dt.year - ((now.month, now.day) < (dt.month, dt.day)))


# ============================================================
# Config
# ============================================================

@dataclass
class DatasetPaths:
    doctor_responses: str = "data/doctor_responses_revised_5.csv"
    claims: str = "data/F_CLM_TRANSACTION.csv"
    product: str = "data/v_d_product.csv"
    prescription: str = "data/v_xxiris_om_prescription.csv"
    member: str = "data/v_d_member.csv"
    patient_history: str = "data/patient_history.csv"  


@dataclass
class AgentConfig:
    doctor_reason_col: str = "REASON_IF_REJECTED"
    doctor_modified_drug_col: str = "MODIFIED_DRUG"

    enable_llm_final_reasoning: bool = True
    final_reasoning_top_k: int = 5
    llm_final_reasoning_temperature: float = 0.1

    # HCP / UHG AI Gateway settings
    hcp_auth_url: str = "https://api.uhg.com/oauth2/token"
    hcp_scope: str = "https://api.uhg.com/.default"
    hcp_grant_type: str = "client_credentials"

    hcp_shared_quota_endpoint: str = "https://api.uhg.com/api/cloud/api-management/ai-gateway/1.0"
    hcp_api_version: str = "2025-01-01-preview"
    hcp_deployment_name: str = "gpt-4o_2024-11-20"
    hcp_model_name: str = "gpt-4o"

    hcp_project_id: str = field(
        default_factory=lambda: os.getenv(
            "HCP_PROJECT_ID",
            "71364f37-e29d-494a-874d-5a9fa0f7e0aa"
        )
    )

    # similarity
    similarity_threshold: float = 0.75
    top_k: int = 5

    # structured similarity weights
    w_original_drug: float = 0.15
    w_recommended_drug: float = 0.15
    w_gpi: float = 0.20
    w_subclass: float = 0.15
    w_class: float = 0.20
    w_diagnosis: float = 0.15

    # scoring engine
    
    decision_weights: Dict[str, float] = field(default_factory=lambda: {
        "ACCEPTED": 0.96,
        "MODIFIED": 0.55,
        "REJECTED": 0.2,
        "UNKNOWN": 0.25,
    })

    # ------------------------------------------------------------
    # Reason-specific rejection weights
    # Lower weight = stronger negative historical signal
    # ------------------------------------------------------------
    rejected_reason_weights: Dict[str, float] = field(default_factory=lambda: {
        "Recommended alternative is not appropriate for the documented diagnosis": 0.2,
        "Documented allergy or prior intolerance to recommended drug/drug class": 0.15,
        "Clinically significant drug-drug interaction risk": 0.15,
        "Contraindication based on patient's current condition or medication profile": 0.15,
        "Patient previously failed recommended drug": 0.17,
        "Recommended alternative may worsen an existing comorbidity": 0.2,
    })

    half_life_days: int = 3000

    # doctor_responses schema columns (IMPORTANT: uppercase for your dataset)
    doctor_case_id_col: str = "CASE_ID"
    doctor_claim_id_col: str = "CLAIM_NBR"
    doctor_original_drug_col: str = "ORIGINAL_DRUG"
    doctor_original_prod_sk_col: str = "ORIGINAL_PROD_SK"
    doctor_recommended_drug_col: str = "RECOMMENDED_DRUG"
    doctor_recommended_prod_sk_col: str = "RECOMMENDED_PROD_SK"
    doctor_decision_col: str = "DECISION"
    doctor_timestamp_col: str = "RESPONSE_DT"
    doctor_dx_col: str = "DX_CD"
    doctor_member_key_col: str = "MBR_SK"

    # claims schema
    claim_id_col: str = "CLAIM_NBR"
    claim_member_key_col: str = "MBR_SK"
    claim_member_id_col_candidates: Tuple[str, ...] = ("MBR_ID", "ORIG_MEMBER_ID")
    claim_dx_col: str = "DX_CD"

    # product schema
    product_key_col: str = "PROD_SK"
    product_id_col: str = "PROD_ID"
    product_name_col: str = "PROD_NM"
    product_generic_col: str = "GNRC_NM"
    product_gpi_col: str = "GPI_NO"
    product_class_col: str = "DRG_CLASS_NM"
    product_subclass_col: str = "DRG_SUB_CLASS_NM"
    product_equiv_col: str = "DRG_FDA_THRPC_EQVLC_CD"

    # prescription schema
    rx_patient_id_col: str = "PATIENT_ACCOUNT_ID"
    rx_dx_col: str = "ICD10_DIAGNOSIS_CODE"

    # member schema (actual v_d_member.csv columns)
    member_key_col: str = "MBR_SK"
    member_id_col: str = "MBR_ID"
    member_dob_col: str = "DATE_OF_BIRTH"
    member_sex_col: str = "GENDER_CD"
    member_age_col: str = "AGE"
    member_allergies_col: str = "ALLERGIES"
    member_current_meds_col: str = "CURRENT_MEDICATIONS"

    # patient history schema (optional external table if you still want it)
    patient_history_id_candidates: Tuple[str, ...] = ("MBR_SK", "patient_id", "MBR_ID", "PATIENT_ACCOUNT_ID")
    patient_history_meds_col: str = "current_medications"
    patient_history_allergies_col: str = "allergies"

    # optional debug
    debug: bool = False


# ============================================================
# Agent
# ============================================================

class PastDecisionsAgent:
    def _normalize_reason_text(self, value: Any) -> str:
        """
        Normalizes doctor decision reasons so fixed radio-button labels
        can be matched reliably.
        """

        text = normalize_text(value)

        if not text:
            return ""

        # Normalize different dash styles
        text = text.replace("–", "-").replace("—", "-")

        # Normalize apostrophes
        text = text.replace("’", "'").replace("‘", "'")

        # Normalize whitespace
        text = re.sub(r"\s+", " ", text).strip()

        return text

    def _reason_based_weight(
        self,
        reason: Any,
        reason_weight_map: Dict[str, float],
        default_weight: float,
    ) -> float:
        """
        Returns reason-specific weight for fixed doctor decision reasons.

        If multiple reasons are present in REASON_IF_REJECTED, this returns
        the most conservative matching weight, i.e., the lowest weight.
        """

        reason_text = self._normalize_reason_text(reason)

        if not reason_text:
            return float(default_weight)

        matched_weights = []

        for reason_label, weight in reason_weight_map.items():
            normalized_label = self._normalize_reason_text(reason_label)

            if normalized_label and normalized_label in reason_text:
                matched_weights.append(float(weight))

        if not matched_weights:
            return float(default_weight)

        return min(matched_weights)

    def _clean_optional_text(self, value: Any) -> Optional:
        if value is None:
            return None

        try:
            if pd.isna(value):
                return None
        except Exception:
            pass

        text = str(value).strip()

        if not text or text.lower() in ("nan", "none", "null"):
            return None

        return text

    def _get_hcp_access_token(self) -> str:
        """
        Gets an HCP OAuth access token using client credentials.
        This replaces any direct OpenAI API key based authentication.
        """

        client_id = os.getenv("HCP_CLIENT_ID")
        client_secret = os.getenv("HCP_CLIENT_SECRET")

        if not client_id or not client_secret:
            raise ValueError(
                "Missing HCP credentials. Please set HCP_CLIENT_ID and HCP_CLIENT_SECRET "
                "as environment variables or in your .env file."
            )

        body = {
            "grant_type": self.config.hcp_grant_type,
            "scope": self.config.hcp_scope,
            "client_id": client_id,
            "client_secret": client_secret,
        }

        headers = {
            "Content-Type": "application/x-www-form-urlencoded"
        }

        with httpx.Client(timeout=60) as client:
            resp = client.post(
                self.config.hcp_auth_url,
                headers=headers,
                data=body,
            )

        resp.raise_for_status()

        token_payload = resp.json()

        if "access_token" not in token_payload:
            raise RuntimeError(f"HCP token response did not contain access_token: {token_payload}")

        return token_payload["access_token"]


    def _get_hcp_oai_client(self) -> openai.AzureOpenAI:
        """
        Creates an AzureOpenAI-compatible client using the HCP AI Gateway.
        """

        access_token = self._get_hcp_access_token()

        return openai.AzureOpenAI(
            azure_endpoint=self.config.hcp_shared_quota_endpoint,
            api_version=self.config.hcp_api_version,
            azure_deployment=self.config.hcp_deployment_name,
            azure_ad_token=access_token,
            default_headers={
                "projectId": self.config.hcp_project_id,
                # "x-upstream-env": "stg",  # uncomment if your senior/team asks for staging
            },
        )


    def _call_llm(self, messages: List[Dict[str, str]], temperature: float = 0.0) -> str:
        """
        Generic LLM caller used by the PastDecisionsAgent.
        Keeps the rest of your agent logic independent from the auth/client details.
        """

        client = self._get_hcp_oai_client()

        response = client.chat.completions.create(
            model=self.config.hcp_model_name,
            messages=messages,
            temperature=temperature,
        )

        return response.choices[0].message.content or ""

    def _parse_llm_json_response(self, text: str) -> Dict[str, Any]:
        if not text:
            raise ValueError("Empty LLM response.")

        cleaned = text.strip()

        # Remove ```json ... ``` if present
        cleaned = re.sub(r"^```json\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"^```\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

        return json.loads(cleaned)

    def __init__(
        self,
        dataset_paths: Optional[DatasetPaths] = None,
        config: Optional[AgentConfig] = None,
        llm_patient_adjustment_provider: Optional[
            Callable[[Dict[str, Any], List[Dict[str, Any]]], Tuple[float, str]]
        ] = None,
    ) -> None:
        self.paths = dataset_paths or DatasetPaths()
        self.config = config or AgentConfig()
        self.llm_patient_adjustment_provider = llm_patient_adjustment_provider
        self.data = self._load_datasets()

    def _average_top_case_confidence(
        self,
        top_case_summaries: List[Dict[str, Any]],
    ) -> float:
        if not top_case_summaries:
            return 0.0

        scores = [
            float(case.get("final_score_after_patient_adjustment", 0.0))
            for case in top_case_summaries
        ]

        if not scores:
            return 0.0

        return round(sum(scores) / len(scores), 4)

    # --------------------------------------------------------
    # Public method
    # --------------------------------------------------------
    def run(self, payload: Dict[str, Any], clinical_output: Dict[str, Any]) -> Dict[str, Any]:
        current_case = self._build_current_case(payload, clinical_output)
        historical_cases = self._build_historical_cases()

        if self.config.debug:
            print("TOTAL HISTORICAL CASES:", len(historical_cases))
            for x in historical_cases[:10]:
                print(
                    "CASE:", x.get("case_id"),
                    "| CLAIM:", x.get("claim_id"),
                    "| ORIG:", x.get("original_drug"),
                    "| REC:", x.get("recommended_drug"),
                    "| DX:", x.get("diagnosis"),
                    "| HIST PRODUCT:", x.get("recommended_product"),
                )

        # --------------------------------------------------------
        # Step 1: Similarity Engine
        # --------------------------------------------------------
        matched = []

        for hist in historical_cases:
            structured_similarity = self._structured_similarity(current_case, hist)
            final_similarity = structured_similarity

            if self.config.debug:
                print(
                    "DEBUG:",
                    hist.get("case_id"),
                    "structured=",
                    structured_similarity,
                    "final=",
                    final_similarity,
                )

            if final_similarity >= self.config.similarity_threshold:
                row = dict(hist)
                row["structured_similarity"] = round(structured_similarity, 4)
                row["similarity"] = round(final_similarity, 4)
                matched.append(row)

        # --------------------------------------------------------
        # Step 2: Filter + Rank
        # --------------------------------------------------------
        matched.sort(key=lambda x: x["similarity"], reverse=True)
        top_matches = matched[: self.config.top_k]

        # --------------------------------------------------------
        # Step 3: Decision Weight + Time Decay Engine
        # --------------------------------------------------------
        scored_matches = []

        for case in top_matches:
            decision_weight = self._decision_weight(
                case.get("decision"),
                case.get("decision_reason"),
            )

            time_decay = self._time_decay(case.get("timestamp"))

            case_score = case["similarity"] * decision_weight * time_decay

            scored_case = dict(case)
            scored_case["decision_reason"] = case.get("decision_reason")
            scored_case["modified_drug"] = case.get("modified_drug")
            scored_case["decision_weight"] = round(decision_weight, 4)
            scored_case["time_decay"] = round(time_decay, 4)
            scored_case["case_score"] = round(case_score, 4)

            scored_matches.append(scored_case)

        historical_score = self._aggregate_historical_score(scored_matches)

        # --------------------------------------------------------
        # Step 4: Rule-Based Patient Adjustment
        # --------------------------------------------------------
        current_patient_profile = self._get_current_patient_profile(
            current_case.get("patient_id"),
            current_case=current_case,
        )

        for match in scored_matches:
            rule_adjustment_score, rule_adjustment_explanation = self._rule_based_patient_adjustment(
                current_patient_profile,
                [match],
            )

            match["rule_adjustment_score"] = round(rule_adjustment_score, 4)
            match["rule_adjustment_explanation"] = rule_adjustment_explanation
            match["combined_patient_adjustment_score"] = round(rule_adjustment_score, 4)

        # --------------------------------------------------------
        # Step 5: Overall Rule-Based Patient Adjustment Score
        # --------------------------------------------------------
        if scored_matches:
            total_weight = sum(
                float(m.get("case_score", 0.0))
                for m in scored_matches
            )

            if total_weight > 0:
                adjustment_score = sum(
                    float(m.get("combined_patient_adjustment_score", 0.0))
                    * float(m.get("case_score", 0.0))
                    for m in scored_matches
                ) / total_weight
            else:
                adjustment_score = sum(
                    float(m.get("combined_patient_adjustment_score", 0.0))
                    for m in scored_matches
                ) / len(scored_matches)

            adjustment_score = round(adjustment_score, 4)
        else:
            adjustment_score = 0.0

        # --------------------------------------------------------
        # Step 6: Build Top Case Summaries
        # --------------------------------------------------------
        top_case_summaries = self._build_top_case_summaries(
            current_case,
            scored_matches,
        )

        # --------------------------------------------------------
        # Step 7: Average Confidence Score Across Top Cases
        # --------------------------------------------------------
        average_confidence_score = self._average_top_case_confidence(
            top_case_summaries
        )

        # --------------------------------------------------------
        # Step 8: Final LLM Reasoning Layer
        # LLM only gives one final explanation.
        # It does not create or change any score.
        # --------------------------------------------------------
        final_reasoning = self._generate_final_llm_reasoning(
            current_case=current_case,
            top_case_summaries=top_case_summaries,
            average_confidence_score=average_confidence_score,
        )

        return {
            "average_confidence_score": average_confidence_score,
            "final_score": average_confidence_score,
            "historical_score": round(historical_score, 4),
            "rule_based_patient_adjustment_score": round(adjustment_score, 4),
            "final_statement": final_reasoning.get("final_statement", ""),
            "top_cases": top_case_summaries,
        }

    # --------------------------------------------------------
    # Dataset loading
    # --------------------------------------------------------
    def _load_datasets(self) -> Dict[str, pd.DataFrame]:
        data = {
            "doctor_responses": self._read_csv_required(self.paths.doctor_responses),
            "claims": self._read_csv_required(self.paths.claims),
            "product": self._read_csv_required(self.paths.product),
            "prescription": self._read_csv_required(self.paths.prescription),
            "member": self._read_csv_required(self.paths.member),
        }
        data["patient_history"] = self._read_csv_optional(self.paths.patient_history)
        return data

    def _read_csv_required(self, path: str) -> pd.DataFrame:
        if not os.path.exists(path):
            raise FileNotFoundError(f"Required dataset missing: {path}")
        return pd.read_csv(path, dtype=str)

    def _read_csv_optional(self, path: str) -> pd.DataFrame:
        if not os.path.exists(path):
            return pd.DataFrame()
        return pd.read_csv(path, dtype=str)

    # --------------------------------------------------------
    # Normalizers for IDs
    # --------------------------------------------------------
    def _norm_id(self, value: Any) -> str:
        text = normalize_text(value)
        if text.endswith(".0"):
            text = text[:-2]
        return text

    # --------------------------------------------------------
    # Product lookup helpers
    # --------------------------------------------------------
    def _find_product_by_sk(self, prod_sk: Any) -> Optional[pd.Series]:
        df = self.data["product"]
        cfg = self.config

        if df.empty or prod_sk is None or cfg.product_key_col not in df.columns:
            return None

        key = self._norm_id(prod_sk)
        if not key:
            return None

        s = df[df[cfg.product_key_col].astype(str).map(self._norm_id) == key]
        if not s.empty:
            return s.iloc[0]
        return None

    def _find_best_product(self, drug_name: str) -> Optional[pd.Series]:
        df = self.data["product"]
        cfg = self.config

        if df.empty or not drug_name:
            return None

        drug_name_clean = normalize_text(drug_name)

        # 1) exact generic match
        if cfg.product_generic_col in df.columns:
            generic_series = df[cfg.product_generic_col].astype(str).map(normalize_text)
            exact_generic = df[generic_series == drug_name_clean]
            if not exact_generic.empty:
                return exact_generic.iloc[0]

        # 2) exact product name match
        if cfg.product_name_col in df.columns:
            product_series = df[cfg.product_name_col].astype(str).map(normalize_text)
            exact_name = df[product_series == drug_name_clean]
            if not exact_name.empty:
                return exact_name.iloc[0]

        # 3) contains match in product name
        if cfg.product_name_col in df.columns:
            product_series = df[cfg.product_name_col].astype(str).map(normalize_text)
            contains = df[product_series.apply(lambda x: drug_name_clean in x if x else False)]
            if not contains.empty:
                return contains.iloc[0]

        # 4) fuzzy fallback
        best_row = None
        best_score = 0.0

        for _, row in df.iterrows():
            scores = []
            for col in [cfg.product_name_col, cfg.product_generic_col]:
                if col in df.columns:
                    val = row.get(col)
                    scores.append(string_similarity(drug_name_clean, val))

            score = max(scores) if scores else 0.0
            if score > best_score:
                best_score = score
                best_row = row

        return best_row if best_score >= 0.50 else None

    def _product_features(self, row: Optional[pd.Series]) -> Dict[str, Any]:
        if row is None:
            return {}
        cfg = self.config
        return {
            "PROD_SK": row.get(cfg.product_key_col),
            "PROD_ID": row.get(cfg.product_id_col),
            "PROD_NM": row.get(cfg.product_name_col),
            "GNRC_NM": row.get(cfg.product_generic_col),
            "GPI_NO": row.get(cfg.product_gpi_col),
            "DRG_CLASS_NM": row.get(cfg.product_class_col),
            "DRG_SUB_CLASS_NM": row.get(cfg.product_subclass_col),
            "DRG_FDA_THRPC_EQVLC_CD": row.get(cfg.product_equiv_col),
        }

    # --------------------------------------------------------
    # Current case build
    # --------------------------------------------------------
    def _build_current_case(self, payload: Dict[str, Any], clinical_output: Dict[str, Any]) -> Dict[str, Any]:
        original_drug = payload.get("original_drug") or payload.get("drug")
        recommended_drug = clinical_output.get("recommended_drug") or clinical_output.get("recommended")

        patient_id = payload.get("patient_id")
        member_key = payload.get("member_key") or payload.get("mbr_sk") or payload.get("MBR_SK")

        claim_id = payload.get("claim_id") or payload.get("CLAIM_NBR")
        diagnosis = payload.get("diagnosis")

        if not original_drug:
            raise ValueError("payload must include 'drug' or 'original_drug'")
        if not recommended_drug:
            raise ValueError("clinical_output must include 'recommended' or 'recommended_drug'")
        if not patient_id and not member_key:
            raise ValueError("payload must include either 'patient_id' or 'member_key'/'mbr_sk'/'MBR_SK'")

        original_product = self._find_best_product(original_drug)
        recommended_product = self._find_best_product(recommended_drug)

        claim_row = self._find_claim_row(claim_id, patient_id=patient_id, member_key=member_key)
        rx_row = self._find_rx_row(patient_id, diagnosis) if patient_id else None

        if not diagnosis:
            diagnosis = self._extract_diagnosis(claim_row, rx_row)

        # If member_key not provided, derive from claim if possible
        if not member_key and claim_row is not None and self.config.claim_member_key_col in claim_row.index:
            member_key = claim_row.get(self.config.claim_member_key_col)

        return {
            "claim_id": claim_id,
            "patient_id": patient_id,
            "member_key": member_key,
            "original_drug": original_drug,
            "recommended_drug": recommended_drug,
            "diagnosis": diagnosis,
            "original_product": self._product_features(original_product),
            "recommended_product": self._product_features(recommended_product),
        }

    def _find_claim_row(
        self,
        claim_id: Any,
        patient_id: Optional[str] = None,
        member_key: Optional[str] = None
    ) -> Optional[pd.Series]:
        df = self.data["claims"]
        cfg = self.config

        if claim_id is not None and cfg.claim_id_col in df.columns:
            s = df[df[cfg.claim_id_col].astype(str).map(self._norm_id) == self._norm_id(claim_id)]
            if not s.empty:
                return s.iloc[0]

        # Try by MBR_SK if provided
        if member_key and cfg.claim_member_key_col in df.columns:
            s = df[df[cfg.claim_member_key_col].astype(str).map(self._norm_id) == self._norm_id(member_key)]
            if not s.empty:
                return s.iloc[0]

        # Fallback to patient_id against member-id-like columns if provided
        if patient_id:
            for col in cfg.claim_member_id_col_candidates:
                if col in df.columns:
                    s = df[df[col].astype(str).map(self._norm_id) == self._norm_id(patient_id)]
                    if not s.empty:
                        return s.iloc[0]

        return None

    def _find_rx_row(self, patient_id: str, diagnosis: Optional[str]) -> Optional[pd.Series]:
        df = self.data["prescription"]
        cfg = self.config
        narrowed = df

        if cfg.rx_patient_id_col in df.columns:
            subset = df[df[cfg.rx_patient_id_col].astype(str).map(self._norm_id) == self._norm_id(patient_id)]
            if not subset.empty:
                narrowed = subset

        if diagnosis and cfg.rx_dx_col in narrowed.columns:
            subset = narrowed[narrowed[cfg.rx_dx_col].astype(str).map(normalize_text) == normalize_text(diagnosis)]
            if not subset.empty:
                return subset.iloc[0]

        return narrowed.iloc[0] if not narrowed.empty else None

    def _extract_diagnosis(self, claim_row: Optional[pd.Series], rx_row: Optional[pd.Series]) -> Optional[str]:
        cfg = self.config
        if claim_row is not None and cfg.claim_dx_col in claim_row.index and claim_row.get(cfg.claim_dx_col):
            return str(claim_row.get(cfg.claim_dx_col))
        if rx_row is not None and cfg.rx_dx_col in rx_row.index and rx_row.get(cfg.rx_dx_col):
            return str(rx_row.get(cfg.rx_dx_col))
        return None

    # --------------------------------------------------------
    # Historical case build
    # --------------------------------------------------------
    def _build_historical_cases(self) -> List[Dict[str, Any]]:
        dr = self.data["doctor_responses"]
        cases = []
        cfg = self.config

        for _, row in dr.iterrows():
            case_id = row.get(cfg.doctor_case_id_col)               # CASE_ID
            claim_id = row.get(cfg.doctor_claim_id_col)             # CLAIM_NBR
            original_drug = row.get(cfg.doctor_original_drug_col)
            recommended_drug = row.get(cfg.doctor_recommended_drug_col)

            # reliable direct fields from doctor_responses
            diagnosis = row.get(cfg.doctor_dx_col)
            member_key = row.get(cfg.doctor_member_key_col)

            # use claim_id (CLAIM_NBR) for claims lookup
            claim_row = self._find_historical_claim_row(claim_id)

            if claim_row is not None:
                if not diagnosis:
                    diagnosis = claim_row.get(cfg.claim_dx_col)
                if not member_key:
                    member_key = claim_row.get(cfg.claim_member_key_col)

            # BEST FIX: use *_PROD_SK directly if present, fallback to name lookup
            original_prod_sk = row.get(cfg.doctor_original_prod_sk_col)
            recommended_prod_sk = row.get(cfg.doctor_recommended_prod_sk_col)

            original_product_row = self._find_product_by_sk(original_prod_sk)
            if original_product_row is None:
                original_product_row = self._find_best_product(str(original_drug))

            recommended_product_row = self._find_product_by_sk(recommended_prod_sk)
            if recommended_product_row is None:
                recommended_product_row = self._find_best_product(str(recommended_drug))

            cases.append({
                "case_id": case_id,
                "claim_id": claim_id,
                "original_drug": original_drug,
                "recommended_drug": recommended_drug,
                "decision": row.get(cfg.doctor_decision_col),

                # New fields for final LLM reasoning
                "modified_drug": self._clean_optional_text(
                    row.get(cfg.doctor_modified_drug_col)
                ),
                "decision_reason": self._clean_optional_text(
                    row.get(cfg.doctor_reason_col)
                ),

                "timestamp": row.get(cfg.doctor_timestamp_col),
                "diagnosis": diagnosis,
                "member_key": member_key,
                "original_product": self._product_features(original_product_row),
                "recommended_product": self._product_features(recommended_product_row),
            })

        return cases

    def _find_historical_claim_row(self, claim_id: Any) -> Optional[pd.Series]:
        df = self.data["claims"]
        cfg = self.config

        if claim_id is None:
            return None

        if cfg.claim_id_col in df.columns:
            s = df[df[cfg.claim_id_col].astype(str).map(self._norm_id) == self._norm_id(claim_id)]
            if not s.empty:
                return s.iloc[0]

        return None

    # --------------------------------------------------------
    # Step 3: Rule Based similarity
    # --------------------------------------------------------
    def _structured_similarity(self, current: Dict[str, Any], hist: Dict[str, Any]) -> float:
        cfg = self.config

        original_score = self._drug_similarity(
            current["original_drug"], current["original_product"],
            hist["original_drug"], hist["original_product"]
        )
        recommended_score = self._drug_similarity(
            current["recommended_drug"], current["recommended_product"],
            hist["recommended_drug"], hist["recommended_product"]
        )
        diagnosis_score = self._diagnosis_similarity(current.get("diagnosis"), hist.get("diagnosis"))
        gpi_score = self._exact_match(
            current["recommended_product"].get("GPI_NO"),
            hist["recommended_product"].get("GPI_NO")
        )
        subclass_score = self._exact_match(
            current["recommended_product"].get("DRG_SUB_CLASS_NM"),
            hist["recommended_product"].get("DRG_SUB_CLASS_NM")
        )
        class_score = self._exact_match(
            current["recommended_product"].get("DRG_CLASS_NM"),
            hist["recommended_product"].get("DRG_CLASS_NM")
        )

        score = (
            cfg.w_original_drug * original_score
            + cfg.w_recommended_drug * recommended_score
            + cfg.w_gpi * gpi_score
            + cfg.w_subclass * subclass_score
            + cfg.w_class * class_score
            + cfg.w_diagnosis * diagnosis_score
        )
        return max(0.0, min(1.0, score))

    def _drug_similarity(self, cur_name: Any, cur_prod: Dict[str, Any], hist_name: Any, hist_prod: Dict[str, Any]) -> float:
        exact = 1.0 if normalize_text(cur_name) == normalize_text(hist_name) and normalize_text(cur_name) else 0.0
        fuzzy = string_similarity(cur_name, hist_name)

        gpi = self._exact_match(cur_prod.get("GPI_NO"), hist_prod.get("GPI_NO"))
        subclass = self._exact_match(cur_prod.get("DRG_SUB_CLASS_NM"), hist_prod.get("DRG_SUB_CLASS_NM"))
        drug_class = self._exact_match(cur_prod.get("DRG_CLASS_NM"), hist_prod.get("DRG_CLASS_NM"))
        equiv = self._exact_match(cur_prod.get("DRG_FDA_THRPC_EQVLC_CD"), hist_prod.get("DRG_FDA_THRPC_EQVLC_CD"))

        weighted = (
            0.20 * fuzzy
            + 0.25 * drug_class
            + 0.20 * subclass
            + 0.25 * gpi
            + 0.10 * equiv
        )

        return max(exact, fuzzy, weighted)

    def medication_profile_similarity(
        self,
        current_meds: List[str],
        hist_meds: List[str]
    ) -> float:
        if not current_meds or not hist_meds:
            return 0.0

        # 1. Exact medication overlap
        exact_overlap = jaccard_similarity(current_meds, hist_meds)

        # 2. Product feature lookup
        current_products = [
            self._product_features(self._find_best_product(med))
            for med in current_meds
        ]
        hist_products = [
            self._product_features(self._find_best_product(med))
            for med in hist_meds
        ]

        current_classes = [
            p.get("DRG_CLASS_NM") for p in current_products if p.get("DRG_CLASS_NM")
        ]
        hist_classes = [
            p.get("DRG_CLASS_NM") for p in hist_products if p.get("DRG_CLASS_NM")
        ]

        current_subclasses = [
            p.get("DRG_SUB_CLASS_NM") for p in current_products if p.get("DRG_SUB_CLASS_NM")
        ]
        hist_subclasses = [
            p.get("DRG_SUB_CLASS_NM") for p in hist_products if p.get("DRG_SUB_CLASS_NM")
        ]

        current_gpis = [
            p.get("GPI_NO") for p in current_products if p.get("GPI_NO")
        ]
        hist_gpis = [
            p.get("GPI_NO") for p in hist_products if p.get("GPI_NO")
        ]

        class_overlap = jaccard_similarity(current_classes, hist_classes)
        subclass_overlap = jaccard_similarity(current_subclasses, hist_subclasses)
        gpi_overlap = jaccard_similarity(current_gpis, hist_gpis)

        profile_similarity = (
            0.50 * exact_overlap
            + 0.25 * class_overlap
            + 0.15 * subclass_overlap
            + 0.10 * gpi_overlap
        )

        return max(0.0, min(1.0, profile_similarity))

    def _diagnosis_similarity(self, current_dx: Any, hist_dx: Any) -> float:
        if normalize_text(current_dx) and normalize_text(current_dx) == normalize_text(hist_dx):
            return 1.0
        if not normalize_text(current_dx) or not normalize_text(hist_dx):
            return 0.0
        return string_similarity(current_dx, hist_dx)

    def _exact_match(self, a: Any, b: Any) -> float:
        return 1.0 if normalize_text(a) and normalize_text(a) == normalize_text(b) else 0.0

    # --------------------------------------------------------
    # Step 5: scoring engine
    # --------------------------------------------------------
    def _decision_weight(
        self,
        decision: Any,
        decision_reason: Any = None,
    ) -> float:
        """
        Returns decision weight using both:
        - decision outcome: ACCEPTED / MODIFIED / REJECTED
        - fixed doctor reason from REASON_IF_REJECTED

        ACCEPTED:
            Uses accepted baseline weight.

        MODIFIED:
            The finalized dataset no longer contains MODIFIED decisions.
            A flat fallback weight is kept for backward compatibility only.

        REJECTED:
            Uses reason-specific rejected weight when available.
        """

        cfg = self.config
        decision_norm = normalize_text(decision).upper()

        if decision_norm == "ACCEPTED":
            return float(cfg.decision_weights.get("ACCEPTED", 0.90))

        if decision_norm == "MODIFIED":
            return float(cfg.decision_weights.get("MODIFIED", 0.55))

        if decision_norm == "REJECTED":
            default_rejected_weight = float(cfg.decision_weights.get("REJECTED", 0.05))

            return self._reason_based_weight(
                reason=decision_reason,
                reason_weight_map=cfg.rejected_reason_weights,
                default_weight=default_rejected_weight,
            )

        return float(cfg.decision_weights.get("UNKNOWN", 0.25))

    def _time_decay(self, timestamp: Any) -> float:
        dt = parse_any_datetime(timestamp)
        if dt is None:
            return 1.0

        now = datetime.now(timezone.utc)
        days_old = max(0, (now - dt).days)

        # 15-year long-term half-life
        half_life = max(1, self.config.half_life_days)
        long_term_decay = 0.5 ** (days_old / half_life)

        # New-case maturity weighting
        if days_old < 30:
            maturity_weight = 0.60
        elif days_old < 90:
            maturity_weight = 0.70
        elif days_old < 180:
            maturity_weight = 0.80
        elif days_old < 365:
            maturity_weight = 0.90
        else:
            maturity_weight = 1.00

        return maturity_weight * long_term_decay

    def _aggregate_historical_score(self, scored_matches: List[Dict[str, Any]]) -> float:
        if not scored_matches:
            return 0.0
        avg = sum(m["case_score"] for m in scored_matches) / len(scored_matches)
        accepted = sum(
            1 for m in scored_matches
            if normalize_text(m.get("decision")).upper() == "ACCEPTED"
        )
        acceptance_ratio = accepted / len(scored_matches)
        return max(0.0, min(1.0, avg + 0.05 * acceptance_ratio))

    # --------------------------------------------------------
    # Step 6: patient adjustment layer
    # --------------------------------------------------------
    def _get_current_patient_profile(
        self,
        patient_id: Optional[str],
        current_case: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        cfg = self.config
        member_df = self.data["member"]
        patient_history_df = self.data["patient_history"]

        member_row = None
        patient_row = None

        member_key = None
        if current_case is not None:
            member_key = current_case.get("member_key")

        # --------------------------------------------------
        # 1) BEST PATH: resolve directly by MBR_SK / member_key
        # --------------------------------------------------
        if member_key and cfg.member_key_col in member_df.columns:
            s = member_df[
                member_df[cfg.member_key_col].astype(str).map(self._norm_id) == self._norm_id(member_key)
            ]
            if not s.empty:
                member_row = s.iloc[0]

        # --------------------------------------------------
        # 2) Fallback: resolve by MBR_ID using patient_id
        # --------------------------------------------------
        if member_row is None and patient_id and cfg.member_id_col in member_df.columns:
            s = member_df[
                member_df[cfg.member_id_col].astype(str).map(self._norm_id) == self._norm_id(patient_id)
            ]
            if not s.empty:
                member_row = s.iloc[0]

        # --------------------------------------------------
        # 3) If still not found, try claim-based lookup
        # --------------------------------------------------
        if member_row is None and current_case is not None:
            claim_id = current_case.get("claim_id")
            claim_row = self._find_claim_row(
                claim_id,
                patient_id=patient_id,
                member_key=member_key
            )
            if claim_row is not None and cfg.claim_member_key_col in claim_row.index:
                member_key_from_claim = claim_row.get(cfg.claim_member_key_col)
                if member_key_from_claim and cfg.member_key_col in member_df.columns:
                    s = member_df[
                        member_df[cfg.member_key_col].astype(str).map(self._norm_id) == self._norm_id(member_key_from_claim)
                    ]
                    if not s.empty:
                        member_row = s.iloc[0]
                        member_key = member_key_from_claim

        # --------------------------------------------------
        # 4) Patient history lookup using member_key first, then member_id, then patient_id
        # --------------------------------------------------
        if not patient_history_df.empty:
            lookup_values = []

            if member_key:
                lookup_values.append(member_key)

            if member_row is not None:
                resolved_member_id = member_row.get(cfg.member_id_col)
                if resolved_member_id:
                    lookup_values.append(resolved_member_id)

                resolved_member_key = member_row.get(cfg.member_key_col)
                if resolved_member_key and resolved_member_key not in lookup_values:
                    lookup_values.append(resolved_member_key)

            if patient_id:
                lookup_values.append(patient_id)

            for lookup_value in lookup_values:
                for col in cfg.patient_history_id_candidates:
                    if col in patient_history_df.columns:
                        s = patient_history_df[
                            patient_history_df[col].astype(str).map(self._norm_id) == self._norm_id(lookup_value)
                        ]
                        if not s.empty:
                            patient_row = s.iloc[0]
                            break
                if patient_row is not None:
                    break

        return {
        "patient_id": patient_id,
        "member_id": member_row.get(cfg.member_id_col) if member_row is not None else None,
        "member_key": member_row.get(cfg.member_key_col) if member_row is not None else member_key,
        "dob": member_row.get(cfg.member_dob_col) if member_row is not None else None,
        "age": (
            int(member_row.get(cfg.member_age_col))
            if member_row is not None and member_row.get(cfg.member_age_col) not in (None, "", "nan")
            else age_from_dob(member_row.get(cfg.member_dob_col)) if member_row is not None else None
        ),
        "sex": member_row.get(cfg.member_sex_col) if member_row is not None else None,
        "current_medications": (
            member_row.get(cfg.member_current_meds_col)
            if member_row is not None and cfg.member_current_meds_col in member_row.index
            else (
                patient_row.get(cfg.patient_history_meds_col)
                if patient_row is not None and cfg.patient_history_meds_col in patient_row.index else None
            )
        ),
        "allergies": (
            member_row.get(cfg.member_allergies_col)
            if member_row is not None and cfg.member_allergies_col in member_row.index
            else (
                patient_row.get(cfg.patient_history_allergies_col)
                if patient_row is not None and cfg.patient_history_allergies_col in patient_row.index else None
            )
        ),
    }

    def _get_historical_patient_profile(self, match: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        cfg = self.config
        member_df = self.data["member"]
        patient_history_df = self.data["patient_history"]

        member_key = match.get("member_key")
        if member_key is None or cfg.member_key_col not in member_df.columns:
            return None

        s = member_df[
            member_df[cfg.member_key_col].astype(str).map(self._norm_id) == self._norm_id(member_key)
        ]
        if s.empty:
            return None

        member_row = s.iloc[0]
        member_id = member_row.get(cfg.member_id_col)

        patient_row = None
        if not patient_history_df.empty:
            lookup_values = [member_key]
            if member_id:
                lookup_values.append(member_id)

            for lookup_value in lookup_values:
                for col in cfg.patient_history_id_candidates:
                    if col in patient_history_df.columns:
                        s2 = patient_history_df[
                            patient_history_df[col].astype(str).map(self._norm_id) == self._norm_id(lookup_value)
                        ]
                        if not s2.empty:
                            patient_row = s2.iloc[0]
                            break
                if patient_row is not None:
                    break

        return {
        "patient_id": member_id,
        "dob": member_row.get(cfg.member_dob_col),
        "age": (
            int(member_row.get(cfg.member_age_col))
            if member_row.get(cfg.member_age_col) not in (None, "", "nan")
            else age_from_dob(member_row.get(cfg.member_dob_col))
        ),
        "sex": member_row.get(cfg.member_sex_col),
        "current_medications": (
            member_row.get(cfg.member_current_meds_col)
            if cfg.member_current_meds_col in member_row.index
            else (
                patient_row.get(cfg.patient_history_meds_col)
                if patient_row is not None and cfg.patient_history_meds_col in patient_row.index else None
            )
        ),
        "allergies": (
            member_row.get(cfg.member_allergies_col)
            if cfg.member_allergies_col in member_row.index
            else (
                patient_row.get(cfg.patient_history_allergies_col)
                if patient_row is not None and cfg.patient_history_allergies_col in patient_row.index else None
            )
        ),
        "decision": match.get("decision"),
    }

    def _age_group(self, age: Optional[int]) -> Optional:

        if age is None:
            return None

        try:
            age = int(age)
        except Exception:
            return None

        if age < 0:
            return None

        if age < 1:
            return "newborn"
        elif age <= 2:
            return "infant"
        elif age <= 5:
            return "toddler"
        elif age <= 12:
            return "child"
        elif age <= 17:
            return "adolescent"
        elif age <= 25:
            return "young_adult"
        elif age <= 44:
            return "adult"
        elif age <= 64:
            return "middle_aged_adult"
        elif age <= 74:
            return "older_adult"
        else:
            return "senior"


    def _age_group_similarity(
        self,
        current_age: Optional[int],
        hist_age: Optional[int]
    ) -> float:
        """
        Calculates age similarity based on distance between age groups,
        not direct year difference.
        """

        age_group_order = [
            "newborn",
            "infant",
            "toddler",
            "child",
            "adolescent",
            "young_adult",
            "adult",
            "middle_aged_adult",
            "older_adult",
            "senior",
        ]

        current_group = self._age_group(current_age)
        hist_group = self._age_group(hist_age)

        if current_group is None or hist_group is None:
            return 0.0

        current_idx = age_group_order.index(current_group)
        hist_idx = age_group_order.index(hist_group)

        group_distance = abs(current_idx - hist_idx)

        # Same age group
        if group_distance == 0:
            return 1.0

        # Neighboring age groups
        if group_distance == 1:
            return 0.75

        # Moderately close age groups
        if group_distance == 2:
            return 0.50

        # Distant age groups
        if group_distance == 3:
            return 0.25

        # Very different age groups
        return 0.0

    def _rule_based_patient_adjustment(
        self,
        current_patient: Dict[str, Any],
        scored_matches: List[Dict[str, Any]]
    ) -> Tuple[float, str]:
        if not scored_matches:
            return 0.0, "No similar historical cases available for rule-based patient adjustment."

        age_scores = []
        sex_scores = []
        med_scores = []
        allergy_scores = []
        signed_scores = []
        confidence_weights = []

        current_age = current_patient.get("age")
        current_sex = normalize_text(current_patient.get("sex"))
        current_meds = split_tokens(current_patient.get("current_medications"))
        current_allergies = split_tokens(current_patient.get("allergies"))

        for match in scored_matches:
            hist_patient = self._get_historical_patient_profile(match)
            if hist_patient is None:
                continue

            hist_age = hist_patient.get("age")
            hist_sex = normalize_text(hist_patient.get("sex"))
            hist_meds = split_tokens(hist_patient.get("current_medications"))
            hist_allergies = split_tokens(hist_patient.get("allergies"))

            age_sim = self._age_group_similarity(current_age, hist_age)

            sex_sim = 0.0
            if current_sex and hist_sex:
                sex_sim = 1.0 if current_sex == hist_sex else 0.0

            med_sim = self.medication_profile_similarity(current_meds, hist_meds)
            allergy_sim = jaccard_similarity(current_allergies, hist_allergies)

            decision = normalize_text(match.get("decision")).upper()
            if decision == "ACCEPTED":
                signed = 1.0
            elif decision == "REJECTED":
                signed = -1.0
            else:
                signed = 0.3

            confidence = float(match.get("case_score", 0.0))

            age_scores.append(age_sim * confidence)
            sex_scores.append(sex_sim * confidence)
            med_scores.append(med_sim * confidence)
            allergy_scores.append(allergy_sim * confidence)
            signed_scores.append(signed * confidence)
            confidence_weights.append(confidence)

        if not confidence_weights:
            return 0.0, "Rule-based patient adjustment skipped because historical patient profiles were unavailable."

        denom = sum(confidence_weights)
        if denom <= 0:
            return 0.0, "Rule-based patient adjustment skipped because confidence weights were zero."

        avg_age = sum(age_scores) / denom
        avg_sex = sum(sex_scores) / denom
        avg_med = sum(med_scores) / denom
        avg_allergy = sum(allergy_scores) / denom
        avg_signed = sum(signed_scores) / denom

        raw_adjustment = (
            0.03 * avg_age
            + 0.03 * avg_sex
            + 0.06 * avg_med
            + 0.02 * avg_allergy
        ) * avg_signed

        explanation = (
            f"Rule-based patient adjustment: age_similarity={avg_age:.2f}, "
            f"sex_similarity={avg_sex:.2f}, medication_pattern_similarity={avg_med:.2f}, "
            f"allergy_profile_similarity={avg_allergy:.2f}, historical_decision_trend={avg_signed:.2f}."
        )
        return raw_adjustment, explanation

    def _build_case_reasoning(
        self,
        current_case: Dict[str, Any],
        match: Dict[str, Any],
        rule_adjustment_score: float,
        adjustment_score: float,
        final_score_after_patient_adjustment: float,
        rule_adjustment_explanation: str,
    ) -> List[str]:
        reasons = []

        if normalize_text(current_case.get("original_drug")) == normalize_text(match.get("original_drug")):
            reasons.append("Original drug matches the current case.")
        else:
            reasons.append("Original drug is clinically similar based on product and therapeutic features.")

        if normalize_text(current_case.get("recommended_drug")) == normalize_text(match.get("recommended_drug")):
            reasons.append("Recommended drug matches the current recommendation.")
        else:
            reasons.append("Recommended drug is clinically similar to the current recommendation.")

        current_dx = current_case.get("diagnosis")
        hist_dx = match.get("diagnosis")

        if normalize_text(current_dx) == normalize_text(hist_dx):
            reasons.append(f"Diagnosis matches exactly: {hist_dx}.")
        elif current_dx and hist_dx:
            reasons.append(
                f"Diagnosis is related but not exact: current={current_dx}, historical={hist_dx}."
            )
        else:
            reasons.append("Diagnosis comparison was limited because one diagnosis value is missing.")

        current_rec_product = current_case.get("recommended_product", {})
        hist_rec_product = match.get("recommended_product", {})

        if self._exact_match(
            current_rec_product.get("DRG_CLASS_NM"),
            hist_rec_product.get("DRG_CLASS_NM"),
        ):
            reasons.append(
                f"Recommended drug class matches: {hist_rec_product.get('DRG_CLASS_NM')}."
            )

        if self._exact_match(
            current_rec_product.get("DRG_SUB_CLASS_NM"),
            hist_rec_product.get("DRG_SUB_CLASS_NM"),
        ):
            reasons.append(
                f"Recommended drug subclass matches: {hist_rec_product.get('DRG_SUB_CLASS_NM')}."
            )

        if self._exact_match(
            current_rec_product.get("GPI_NO"),
            hist_rec_product.get("GPI_NO"),
        ):
            reasons.append("Recommended product GPI matches exactly.")

        decision = normalize_text(match.get("decision")).upper()

        if decision == "ACCEPTED":
            reasons.append("Historical decision was accepted, which supports the recommendation.")
        elif decision == "REJECTED":
            reasons.append("Historical decision was rejected, which weakens support for the recommendation.")
        elif decision == "MODIFIED":
            reasons.append("Historical decision was modified, giving partial support.")
        else:
            reasons.append("Historical decision was unknown, so default decision weighting was applied.")

        decision_reason = self._clean_optional_text(match.get("decision_reason"))
        if decision_reason:
            reasons.append(f"Historical doctor reasoning: {decision_reason}.")

        modified_drug = self._clean_optional_text(match.get("modified_drug"))
        if modified_drug:
            reasons.append(f"Historical modified drug: {modified_drug}.")

        reasons.append(
            f"Case score combines structured_similarity={match.get('structured_similarity')}, "
            f"reason-aware decision_weight={match.get('decision_weight')}, "
            f"and time_decay={match.get('time_decay')}, resulting in "
            f"case_score={match.get('case_score')}."
        )

        reasons.append(
            f"Rule-based patient adjustment was applied with "
            f"rule_adjustment_score={round(rule_adjustment_score, 4)} and "
            f"combined_patient_adjustment_score={round(adjustment_score, 4)}."
        )

        if rule_adjustment_explanation:
            reasons.append(
                f"Rule-based patient adjustment explanation: {rule_adjustment_explanation}"
            )

        return reasons

    def _build_top_case_summaries(
        self,
        current_case: Dict[str, Any],
        scored_matches: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        summaries = []

        for rank, match in enumerate(scored_matches[: self.config.top_k], start=1):
            modified_score = float(match.get("case_score", 0.0))

            rule_adjustment_score = float(match.get("rule_adjustment_score", 0.0))
            combined_patient_adjustment_score = float(
                match.get("combined_patient_adjustment_score", 0.0)
            )

            rule_adjustment_explanation = match.get("rule_adjustment_explanation", "")

            final_score_after_patient_adjustment = max(
                0.0,
                min(1.0, modified_score + combined_patient_adjustment_score)
            )

            summaries.append({
                "rank": rank,
                "case_id": match.get("case_id"),
                "claim_id": match.get("claim_id"),
                "date": match.get("timestamp"),

                "decision": match.get("decision"),
                "modified_drug": self._clean_optional_text(match.get("modified_drug")),
                "decision_reason": self._clean_optional_text(match.get("decision_reason")),

                "original_drug": match.get("original_drug"),
                "recommended_drug": match.get("recommended_drug"),
                "diagnosis": match.get("diagnosis"),

                "structured_similarity_score": match.get("structured_similarity"),
                "similarity_score": match.get("similarity"),
                "decision_weight": match.get("decision_weight"),
                "time_decay": match.get("time_decay"),

                "modified_score_after_time_decay_and_decision_weight": round(
                    modified_score,
                    4,
                ),

                "rule_adjustment_score": round(rule_adjustment_score, 4),
                "combined_patient_adjustment_score": round(
                    combined_patient_adjustment_score,
                    4,
                ),

                "final_score_after_patient_adjustment": round(
                    final_score_after_patient_adjustment,
                    4,
                ),

                "rule_adjustment_explanation": rule_adjustment_explanation,

                "reasoning": self._build_case_reasoning(
                    current_case=current_case,
                    match=match,
                    rule_adjustment_score=rule_adjustment_score,
                    adjustment_score=combined_patient_adjustment_score,
                    final_score_after_patient_adjustment=final_score_after_patient_adjustment,
                    rule_adjustment_explanation=rule_adjustment_explanation,
                ),
            })

        return summaries

    def _build_final_llm_reasoning_context(
        self,
        current_case: Dict[str, Any],
        top_case_summaries: List[Dict[str, Any]],
        average_confidence_score: float,
    ) -> Dict[str, Any]:
        cases_for_llm = []

        for case in top_case_summaries[: self.config.final_reasoning_top_k]:
            cases_for_llm.append({
                "rank": case.get("rank"),
                "case_id": case.get("case_id"),

                "decision": case.get("decision"),
                "modified_drug": case.get("modified_drug"),
                "decision_reason": case.get("decision_reason"),

                "original_drug": case.get("original_drug"),
                "recommended_drug": case.get("recommended_drug"),
                "diagnosis": case.get("diagnosis"),

                "structured_similarity_score": case.get("structured_similarity_score"),
                "similarity_score": case.get("similarity_score"),
                "decision_weight": case.get("decision_weight"),
                "time_decay": case.get("time_decay"),
                "modified_score_after_time_decay_and_decision_weight": case.get(
                    "modified_score_after_time_decay_and_decision_weight"
                ),
                "rule_adjustment_score": case.get("rule_adjustment_score"),
                "final_score_after_patient_adjustment": case.get(
                    "final_score_after_patient_adjustment"
                ),

                "rule_adjustment_explanation": case.get("rule_adjustment_explanation"),
                "case_reasoning": case.get("reasoning", []),
            })

        return {
            "current_case": {
                "original_drug": current_case.get("original_drug"),
                "recommended_drug": current_case.get("recommended_drug"),
                "diagnosis": current_case.get("diagnosis"),
                "patient_id": current_case.get("patient_id"),
                "member_key": current_case.get("member_key"),
            },
            "average_confidence_score": average_confidence_score,
            "top_historical_cases": cases_for_llm,
        }

    def _build_final_llm_reasoning_messages(
        self,
        reasoning_context: Dict[str, Any],
    ) -> List[Dict[str, str]]:
        system_prompt = """
    You are the final reasoning layer of a Past Decisions Agent.

    You will receive:
    - The current prescription substitution case.
    - The top historical cases retrieved by the similarity engine.
    - Structured similarity outputs.
    - Time decay outputs.
    - Reason-aware decision weight outputs.
    - Rule-based patient adjustment outputs.
    - Historical doctor decisions.
    - Historical doctor reasoning from the doctor responses dataset.

    Your job:
    Create one concise final reasoning statement for the Orchestrator.

    Core rules:
    - Use historical doctor decisions and reasons as evidence.
    - Explain whether historical evidence generally supports, weakens, or partially supports the recommendation.
    - Mention whether the evidence is mostly accepted, mixed, modified, rejected, safety-related, patient-specific, or administratively/clinically cautious.
    - Do not make a clinical decision.
    - Do not approve or reject the prescription.
    - Do not invent facts.
    - Do not mention numeric scores, exact percentages, weights, thresholds, or confidence values.
    - Do not output any confidence number.
    - The system will separately return the average confidence score.

    Similarity interpretation rules:
    - Be precise when describing similarity.
    - If all top cases match exactly on original drug, recommended drug, and diagnosis, you may say "exact historical matches."
    - If some cases match exactly and others are only clinically related, say "a mix of exact and closely related matches."
    - Do not say all cases are exact matches if any case has a related but non-exact diagnosis, different original drug, or different therapeutic context.
    - Distinguish exact diagnosis matches from related diagnosis-family matches.
    - Distinguish same-class therapeutic similarity from true drug equivalence.
    - Do not imply two drugs are interchangeable unless they are in the same class/subclass and the historical evidence supports that interpretation.
    - If fewer than four historical cases are retrieved, mention that the available historical evidence is limited.
    - For respiratory cases, do not imply that inhaled corticosteroids, leukotriene modifiers, short-acting beta agonists, and long-acting muscarinic antagonists are directly interchangeable. They may be related within asthma/COPD treatment context, but they have different therapeutic roles. Describe historical support as related respiratory-treatment evidence unless the drugs are in the same class/subclass.

    Decision interpretation rules:
    - ACCEPTED cases support the recommendation.
    - MODIFIED cases provide partial support, because the recommendation was not accepted exactly as proposed.
    - REJECTED cases weaken support.
    - If top cases contain a mix of ACCEPTED, MODIFIED, and REJECTED decisions, describe the evidence as "partial support with caution" unless accepted exact matches clearly dominate.
    - If the top-ranked case is MODIFIED or REJECTED, explicitly mention that as a cautionary signal.
    - If accepted cases dominate but there are meaningful modified or rejected cases, use wording such as "generally supports with caution."
    - If rejected cases dominate, use wording such as "cautionary evidence" or "weakens support."
    - Do not overstate support when there are important rejected or modified exact matches.

    Patient-specific rejection and modification rules:
    When a historical case is REJECTED or MODIFIED for a patient-specific reason, evaluate whether that concern appears transferable to the current patient.

    Patient-specific reasons include:
    - Documented allergy or prior intolerance to recommended drug/drug class
    - Clinically significant drug-drug interaction risk
    - Contraindication based on patient’s current condition or medication profile
    - Recommended alternative may worsen an existing comorbidity
    - Patient previously failed recommended drug
    - Modified due to drug-drug interaction concern
    - Modified due to allergy, intolerance, or prior adverse reaction history

    Use the rule-based patient adjustment explanation and similarity factors to interpret transferability:
    - If medication_pattern_similarity is high and the historical reason involves drug interaction or medication-profile concern, mention that the historical concern may be more applicable to the current patient.
    - If medication_pattern_similarity is low, say the interaction or medication-profile concern may be less transferable.
    - If allergy_profile_similarity is high and the historical reason involves allergy, intolerance, or adverse reaction, mention that the allergy/intolerance concern may be more applicable.
    - If allergy_profile_similarity is low or the historical reason is not allergy-related, do not imply allergy risk.
    - If the historical reason is comorbidity-related, only say the concern is strongly transferable if current and historical medical-condition similarity is explicitly available and high.
    - If medical-condition similarity is not available, say the comorbidity concern is clinically relevant but transferability to the current patient is uncertain.
    - Do not infer a current allergy, interaction, contraindication, renal issue, hepatic issue, prior failure, or comorbidity unless the retrieved case evidence or patient-profile data explicitly supports it.
    - When counting exact matches, verify exactness separately for original drug, recommended drug, and diagnosis. If any case has a related but non-exact diagnosis, do not count it as an exact match; call it a closely related match instead.

    Transferability wording rules:
    - If medication_pattern_similarity is 0.70 or higher, describe medication-profile transferability as strong.
    - If medication_pattern_similarity is between 0.30 and 0.69, describe medication-profile transferability as moderate or partial.
    - If medication_pattern_similarity is below 0.30, describe medication-profile transferability as limited or weak.
    - If allergy_profile_similarity is 0.70 or higher and the historical reason is allergy/intolerance/adverse-reaction related, describe allergy-profile transferability as strong.
    - If allergy_profile_similarity is low or the reason is not allergy-related, do not imply an allergy concern.
    - For comorbidity-related rejection reasons, do not use phrases like "highly transferable" unless an explicit medical-condition similarity signal is available.
    - If only diagnosis similarity is available, say the concern is "clinically relevant" rather than "highly transferable."
    - Do not overstate transferability.

    Stable-therapy rejection rules:
    If the rejection reason is:
    "Patient is stable on current therapy; substitution may cause unnecessary disruption"

    Then describe it as:
    "patient-specific stable therapy concern"

    Do not describe stable-therapy rejection as:
    - a general safety concern
    - contraindication
    - allergy issue
    - drug interaction
    - evidence that the recommended drug is broadly unsafe

    Explain that this type of rejection weakens support in that specific patient context, but does not necessarily mean the recommended drug is broadly unsafe or clinically inappropriate.

    Heart failure treatment-context rules:
    For heart failure cases, be careful when original and recommended drugs have different therapeutic roles.
    Examples:
    - ARNI
    - beta blocker
    - loop diuretic
    - aldosterone antagonist
    - ACE inhibitor
    - potassium-sparing diuretic

    These may all be relevant to heart failure but are not automatically interchangeable.
    Describe historical support as related heart-failure treatment-context evidence, not direct therapeutic equivalence, unless the drugs are in the same class/subclass.

    Mixed-evidence summary rules:
    When summarizing mixed evidence:
    - Clearly separate general therapeutic support from patient-specific caution.
    - Accepted exact or close matches support the recommendation.
    - Modified cases mean clinicians partially agreed but changed something.
    - Rejected cases weaken support, but patient-specific rejection reasons should strongly weaken the current case only if patient similarity suggests the concern may transfer.
    - If rejection reasons are patient-specific and transferability is unclear, say the rejection is a cautionary signal rather than broad evidence against the recommendation.
    - Avoid saying "strongly supports" if there are multiple rejected cases or if the highest-ranked case is rejected.
    - Avoid saying "weakens support overall" if accepted exact matches clearly outnumber rejected cases and rejected reasons appear patient-specific or weakly transferable.
    - Use balanced language such as "partial support with caution" when evidence is mixed.

    Reasoning style:
    - Write in one concise paragraph.
    - Be clear and orchestrator-facing.
    - Do not use bullet points.
    - Do not mention internal field names unless needed for clarity.
    - Do not mention exact numeric similarity values.
    - Do not mention the average confidence score.
    - Do not hallucinate clinical facts not present in the retrieved cases.
    - Do not introduce new medical reasoning beyond the retrieved historical evidence and provided patient-similarity factors.

    Return only valid JSON in this exact format:

    {
    "final_statement": "short reasoning statement for orchestrator"
    }
    """

        user_prompt = json.dumps(reasoning_context, indent=2, default=str)

        return [
            {
                "role": "system",
                "content": system_prompt.strip(),
            },
            {
                "role": "user",
                "content": user_prompt,
            },
        ]

    def _generate_final_llm_reasoning(
        self,
        current_case: Dict[str, Any],
        top_case_summaries: List[Dict[str, Any]],
        average_confidence_score: float,
    ) -> Dict[str, Any]:
        if not top_case_summaries:
            return {
                "final_statement": (
                    "No sufficiently similar historical cases were found. "
                    "Past Decisions evidence is limited, so the recommendation should rely more heavily on the other agents."
                )
            }

        if not self.config.enable_llm_final_reasoning:
            return {
                "final_statement": self._build_default_final_statement(top_case_summaries)
            }

        try:
            context = self._build_final_llm_reasoning_context(
                current_case=current_case,
                top_case_summaries=top_case_summaries,
                average_confidence_score=average_confidence_score,
            )

            messages = self._build_final_llm_reasoning_messages(context)

            content = self._call_llm(
                messages=messages,
                temperature=self.config.llm_final_reasoning_temperature,
            )

            parsed = self._parse_llm_json_response(content)

            final_statement = str(parsed.get("final_statement", "")).strip()

            if not final_statement:
                final_statement = self._build_default_final_statement(top_case_summaries)

            return {
                "final_statement": final_statement
            }

        except Exception as exc:
            if self.config.debug:
                print("FINAL LLM REASONING ERROR:", str(exc))

            return {
                "final_statement": self._build_default_final_statement(top_case_summaries)
            }

    def _build_default_final_statement(
        self,
        top_case_summaries: List[Dict[str, Any]],
    ) -> str:
        if not top_case_summaries:
            return (
                "No sufficiently similar historical cases were available. "
                "Past Decisions evidence is limited."
            )

        accepted = sum(
            1 for case in top_case_summaries
            if normalize_text(case.get("decision")).upper() == "ACCEPTED"
        )

        modified = sum(
            1 for case in top_case_summaries
            if normalize_text(case.get("decision")).upper() == "MODIFIED"
        )

        rejected = sum(
            1 for case in top_case_summaries
            if normalize_text(case.get("decision")).upper() == "REJECTED"
        )

        if rejected > accepted:
            return (
                "Historical evidence is cautious because rejected cases are strongly represented among similar past decisions. "
                "The Orchestrator should review the recommendation carefully alongside Clinical, Policy, and Financial agent outputs."
            )

        if accepted > rejected and modified == 0:
            return (
                "Historical evidence generally supports the recommendation because similar past cases were accepted by doctors. "
                "The Orchestrator can treat Past Decisions as a supportive signal."
            )

        return (
            "Historical evidence is mixed because similar past cases include accepted, modified, and/or rejected decisions. "
            "The Orchestrator should combine this signal with Clinical, Policy, and Financial agent outputs."
        )

def _backend_data_path(filename: str) -> str:
    backend_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    return os.path.join(backend_root, "data", filename)


def _doctor_responses_filename() -> str:
    """Resolve the doctor feedback file used by both API writes and past scoring.

    Defaults to doctor_responses_revised_5.csv, but allows override for
    backfills/debug datasets.
    """
    return os.getenv("PBM_DOCTOR_RESPONSES_FILE", "doctor_responses_revised_5.csv")


@lru_cache(maxsize=1)
def _build_orchestrator_agent() -> PastDecisionsAgent:
    dataset_paths = DatasetPaths(
        doctor_responses=_backend_data_path(_doctor_responses_filename()),
        claims=_backend_data_path("F_CLM_TRANSACTION.csv"),
        product=_backend_data_path("v_d_product.csv"),
        prescription=_backend_data_path("v_xxiris_om_prescription.csv"),
        member=_backend_data_path("v_d_member.csv"),
        patient_history=_backend_data_path("patient_history.csv"),
    )
    return PastDecisionsAgent(dataset_paths=dataset_paths, config=AgentConfig(debug=False))


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _drug_name_from_prod_sk(agent: PastDecisionsAgent, prod_sk: Any) -> Optional[str]:
    if prod_sk is None:
        return None
    row = agent._find_product_by_sk(prod_sk)
    if row is None:
        return None
    product_name = row.get(agent.config.product_name_col)
    if product_name is None:
        return None
    text = str(product_name).strip()
    return text or None


async def past_decisions_agent(candidate_payload: Dict[str, Any]) -> Dict[str, Any]:
    """Async adapter that maps orchestrator candidate input into PastDecisionsAgent.run()."""
    try:
        agent = _build_orchestrator_agent()
        # Refresh mutable doctor feedback on every request so new accepts/rejects
        # are reflected immediately without restarting the backend process.
        agent.data["doctor_responses"] = agent._read_csv_required(agent.paths.doctor_responses)

        original_name = _drug_name_from_prod_sk(agent, candidate_payload.get("original_drug_id"))
        recommended_name = _drug_name_from_prod_sk(agent, candidate_payload.get("drug_id"))

        if not original_name or not recommended_name:
            return {
                "match": None,
                "score": 0.0,
                "has_signal": False,
                "final_statement": "",
                "average_confidence_score": 0.0,
                "notes": "Past decisions skipped: unable to map drug IDs to product names.",
                "top_cases": [],
                "raw": {},
            }

        payload = {
            "claim_id": candidate_payload.get("claim_id"),
            "drug": original_name,
            "member_key": candidate_payload.get("member_id"),
            "diagnosis": candidate_payload.get("diagnosis"),
        }
        clinical_output = {"recommended": recommended_name}

        result = await asyncio.to_thread(agent.run, payload, clinical_output)

        top_cases = result.get("top_cases") or []
        average_confidence_score = _safe_float(result.get("average_confidence_score"), 0.0)
        final_statement = str(result.get("final_statement") or "").strip()
        has_signal = bool(top_cases)

        return {
            "match": top_cases[0] if has_signal else None,
            "score": average_confidence_score,
            "has_signal": has_signal,
            "final_statement": final_statement,
            "average_confidence_score": average_confidence_score,
            "notes": (
                "Historical precedent evaluated."
                if has_signal
                else "No sufficiently similar historical cases found."
            ),
            "top_cases": top_cases,
            "raw": result,
        }
    except Exception as exc:
        return {
            "match": None,
            "score": 0.0,
            "has_signal": False,
            "final_statement": "",
            "average_confidence_score": 0.0,
            "notes": f"Past decisions adapter error: {exc}",
            "top_cases": [],
            "raw": {},
        }


__all__ = ["DatasetPaths", "AgentConfig", "PastDecisionsAgent", "past_decisions_agent"]