import sqlite3
from pathlib import Path

DB_PATH = Path("policy_agent.db")
SQL_PATH = Path("policy_agent_schema_sqlite.sql")

if DB_PATH.exists():
    DB_PATH.unlink()

conn = sqlite3.connect(DB_PATH)
conn.execute("PRAGMA foreign_keys = ON")

sql = SQL_PATH.read_text(encoding="utf-8")
conn.executescript(sql)

cur = conn.cursor()
cur.execute("SELECT COUNT(1) FROM claims")
claims_count = cur.fetchone()[0]

cur.execute("SELECT COUNT(1) FROM drug_policy_evaluations")
evals_count = cur.fetchone()[0]

cur.execute(
    "SELECT policy_state, COUNT(1) FROM drug_policy_evaluations GROUP BY policy_state ORDER BY policy_state"
)
states = cur.fetchall()

conn.commit()
conn.close()

print(f"Loaded claims={claims_count}, evaluations={evals_count}, states={states}")
