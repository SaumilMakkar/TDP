"""Stage B configuration for member and clinical reference data paths."""

from __future__ import annotations

import os
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]

# Sprint B1/B2 source tables (member profile data).
MEMBER_DATA_DIR = Path(
    os.getenv("STAGE_B_MEMBER_DATA_DIR", str(REPO_ROOT / "files"))
).resolve()

# Stage B deterministic safety references used in later sprints.
STAGE_B_DATA_DIR = Path(
    os.getenv("STAGE_B_DATA_DIR", str(REPO_ROOT / "stage_b" / "data"))
).resolve()

MEMBER_CSV_NAME = "v_d_member.csv"


def member_csv_path(filename: str = MEMBER_CSV_NAME) -> Path:
    path = MEMBER_DATA_DIR / filename
    if not path.exists():
        raise FileNotFoundError(
            f"Expected Stage B member CSV '{filename}' at {path}. "
            f"Set STAGE_B_MEMBER_DATA_DIR to the correct directory if needed."
        )
    return path
