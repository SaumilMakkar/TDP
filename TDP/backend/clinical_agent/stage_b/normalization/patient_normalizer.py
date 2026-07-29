"""Stage B Sprint B1/B2 patient normalization and retrieval."""

from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

from stage_b.config import MEMBER_CSV_NAME, member_csv_path


PATIENT_REQUIRED_COLUMNS = {
    "MBR_SK",
    "MBR_ID",
    "PLN_SK",
    "AGE",
    "MEDICAL_CONDITIONS",
    "ALLERGIES",
    "CURRENT_MEDICATIONS",
}

MEMBER_CSV_PATH = member_csv_path(MEMBER_CSV_NAME)
MEMBER_DF = pd.read_csv(
    MEMBER_CSV_PATH,
    dtype={"MBR_SK": "Int64", "MBR_ID": "string", "PLN_SK": "Int64", "AGE": "Int64"},
    low_memory=False,
)

missing_member_cols = PATIENT_REQUIRED_COLUMNS - set(MEMBER_DF.columns)
if missing_member_cols:
    raise ValueError(
        f"{MEMBER_CSV_NAME} schema mismatch. Missing required columns: {sorted(missing_member_cols)}"
    )


@dataclass
class Patient:
    mbr_sk: int
    mbr_id: str
    plan_sk: int
    age: int
    conditions: list[str]
    allergies: list[str]
    current_medications: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def _is_null(value: object) -> bool:
    return value is None or pd.isna(value) or str(value).strip() == ""


def _split_multi_value(value: object) -> list[str]:
    if _is_null(value):
        return []
    text = str(value).strip()
    # Dataset values are pipe-delimited today; keep tolerant parsing.
    for delimiter in ("|", ";", ","):
        if delimiter in text:
            return [item.strip() for item in text.split(delimiter) if item.strip()]
    return [text] if text else []


def _to_int(value: object, default: int = 0) -> int:
    if _is_null(value):
        return int(default)
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return int(default)


def resolve_member_id(member_identifier: object) -> str:
    """Resolve various member identifier forms to canonical MBR_ID.

    Accepted inputs:
    - MBR_ID (e.g., MBR0002004)
    - PATIENT_ACCOUNT_ID (e.g., PAT0002004)
    - MBR_SK numeric/id-like value (e.g., 2004)
    """
    text = str(member_identifier or "").strip()
    if not text:
        raise ValueError("member identifier must be a non-empty string.")

    # 1) Exact MBR_ID match
    by_mbr_id = MEMBER_DF[MEMBER_DF["MBR_ID"].astype("string") == text]
    if not by_mbr_id.empty:
        return str(by_mbr_id.iloc[0].get("MBR_ID")).strip()

    # 2) Exact PATIENT_ACCOUNT_ID match
    by_patient_account = MEMBER_DF[MEMBER_DF["PATIENT_ACCOUNT_ID"].astype("string") == text]
    if not by_patient_account.empty:
        return str(by_patient_account.iloc[0].get("MBR_ID")).strip()

    # 3) Numeric MBR_SK match
    try:
        mbr_sk = int(text)
        by_mbr_sk = MEMBER_DF[MEMBER_DF["MBR_SK"].astype("Int64") == mbr_sk]
        if not by_mbr_sk.empty:
            return str(by_mbr_sk.iloc[0].get("MBR_ID")).strip()
    except (TypeError, ValueError):
        pass

    raise KeyError(f"Member identifier {text} was not found in {MEMBER_CSV_NAME}.")


def build_patient(mbr_id: str) -> Patient:
    mbr_text = resolve_member_id(mbr_id)
    matches = MEMBER_DF[MEMBER_DF["MBR_ID"].astype("string") == mbr_text]
    if matches.empty:
        raise KeyError(f"MBR_ID {mbr_text} was not found in {MEMBER_CSV_NAME}.")

    row = matches.iloc[0]
    age = _to_int(row.get("AGE"), default=0)
    mbr_sk = _to_int(row.get("MBR_SK"), default=0)
    plan_sk = _to_int(row.get("PLN_SK"), default=0)

    return Patient(
        mbr_sk=mbr_sk,
        mbr_id=mbr_text,
        plan_sk=plan_sk,
        age=age,
        conditions=_split_multi_value(row.get("MEDICAL_CONDITIONS")),
        allergies=_split_multi_value(row.get("ALLERGIES")),
        current_medications=_split_multi_value(row.get("CURRENT_MEDICATIONS")),
    )
