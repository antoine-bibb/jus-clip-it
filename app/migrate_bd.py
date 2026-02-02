import sqlite3
from pathlib import Path

db = Path("app/data/app.db")  # adjust if yours is different

conn = sqlite3.connect(db)
cur = conn.cursor()

def has_col(table, col):
    cur.execute(f"PRAGMA table_info({table})")
    return any(r[1] == col for r in cur.fetchall())

changed = False

if not has_col("users", "plan"):
    cur.execute("ALTER TABLE users ADD COLUMN plan TEXT NOT NULL DEFAULT 'free'")
    print("✅ added users.plan")
    changed = True
else:
    print("ℹ users.plan already exists")

if not has_col("users", "credits_reset_at"):
    cur.execute("ALTER TABLE users ADD COLUMN credits_reset_at TEXT")
    print("✅ added users.credits_reset_at")
    changed = True
else:
    print("ℹ users.credits_reset_at already exists")

conn.commit()
conn.close()

print("✅ migration complete" + (" (changes applied)" if changed else " (no changes needed)"))
