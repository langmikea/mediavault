"""
backfill_dates.py — Run AI pre-processing on existing enriched queue items with null post_date
"""
import sqlite3, json, os, sys
sys.path.insert(0, r"C:\AI\Platform\MediaVault\core")
from ingest_engine import ai_preprocess

DB_PATH = r"C:\AI\Platform\MediaVault\core\mediavault.sqlite"

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

rows = conn.execute("""
    SELECT queue_id, enrichment_json, source_url
    FROM ingest_queue
    WHERE status = 'enriched'
""").fetchall()

print(f"Found {len(rows)} enriched items to check.")
updated = 0

for row in rows:
    ej = json.loads(row["enrichment_json"]) if row["enrichment_json"] else {}
    if ej.get("post_date"):
        print(f"  [{row['queue_id']}] Already has date: {ej['post_date']} - skipping")
        continue

    # Build minimal data dict for ai_preprocess
    data = {
        "post_text": ej.get("extracted_text") or ej.get("description_long") or "",
        "title": "",
        "url": row["source_url"] or "",
        "post_url": row["source_url"] or "",
        "platform": ej.get("source_platform") or "facebook",
        "images": ej.get("_extension_images") or [],
        "post_date": None,
    }

    print(f"  [{row['queue_id']}] Processing: {(row['source_url'] or '')[:60]}")
    ai = ai_preprocess(data)

    if ai.get("post_date"):
        ej["post_date"] = ai["post_date"]
        ej["post_date_confidence"] = ai.get("post_date_confidence", "estimated")
        conn.execute(
            "UPDATE ingest_queue SET enrichment_json=? WHERE queue_id=?",
            (json.dumps(ej), row["queue_id"])
        )
        conn.commit()
        print(f"    -> Date set: {ai['post_date']} ({ai.get('post_date_confidence')})")
        updated += 1
    else:
        print(f"    -> No date found")

conn.close()
print(f"\nDone. {updated} items updated.")
