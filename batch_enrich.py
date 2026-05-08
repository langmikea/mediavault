"""
batch_enrich.py — MediaVault batch vision enrichment
Loops all queue rows with status='pending' (or 'enriched' for retry) that have
a raw_path, runs Sonnet vision via imgserver /enrich proxy, writes result back.

Usage:
  python batch_enrich.py            # process pending only
  python batch_enrich.py --retry    # reprocess enriched rows too
  python batch_enrich.py --dry-run  # print queue without calling API
"""

import json, sys, time, urllib.request, urllib.error, sqlite3
from pathlib import Path

BASE     = Path("C:/AI/Platform/MediaVault")
DB_PATH  = BASE / "core/mediavault.sqlite"
SRV      = "http://127.0.0.1:51822"
MODEL    = "claude-sonnet-4-5"
MAX_TOK  = 1000
DELAY    = 1.2

PROMPT = """You are archiving media for a Hunter Root fan archive. Hunter Root is an independent musician from central Pennsylvania. His bands include Seeds and Medusa's Disco. His brother Nick Root is also a musician.

Analyze this image and return ONLY a JSON object with these fields (omit any field you cannot determine):
{
  "post_date": "YYYY-MM-DD or null",
  "description_short": "one sentence, what is shown",
  "description_long": "2-4 sentences with detail",
  "extracted_text": "any visible text verbatim",
  "author_name": "person who posted, if visible",
  "source_platform": "facebook|instagram|youtube|other",
  "media_type_in_post": "photo|video|link|text|reel|story",
  "tags_year_era": "year or era if determinable",
  "tags_content_type": "performance|portrait|candid|artwork|merch|promo|other",
  "tags_subject": "main subject tags comma separated",
  "tags_topic": "topic tags comma separated",
  "tags_song_reference": "song title if referenced",
  "tags_keywords": "other keywords comma separated",
  "notes": "anything unusual or worth flagging"
}
Return ONLY the JSON object. No markdown, no explanation."""


def srv_get(path):
    req = urllib.request.Request(SRV + path)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def srv_post(path, payload):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(SRV + path, data=data,
                                  headers={"Content-Type": "application/json"},
                                  method="POST")
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read())


def get_queue():
    force_keep = "--force-keep" in sys.argv
    retry      = "--retry"      in sys.argv
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    if force_keep:
        statuses = ("keep",)
    elif retry:
        statuses = ("pending", "enriched")
    else:
        statuses = ("pending",)
    placeholders = ",".join("?" * len(statuses))
    rows = conn.execute(
        f"SELECT queue_id, raw_path, enrichment_json, artifact_id "
        f"FROM ingest_queue WHERE status IN ({placeholders}) AND raw_path IS NOT NULL "
        f"AND raw_path != '' ORDER BY queued_at ASC",
        list(statuses)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def enrich_one(row):
    img_resp = srv_get(f"/image?path={urllib.request.quote(row['raw_path'], safe='')}")
    b64  = img_resp["b64"]
    mt   = img_resp.get("media_type", "image/jpeg")

    payload = {
        "model": MODEL,
        "max_tokens": MAX_TOK,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": mt, "data": b64}},
                {"type": "text",  "text": PROMPT}
            ]
        }]
    }

    api_resp = srv_post("/enrich", payload)

    text = ""
    for block in api_resp.get("content", []):
        if block.get("type") == "text":
            text += block.get("text", "")

    text = text.strip().lstrip("```json").rstrip("```").strip()
    parsed = json.loads(text)
    return parsed


def merge(existing_json_str, new_data):
    PROTECTED = ["capture_device", "gps_lat", "gps_lon", "gps_location",
                 "post_date_confidence", "post_date"]
    try:
        existing = json.loads(existing_json_str or "{}")
    except Exception:
        existing = {}

    merged = dict(existing)
    for k, v in new_data.items():
        if k not in PROTECTED and (k not in merged or merged[k] is None or merged[k] == ""):
            merged[k] = v

    if not merged.get("post_date") and new_data.get("post_date"):
        merged["post_date"] = new_data["post_date"]

    from datetime import datetime, timezone
    merged["_ai_enriched_at"] = datetime.now(timezone.utc).isoformat()
    merged["_ai_fields"] = [k for k in new_data if k not in PROTECTED and k not in existing]
    return merged


def main():
    retry  = "--retry"   in sys.argv
    dry    = "--dry-run" in sys.argv

    rows = get_queue()
    if not rows:
        print("No items to enrich.")
        return

    print(f"{'DRY RUN — ' if dry else ''}Found {len(rows)} item(s) to enrich.")
    print()

    ok = fail = 0
    for i, row in enumerate(rows, 1):
        qid  = row["queue_id"]
        path = row["raw_path"]
        aid  = row["artifact_id"] or "(no artifact id)"
        print(f"[{i}/{len(rows)}] {aid}  {Path(path).name}")

        if dry:
            print("        (dry run — skipping API call)")
            continue

        try:
            parsed = enrich_one(row)
            merged = merge(row.get("enrichment_json"), parsed)
            ej     = json.dumps(merged)
            srv_post("/api/queue-update", {
                "queue_id":       qid,
                "status":         "enriched",
                "enrichment_json": ej
            })
            desc = parsed.get("description_short", "")[:70]
            print(f"        OK  — {desc}")
            ok += 1
        except Exception as e:
            print(f"        FAIL — {e}")
            fail += 1

        if i < len(rows):
            time.sleep(DELAY)

    print()
    print(f"Done. {ok} enriched, {fail} failed.")
    if fail:
        print("Re-run with --retry to retry failed items after fixing any issues.")


if __name__ == "__main__":
    main()
