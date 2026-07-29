import json
import urllib.request

URL = "http://127.0.0.1:8000/api/claim/evaluate"

tests = [
    {"drug_id": "1037", "plan_id": "3001", "member_id": "2061", "diagnosis": "J06.9"},
    {"drug_id": "1036", "plan_id": "3001", "member_id": "2061", "diagnosis": "J06.9"},
    {"drug_id": "1035", "plan_id": "3001", "member_id": "2061", "diagnosis": "J06.9"},
    {"drug_id": "1035", "plan_id": "3003", "member_id": "2061", "diagnosis": "L03.119"},
    {"drug_id": "1037", "plan_id": "3003", "member_id": "2094", "diagnosis": "J06.9"},
    {"drug_id": "1004", "plan_id": "3001", "member_id": "2094", "diagnosis": "E78.5"},
    {"drug_id": "1005", "plan_id": "3001", "member_id": "2094", "diagnosis": "E78.5"},
    {"drug_id": "1022", "plan_id": "3005", "member_id": "2122", "diagnosis": "I48.2"},
    {"drug_id": "1023", "plan_id": "3005", "member_id": "2122", "diagnosis": "I48.2"},
    {"drug_id": "1009", "plan_id": "3002", "member_id": "2038", "diagnosis": "E11.618"},
    {"drug_id": "1039", "plan_id": "3002", "member_id": "2038", "diagnosis": "E11.618"},
    {"drug_id": "1018", "plan_id": "3009", "member_id": "2036", "diagnosis": "J45.901"},
    {"drug_id": "1019", "plan_id": "3009", "member_id": "2036", "diagnosis": "J45.901"},
    {"drug_id": "1016", "plan_id": "3006", "member_id": "2134", "diagnosis": "M81.6"},
    {"drug_id": "1017", "plan_id": "3006", "member_id": "2134", "diagnosis": "M81.6"},
]

for t in tests:
    payload = {
        "drug_id": t["drug_id"],
        "plan_id": t["plan_id"],
        "member_id": t["member_id"],
        "quantity": 30,
        "fill_date": "2025-06-01",
        "diagnosis": t["diagnosis"],
    }
    try:
        req = urllib.request.Request(
            URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            d = json.load(resp)
        decision = d.get("summary", {}).get("decision")
        escalated = d.get("escalated")
        chosen = d.get("summary", {}).get("chosen_drug")
        conf = d.get("summary", {}).get("confidence_score")
        outcomes = "|".join(
            f"{c.get('drug_id')}:{c.get('outcome')}"
            for c in d.get("summary", {}).get("candidate_outcomes", [])
        )
        print(
            f"drug={t['drug_id']} plan={t['plan_id']} mbr={t['member_id']} dx={t['diagnosis']} "
            f"=> decision={decision} escalated={escalated} chosen={chosen} conf={conf} outcomes={outcomes}"
        )
    except Exception as e:
        print(
            f"drug={t['drug_id']} plan={t['plan_id']} mbr={t['member_id']} dx={t['diagnosis']} "
            f"=> ERROR {e}"
        )
