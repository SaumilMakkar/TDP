"""Scan F_CLM_TRANSACTION.csv and collect 2 examples per decision path."""
import csv, json, urllib.request

URL = "http://127.0.0.1:8000/api/claim/evaluate"

def call(payload):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(URL, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)

rows = []
with open(r"C:\Users\smakkar5\Desktop\PBM\backend\data\F_CLM_TRANSACTION.csv") as f:
    rows = list(csv.DictReader(f))[:400]

auto, dr, ko = [], [], []

for r in rows:
    payload = {
        "drug_id": r["PROD_SK"], "plan_id": r["PLN_SK"],
        "member_id": r["MBR_SK"], "quantity": 30,
        "fill_date": "2025-06-01", "diagnosis": r["DX_CD"]
    }
    try:
        res = call(payload)
        d = res["summary"]["decision"]
        esc = res.get("escalated")
        conf = res["summary"].get("confidence_score")
        outcomes = "|".join(f"{c['drug_id']}:{c['outcome']}" for c in res["summary"].get("candidate_outcomes", []))
        fc = res.get("final_candidates", [{}])[0]
        tp = fc.get("threshold_pass", {})
        obj = {**payload, "decision": d, "escalated": esc, "confidence": conf, "outcomes": outcomes,
               "pol": tp.get("policy"), "clin": tp.get("clinical"),
               "fin": tp.get("financial"), "past": tp.get("past")}
        if d == "auto_approve" and len(auto) < 2: auto.append(obj)
        elif d == "doctor_review" and len(dr) < 2: dr.append(obj)
        elif d == "keep_original" and len(ko) < 2: ko.append(obj)
        if len(auto) >= 2 and len(dr) >= 2 and len(ko) >= 2:
            break
    except Exception as e:
        pass

for label, group in [("AUTO_APPROVE", auto), ("DOCTOR_REVIEW", dr), ("KEEP_ORIGINAL", ko)]:
    print(f"\n=== {label} ===")
    for x in group:
        print(f"  drug_id={x['drug_id']} plan_id={x['plan_id']} member_id={x['member_id']} diagnosis={x['diagnosis']}")
        print(f"  decision={x['decision']} escalated={x['escalated']} confidence={x['confidence']}")
        print(f"  thresholds: policy={x['pol']} clinical={x['clin']} financial={x['fin']} past={x['past']}")
        print(f"  outcomes: {x['outcomes']}")
        print()
