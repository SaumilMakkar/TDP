"""Therapeutic class evidence matching for Stage A Sprint 5."""

from __future__ import annotations

import logging

from stage_a.evidence.knowledge_base import CLINICAL_KB, normalize_text
from stage_a.evidence.scoring import best_pair_bucket

logger = logging.getLogger(__name__)

_BROAD_CLASS_TERMS = {
    "antidiabetics",
    "antibiotics",
    "antidepressants",
    "anticonvulsants",
    "anticoagulants",
    "antiplatelet",
    "diuretics",
    "statin",
}

_CLASS_FAMILY_RULES = {
    "biguanide": "insulin_sensitizer",
    "biguanides": "insulin_sensitizer",
    "sulfonylurea": "insulin_secretagogue",
    "sulfonylureas": "insulin_secretagogue",
    "dpp 4 inhibitor": "incretin_modulator",
    "dpp 4 inhibitors": "incretin_modulator",
    "dipeptidyl peptidase 4 inhibitor": "incretin_modulator",
    "dipeptidyl peptidase 4 inhibitors": "incretin_modulator",
    "sglt2 inhibitor": "glucose_excretion",
    "sglt2 inhibitors": "glucose_excretion",
    "sodium glucose cotransporter 2 inhibitor": "glucose_excretion",
    "sodium glucose cotransporter 2 inhibitors": "glucose_excretion",
}

_CLASS_FAMILY_SIMILARITY = {
    frozenset({"insulin_sensitizer", "glucose_excretion"}): 0.75,
    frozenset({"insulin_sensitizer", "incretin_modulator"}): 0.5,
    frozenset({"insulin_sensitizer", "insulin_secretagogue"}): 0.25,
    frozenset({"incretin_modulator", "glucose_excretion"}): 0.5,
    frozenset({"incretin_modulator", "insulin_secretagogue"}): 0.5,
    frozenset({"glucose_excretion", "insulin_secretagogue"}): 0.25,
}


def _concept_to_family(concept: str) -> str | None:
    for key, family in _CLASS_FAMILY_RULES.items():
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
            best = max(best, _CLASS_FAMILY_SIMILARITY.get(frozenset({left, right}), 0.0))
    return best


def _class_concepts_for_drug(drug: object) -> set[str]:
    concepts: set[str] = set()

    therapeutic_class = normalize_text(getattr(drug, "therapeutic_class", None))
    if therapeutic_class:
        concepts.add(therapeutic_class)

    rxnorm_ref = getattr(drug, "rxnorm_ref", None)
    if isinstance(rxnorm_ref, dict):
        normalized_class = normalize_text(rxnorm_ref.get("csv_therapeutic_class_normalized"))
        raw_class = normalize_text(rxnorm_ref.get("csv_therapeutic_class_raw"))
        if normalized_class:
            concepts.add(normalized_class)
        if raw_class:
            concepts.add(raw_class)

    concepts.update(CLINICAL_KB.classes_for_drug(drug))
    return concepts


def class_match(drugA, drugB) -> float:
    """Compare therapeutic class concepts and return a bucket score with insufficient-data status."""
    classes_a = _class_concepts_for_drug(drugA)
    classes_b = _class_concepts_for_drug(drugB)

    insufficient_data = not classes_a or not classes_b
    if insufficient_data:
        logger.info("class_match: insufficient_data because therapeutic class is missing.")
        class_match.last_result = {"insufficient_data": True}
        return 0.0

    shared_terms = classes_a & classes_b
    if shared_terms:
        non_broad_shared = [term for term in shared_terms if term not in _BROAD_CLASS_TERMS]
        if non_broad_shared:
            class_match.last_result = {"insufficient_data": False}
            return 1.0

        family_score = _family_similarity_score(classes_a, classes_b)
        class_match.last_result = {"insufficient_data": False}
        return max(0.5, family_score)

    family_score = _family_similarity_score(classes_a, classes_b)
    if family_score > 0.0:
        class_match.last_result = {"insufficient_data": False}
        return family_score

    class_match.last_result = {"insufficient_data": False}
    return best_pair_bucket(classes_a, classes_b)


class_match.last_result = {"insufficient_data": False}
