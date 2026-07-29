import sqlite3
import os

DB_PATH = os.path.join("frontend", "database", "doctor_decisions.db")
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

# Get prescription table schema
cursor.execute("PRAGMA table_info(prescription);")
cols = cursor.fetchall()
print("PRESCRIPTION table columns:")
for col in cols:
    print(f"  {col[1]}: {col[2]}")

# Get doctor_decision table schema
cursor.execute("PRAGMA table_info(doctor_decision);")
cols = cursor.fetchall()
print("\nDOCTOR_DECISION table columns:")
for col in cols:
    print(f"  {col[1]}: {col[2]}")

# Get pbm_response table schema
cursor.execute("PRAGMA table_info(pbm_response);")
cols = cursor.fetchall()
print("\nPBM_RESPONSE table columns:")
for col in cols:
    print(f"  {col[1]}: {col[2]}")

conn.close()
