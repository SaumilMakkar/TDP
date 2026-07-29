"""Reference-table lookup service for Stage A runtime RxNorm/RxClass attributes."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


class RxNormReferenceService:
    """Load and index rxnorm_reference_corrected.csv for fast in-memory lookups."""

    def __init__(self, reference_csv_path: str | Path):
        self.reference_csv_path = Path(reference_csv_path)
        self._df = pd.read_csv(
            self.reference_csv_path,
            dtype={"verified_ndc": "string", "matched_prod_sks": "string"},
            low_memory=False,
        )

        self._by_generic_name: dict[str, dict[str, Any]] = {}
        self._by_prod_sk: dict[str, dict[str, Any]] = {}

        for _, row in self._df.iterrows():
            row_dict = self._row_to_dict(row)

            generic_key = self._normalize_key(row_dict.get("csv_generic_name"))
            if generic_key:
                self._by_generic_name[generic_key] = row_dict

            matched_prod_sks = row_dict.get("matched_prod_sks")
            for prod_sk in self._parse_prod_sks(matched_prod_sks):
                self._by_prod_sk[prod_sk] = row_dict

        logger.info(
            "Loaded RxNorm reference table %s with %s rows, %s generic-name keys, %s PROD_SK keys.",
            self.reference_csv_path,
            len(self._df),
            len(self._by_generic_name),
            len(self._by_prod_sk),
        )

    def _row_to_dict(self, row: pd.Series) -> dict[str, Any]:
        as_dict = row.to_dict()
        for key, value in list(as_dict.items()):
            if pd.isna(value):
                as_dict[key] = None
            elif isinstance(value, str):
                stripped = value.strip()
                as_dict[key] = stripped if stripped else None
        return as_dict

    def _normalize_key(self, value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip().lower()
        return text or None

    def _parse_prod_sks(self, value: object) -> list[str]:
        if value is None:
            return []
        text = str(value).strip()
        if not text:
            return []
        parsed: list[str] = []
        for token in text.split(";"):
            sk = token.strip()
            if sk:
                parsed.append(sk)
        return parsed

    def get_by_generic_name(self, generic_name: str) -> dict[str, Any] | None:
        key = self._normalize_key(generic_name)
        if key is None:
            return None
        row = self._by_generic_name.get(key)
        return dict(row) if row else None

    def get_by_prod_sk(self, prod_sk: object) -> dict[str, Any] | None:
        if prod_sk is None:
            return None
        key = str(prod_sk).strip()
        if not key:
            return None
        row = self._by_prod_sk.get(key)
        return dict(row) if row else None

    def is_field_verified(self, row: dict[str, Any], field: str) -> bool:
        if not isinstance(row, dict):
            return False
        raw = row.get(field)
        if raw is None:
            return False
        text = str(raw).strip()
        if not text:
            return False
        if text.lower() == "needs_verification":
            return False
        return True
