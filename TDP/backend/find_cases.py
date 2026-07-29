import csv, json, urllib.request

URL = "http://127.0.0.1:8000/api/claim/evaluate"

# Targeted payloads: try different plan/member combos
tests = [
    ("1036","3001","2094","J06.9"),
    ("1036","3002","2094","J06.9"),
    ("1037","3001","2061","J06.9"),
    ("1037","3002","2061","J06.9"),
    ("1035","3001","2094","J06.9"),
    ("1036","3001","2061","J06.9"),
    ("1037","3003","2094","J06.9"),
    ("1035","3002","2094","J06.9"),
    ("1036","3003","2061","L03.119"),
    ("1037","3003","2094","L03.119"),
]

auto, dr, ko = [], [], []

for drug_id, plan_id, member_id, dx in tests:
    p = {"drug_id":drug_id,"plan_id":plan_id,"member_id":member_id,"quantity":30,"fill_date":"2025-06-01","diagnosis":dx}
    try:
        req = urllib.request.Request(URL, data=json.dumps(p).encode(), headers={"Content-Type":"application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=20) as r:
            d = json.load(r)
        dec = d["summary"]["decision"]
        esc = d.get("escalated")
        conf = d["summary"].get("confidence_score")
        outs = "|".join(f"{c['drug_id']}:{c['outcome']}" for c in d["summary"].get("candidate_outcomes",[]))
        fc = d.get("final_candidates",[{}])[0]
        tp = fc.get("threshold_pass",{})
        print(f"drug={drug_id} plan={plan_id} mbr={member_id} dx={dx} -> {dec} esc={esc} conf={conf}")
        print(f"  outcomes: [{outs}]")
        print(f"  pol={tp.get('policy')} clin={tp.get('clinical')} fin={tp.get('financial')} past={tp.get('past')}")
        if dec == "auto_approve": auto.append(p)
        elif dec == "doctor_review": dr.append(p)
        elif dec == "keep_original": ko.append(p)
    except Exception as e:
        print(f"ERR {drug_id}/{plan_id}/{member_id}: {e}")

print(f"\nFound: auto={len(auto)} doctor_review={len(dr)} keep_original={len(ko)}")
