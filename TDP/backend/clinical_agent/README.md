# Clinical Agent Bundle

This folder contains the minimum code and data needed to run `clinical_agent_pipeline.py` outside the main repository.

## Contents
- `clinical_agent_pipeline.py`
- `stage_a/`
- `stage_b/`
- `stage_c/`
- `app/llm/llm.py`
- `files/`
- `.env.example`
- `requirements.txt`

## Setup
1. Create and activate a Python 3.10+ virtual environment.
2. Install dependencies:
   `pip install -r requirements.txt`
3. If Stage A or Stage B LLM reasoning is needed, create a `.env` file from `.env.example` and provide the required `UHG_*` values.

## Run
- Default run with tidy progress trace:
  `python clinical_agent_pipeline.py`
- Quiet run:
  `python clinical_agent_pipeline.py --no-trace`
- Compact terminal summary:
  `python clinical_agent_pipeline.py --pretty`
- Write debug artifact too:
  `python clinical_agent_pipeline.py --debug`

## Notes
- The pipeline expects the `files/`, `stage_b/data/`, and code folders to remain next to `clinical_agent_pipeline.py` as bundled here.
- The output file is written to `clinical_agent_output.json` in the same folder unless `--output-file` is provided.
