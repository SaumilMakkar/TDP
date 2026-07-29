from __future__ import annotations

import json
import sys
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from run_past_decisions_postprocess import run_agent_and_summarize_for_ori


SAMPLE_PAYLOAD = {
    "original_drug": "Lisinopril",
    "patient_id": "100245",
    "claim_id": "9001123",
    "diagnosis": "I10",
}

SAMPLE_CLINICAL_OUTPUT = {
    "recommended_drug": "Losartan",
}



# SAMPLE_PAYLOAD = {
# "original_drug": "Atorvastatin",
# "patient_id": "2020",
# "claim_id": None,
# "diagnosis": "E78.5",
# }

# SAMPLE_CLINICAL_OUTPUT = {
# "recommended_drug": "Rosuvastatin"
# }

def main() -> None:
    load_dotenv(override=True)

    final_output = run_agent_and_summarize_for_ori(
        payload=SAMPLE_PAYLOAD,
        clinical_output=SAMPLE_CLINICAL_OUTPUT,
        similarity_threshold=0.30,
        top_k=5,
        enable_agent_llm_adjustment=False,
        skip_llm=False,
    )

    print(json.dumps(final_output, indent=2, default=str))


if __name__ == "__main__":
    main()