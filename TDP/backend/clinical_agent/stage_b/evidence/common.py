"""Shared helpers for Stage B evidence engines."""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from stage_a.normalization.drug_builder import build_drug


_NON_ALNUM_RE = re.compile(r"[^a-z0-9\s]")
_WHITESPACE_RE = re.compile(r"\s+")
BUCKET_VALUES: tuple[float, ...] = (0.0, 0.25, 0.5, 0.75, 1.0)


_CONCEPT_ALIASES: dict[str, tuple[str, ...]] = {
    "nsaid": (
        "nonsteroidal anti inflammatory",
        "non steroidal anti inflammatory",
        "cox inhibitor",
    ),
    "ace inhibitor": (
        "acei",
        "angiotensin converting enzyme inhibitor",
    ),
    "angiotensin receptor blocker": (
        "arb",
    ),
    "beta blocker": (
        "beta adrenergic blocker",
    ),
    "benzodiazepine": (
        "benzo",
    ),
    "opioid": (
        "opiate",
    ),
    "proton pump inhibitor": (
        "ppi",
    ),
    "sulfonamide": (
        "sulfa",
    ),
    "heart failure": (
        "congestive heart failure",
        "chf",
    ),
    "type 2 diabetes": (
        "t2dm",
        "dm2",
        "type ii diabetes",
    ),
    "active bleeding": (
        "bleeding",
        "hemorrhage",
        "haemorrhage",
    ),
    "aminopenicillin": (
        "amoxicillin",
        "ampicillin",
    ),
}


def normalize_text(value: object) -> str:
    text = str(value or "").strip().lower()
    text = _NON_ALNUM_RE.sub(" ", text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text


def normalize_list(values: list[str] | None) -> list[str]:
    if not values:
        return []
    return [normalize_text(item) for item in values if normalize_text(item)]


def bucketize(value: float) -> float:
    value = max(0.0, min(1.0, float(value)))
    nearest = min(BUCKET_VALUES, key=lambda bucket: abs(bucket - value))
    return float(nearest)


def _token_set(text: str) -> set[str]:
    return {token for token in normalize_text(text).split() if token}


def _is_phrase_subset(needle: str, haystack: str) -> bool:
    needle_tokens = _token_set(needle)
    haystack_tokens = _token_set(haystack)
    if not needle_tokens or not haystack_tokens:
        return False
    return needle_tokens.issubset(haystack_tokens)


def _expand_semantic_variants(value: object) -> set[str]:
    normalized = normalize_text(value)
    if not normalized:
        return set()

    variants: set[str] = {normalized}
    for canonical, aliases in _CONCEPT_ALIASES.items():
        canonical_norm = normalize_text(canonical)
        alias_norms = {normalize_text(alias) for alias in aliases if normalize_text(alias)}
        terms = {canonical_norm} | alias_norms

        if normalized in terms:
            variants |= terms
            continue

        if any(_is_phrase_subset(term, normalized) or _is_phrase_subset(normalized, term) for term in terms):
            variants.add(canonical_norm)
            variants |= alias_norms

    return variants


def _base_similarity(left_text: str, right_text: str) -> float:
    if not left_text or not right_text:
        return 0.0
    if left_text == right_text:
        return 1.0
    if left_text in right_text or right_text in left_text:
        return 0.75

    left_tokens = _token_set(left_text)
    right_tokens = _token_set(right_text)
    if left_tokens and right_tokens:
        overlap = len(left_tokens & right_tokens)
        if overlap > 0:
            jaccard = overlap / max(1, len(left_tokens | right_tokens))
            containment = overlap / max(1, min(len(left_tokens), len(right_tokens)))

            if containment >= 0.8:
                return 0.75
            if jaccard >= 0.5:
                return 0.5
            return 0.25

    ratio = SequenceMatcher(None, left_text, right_text).ratio()
    if ratio >= 0.88:
        return 0.75
    if ratio >= 0.72:
        return 0.5
    if ratio >= 0.45:
        return 0.25
    return 0.0


def semantic_similarity(left: object, right: object) -> float:
    """Return bucketized semantic similarity for two normalized terms."""
    left_variants = _expand_semantic_variants(left)
    right_variants = _expand_semantic_variants(right)
    if not left_variants or not right_variants:
        return 0.0

    best = 0.0
    for left_text in left_variants:
        for right_text in right_variants:
            best = max(best, _base_similarity(left_text, right_text))
            if best >= 1.0:
                return 1.0
    return float(bucketize(best))


def best_semantic_similarity(term: object, candidates: list[str] | set[str]) -> float:
    best = 0.0
    for candidate in candidates:
        best = max(best, semantic_similarity(term, candidate))
        if best >= 1.0:
            return 1.0
    return float(bucketize(best))


def candidate_drug_context(candidate_prod_id: int) -> dict[str, object]:
    """Return normalized candidate drug descriptors for Stage B checks."""
    drug = build_drug(int(candidate_prod_id), include_inactive=True)
    ingredients = normalize_list(drug.ingredients)

    tokens: set[str] = set(ingredients)
    for raw in [drug.generic_name, drug.product_name, drug.therapeutic_class, drug.dosage_form]:
        normalized = normalize_text(raw)
        if normalized:
            tokens.add(normalized)
            tokens.update(part for part in normalized.split() if part)

    return {
        "prod_id": int(drug.product_id),
        "prod_name": drug.product_name,
        "generic_name": normalize_text(drug.generic_name),
        "therapeutic_class": normalize_text(drug.therapeutic_class),
        "ingredients": ingredients,
        "tokens": sorted(tokens),
    }
