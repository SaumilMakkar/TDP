"""Backend-local wrapper for running the Stage B demo without manual env setup."""

from __future__ import annotations

import os
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parent
REPO_ROOT = BACKEND_DIR.parent

os.environ.setdefault("STAGE_A_DATA_DIR", str(BACKEND_DIR / "data"))

# Edit these defaults here instead of passing them on the command line.
DEFAULT_MEMBER = "MBR0002002"
DEFAULT_DIAGNOSIS = "I10"
DEFAULT_ORIGINAL_DRUG = "Lisinopril"
DEFAULT_CANDIDATE_DRUG = "Amlodipine"

sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(BACKEND_DIR))

from stage_b.run_demo import main


def _ensure_default_args() -> None:
    argv = list(sys.argv)

    if "--member" not in argv:
        argv.extend(["--member", DEFAULT_MEMBER])
    if "--diagnosis" not in argv:
        argv.extend(["--diagnosis", DEFAULT_DIAGNOSIS])
    if "--original-drug" not in argv:
        argv.extend(["--original-drug", DEFAULT_ORIGINAL_DRUG])
    if "--candidate-drug" not in argv:
        argv.extend(["--candidate-drug", DEFAULT_CANDIDATE_DRUG])

    sys.argv = argv


if __name__ == "__main__":
    _ensure_default_args()
    raise SystemExit(main())