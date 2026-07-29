"""Sprint 1 core model builder using real CSV sources only."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass

import pandas as pd

from stage_a.config import (
    DATA_DIR,
    INGREDIENT_CSV_NAME,
    PRODUCT_CSV_NAME,
    REPO_ROOT,
    csv_path,
)
from stage_a.normalization.rxnorm_reference_service import RxNormReferenceService

logger = logging.getLogger(__name__)

PRODUCT_REQUIRED_COLUMNS = {
    "PROD_SK",
    "PROD_ID",
    "PROD_NM",
    "GNRC_NM",
    "THRPC_CLASS_NM",
    "DRG_DOSAG_FRM_NM",
    "NDC",
    "GPI",
    "PROD_ACTV_FLG",
    "DRG_CLASS_NM",
    "RXCUI",
}
INGREDIENT_REQUIRED_COLUMNS = {
    "PROD_SK",
    "PROD_ID",
    "PIG_GNRC_NM",
    "PIG_STRNGTH",
    "PIG_STRNGTH_UOM_CD",
    "PIG_ING_TYPE_CD",
    "PIG_SEQ_NBR",
}


@dataclass
class Drug:
    product_id: int
    product_name: str
    generic_name: str
    ndc: str
    gpi: str
    ingredients: list[str]
    strengths: list[dict[str, object]]
    dosage_form: str | None
    therapeutic_class: str | None
    rxnorm_ref: dict[str, object] | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _is_null(value: object) -> bool:
    return value is None or pd.isna(value) or str(value).strip() == ""


def _clean_str(value: object) -> str | None:
    if _is_null(value):
        return None
    return str(value).strip()


PRODUCT_CSV_PATH = csv_path(PRODUCT_CSV_NAME)
INGREDIENT_CSV_PATH = csv_path(INGREDIENT_CSV_NAME)

PRODUCT_DF = pd.read_csv(
    PRODUCT_CSV_PATH,
    dtype={"PROD_SK": "Int64", "NDC": "string", "GPI": "string", "RXCUI": "string"},
    low_memory=False,
)
INGREDIENT_DF = pd.read_csv(
    INGREDIENT_CSV_PATH,
    dtype={"PROD_SK": "Int64", "PIG_SEQ_NBR": "Int64"},
    low_memory=False,
)

RXNORM_REFERENCE_CSV_PATH = REPO_ROOT / "stage_a" / "data" / "rxnorm_reference_corrected.csv"
RXNORM_REFERENCE_SERVICE = RxNormReferenceService(RXNORM_REFERENCE_CSV_PATH)

missing_product_cols = PRODUCT_REQUIRED_COLUMNS - set(PRODUCT_DF.columns)
if missing_product_cols:
    raise ValueError(
        f"{PRODUCT_CSV_NAME} schema mismatch. Missing required columns: {sorted(missing_product_cols)}"
    )

missing_ingredient_cols = INGREDIENT_REQUIRED_COLUMNS - set(INGREDIENT_DF.columns)
if missing_ingredient_cols:
    raise ValueError(
        f"{INGREDIENT_CSV_NAME} schema mismatch. "
        f"Missing required columns: {sorted(missing_ingredient_cols)}"
    )


def _build_from_product_row(
    product_row: pd.Series,
    include_inactive: bool,
    ingredient_df: pd.DataFrame,
) -> Drug:
    if not include_inactive and _clean_str(product_row.get("PROD_ACTV_FLG")) != "Y":
        raise ValueError(
            f"PROD_SK {int(product_row['PROD_SK'])} is inactive (PROD_ACTV_FLG != 'Y')."
        )

    prod_sk = int(product_row["PROD_SK"])
    ingredient_rows = ingredient_df[
        (ingredient_df["PROD_SK"] == prod_sk)
        & (ingredient_df["PIG_ING_TYPE_CD"].astype("string").str.upper() == "ACTIVE")
    ].copy()
    ingredient_rows = ingredient_rows.sort_values("PIG_SEQ_NBR", na_position="last")

    ingredients: list[str] = []
    strengths: list[dict[str, object]] = []
    for _, ing_row in ingredient_rows.iterrows():
        ingredient_name = _clean_str(ing_row.get("PIG_GNRC_NM"))
        if ingredient_name is None:
            logger.warning(
                "Missing PIG_GNRC_NM for PROD_SK=%s at PIG_SEQ_NBR=%s.",
                prod_sk,
                _clean_str(ing_row.get("PIG_SEQ_NBR")),
            )
            continue
        ingredients.append(ingredient_name)
        raw_strength = ing_row.get("PIG_STRNGTH")
        strength_value = None if _is_null(raw_strength) else float(raw_strength)
        strengths.append(
            {
                "ingredient": ingredient_name,
                "strength": strength_value,
                "unit": _clean_str(ing_row.get("PIG_STRNGTH_UOM_CD")),
            }
        )

    therapeutic_class = _clean_str(product_row.get("THRPC_CLASS_NM")) or _clean_str(
        product_row.get("DRG_CLASS_NM")
    )
    if therapeutic_class is None:
        logger.warning(
            "Missing therapeutic class for PROD_SK=%s (THRPC_CLASS_NM and DRG_CLASS_NM are null).",
            prod_sk,
        )

    rxnorm_ref = RXNORM_REFERENCE_SERVICE.get_by_prod_sk(prod_sk)
    if rxnorm_ref is None:
        logger.warning(
            "No RxNorm reference row found for PROD_SK=%s; runtime normalization fields will be missing.",
            prod_sk,
        )

    return Drug(
        product_id=prod_sk,
        product_name=_clean_str(product_row.get("PROD_NM")) or "",
        generic_name=_clean_str(product_row.get("GNRC_NM")) or "",
        ndc=_clean_str(product_row.get("NDC")) or "",
        gpi=_clean_str(product_row.get("GPI")) or "",
        ingredients=ingredients,
        strengths=strengths,
        dosage_form=_clean_str(product_row.get("DRG_DOSAG_FRM_NM")),
        therapeutic_class=therapeutic_class,
        rxnorm_ref=rxnorm_ref,
    )


def build_drug(product_id: int, include_inactive: bool = False) -> Drug:
    rows = PRODUCT_DF[PRODUCT_DF["PROD_SK"] == int(product_id)]
    if rows.empty:
        raise KeyError(f"PROD_SK not found: {product_id}")
    return _build_from_product_row(
        rows.iloc[0],
        include_inactive=include_inactive,
        ingredient_df=INGREDIENT_DF,
    )


def build_drug_from_ndc(ndc: str, include_inactive: bool = False) -> Drug:
    ndc_norm = str(ndc).strip()
    rows = PRODUCT_DF[PRODUCT_DF["NDC"].astype("string").str.strip() == ndc_norm]
    if rows.empty:
        raise KeyError(f"NDC not found: {ndc}")
    return _build_from_product_row(
        rows.iloc[0],
        include_inactive=include_inactive,
        ingredient_df=INGREDIENT_DF,
    )


def build_drug_from_dataframes(
    product_df: pd.DataFrame,
    ingredient_df: pd.DataFrame,
    product_id: int,
    include_inactive: bool = False,
) -> Drug:
    rows = product_df[product_df["PROD_SK"] == int(product_id)]
    if rows.empty:
        raise KeyError(f"PROD_SK not found in provided DataFrame: {product_id}")
    return _build_from_product_row(
        rows.iloc[0],
        include_inactive=include_inactive,
        ingredient_df=ingredient_df,
    )


class DrugBuilder:
    """Compatibility wrapper around Sprint 1 module-level builders."""

    @property
    def product_df(self) -> pd.DataFrame:
        return PRODUCT_DF

    @property
    def ingredient_df(self) -> pd.DataFrame:
        return INGREDIENT_DF

    def build(self, prod_sk: int, include_inactive: bool = False) -> Drug:
        return build_drug(product_id=prod_sk, include_inactive=include_inactive)

    def build_from_ndc(self, ndc: str, include_inactive: bool = False) -> Drug:
        return build_drug_from_ndc(ndc=ndc, include_inactive=include_inactive)
