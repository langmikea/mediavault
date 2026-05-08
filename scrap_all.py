import sqlite3
conn = sqlite3.connect("core/mediavault.sqlite")
rows = conn.execute("SELECT queue_id FROM ingest_queue WHERE status NOT IN ('keep','skip','failed')").fetchall()
ids = [r[0] for r in rows]
if ids:
    conn.execute(f"UPDATE ingest_queue SET status='skip' WHERE queue_id IN ({','.join(str(i) for i in ids)})")
    conn.commit()
    print(f"Scrapped {len(ids)} records: {ids}")
else:
    print("Queue already clean")
conn.close()
