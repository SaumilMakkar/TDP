from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


from app.stage_a.data.drug_repository import DrugRepository
from app.stage_a.models.drug import Drug
from app.stage_a.normalization.drug_builder import DrugBuilder


@dataclass(frozen=True)
class AlternativeCandidate:
    """Alternative candidate with source formulary metadata."""

    drug: Drug
    alt_seq_nbr: int
    formulary_alt_sk: Optional[str]
    therapeutic_group: Optional[str]


class FormularyService:
    """Sprint 2 retrieval service for formulary alternatives."""

    def __init__(
        self,
        repository: Optional[DrugRepository] = None,
        builder: Optional[DrugBuilder] = None,
    ):
        self.repository = repository or DrugRepository()
        self.builder = builder or DrugBuilder(self.repository)

    def get_alternatives(self, prod_sk: str) -> List[AlternativeCandidate]:
        rows = self.repository.get_formulary_alternatives(prod_sk)
        alternatives: List[AlternativeCandidate] = []
        for row in rows:
            alt_prod_sk = str(row.get("ALT_PROD_SK", "")).strip()
            if not alt_prod_sk:
                continue

            drug = self.builder.build(alt_prod_sk)
            if drug is None:
                continue

            try:
                seq = int(str(row.get("ALT_SEQ_NBR", "")).strip())
            except ValueError:
                seq = 999

            alternatives.append(
                AlternativeCandidate(
                    drug=drug,
                    alt_seq_nbr=seq,
                    formulary_alt_sk=(str(row.get("FRMLRY_ALT_SK", "")).strip() or None),
                    therapeutic_group=(str(row.get("THRPC_GROUP", "")).strip() or None),
                )
            )
        return alternatives
