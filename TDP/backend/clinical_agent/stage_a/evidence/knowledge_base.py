"""Local clinical knowledge enrichment for Stage A Sprint 5.

This module loads supplemental class/mechanism descriptors from the bundled
Stage A CSV files and exposes deterministic lookups.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pandas as pd

from stage_a.config import INGREDIENT_CSV_NAME, PRODUCT_CSV_NAME, csv_path

logger = logging.getLogger(__name__)

_WHITESPACE_RE = re.compile(r"\s+")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9\s]")
_PARENS_RE = re.compile(r"\(([^)]*)\)")


def normalize_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text or text == "nan":
        return None
    text = _NON_ALNUM_RE.sub(" ", text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text or None


def split_semicolon_terms(value: object) -> set[str]:
    if value is None:
        return set()

    raw = str(value).strip()
    if not raw or raw.lower() == "nan":
        return set()

    terms: set[str] = set()
    for part in raw.split(";"):
        normalized = normalize_text(part)
        if normalized:
            terms.add(normalized)
    return terms


def _expand_therapeutic_class(value: object) -> set[str]:
    text = normalize_text(value)
    if text is None:
        return set()

    terms: set[str] = {text}

    paren_matches = _PARENS_RE.findall(str(value))
    for inner in paren_matches:
        normalized_inner = normalize_text(inner)
        if normalized_inner:
            terms.add(normalized_inner)

    without_parens = _PARENS_RE.sub("", str(value))
    normalized_without = normalize_text(without_parens)
    if normalized_without:
        terms.add(normalized_without)

    return terms


class ClinicalKnowledgeBase:
    """Deterministic enrichment source for therapeutic class and MOA concepts."""

    def __init__(self):
        self._classes_by_key: dict[str, set[str]] = {}
        self._moa_by_key: dict[str, set[str]] = {}
        self._class_terms_by_prod_sk: dict[str, set[str]] = {}
        self._moa_terms_by_prod_sk: dict[str, set[str]] = {}
        self._load_from_product_catalog(csv_path(PRODUCT_CSV_NAME))
        self._load_from_product_ingredients(csv_path(INGREDIENT_CSV_NAME))

    def _add_terms(self, key: str | None, class_terms: set[str], moa_terms: set[str]) -> None:
        if not key:
            return

        existing_classes = self._classes_by_key.setdefault(key, set())
        existing_classes.update(class_terms)

        existing_moa = self._moa_by_key.setdefault(key, set())
        existing_moa.update(moa_terms)

    def _load_from_product_catalog(self, csv_file: Path) -> None:
        if not csv_file.exists():
            logger.warning("Clinical knowledge CSV not found: %s", csv_file)
            return

        df = pd.read_csv(csv_file, low_memory=False)
        required = {"PROD_SK", "PROD_NM", "GNRC_NM", "THRPC_CLASS_NM"}
        if not required.issubset(set(df.columns)):
            logger.warning(
                "Clinical knowledge CSV missing required columns. expected=%s actual=%s",
                sorted(required),
                sorted(df.columns),
            )
            return

        for _, row in df.iterrows():
            prod_sk = normalize_text(row.get("PROD_SK"))
            class_terms = _expand_therapeutic_class(row.get("THRPC_CLASS_NM"))
            moa_terms = _expand_therapeutic_class(row.get("DRG_CLASS_NM"))
            moa_terms.update(_expand_therapeutic_class(row.get("DRG_SUB_CLASS_NM")))
            if not moa_terms:
                moa_terms = set(class_terms)

            for key in {normalize_text(row.get("PROD_NM")), normalize_text(row.get("GNRC_NM"))}:
                self._add_terms(key, class_terms, moa_terms)

            if prod_sk:
                self._class_terms_by_prod_sk[prod_sk] = set(class_terms)
                self._moa_terms_by_prod_sk[prod_sk] = set(moa_terms)

        logger.info(
            "Loaded clinical knowledge from %s with %s concept keys.",
            csv_file,
            len(self._classes_by_key),
        )

    def _load_from_product_ingredients(self, csv_file: Path) -> None:
        if not csv_file.exists():
            logger.warning("Clinical knowledge CSV not found: %s", csv_file)
            return

        df = pd.read_csv(csv_file, low_memory=False)
        required = {"PROD_SK", "PIG_GNRC_NM", "PIG_ING_TYPE_CD"}
        if not required.issubset(set(df.columns)):
            logger.warning(
                "Clinical knowledge CSV missing required columns. expected=%s actual=%s",
                sorted(required),
                sorted(df.columns),
            )
            return

        for _, row in df.iterrows():
            ingredient_type = normalize_text(row.get("PIG_ING_TYPE_CD"))
            if ingredient_type and ingredient_type != "active":
                continue

            ingredient_name = normalize_text(row.get("PIG_GNRC_NM"))
            if not ingredient_name:
                continue

            prod_sk = normalize_text(row.get("PROD_SK"))
            if not prod_sk:
                continue

            class_terms = self._class_terms_by_prod_sk.get(prod_sk, set())
            moa_terms = self._moa_terms_by_prod_sk.get(prod_sk, set())
            if not class_terms and not moa_terms:
                continue

            self._add_terms(ingredient_name, class_terms, moa_terms)

        logger.info(
            "Loaded clinical knowledge from %s with %s concept keys.",
            csv_file,
            len(self._classes_by_key),
        )

    def classes_for_drug(self, drug: object) -> set[str]:
        return self._lookup(drug, self._classes_by_key)

    def moa_for_drug(self, drug: object) -> set[str]:
        return self._lookup(drug, self._moa_by_key)

    def _lookup(self, drug: object, source: dict[str, set[str]]) -> set[str]:
        keys: list[str] = []

        generic_name = normalize_text(getattr(drug, "generic_name", None))
        if generic_name:
            keys.append(generic_name)

        product_name = normalize_text(getattr(drug, "product_name", None))
        if product_name:
            keys.append(product_name)

        ingredients = list(getattr(drug, "ingredients", []) or [])
        for ingredient in ingredients:
            normalized = normalize_text(ingredient)
            if normalized:
                keys.append(normalized)

        concepts: set[str] = set()
        for key in keys:
            concepts.update(source.get(key, set()))
        return concepts
CLINICAL_KB = ClinicalKnowledgeBase()
