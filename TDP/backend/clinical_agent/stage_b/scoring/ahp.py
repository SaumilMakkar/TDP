"""AHP utilities for Stage B risk weighting."""

from __future__ import annotations

from functools import lru_cache
from typing import Mapping, Sequence

import numpy as np


CRITERIA: tuple[str, ...] = (
    "contraindication",
    "allergy",
    "interaction",
    "renal_hepatic",
    "duplicate_therapy",
    "condition",
    "age",
)

RANDOM_INDEX_BY_N: dict[int, float] = {
    1: 0.0,
    2: 0.0,
    3: 0.58,
    4: 0.90,
    5: 1.12,
    6: 1.24,
    7: 1.32,
    8: 1.41,
    9: 1.45,
    10: 1.49,
}
DEFAULT_CONSISTENCY_THRESHOLD = 0.10


def _build_pairwise_from_priority(weights: Sequence[float]) -> np.ndarray:
    priority = np.array(weights, dtype=float)
    if priority.ndim != 1 or len(priority) != len(CRITERIA):
        raise ValueError("Priority vector must align with Stage B criteria.")
    if np.any(priority <= 0.0):
        raise ValueError("Priority vector must be strictly positive.")
    return priority[:, None] / priority[None, :]


# Priority percentages are clinically risk-first and sum exactly to 100.
# Order follows CRITERIA: contraindication, allergy, interaction, renal/hepatic,
# duplicate therapy, condition fit, age risk.
_DEFAULT_PRIORITY_PERCENTAGES: tuple[float, ...] = (27.0, 21.0, 19.0, 15.0, 8.0, 7.0, 3.0)


# This is the AHP source of truth for Stage B weights.
DEFAULT_PAIRWISE_MATRIX = _build_pairwise_from_priority(_DEFAULT_PRIORITY_PERCENTAGES)


def _validate_pairwise_matrix(pairwise_matrix: np.ndarray) -> None:
    if pairwise_matrix.ndim != 2 or pairwise_matrix.shape[0] != pairwise_matrix.shape[1]:
        raise ValueError("AHP pairwise matrix must be square.")
    if pairwise_matrix.shape[0] != len(CRITERIA):
        raise ValueError(
            f"AHP pairwise matrix must be {len(CRITERIA)}x{len(CRITERIA)} for Stage B criteria."
        )
    if not np.all(np.isfinite(pairwise_matrix)):
        raise ValueError("AHP pairwise matrix must contain finite numeric values.")
    if np.any(pairwise_matrix <= 0.0):
        raise ValueError("AHP pairwise matrix entries must be strictly positive.")
    if not np.allclose(np.diag(pairwise_matrix), np.ones(pairwise_matrix.shape[0]), atol=1e-8):
        raise ValueError("AHP pairwise matrix diagonal must be all ones.")
    if not np.allclose(pairwise_matrix * pairwise_matrix.T, np.ones(pairwise_matrix.shape), atol=1e-6):
        raise ValueError("AHP pairwise matrix must be reciprocal (a_ij = 1 / a_ji).")


def compute_consistency_ratio(pairwise_matrix: np.ndarray) -> float:
    """Compute Saaty consistency ratio for a square pairwise matrix."""
    matrix = np.array(pairwise_matrix, dtype=float)
    _validate_pairwise_matrix(matrix)

    n = matrix.shape[0]
    if n <= 2:
        return 0.0

    eigenvalues = np.linalg.eigvals(matrix)
    lambda_max = float(np.max(eigenvalues.real))
    ci = (lambda_max - n) / (n - 1)
    ri = RANDOM_INDEX_BY_N.get(n)
    if ri is None or ri == 0.0:
        return 0.0
    return float(ci / ri)


def derive_ahp_weights(
    pairwise_matrix: np.ndarray,
    criteria: Sequence[str] = CRITERIA,
    *,
    enforce_consistency: bool = True,
    consistency_threshold: float = DEFAULT_CONSISTENCY_THRESHOLD,
) -> dict[str, float]:
    """Compute normalized AHP weights from principal eigenvector."""
    matrix = np.array(pairwise_matrix, dtype=float)
    _validate_pairwise_matrix(matrix)
    if len(criteria) != matrix.shape[0]:
        raise ValueError("Criteria length must match matrix dimensions.")

    if enforce_consistency:
        consistency_ratio = compute_consistency_ratio(matrix)
        if consistency_ratio > float(consistency_threshold):
            raise ValueError(
                f"AHP consistency ratio {consistency_ratio:.4f} exceeds threshold {consistency_threshold:.4f}."
            )

    eigenvalues, eigenvectors = np.linalg.eig(matrix)
    principal_index = int(np.argmax(eigenvalues.real))
    principal_vector = np.abs(eigenvectors[:, principal_index].real)

    vector_sum = float(principal_vector.sum())
    if vector_sum <= 0.0:
        raise ValueError("Invalid AHP eigenvector; cannot normalize weights.")

    normalized = principal_vector / vector_sum
    normalized = normalized / float(normalized.sum())
    return {name: float(normalized[i]) for i, name in enumerate(criteria)}


def weights_to_percentages(weights: Mapping[str, float]) -> dict[str, int]:
    """Convert normalized weights to integer percentages summing exactly to 100."""
    ordered = [float(weights.get(name, 0.0)) for name in CRITERIA]
    total = float(sum(ordered))
    if total <= 0.0:
        raise ValueError("Weights must have a positive sum.")

    normalized = [value / total for value in ordered]
    raw_percent = [value * 100.0 for value in normalized]
    floor_values = [int(np.floor(value)) for value in raw_percent]
    remainder = 100 - sum(floor_values)

    fractional_order = sorted(
        range(len(raw_percent)),
        key=lambda idx: (raw_percent[idx] - floor_values[idx]),
        reverse=True,
    )
    for idx in fractional_order[: max(0, remainder)]:
        floor_values[idx] += 1

    return {name: int(floor_values[i]) for i, name in enumerate(CRITERIA)}


def compute_weighted_score(
    criterion_scores: Mapping[str, float],
    weights: Mapping[str, float],
) -> float:
    score = 0.0
    for criterion, weight in weights.items():
        score += float(weight) * float(criterion_scores.get(criterion, 0.0))
    return float(score)


@lru_cache(maxsize=1)
def get_default_stage_b_weights() -> dict[str, float]:
    """Memoized Stage B AHP weights derived from default pairwise matrix."""
    return derive_ahp_weights(DEFAULT_PAIRWISE_MATRIX)


@lru_cache(maxsize=1)
def get_default_stage_b_weight_percentages() -> dict[str, int]:
    """Memoized Stage B AHP percentages summing exactly to 100."""
    return weights_to_percentages(get_default_stage_b_weights())
