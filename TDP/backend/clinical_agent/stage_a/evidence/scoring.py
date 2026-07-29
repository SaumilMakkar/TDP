"""Shared deterministic bucket scoring helpers for Stage A evidence."""

from __future__ import annotations

import re
from difflib import SequenceMatcher

BUCKET_SCORES = {0.0, 0.25, 0.5, 0.75, 1.0}

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_simple_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text or text == "nan":
        return None
    return _WHITESPACE_RE.sub(" ", text)


def token_set(value: str | None) -> set[str]:
    if value is None:
        return set()
    return {part for part in value.split(" ") if part}


def exact_or_containment_score(left: str, right: str) -> float:
    if left == right:
        return 1.0
    if left in right or right in left:
        return 0.75
    return 0.0


def jaccard_score(left_tokens: set[str], right_tokens: set[str]) -> float:
    if not left_tokens or not right_tokens:
        return 0.0
    intersection = len(left_tokens & right_tokens)
    if intersection == 0:
        return 0.0
    union = len(left_tokens | right_tokens)
    if union == 0:
        return 0.0
    return intersection / union


def bucket_from_token_overlap(left: str | None, right: str | None) -> float:
    if left is None or right is None:
        return 0.0

    base = exact_or_containment_score(left, right)
    if base > 0.0:
        return base

    overlap = jaccard_score(token_set(left), token_set(right))
    if overlap >= 0.67:
        return 0.75
    if overlap >= 0.34:
        return 0.5
    if overlap > 0.0:
        return 0.25
    return 0.0


def soft_bucket_from_text_similarity(left: str | None, right: str | None) -> float:
    if left is None or right is None:
        return 0.0

    base = exact_or_containment_score(left, right)
    if base > 0.0:
        return base

    overlap = jaccard_score(token_set(left), token_set(right))
    if overlap >= 0.67:
        return 0.75
    if overlap >= 0.34:
        return 0.5

    ratio = SequenceMatcher(None, left, right).ratio()
    if ratio >= 0.75:
        return 0.5
    if ratio >= 0.45:
        return 0.25
    return 0.25


def best_pair_bucket(left_values: set[str], right_values: set[str]) -> float:
    best = 0.0
    for left in left_values:
        for right in right_values:
            best = max(best, bucket_from_token_overlap(left, right))
            if best == 1.0:
                return best
    return best
