import csv
import json
import urllib.request

URL = "http://127.0.0.1:8000/api/claim/evaluate"
CSV_PATH = r"c:\Users\smakkar5\Desktop\PBM\backend\data\F_CLM_TRANSACTION.csv"

with open(CSV_PATH, encoding="utf-8") as f:
    rows = list(csv.DictReader(f))[:500]

doctor_review = []
auto_approve = []

for r in rows:
    payload = {
        "drug_id": str(r["PROD_SK"]),
        "plan_id": str(r["PLN_SK"]),
        "member_id": str(r["MBR_SK"]),
        "quantity": 30,
        "fill_date": "2025-06-01",
        "diagnosis": str(r.get("DX_CD", "")),
    }
    try:
        req = urllib.request.Request(
            URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=25) as resp:
            data = json.load(resp)

        summary = data.get("summary") or {}
        decision = summary.get("decision")

        if decision == "doctor_review" and len(doctor_review) < 5:
            outcomes = "|".join(
                f"{c.get('drug_id')}:{c.get('outcome')}"
                for c in summary.get("candidate_outcomes", [])
            )
            doctor_review.append(
                {
                    "payload": payload,
                    "escalated": data.get("escalated"),
                    "confidence": summary.get("confidence_score"),
                    "outcomes": outcomes,
                }
            )

        if decision == "auto_approve" and len(auto_approve) < 5:
            auto_approve.append(
                {
                    "payload": payload,
                    "chosen_drug": summary.get("chosen_drug"),
                    "confidence": summary.get("confidence_score"),
                }
            )

        if len(doctor_review) >= 2 and len(auto_approve) >= 1:
            break

    except Exception:
        continue

print("DR_COUNT", len(doctor_review))
for i, row in enumerate(doctor_review, start=1):
    p = row["payload"]
    print(
        f"DR{i} {p['drug_id']} {p['plan_id']} {p['member_id']} {p['diagnosis']} "
        f"escalated={row['escalated']} conf={row['confidence']} outcomes={row['outcomes']}"
    )

print("AA_COUNT", len(auto_approve))
for i, row in enumerate(auto_approve, start=1):
    p = row["payload"]
    print(
        f"AA{i} {p['drug_id']} {p['plan_id']} {p['member_id']} {p['diagnosis']} "
        f"chosen={row['chosen_drug']} conf={row['confidence']}"
    )
