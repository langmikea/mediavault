"""
Phase v5-6 Ops test seed: tag and release the Reverend artifact.

Adds six tags to MV-20260510-001, creates corresponding vocabulary
entries in the tags table, and sets status='released' with released_at.

Idempotent: re-running is safe. Detects existing state and skips
already-applied changes.
"""
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "core" / "mediavault.sqlite"
TARGET_ID = "MV-20260510-001"

# Tags to add: (slug, category, display_name)
NEW_TAGS = [
    ("exhibit:hunter_root", "exhibit",     "Exhibit:Hunter Root"),
    ("mood:snarky",         "mood",        "Mood:Snarky"),
    ("mood:defiant",        "mood",        "Mood:Defiant"),
    ("motif:pink-hats",     "motif",       "Motif:Pink Hats"),
    ("theme:resistance",    "theme",       "Theme:Resistance"),
    ("era:arkansas",        "era",         "Era:Arkansas"),
]

def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Verify target exists
    row = cur.execute(
        "SELECT id, status, tags FROM artifacts WHERE id = ?",
        (TARGET_ID,)
    ).fetchone()
    if row is None:
        print(f"FAIL: artifact {TARGET_ID} not found")
        sys.exit(1)

    existing_tags = json.loads(row["tags"]) if row["tags"] else []
    print(f"Existing tags on {TARGET_ID}: {existing_tags}")
    print(f"Current status: {row['status']}")

    # Step 1: add tags to the artifact's tags JSON array
    new_slugs = [t[0] for t in NEW_TAGS]
    merged_tags = list(existing_tags)
    added = []
    for slug in new_slugs:
        if slug not in merged_tags:
            merged_tags.append(slug)
            added.append(slug)

    if added:
        cur.execute(
            "UPDATE artifacts SET tags = ? WHERE id = ?",
            (json.dumps(merged_tags), TARGET_ID)
        )
        print(f"Added to artifact: {added}")
    else:
        print("No new tags to add to artifact")

    # Step 2: vocabulary entries — inspect tags table schema first,
    # then INSERT OR IGNORE matching rows
    schema = cur.execute("PRAGMA table_info(tags)").fetchall()
    columns = [c["name"] for c in schema]
    print(f"tags table columns: {columns}")

    # Build INSERT based on actual columns (slug + category + display_name
    # at minimum; tolerate variations)
    vocab_added = []
    for slug, category, display_name in NEW_TAGS:
        # Check whether the tag already exists
        existing = cur.execute(
            "SELECT slug FROM tags WHERE slug = ?",
            (slug,)
        ).fetchone()
        if existing:
            continue

        # Build column list dynamically based on schema
        insert_cols = []
        insert_vals = []
        if "slug" in columns:
            insert_cols.append("slug")
            insert_vals.append(slug)
        if "category" in columns:
            insert_cols.append("category")
            insert_vals.append(category)
        if "display_name" in columns:
            insert_cols.append("display_name")
            insert_vals.append(display_name)
        if "created_at" in columns:
            insert_cols.append("created_at")
            insert_vals.append(now_iso())
        if "is_proposed" in columns:
            insert_cols.append("is_proposed")
            insert_vals.append(0)

        placeholders = ",".join("?" for _ in insert_cols)
        col_list = ",".join(insert_cols)
        cur.execute(
            f"INSERT INTO tags ({col_list}) VALUES ({placeholders})",
            insert_vals
        )
        vocab_added.append(slug)

    if vocab_added:
        print(f"Added to vocabulary: {vocab_added}")
    else:
        print("No new vocabulary entries to add")

    # Step 3: release the artifact
    if row["status"] != "released":
        cur.execute(
            "UPDATE artifacts SET status = 'released', released_at = ? "
            "WHERE id = ?",
            (now_iso(), TARGET_ID)
        )
        print(f"Released {TARGET_ID} at {now_iso()}")
    else:
        print(f"Already released")

    conn.commit()

    # Final verification
    final = cur.execute(
        "SELECT id, status, tags, released_at FROM artifacts WHERE id = ?",
        (TARGET_ID,)
    ).fetchone()
    print()
    print("Final state:")
    print(f"  id: {final['id']}")
    print(f"  status: {final['status']}")
    print(f"  released_at: {final['released_at']}")
    print(f"  tags: {json.loads(final['tags'])}")

    conn.close()

if __name__ == "__main__":
    main()
