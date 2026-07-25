#!/usr/bin/env python3
"""One-time migration: remove spurious garage_events rows where the state
matches the previous event for the same door (false transitions generated on
monitor restarts before the startup-seeding fix)."""

import sqlite3
import os
import sys

DB_PATH = os.path.expanduser("~/.local/share/smart-home/readings.db")
if len(sys.argv) > 1:
    DB_PATH = sys.argv[1]

conn = sqlite3.connect(DB_PATH)

rows = conn.execute(
    "SELECT id, name, ts, state FROM garage_events ORDER BY name, ts"
).fetchall()

to_delete = []
last_state: dict[str, str] = {}

for row_id, name, ts, state in rows:
    if name in last_state and last_state[name] == state:
        to_delete.append((row_id, name, ts, state))
    else:
        last_state[name] = state

if not to_delete:
    print("Nothing to delete.")
    conn.close()
    sys.exit(0)

print(f"Found {len(to_delete)} spurious event(s):")
for row_id, name, ts, state in to_delete:
    print(f"  id={row_id}  {name}  {ts}  {state}")

confirm = input("\nDelete these rows? [y/N] ").strip().lower()
if confirm != "y":
    print("Aborted.")
    conn.close()
    sys.exit(1)

conn.execute(
    f"DELETE FROM garage_events WHERE id IN ({','.join('?' * len(to_delete))})",
    [r[0] for r in to_delete],
)
conn.commit()
print(f"Deleted {len(to_delete)} row(s).")
conn.close()
