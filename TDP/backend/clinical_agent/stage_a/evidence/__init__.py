"""Clinical evidence engine for Stage A Sprint 4."""

from __future__ import annotations

from dataclasses import dataclass

from stage_a.evidence.combo import combo_match
from stage_a.evidence.therapeutic_class import class_match
from stage_a.evidence.form import form_match
from stage_a.evidence.ingredient import ingredient_match
from stage_a.evidence.moa import moa_match
from stage_a.evidence.moiety import moiety_match
from stage_a.evidence.route import route_match
from stage_a.evidence.strength import strength_match


@dataclass
class _IngredientView:
    ingredients: list[str]
    rxnorm_ingredient: str | None
    active_moiety: str | None
    moa_class: str | None
    therapeutic_class: str | None
    drug_class: str | None
    drug_subclass: str | None
    atc_level_1: str | None
    atc_level_2: str | None
    atc_level_3: str | None
    atc_level_4: str | None
    atc_level_5: str | None
    rxnorm: dict[str, object]
    rxnorm_ref: dict[str, object]


def _safe_ref_value(ref: dict[str, object], *keys: str) -> str | None:
    for key in keys:
        value = ref.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text and text.lower() != "nan":
            return text
    return None


def evaluate_evidence(drugA, drugB, drugA_rxnorm, drugB_rxnorm) -> dict:
    """
    Return raw 0/1 evidence plus per-field insufficient-data flags.
    """
    ref_a = dict(getattr(drugA, "rxnorm_ref", {}) or {})
    ref_b = dict(getattr(drugB, "rxnorm_ref", {}) or {})

    ingredient_a = _IngredientView(
        ingredients=list(getattr(drugA, "ingredients", []) or []),
        rxnorm_ingredient=(drugA_rxnorm or {}).get("ingredient"),
        active_moiety=(drugA_rxnorm or {}).get("active_moiety"),
        moa_class=_safe_ref_value(ref_a, "verified_moa_classes_normalized", "verified_moa_classes_raw", "moa_class"),
        therapeutic_class=_safe_ref_value(ref_a, "csv_therapeutic_class_normalized", "csv_therapeutic_class_raw")
        or getattr(drugA, "therapeutic_class", None),
        drug_class=getattr(drugA, "therapeutic_class", None),
        drug_subclass=_safe_ref_value(ref_a, "drug_subclass", "therapeutic_subclass", "pharmacologic_subclass"),
        atc_level_1=_safe_ref_value(ref_a, "atc_level_1", "atc1"),
        atc_level_2=_safe_ref_value(ref_a, "atc_level_2", "atc2"),
        atc_level_3=_safe_ref_value(ref_a, "atc_level_3", "atc3"),
        atc_level_4=_safe_ref_value(ref_a, "atc_level_4", "atc4"),
        atc_level_5=_safe_ref_value(ref_a, "atc_level_5", "atc5"),
        rxnorm=dict(drugA_rxnorm or {}),
        rxnorm_ref=ref_a,
    )
    ingredient_b = _IngredientView(
        ingredients=list(getattr(drugB, "ingredients", []) or []),
        rxnorm_ingredient=(drugB_rxnorm or {}).get("ingredient"),
        active_moiety=(drugB_rxnorm or {}).get("active_moiety"),
        moa_class=_safe_ref_value(ref_b, "verified_moa_classes_normalized", "verified_moa_classes_raw", "moa_class"),
        therapeutic_class=_safe_ref_value(ref_b, "csv_therapeutic_class_normalized", "csv_therapeutic_class_raw")
        or getattr(drugB, "therapeutic_class", None),
        drug_class=getattr(drugB, "therapeutic_class", None),
        drug_subclass=_safe_ref_value(ref_b, "drug_subclass", "therapeutic_subclass", "pharmacologic_subclass"),
        atc_level_1=_safe_ref_value(ref_b, "atc_level_1", "atc1"),
        atc_level_2=_safe_ref_value(ref_b, "atc_level_2", "atc2"),
        atc_level_3=_safe_ref_value(ref_b, "atc_level_3", "atc3"),
        atc_level_4=_safe_ref_value(ref_b, "atc_level_4", "atc4"),
        atc_level_5=_safe_ref_value(ref_b, "atc_level_5", "atc5"),
        rxnorm=dict(drugB_rxnorm or {}),
        rxnorm_ref=ref_b,
    )

    evidence = {
        "ingredient": ingredient_match(ingredient_a, ingredient_b),
        "moiety": moiety_match(ingredient_a, ingredient_b),
        "class": class_match(drugA, drugB),
        "moa": moa_match(drugA, drugB),
        "combo": combo_match(drugA, drugB),
        "route": route_match(drugA_rxnorm, drugB_rxnorm),
        "form": form_match(drugA, drugB, drugA_rxnorm=drugA_rxnorm, drugB_rxnorm=drugB_rxnorm),
        "strength": strength_match(drugA, drugB),
    }

    insufficient_data = {
        "ingredient": bool(ingredient_match.last_result.get("insufficient_data", False)),
        "moiety": bool(moiety_match.last_result.get("insufficient_data", False)),
        "class": bool(class_match.last_result.get("insufficient_data", False)),
        "moa": bool(moa_match.last_result.get("insufficient_data", False)),
        "combo": False,
        "route": bool(route_match.last_result.get("insufficient_data", False)),
        "form": bool(form_match.last_result.get("insufficient_data", False)),
        "strength": bool(strength_match.last_result.get("insufficient_data", False)),
    }

    return {
        **evidence,
        "insufficient_data": insufficient_data,
    }


__all__ = [
    "evaluate_evidence",
    "ingredient_match",
    "moiety_match",
    "class_match",
    "moa_match",
    "combo_match",
    "route_match",
    "form_match",
    "strength_match",
]
