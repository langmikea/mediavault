"""
enrich_helper.py - Export queue for Claude enrichment, import results back
C:\AI\Platform\MediaVault\core\enrich_helper.py

Usage:
  python enrich_helper.py export        # export pending items to enrich_queue.json
  python enrich_helper.py import        # import enrich_results.json back to DB

Workflow:
  1. python enrich_helper.py export
  2. Upload screenshots + enrich_queue.json to Claude
  3. Claude returns enrich_results.json
  4. Save enrich_results.json to C:\AI\Platform\MediaVault\core\
  5. python enrich_helper.py import
  6. Open inbox to review
"""

import json, sqlite3, sys
from pathlib import Path

DB   = Path("C:/AI/Platform/MediaVault/core/mediavault.sqlite")
CORE = Path("C:/AI/Platform/MediaVault/core")

def export_queue():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT queue_id, domain, ingest_source, raw_path, source_url "
        "FROM ingest_queue WHERE status='pending' ORDER BY queued_at"
    ).fetchall()
    items = [dict(r) for r in rows]
    conn.close()
    out = CORE / "enrich_queue.json"
    out.write_text(json.dumps(items, indent=2))
    print(f"Exported {len(items)} pending items to {out}")
    print("Upload this file + the screenshots to Claude for enrichment.")

def import_results():
    src = CORE / "enrich_results.json"
    if not src.exists():
        print(f"Not found: {src}")
        return
    results = json.loads(src.read_text())
    conn = sqlite3.connect(DB)
    updated = 0
    for r in results:
        qid = r.get("queue_id")
        data = r.get("enrichment")
        if qid and data:
            conn.execute(
                "UPDATE ingest_queue SET enrichment_json=?, status='enriched' WHERE queue_id=?",
                [json.dumps(data), qid]
            )
            updated += 1
    conn.commit()
    conn.close()
    print(f"Imported enrichment for {updated} items. Open the inbox to review.")

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "export"
    if cmd == "export": export_queue()
    elif cmd == "import": import_results()
    else: print("Usage: python enrich_helper.py [export|import]")
