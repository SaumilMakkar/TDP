from __future__ import annotations

from typing import Dict

from app.stage_a.models.drug import Drug


def compare(original_drug: Drug, candidate_drug: Drug) -> Dict[str, object]:
    """Deterministic side-by-side comparison for Sprint 2.

    No similarity score is produced in Sprint 2. This function only exposes
    factual comparison evidence used by future scoring sprints.
    """
    original_ings = set(original_drug.ingredients)
    candidate_ings = set(candidate_drug.ingredients)
    ingredient_overlap = sorted(original_ings & candidate_ings)

    return {
        "original_prod_sk": original_drug.product_id,
        "candidate_prod_sk": candidate_drug.product_id,
        "same_generic": original_drug.generic_name == candidate_drug.generic_name,
        "same_form": original_drug.dosage_form == candidate_drug.dosage_form,
        "same_therapeutic_class": (
            original_drug.therapeutic_class == candidate_drug.therapeutic_class
        ),
        "ingredient_overlap": ingredient_overlap,
        "ingredient_overlap_count": len(ingredient_overlap),
        "original_ingredient_count": len(original_ings),
        "candidate_ingredient_count": len(candidate_ings),
    }
