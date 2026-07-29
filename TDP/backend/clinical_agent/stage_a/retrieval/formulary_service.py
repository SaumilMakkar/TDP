"""Sprint 2 retrieval against formulary_alternative CSV only."""

from __future__ import annotations

import logging

import pandas as pd

from stage_a.config import FORMULARY_CSV_NAME, csv_path
from stage_a.normalization.drug_builder import (
    Drug,
    DrugBuilder,
)

logger = logging.getLogger(__name__)

FORMULARY_REQUIRED_COLUMNS = {
    "TRGT_PROD_SK",
    "ALT_PROD_SK",
    "ALT_SEQ_NBR",
}


def _resolve_formulary_csv() -> str:
    return str(csv_path(FORMULARY_CSV_NAME))


FORMULARY_DF = pd.read_csv(
    _resolve_formulary_csv(),
    dtype={"TRGT_PROD_SK": "Int64", "ALT_PROD_SK": "Int64", "ALT_SEQ_NBR": "Int64"},
    low_memory=False,
)

missing_cols = FORMULARY_REQUIRED_COLUMNS - set(FORMULARY_DF.columns)
if missing_cols:
    raise ValueError(
        f"{FORMULARY_CSV_NAME} schema mismatch. "
        f"Missing required columns: {sorted(missing_cols)}"
    )


def get_alternatives(
    prod_sk: int,
    include_inactive_products: bool = False,
) -> list[Drug]:
    candidate_rows = FORMULARY_DF[FORMULARY_DF["TRGT_PROD_SK"] == int(prod_sk)].copy()
    candidate_rows = candidate_rows.sort_values("ALT_SEQ_NBR", na_position="last")

    builder = DrugBuilder()
    alternatives: list[Drug] = []
    for _, row in candidate_rows.iterrows():
        alt_prod_sk = row.get("ALT_PROD_SK")
        if pd.isna(alt_prod_sk):
            logger.warning("Missing ALT_PROD_SK for TRGT_PROD_SK=%s row id=%s", prod_sk, row.get("FRMLRY_ALT_SK"))
            continue
        try:
            alternatives.append(
                builder.build(int(alt_prod_sk), include_inactive=include_inactive_products)
            )
        except (KeyError, ValueError) as exc:
            logger.warning(
                "Could not build alternative PROD_SK=%s for TRGT_PROD_SK=%s: %s",
                int(alt_prod_sk),
                prod_sk,
                exc,
            )
    return alternatives


def compare(original_drug: Drug, candidate_drug: Drug) -> dict:
    def _eq(left: str | None, right: str | None) -> bool | None:
        if left is None or right is None:
            return None
        return left.strip().lower() == right.strip().lower()

    original_set = {item.strip().lower() for item in original_drug.ingredients if item}
    candidate_set = {item.strip().lower() for item in candidate_drug.ingredients if item}

    return {
        "original_product_id": original_drug.product_id,
        "candidate_product_id": candidate_drug.product_id,
        "generic_name_match": _eq(original_drug.generic_name, candidate_drug.generic_name),
        "dosage_form_match": _eq(original_drug.dosage_form, candidate_drug.dosage_form),
        "therapeutic_class_match": _eq(
            original_drug.therapeutic_class,
            candidate_drug.therapeutic_class,
        ),
        "ingredient_overlap": sorted(original_set & candidate_set),
        "ingredient_original_only": sorted(original_set - candidate_set),
        "ingredient_candidate_only": sorted(candidate_set - original_set),
        "original": original_drug.to_dict(),
        "candidate": candidate_drug.to_dict(),
    }


class FormularyService:
    """Compatibility wrapper for Sprint 2 public functions."""

    def get_alternatives(
        self,
        prod_sk: int,
        include_inactive_products: bool = False,
    ) -> list[Drug]:
        return get_alternatives(prod_sk, include_inactive_products)

    def compare(self, original_drug: Drug, candidate_drug: Drug) -> dict:
        return compare(original_drug, candidate_drug)
