"""
drug_db.py - Data access layer for PBM drugs, formulary, and patient information.

This module provides a centralized interface to all CSV data sources used by the
clinical agent and orchestrator. It caches DataFrames and provides methods for
looking up drugs, ingredients, formulary alternatives, member data, and prescription
history.
"""

import os
import logging
from datetime import datetime
from functools import lru_cache

import pandas as pd

logger = logging.getLogger(__name__)


class DrugDB:
    """Data access layer for PBM clinical and formulary data."""

    def __init__(self, data_dir: str = None):
        """Initialize DrugDB with path to data directory.
        
        Args:
            data_dir: Path to directory containing CSV files. Defaults to
                     ../data relative to this file, or PBM_DATA_DIR env var.
        """
        if data_dir is None:
            data_dir = os.environ.get(
                "PBM_DATA_DIR",
                os.path.join(os.path.dirname(__file__), "..", "..", "data")
            )
        self.data_dir = data_dir
        self._products = None
        self._ingredients = None
        self._formulary_alt = None
        self._members = None
        self._prescriptions = None
        self._claims = None

    def _load_products(self) -> pd.DataFrame:
        """Load product dimension table."""
        if self._products is None:
            path = os.path.join(self.data_dir, "v_d_product.csv")
            self._products = pd.read_csv(path, dtype={"PROD_SK": str, "PROD_ID": str})
            self._products.set_index("PROD_SK", inplace=True)
        return self._products

    def _load_ingredients(self) -> pd.DataFrame:
        """Load ingredient dimension table."""
        if self._ingredients is None:
            path = os.path.join(self.data_dir, "v_d_prod_ingredient.csv")
            self._ingredients = pd.read_csv(path, dtype={"PROD_SK": str})
        return self._ingredients

    def _load_formulary_alternatives(self) -> pd.DataFrame:
        """Load formulary alternative mappings."""
        if self._formulary_alt is None:
            path = os.path.join(self.data_dir, "v_d_formulary_alternative.csv")
            self._formulary_alt = pd.read_csv(path, dtype={"TRGT_PROD_SK": str, "ALT_PROD_SK": str})
            # Convert date columns
            self._formulary_alt["FRMLRY_FROM_DT"] = pd.to_datetime(self._formulary_alt["FRMLRY_FROM_DT"])
            self._formulary_alt["FRMLRY_THRU_DT"] = pd.to_datetime(self._formulary_alt["FRMLRY_THRU_DT"])
        return self._formulary_alt

    def _load_members(self) -> pd.DataFrame:
        """Load member dimension table."""
        if self._members is None:
            path = os.path.join(self.data_dir, "v_d_member.csv")
            self._members = pd.read_csv(path, dtype={"MBR_SK": str, "PLN_SK": str})
            self._members.set_index("MBR_SK", inplace=True)
        return self._members

    def _load_prescriptions(self) -> pd.DataFrame:
        """Load prescription history."""
        if self._prescriptions is None:
            path = os.path.join(self.data_dir, "v_xxiris_om_prescription.csv")
            self._prescriptions = pd.read_csv(path, dtype={"MBR_SK": str, "PROD_SK": str})
            # Convert date columns
            self._prescriptions["DATE_WRITTEN"] = pd.to_datetime(self._prescriptions["DATE_WRITTEN"])
            self._prescriptions["DATE_FILLED"] = pd.to_datetime(self._prescriptions["DATE_FILLED"], errors="coerce")
        return self._prescriptions

    def _load_claims(self) -> pd.DataFrame:
        """Load claim transaction data."""
        if self._claims is None:
            path = os.path.join(self.data_dir, "F_CLM_TRANSACTION.csv")
            self._claims = pd.read_csv(path, dtype={"MBR_SK": str, "PROD_SK": str, "CLAIM_NBR": str})
            # Convert date columns
            self._claims["CLAIM_PROC_DT"] = pd.to_datetime(self._claims["CLAIM_PROC_DT"], errors="coerce")
            self._claims["FILLED_DT"] = pd.to_datetime(self._claims["FILLED_DT"], errors="coerce")
        return self._claims

    # ---- Product lookups ----

    def get_product(self, prod_sk: str) -> dict:
        """Get product record by PROD_SK.
        
        Args:
            prod_sk: Product surrogate key
            
        Returns:
            Product record as a dict, or empty dict if not found
        """
        products = self._load_products()
        if prod_sk in products.index:
            row = products.loc[prod_sk].to_dict()
            row["PROD_SK"] = str(prod_sk)
            return row
        logger.warning(f"Product {prod_sk} not found")
        return {}

    def get_product_by_name(self, drug_name: str) -> dict:
        """Get product record by drug name.
        
        Args:
            drug_name: Product name (PROD_NM)
            
        Returns:
            First matching product record as a dict, or empty dict if not found
        """
        products = self._load_products()
        matches = products[products["PROD_NM"].str.contains(drug_name, case=False, na=False)]
        if not matches.empty:
            row = matches.iloc[0].to_dict()
            row["PROD_SK"] = str(matches.index[0])
            return row
        logger.warning(f"Product {drug_name} not found")
        return {}

    # ---- Ingredient lookups ----

    def get_ingredients(self, prod_sk: str) -> pd.DataFrame:
        """Get all ingredients for a product.
        
        Args:
            prod_sk: Product surrogate key
            
        Returns:
            DataFrame of ingredients for this product
        """
        ingredients = self._load_ingredients()
        result = ingredients[ingredients["PROD_SK"] == prod_sk]
        if result.empty:
            logger.warning(f"No ingredients found for product {prod_sk}")
        return result

    # ---- Formulary alternative lookups ----

    def get_alternatives(self, prod_sk: str, as_of_date: datetime = None) -> pd.DataFrame:
        """Get formulary alternatives for a product, filtered by date validity.
        
        This is Stage A - fetches all valid alternatives (as of today or specified date),
        with deduplication on ALT_PROD_SK and sorting by ALT_SEQ_NBR.
        
        Args:
            prod_sk: Target product surrogate key
            as_of_date: Optional date to check validity against (default: today)
            
        Returns:
            DataFrame of valid alternatives, deduplicated and sorted by sequence number
        """
        if as_of_date is None:
            as_of_date = datetime.now()

        formulary_alt = self._load_formulary_alternatives()
        
        # Filter by target product
        candidates = formulary_alt[formulary_alt["TRGT_PROD_SK"] == prod_sk].copy()
        
        # Apply date validity filter: today must be between FROM_DT and THRU_DT
        candidates = candidates[
            (candidates["FRMLRY_FROM_DT"] <= as_of_date) &
            (candidates["FRMLRY_THRU_DT"] >= as_of_date)
        ]
        
        # Deduplicate on ALT_PROD_SK (keep first occurrence)
        candidates = candidates.drop_duplicates(subset=["ALT_PROD_SK"], keep="first")
        
        # Sort by sequence number
        candidates = candidates.sort_values("ALT_SEQ_NBR").reset_index(drop=True)
        
        if candidates.empty:
            logger.warning(f"No valid alternatives found for product {prod_sk} as of {as_of_date}")
        
        return candidates

    # ---- Member lookups ----

    def get_member(self, mbr_sk: str) -> dict:
        """Get member record by MBR_SK.
        
        Args:
            mbr_sk: Member surrogate key
            
        Returns:
            Member record as a dict, or empty dict if not found
        """
        members = self._load_members()
        if mbr_sk in members.index:
            return members.loc[mbr_sk].to_dict()
        logger.warning(f"Member {mbr_sk} not found")
        return {}

    # ---- Patient history lookups ----

    def get_patient_history(self, mbr_sk: str) -> pd.DataFrame:
        """Get prescription and claims history for a patient.
        
        This merges prescription history with claims data to provide a complete
        view of what the patient has been prescribed and what claims have been processed.
        Used in Stage B (safety validation) to check for:
          - Provider continuity (same prescriber)
          - Prior authorizations (PA_APPROVED_FLG from claims)
          - Claim status (CLAIM_STAT_ID from claims)
          - Medication conflicts (already prescribed drugs)
        
        Args:
            mbr_sk: Member surrogate key
            
        Returns:
            Merged DataFrame with prescription and claims records for this member
        """
        prescriptions = self._load_prescriptions()
        claims = self._load_claims()
        
        # Get all prescriptions for this member
        member_rx = prescriptions[prescriptions["MBR_SK"] == mbr_sk].copy()
        
        # Get all claims for this member
        member_claims = claims[claims["MBR_SK"] == mbr_sk].copy()
        
        # Merge prescriptions with claims on RX_NUMBER/RX_NBR
        # Left join on prescriptions to keep all prescriptions even if no claim yet
        history = member_rx.merge(
            member_claims[["RX_NBR", "CLAIM_STAT_ID", "PA_APPROVED_FLG", "FILLED_DT", "CLAIM_PROC_DT"]],
            left_on="RX_NUMBER",
            right_on="RX_NBR",
            how="left"
        )
        
        if history.empty:
            logger.warning(f"No history found for member {mbr_sk}")
        
        return history

    # ---- Helper methods for scoring ----

    def get_pa_history(self, mbr_sk: str, prod_sk: str = None) -> pd.DataFrame:
        """Get prior authorization history for a patient, optionally filtered by product.
        
        Args:
            mbr_sk: Member surrogate key
            prod_sk: Optional product to filter on
            
        Returns:
            DataFrame of claims with PA_APPROVED_FLG != 'N'
        """
        history = self.get_patient_history(mbr_sk)
        
        # Filter to rows where PA was involved (PA_APPROVED_FLG is not null/empty)
        pa_records = history[history["PA_APPROVED_FLG"].notna()]
        
        if prod_sk:
            pa_records = pa_records[pa_records["PROD_SK"] == prod_sk]
        
        return pa_records

    def get_claim_status(self, mbr_sk: str, prod_sk: str = None) -> pd.Series:
        """Get claim statuses for a patient's drugs.
        
        Args:
            mbr_sk: Member surrogate key
            prod_sk: Optional product to filter on
            
        Returns:
            Series of claim statuses (PAID, REJECTED, PENDING, etc.)
        """
        history = self.get_patient_history(mbr_sk)
        
        if prod_sk:
            history = history[history["PROD_SK"] == prod_sk]
        
        return history["CLAIM_STAT_ID"]
