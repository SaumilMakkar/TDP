"""Mechanism-of-action evidence matching for Stage A Sprint 5."""

from __future__ import annotations

import logging

from stage_a.evidence.knowledge_base import CLINICAL_KB, normalize_text, split_semicolon_terms
from stage_a.evidence.scoring import best_pair_bucket

logger = logging.getLogger(__name__)

_BROAD_MOA_TERMS = {
    "antidiabetics",
    "antibiotics",
    "antidepressants",
    "anticonvulsants",
    "anticoagulants",
    "antiplatelet agents",
    "diuretics",
    "statins",
}

_MOA_FAMILY_RULES = {
    "biguanide": "insulin_sensitizer",
    "biguanides": "insulin_sensitizer",
    "sulfonylurea": "insulin_secretagogue",
    "sulfonylureas": "insulin_secretagogue",
    "dipeptidyl peptidase 4 inhibitor": "incretin_modulator",
    "dipeptidyl peptidase 4 inhibitors": "incretin_modulator",
    "dpp 4 inhibitor": "incretin_modulator",
    "dpp 4 inhibitors": "incretin_modulator",
    "sodium glucose cotransporter 2 inhibitor": "glucose_excretion",
    "sodium glucose cotransporter 2 inhibitors": "glucose_excretion",
    "sglt2 inhibitor": "glucose_excretion",
    "sglt2 inhibitors": "glucose_excretion",
}

_FAMILY_SIMILARITY = {
    frozenset({"insulin_sensitizer", "glucose_excretion"}): 0.75,
    frozenset({"insulin_sensitizer", "incretin_modulator"}): 0.5,
    frozenset({"insulin_sensitizer", "insulin_secretagogue"}): 0.25,
    frozenset({"incretin_modulator", "glucose_excretion"}): 0.5,
    frozenset({"incretin_modulator", "insulin_secretagogue"}): 0.5,
    frozenset({"glucose_excretion", "insulin_secretagogue"}): 0.25,
}


def _concept_to_family(concept: str) -> str | None:
    for key, family in _MOA_FAMILY_RULES.items():
        if key in concept:
            return family
    return None


def _family_similarity_score(left_concepts: set[str], right_concepts: set[str]) -> float:
    left_families = {family for concept in left_concepts if (family := _concept_to_family(concept))}
    right_families = {family for concept in right_concepts if (family := _concept_to_family(concept))}

    if not left_families or not right_families:
        return 0.0

    if left_families & right_families:
        return 1.0

    best = 0.0
    for left in left_families:
        for right in right_families:
            best = max(best, _FAMILY_SIMILARITY.get(frozenset({left, right}), 0.0))
    return best


def _moa_concepts_for_drug(drug: object) -> set[str]:
    concepts: set[str] = set()

    rxnorm_ref = getattr(drug, "rxnorm_ref", None)
    if isinstance(rxnorm_ref, dict):
        concepts.update(split_semicolon_terms(rxnorm_ref.get("verified_moa_classes_normalized")))
        concepts.update(split_semicolon_terms(rxnorm_ref.get("verified_moa_classes_raw")))

    # Fallback: use supplementary local dataset concepts mapped by ingredient/drug name.
    concepts.update(CLINICAL_KB.moa_for_drug(drug))

    # Last-resort deterministic fallback to therapeutic class wording.
    therapeutic_class = normalize_text(getattr(drug, "therapeutic_class", None))
    if therapeutic_class:
        concepts.add(therapeutic_class)

    return concepts


def moa_match(drugA, drugB) -> float:
    """Compare MOA concepts and return a bucket score with insufficient-data status."""
    moa_a = _moa_concepts_for_drug(drugA)
    moa_b = _moa_concepts_for_drug(drugB)

    insufficient_data = not moa_a or not moa_b
    if insufficient_data:
        logger.info("moa_match: insufficient_data because MOA concepts are missing.")
        moa_match.last_result = {"insufficient_data": True}
        return 0.0

    shared_terms = moa_a & moa_b
    if shared_terms:
        non_broad_shared = [term for term in shared_terms if term not in _BROAD_MOA_TERMS]
        if non_broad_shared:
            moa_match.last_result = {"insufficient_data": False}
            return 1.0

        family_score = _family_similarity_score(moa_a, moa_b)
        moa_match.last_result = {"insufficient_data": False}
        return max(0.5, family_score)

    family_score = _family_similarity_score(moa_a, moa_b)
    if family_score > 0.0:
        moa_match.last_result = {"insufficient_data": False}
        return family_score

    moa_match.last_result = {"insufficient_data": False}
    return best_pair_bucket(moa_a, moa_b)


moa_match.last_result = {"insufficient_data": False}
