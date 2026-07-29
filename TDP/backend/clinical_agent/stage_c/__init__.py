"""Stage C pipeline package for candidate selection through thresholding."""

from .candidate_selection import select_candidates
from .clinical_rationale import build_clinical_rationale
from .composite_score import compute_composite_score, compute_composite_scores
from .config import DEFAULT_STAGE_C_CONFIG, StageCConfig, load_stage_c_config
from .evidence_packaging import package_evidence
from .final_payload import build_final_payload
from .models import StageCCandidate, StageCFlags
from .ranking import rank_candidates
from .safety_flags import evaluate_safety_flags, load_stage_b_patient_labs
from .threshold import apply_threshold, filter_passing_candidates

__all__ = [
	"DEFAULT_STAGE_C_CONFIG",
	"StageCCandidate",
	"StageCConfig",
	"StageCFlags",
	"apply_threshold",
	"build_clinical_rationale",
	"build_final_payload",
	"compute_composite_score",
	"compute_composite_scores",
	"evaluate_safety_flags",
	"filter_passing_candidates",
	"load_stage_b_patient_labs",
	"load_stage_c_config",
	"package_evidence",
	"rank_candidates",
	"select_candidates",
]