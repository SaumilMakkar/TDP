"""Stage C configuration for composite scoring and threshold evaluation."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return float(default)
    try:
        return float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Environment variable {name} must be a float, got {raw!r}.") from exc


@dataclass(slots=True)
class StageCConfig:
    """Configuration for Stage C composite scoring and threshold evaluation."""

    similarity_weight: float = 0.4
    safety_weight: float = 0.6
    minimum_composite_score: float = 0.70


DEFAULT_STAGE_C_CONFIG = StageCConfig(
    similarity_weight=_env_float("STAGE_C_SIMILARITY_WEIGHT", 0.4),
    safety_weight=_env_float("STAGE_C_SAFETY_WEIGHT", 0.6),
    minimum_composite_score=_env_float("STAGE_C_MINIMUM_COMPOSITE_SCORE", 0.50),
)


def load_stage_c_config(**overrides: float) -> StageCConfig:
    """Return Stage C config using env-backed defaults with optional explicit overrides."""

    config = StageCConfig(
        similarity_weight=DEFAULT_STAGE_C_CONFIG.similarity_weight,
        safety_weight=DEFAULT_STAGE_C_CONFIG.safety_weight,
        minimum_composite_score=DEFAULT_STAGE_C_CONFIG.minimum_composite_score,
    )
    for key, value in overrides.items():
        if value is not None:
            setattr(config, key, float(value))
    return config