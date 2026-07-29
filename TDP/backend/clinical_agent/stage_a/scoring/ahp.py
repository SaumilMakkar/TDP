"""AHP utilities for Stage A clinical similarity scoring."""

from __future__ import annotations

from functools import lru_cache
from typing import Mapping, Sequence

import numpy as np


CRITERIA: tuple[str, ...] = (
    "ingredient",
    "moiety",
    "class",
    "moa",
    "combo",
    "route",
    "form",
    "strength",
)


# Bootstrap pairwise matrix from AHP_Stage_A_Implementation_Guide.md.
DEFAULT_PAIRWISE_MATRIX = np.array(
    [
        [1.0, 2.0, 5.0, 5.0, 5.0, 7.0, 7.0, 9.0],
        [1.0 / 2.0, 1.0, 3.0, 3.0, 3.0, 5.0, 5.0, 7.0],
        [1.0 / 5.0, 1.0 / 3.0, 1.0, 1.0 / 2.0, 2.0, 3.0, 3.0, 5.0],
        [1.0 / 5.0, 1.0 / 3.0, 2.0, 1.0, 2.0, 3.0, 3.0, 5.0],
        [1.0 / 5.0, 1.0 / 3.0, 1.0 / 2.0, 1.0 / 2.0, 1.0, 2.0, 2.0, 3.0],
        [1.0 / 7.0, 1.0 / 5.0, 1.0 / 3.0, 1.0 / 3.0, 1.0 / 2.0, 1.0, 2.0, 3.0],
        [1.0 / 7.0, 1.0 / 5.0, 1.0 / 3.0, 1.0 / 3.0, 1.0 / 2.0, 1.0 / 2.0, 1.0, 2.0],
        [1.0 / 9.0, 1.0 / 7.0, 1.0 / 5.0, 1.0 / 5.0, 1.0 / 3.0, 1.0 / 3.0, 1.0 / 2.0, 1.0],
    ],
    dtype=float,
)


def _validate_pairwise_matrix(pairwise_matrix: np.ndarray) -> None:
    if pairwise_matrix.ndim != 2 or pairwise_matrix.shape[0] != pairwise_matrix.shape[1]:
        raise ValueError("AHP pairwise matrix must be square.")
    if pairwise_matrix.shape[0] != len(CRITERIA):
        raise ValueError(
            f"AHP pairwise matrix must be {len(CRITERIA)}x{len(CRITERIA)} for Stage A criteria."
        )


def derive_ahp_weights(
    pairwise_matrix: np.ndarray,
    criteria: Sequence[str] = CRITERIA,
) -> dict[str, float]:
    """Compute normalized AHP weights from the principal eigenvector."""
    matrix = np.array(pairwise_matrix, dtype=float)
    _validate_pairwise_matrix(matrix)

    eigenvalues, eigenvectors = np.linalg.eig(matrix)
    principal_index = int(np.argmax(eigenvalues.real))
    principal_vector = np.abs(eigenvectors[:, principal_index].real)

    vector_sum = float(principal_vector.sum())
    if vector_sum <= 0.0:
        raise ValueError("Invalid AHP eigenvector; cannot normalize weights.")

    normalized = principal_vector / vector_sum
    return {name: float(normalized[i]) for i, name in enumerate(criteria)}


def compute_weighted_similarity_score(
    criterion_scores: Mapping[str, float],
    weights: Mapping[str, float],
) -> float:
    """Compute Stage A similarity score = sum(weight * criterion_score)."""
    score = 0.0
    for criterion, weight in weights.items():
        score += float(weight) * float(criterion_scores.get(criterion, 0.0))
    return float(score)


def rounded_weight_config(weights: Mapping[str, float], ndigits: int = 2) -> dict[str, float]:
    """Return a display-friendly rounded weight config."""
    return {criterion: round(float(value), ndigits) for criterion, value in weights.items()}


@lru_cache(maxsize=1)
def get_default_ahp_weights() -> dict[str, float]:
    """Memoized Stage A AHP weights derived from the default pairwise matrix."""
    return derive_ahp_weights(DEFAULT_PAIRWISE_MATRIX)
