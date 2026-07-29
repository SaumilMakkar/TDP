from __future__ import annotations

import csv
import os
from functools import lru_cache
from typing import Any, Dict, List, Optional


class DrugRepository:
    """CSV-backed repository for Sprint 1 core drug data."""

    def __init__(self, data_dir: Optional[str] = None):
        self.data_dir = data_dir or os.environ.get(
            "PBM_DATA_DIR",
            os.path.join(os.path.dirname(__file__), "..", "..", "..", "data"),
        )

    def _read_csv(self, name: str) -> List[Dict[str, Any]]:
        path = os.path.join(self.data_dir, name)
        with open(path, newline="", encoding="utf-8") as fh:
            return list(csv.DictReader(fh))

    @lru_cache(maxsize=1)
    def _products(self) -> Dict[str, Dict[str, Any]]:
        return {row["PROD_SK"]: row for row in self._read_csv("v_d_product.csv")}

    @lru_cache(maxsize=1)
    def _ingredients(self) -> Dict[str, List[Dict[str, Any]]]:
        out: Dict[str, List[Dict[str, Any]]] = {}
        for row in self._read_csv("v_d_prod_ingredient.csv"):
            out.setdefault(row.get("PROD_SK", ""), []).append(row)
        return out

    @lru_cache(maxsize=1)
    def _formulary_alternatives(self) -> Dict[str, List[Dict[str, Any]]]:
        out: Dict[str, List[Dict[str, Any]]] = {}
        for row in self._read_csv("v_d_formulary_alternative.csv"):
            out.setdefault(row.get("TRGT_PROD_SK", ""), []).append(row)
        return out

    @staticmethod
    def _seq_num(row: Dict[str, Any]) -> int:
        try:
            return int(str(row.get("ALT_SEQ_NBR", "")).strip())
        except (TypeError, ValueError):
            return 999

    @lru_cache(maxsize=1)
    def _products_by_ndc(self) -> Dict[str, Dict[str, Any]]:
        out: Dict[str, Dict[str, Any]] = {}
        for row in self._products().values():
            ndc = str(row.get("NDC", "")).replace("-", "").replace(" ", "")
            if ndc:
                out[ndc] = row
        return out

    def get_product(self, prod_sk: str) -> Optional[Dict[str, Any]]:
        return self._products().get(str(prod_sk))

    def get_product_by_ndc(self, ndc: str) -> Optional[Dict[str, Any]]:
        ndc_clean = str(ndc).replace("-", "").replace(" ", "")
        return self._products_by_ndc().get(ndc_clean)

    def get_ingredients(self, prod_sk: str) -> List[Dict[str, Any]]:
        return list(self._ingredients().get(str(prod_sk), []))

    def get_formulary_alternatives(self, prod_sk: str) -> List[Dict[str, Any]]:
        """Return all formulary alternatives for a target product, ordered by sequence."""
        rows = list(self._formulary_alternatives().get(str(prod_sk), []))
        if not rows:
            return []

        rows = sorted(rows, key=self._seq_num)

        # Deduplicate by ALT_PROD_SK while preserving first sequence hit.
        deduped: List[Dict[str, Any]] = []
        seen = set()
        for row in rows:
            alt = str(row.get("ALT_PROD_SK", "")).strip()
            if not alt or alt in seen:
                continue
            deduped.append(row)
            seen.add(alt)
        return deduped
