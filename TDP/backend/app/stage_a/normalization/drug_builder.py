from __future__ import annotations

from dataclasses import replace
from typing import Dict, Optional

from app.stage_a.data.drug_repository import DrugRepository
from app.stage_a.models.drug import Drug
from app.stage_a.normalization.rxnorm_mapper import RxNormMapper


class DrugBuilder:
    """Builds canonical Drug objects from product + ingredient tables."""

    def __init__(
        self,
        repository: Optional[DrugRepository] = None,
        mapper: Optional[RxNormMapper] = None,
    ):
        self.repository = repository or DrugRepository()
        self.mapper = mapper or RxNormMapper()

    @staticmethod
    def _clean(value: object) -> str:
        if value is None:
            return ""
        return str(value).strip()

    def _active_ingredients(self, prod_sk: str) -> list[str]:
        rows = self.repository.get_ingredients(prod_sk)
        active: list[str] = []
        seen = set()
        for row in rows:
            ing_type = self._clean(row.get("PIG_ING_TYPE_CD")).upper()
            if ing_type != "ACTIVE":
                continue
            ingredient = self._clean(row.get("PIG_GNRC_NM")).lower()
            if ingredient and ingredient not in seen:
                active.append(ingredient)
                seen.add(ingredient)
        return active

    def build(self, prod_sk: str) -> Optional[Drug]:
        product = self.repository.get_product(prod_sk)
        if product is None:
            return None

        return Drug(
            product_id=self._clean(product.get("PROD_SK")),
            product_name=self._clean(product.get("PROD_NM")),
            generic_name=self._clean(product.get("GNRC_NM")).lower(),
            ndc=self._clean(product.get("NDC")) or None,
            gpi=self._clean(product.get("GPI")) or None,
            ingredients=self._active_ingredients(str(prod_sk)),
            dosage_form=self._clean(product.get("DRG_DOSAG_FRM_NM")) or None,
            therapeutic_class=self._clean(product.get("THRPC_CLASS_NM")) or None,
        )

    def build_stage_a_view(self, prod_sk: str) -> Optional[Dict[str, object]]:
        drug = self.build(prod_sk)
        if drug is None:
            return None
        return drug.to_stage_a_dict()

    # ------------------------------------------------------------------ #
    # Sprint 3 — RxNorm normalization
    # ------------------------------------------------------------------ #
    def normalize_drug(self, ndc: str) -> Optional[Drug]:
        """Look up a drug by NDC, build its canonical object, then enrich
        it with RxNorm normalized attributes."""
        product = self.repository.get_product_by_ndc(ndc)
        if product is None:
            return None
        drug = self.build(str(product["PROD_SK"]))
        if drug is None:
            return None
        norm = self.mapper.normalize(ndc)
        return replace(drug, **norm)

    def normalize_drug_by_prod_sk(self, prod_sk: str) -> Optional[Drug]:
        """Build canonical object for prod_sk, then normalize via its NDC.
        Falls back gracefully when NDC is absent."""
        drug = self.build(prod_sk)
        if drug is None:
            return None
        if not drug.ndc:
            return replace(drug, normalization_status="partial")
        norm = self.mapper.normalize(drug.ndc)
        return replace(drug, **norm)
