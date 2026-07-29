from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass(frozen=True)
class Drug:
    """Canonical Drug object for Stage A.

    This model intentionally contains only deterministic facts loaded from
    local PBM reference tables. No similarity/scoring fields are included.

    Sprint 3 adds optional RxNorm-normalized fields. They default to None
    so all Sprint 1/2 code continues to work unchanged. normalization_status
    is 'pending' until normalize_drug() is called, then either 'full'
    (all fields resolved from RxNorm) or 'partial' (no RxNorm hit, local
    fields only).
    """

    product_id: str
    product_name: str
    generic_name: str
    ndc: Optional[str]
    gpi: Optional[str]
    ingredients: List[str] = field(default_factory=list)
    dosage_form: Optional[str] = None
    therapeutic_class: Optional[str] = None
    # Sprint 3 — RxNorm normalized fields
    rxcui: Optional[str] = None
    ingredient_norm: Optional[str] = None
    active_moiety_norm: Optional[str] = None
    route_norm: Optional[str] = None
    dose_form_norm: Optional[str] = None
    normalization_status: str = "pending"

    def to_stage_a_dict(self) -> Dict[str, object]:
        """Compact shape matching Sprint 1 output examples."""
        return {
            "prod_sk": self.product_id,
            "drug": self.product_name,
            "generic": self.generic_name,
            "ingredients": list(self.ingredients),
            "class": self.therapeutic_class,
            "form": self.dosage_form,
        }

    def to_rxnorm_dict(self) -> Dict[str, object]:
        """Sprint 3 output shape — local fields + RxNorm normalized fields."""
        return {
            "prod_sk": self.product_id,
            "ndc": self.ndc,
            "rxcui": self.rxcui,
            "ingredient": self.ingredient_norm,
            "active_moiety": self.active_moiety_norm,
            "route": self.route_norm,
            "dose_form": self.dose_form_norm,
            "normalization_status": self.normalization_status,
        }
