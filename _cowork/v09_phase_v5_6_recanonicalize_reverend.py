"""
Phase v5-6 recanonicalize: bring MV-20260510-001 (Reverend) tags onto
the canonical museum vocabulary.

The v08 seeding script (2026-05-12) added a mix of canonical and
non-canonical tags. Following the canonical vocabulary recovery (see
weird-baby-museum/docs/CANONICAL_VOCABULARY.md), the non-canonical
namespaces `motif` and `theme` must be removed and replaced with their
canonical equivalents.

Idempotent: re-running is safe. Detects existing state and skips
already-applied changes. Mirrors v08's column-detection defensiveness.

Actions:
- Remove from artifact: motif:pink-hats, theme:resistance
- Add to artifact (canonical, tier 1/2/3): album:arkansas, song:reverend,
  people:hunter_root, format:digital, media:video, provenance:official,
  type:music-video, year:2023
- Keep on artifact: exhibit:hunter_root (routing tag), mood:snarky,
  mood:defiant, era:arkansas (all canonical)
- Keep on artifact (legacy MV-side, flagged for operator review):
  author:hunter_root, content_kind:official, platform:youtube,
  scope:hunter_root
- Remove from vocabulary table: motif:pink-hats, theme:resistance
- Add to vocabulary table: the eight canonical tags listed above
"""
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "core" / "mediavault.sqlite"
TARGET_ID = "MV-20260510-001"

# Tags to remove from the artifact AND from the vocabulary table.
REMOVE_TAGS = [
    "motif:pink-hats",
    "theme:resistance",
]

# Tags to add (slug, category, display_name). Canonical-vocabulary
# namespaces per weird-baby-museum/docs/CANONICAL_VOCABULARY.md.
ADD_TAGS = [
    ("album:arkansas",       "album",       "Album:Arkansas"),
    ("song:reverend",        "song",        "Song:Reverend"),
    ("people:hunter_root",   "people",      "People:Hunter Root"),
    ("format:digital",       "format",      "Format:Digital"),
    ("media:video",          "media",       "Media:Video"),
    ("provenance:official",  "provenance",  "Provenance:Official"),
    ("type:music-video",     "type",        "Type:Music Video"),
    ("year:2023",            "year",        "Year:2023"),
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
    print(f"Existing tags on {TARGET_ID}:")
    for t in existing_tags:
        print(f"  - {t}")
    print(f"Current status: {row['status']}")

    # Step 1: remove non-canonical tags from the artifact
    removed = [t for t in REMOVE_TAGS if t in existing_tags]
    merged_tags = [t for t in existing_tags if t not in REMOVE_TAGS]
    if removed:
        print(f"Removing from artifact: {removed}")
    else:
        print("No non-canonical tags to remove from artifact")

    # Step 2: add canonical tags to the artifact's tags JSON array
    added_to_artifact = []
    for slug, _, _ in ADD_TAGS:
        if slug not in merged_tags:
            merged_tags.append(slug)
            added_to_artifact.append(slug)

    if added_to_artifact:
        print(f"Adding to artifact: {added_to_artifact}")
    else:
        print("No new canonical tags to add to artifact")

    if removed or added_to_artifact:
        cur.execute(
            "UPDATE artifacts SET tags = ? WHERE id = ?",
            (json.dumps(merged_tags), TARGET_ID)
        )

    # Step 3: vocabulary table maintenance — inspect schema first,
    # then surgically remove and add rows.
    schema = cur.execute("PRAGMA table_info(tags)").fetchall()
    columns = [c["name"] for c in schema]
    print(f"tags table columns: {columns}")

    vocab_removed = []
    for slug in REMOVE_TAGS:
        existing = cur.execute(
            "SELECT slug FROM tags WHERE slug = ?", (slug,)
        ).fetchone()
        if existing:
            cur.execute("DELETE FROM tags WHERE slug = ?", (slug,))
            vocab_removed.append(slug)

    if vocab_removed:
        print(f"Removed from vocabulary: {vocab_removed}")
    else:
        print("No vocabulary rows to remove")

    vocab_added = []
    for slug, category, display_name in ADD_TAGS:
        existing = cur.execute(
            "SELECT slug FROM tags WHERE slug = ?", (slug,)
        ).fetchone()
        if existing:
            continue

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

    conn.commit()

    # Final verification
    final = cur.execute(
        "SELECT id, status, tags, released_at FROM artifacts WHERE id = ?",
        (TARGET_ID,)
    ).fetchone()
    final_tags = json.loads(final["tags"])
    print()
    print("Final state:")
    print(f"  id: {final['id']}")
    print(f"  status: {final['status']}")
    print(f"  released_at: {final['released_at']}")
    print(f"  tags:")
    for t in sorted(final_tags):
        print(f"    - {t}")

    # Sanity check
    for slug in REMOVE_TAGS:
        if slug in final_tags:
            print(f"WARN: {slug} still present on artifact after run")
    for slug, _, _ in ADD_TAGS:
        if slug not in final_tags:
            print(f"WARN: {slug} missing from artifact after run")

    conn.close()


if __name__ == "__main__":
    main()
