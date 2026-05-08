import sqlite3, json
c = sqlite3.connect(r"C:\AI\Platform\MediaVault\core\mediavault.sqlite")
rows = c.execute("SELECT queue_id, source_url, enrichment_json FROM ingest_queue WHERE ingest_source=? ORDER BY queue_id", ("extension-capture",)).fetchall()
for r in rows:
    d = json.loads(r[2]) if r[2] else {}
    author = (d.get("author_name") or "?")[:30]
    date = d.get("post_date") or "?"
    imgs = len(d.get("_extension_images") or [])
    comments = len(d.get("_comments") or [])
    text = (d.get("extracted_text") or "")[:60].replace("\n", " ")
    print(f"ID:{r[0]} | {author} | date:{date} | img:{imgs} | com:{comments} | {text}")
print(f"Total: {len(rows)}")
