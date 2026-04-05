#!/usr/bin/env python3
"""
Admin user setup script
Usage: python make_admin.py <email>
"""

import sqlite3
import sys
from pathlib import Path

def make_admin(email: str):
    db_path = Path(__file__).parent / "app" / "data" / "app.db"

    if not db_path.exists():
        print(f"❌ Database not found at {db_path}")
        return False

    conn = sqlite3.connect(str(db_path))
    try:
        # Check if user exists
        user = conn.execute("SELECT id, email, is_admin FROM users WHERE email = ?", (email,)).fetchone()
        if not user:
            print(f"❌ User with email '{email}' not found")
            return False

        user_id, user_email, is_admin = user
        if is_admin:
            print(f"ℹ User '{email}' is already an admin")
            return True

        # Make user admin
        conn.execute("UPDATE users SET is_admin = 1 WHERE email = ?", (email,))
        conn.commit()

        print(f"✅ User '{email}' is now an admin with unlimited uploads")
        return True

    except Exception as e:
        print(f"❌ Error: {e}")
        return False
    finally:
        conn.close()

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python make_admin.py <email>")
        sys.exit(1)

    email = sys.argv[1].strip()
    if not email:
        print("❌ Email cannot be empty")
        sys.exit(1)

    success = make_admin(email)
    sys.exit(0 if success else 1)