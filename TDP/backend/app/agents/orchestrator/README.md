# Portable Orchestrator Package

This folder is self-contained for running the standalone `orchestrator.py`.

## Contents
- `orchestrator.py` : full intake-to-summary orchestrator flow
- `requirements.txt` : minimal dependencies
- `.env.example` : optional env vars for live LLM calls

## Quick Start (Windows PowerShell)

1. Open terminal in this folder.
2. Create and activate virtual environment:
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```
3. Install dependencies:
   ```powershell
   pip install -r requirements.txt
   ```
4. Run:
   ```powershell
   python orchestrator.py
   ```

## Output
- Generates `outputs/latest_output.json` in this same folder.

## Optional Live LLM Setup
- If you want live Layer 7/8 calls, create a `.env` file from `.env.example` and fill in credentials.
- Without credentials, the script still runs using fail-safe behavior.

## Optional CLI Arguments
```powershell
python orchestrator.py --case auto_accept
python orchestrator.py --case provider_review
python orchestrator.py --input-json <path_to_input_json>
python orchestrator.py --inline-json '{"member_id":2001,...}'
python orchestrator.py --provider-selected-alternative-id 1014
```
