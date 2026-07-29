import time, json, urllib.request

# Wait briefly for server
time.sleep(1)

# Login as provider
login_data = json.dumps({"username":"prov1","password":"password123"}).encode()
req = urllib.request.Request('http://127.0.0.1:5000/api/login', data=login_data, headers={'Content-Type':'application/json'})
resp = urllib.request.urlopen(req)
login = json.loads(resp.read().decode())
token = login['token']
print('TOKEN:', token)

# Submit prescription
form = {
    'patient_account_id': 'p999',
    'npi_number': '1234567890',
    'phr_id': 'PHR004001',
    'prod_nm': 'AutoApproveDrug',
    'prod_rxcui': '000000',
    'dosage_size': '10 mg',
    'frequency': 'QD',
    'days_supply': 7,
    'diagnosis': 'Z79.899 - Other long term drug therapy'
}
req2 = urllib.request.Request('http://127.0.0.1:5000/api/prescription', data=json.dumps(form).encode(), headers={'Content-Type':'application/json','Authorization': 'Bearer ' + token})
resp2 = urllib.request.urlopen(req2)
out = json.loads(resp2.read().decode())
print('SUBMIT:', out)

# Fetch result
rx = out.get('rx_number')
if rx:
    time.sleep(0.5)
    req3 = urllib.request.Request(f'http://127.0.0.1:5000/api/prescription/{rx}/result', headers={'Authorization': 'Bearer ' + token})
    resp3 = urllib.request.urlopen(req3)
    print('RESULT:', resp3.read().decode())
else:
    print('No rx returned')
