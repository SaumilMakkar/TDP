"""Stage A configuration for real CSV data sources."""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Single source of truth for real Stage A CSV data location.
DATA_DIR = Path(os.getenv("STAGE_A_DATA_DIR", str(REPO_ROOT / "files"))).resolve()

PRODUCT_CSV_NAME = "v_d_product.csv"
INGREDIENT_CSV_NAME = "v_d_prod_ingredient.csv"
FORMULARY_CSV_NAME = "v_d_formulary_alternative.csv"


def csv_path(filename: str) -> Path:
    path = DATA_DIR / filename
    if not path.exists():
        raise FileNotFoundError(
            f"Expected Stage A CSV '{filename}' at {path}. "
            f"Set STAGE_A_DATA_DIR to the correct directory if needed."
        )
    return path
