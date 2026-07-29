from dotenv import load_dotenv
import os
import json
import sys
from pathlib import Path

# Load .env FIRST
load_dotenv(override=True)

print("HCP CLIENT ID SET:", bool(os.getenv("HCP_CLIENT_ID")))
print("HCP CLIENT SECRET SET:", bool(os.getenv("HCP_CLIENT_SECRET")))

# Make sure Python can import app.agents from project root
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from past_decisions_agent_final import (
    DatasetPaths,
    AgentConfig,
    PastDecisionsAgent,
)


# ------------------------------------------------------------
# EDIT THESE INPUTS TO TEST DIFFERENT CASES
# ------------------------------------------------------------
TEST_PAYLOAD = { 
    "claim_id": None, 
    "drug": "Zolpidem 10mg", 
    "member_key": "2190", 
    "diagnosis": "G47.00", 
} 
 
TEST_CLINICAL_OUTPUT = { 
    "recommended": "Levothyroxine 50mcg" 
} 

def main() -> None:
    dataset_paths = DatasetPaths(
        doctor_responses="data/doctor_responses_revised_5.csv",
        claims="data/F_CLM_TRANSACTION.csv",
        product="data/v_d_product.csv",
        prescription="data/v_xxiris_om_prescription.csv",
        member="data/v_d_member.csv",
        patient_history="data/patient_history.csv",
    )

    config = AgentConfig(
        similarity_threshold=0.75,
        top_k=5,

        # Keep debug false so raw matches are not printed
        debug=False,
    )

    agent = PastDecisionsAgent(
        dataset_paths=dataset_paths,
        config=config,
    )

    result = agent.run(
        TEST_PAYLOAD,
        TEST_CLINICAL_OUTPUT,
    )

    # Print clean final result only
    print(json.dumps({
        "average_confidence_score": result.get("average_confidence_score"),
        "final_score": result.get("final_score"),
        "historical_score": result.get("historical_score"),
        "rule_based_patient_adjustment_score": result.get("rule_based_patient_adjustment_score"),
        "final_statement": result.get("final_statement"),
        "top_cases": result.get("top_cases"),
    }, indent=2, default=str))


if __name__ == "__main__":
    main()