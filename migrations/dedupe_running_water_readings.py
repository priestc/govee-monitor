#!/usr/bin/env python3
"""
Keep only the last reading per session for running_water zones.
A new session starts whenever the gap between consecutive readings exceeds 90 seconds.
"""
import sqlite3
from datetime import datetime
from pathlib import Path

DB = Path("~/.local/share/smart-home/readings.db").expanduser()
SESSION_GAP_S = 90

conn = sqlite3.connect(str(DB))
conn.row_factory = sqlite3.Row

zones = [r[0] for r in conn.execute(
    "SELECT name FROM wc_zones WHERE zone_type = 'running_water' ORDER BY name"
).fetchall()]

print(f"Running_water zones: {zones}\n")

ids_to_delete = []

for zone in zones:
    rows = conn.execute(
        "SELECT id, ts FROM pool_readings WHERE zone=? ORDER BY ts",
        (zone,),
    ).fetchall()

    if not rows:
        print(f"  {zone}: no readings, skipping")
        continue

    # Group into sessions
    sessions = []
    current = [rows[0]["id"]]
    prev_ts = datetime.strptime(rows[0]["ts"], "%Y-%m-%d %H:%M:%S")

    for row in rows[1:]:
        ts = datetime.strptime(row["ts"], "%Y-%m-%d %H:%M:%S")
        if (ts - prev_ts).total_seconds() > SESSION_GAP_S:
            sessions.append(current)
            current = []
        current.append(row["id"])
        prev_ts = ts
    sessions.append(current)

    zone_delete = []
    for s in sessions:
        zone_delete.extend(s[:-1])  # all but last in each session

    print(f"  {zone}: {len(rows)} readings → {len(sessions)} session(s) → "
          f"keep {len(sessions)}, delete {len(zone_delete)}")
    for s in sessions:
        keep_id = s[-1]
        keep_ts = next(r["ts"] for r in rows if r["id"] == keep_id)
        print(f"    session of {len(s)}: keep id={keep_id} ({keep_ts}), "
              f"delete {len(s)-1} earlier reading(s)")

    ids_to_delete.extend(zone_delete)

print(f"\nTotal to delete: {len(ids_to_delete)} readings")
if ids_to_delete:
    conn.execute(
        f"DELETE FROM pool_readings WHERE id IN ({','.join('?' * len(ids_to_delete))})",
        ids_to_delete,
    )
    conn.commit()
    print("Done.")
