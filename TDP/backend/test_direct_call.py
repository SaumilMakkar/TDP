import sys
from app.main import _run_orchestrator_new

print("[TEST] Starting direct test of _run_orchestrator_new", file=sys.stderr, flush=True)

result = _run_orchestrator_new({
    'drug_id': '1021',
    'member_id': '2003',
    'plan_id': '3010',
    'pharmacy_id': '4001',
    'quantity': 30,
    'fill_date': '2025-06-01',
    'diagnosis': 'I48.2',
    'provider_npi_number': '1234567890',
})

print("[TEST] Test complete. final_outcome=" + str(result.get('final_outcome')), file=sys.stderr, flush=True)
