"""Find an auto_approve case by scanning CSV rows with a longer timeout."""
import csv, json, urllib.request

URL = "http://127.0.0.1:8000/api/claim/evaluate"

with open(r"C:\Users\smakkar5\Desktop\PBM\backend\data\F_CLM_TRANSACTION.csv") as f:
    rows = list(csv.DictReader(f))

found = 0
for i, r in enumerate(rows[:600]):
    p = {"drug_id": r["PROD_SK"], "plan_id": r["PLN_SK"],
         "member_id": r["MBR_SK"], "quantity": 30,
         "fill_date": "2025-06-01", "diagnosis": r["DX_CD"]}
    try:
        req = urllib.request.Request(URL, data=json.dumps(p).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=60) as resp:
            d = json.load(resp)
        dec = d["summary"]["decision"]
        if dec == "auto_approve":
            fc = d.get("final_candidates", [{}])[0]
            tp = fc.get("threshold_pass", {})
            conf = d["summary"].get("confidence_score")
            chosen = d["summary"].get("chosen_drug")
            print(f"AUTO_APPROVE FOUND:")
            print(f"  drug_id={r['PROD_SK']} plan_id={r['PLN_SK']} member_id={r['MBR_SK']} diagnosis={r['DX_CD']}")
            print(f"  chosen_drug={chosen} confidence={conf} escalated={d.get('escalated')}")
            print(f"  pol={tp.get('policy')} clin={tp.get('clinical')} fin={tp.get('financial')} past={tp.get('past')}")
            found += 1
            if found >= 2:
                break
    except Exception as e:
        pass  # skip timeouts/errors

if found == 0:
    print("No auto_approve found in first 600 rows")
