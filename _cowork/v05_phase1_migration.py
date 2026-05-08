"""
v05_phase1_migration.py
=======================
MediaVault v0.5 — Phase 1 schema migration.

Single transaction. If anything fails, ROLLBACK and stop.

Steps (per COWORK_BRIEF_v05.md §1):
  1.1a  Append author:<slug> to artifact tags JSON for non-junk author_name values.
  1.1b  INSERT vocabulary rows for novel author:* slugs (category='people').
  1.2   ADD tags.category, tags.is_exclusive; preserve rarity group; rebuild
        tags table to drop group_name; recreate tag indexes.
  1.3   Rebuild artifacts table to drop author_name, tags_permission,
        permission_contact, permission_evidence_path; recreate artifact indexes.
  1.5   Verify counts/data preservation/author pill placement; COMMIT or ROLLBACK.

The DB connection runs with foreign_keys = OFF during the rebuild (standard
SQLite rebuild-and-rename pattern), then PRAGMA foreign_key_check before COMMIT.
"""

from __future__ import annotations
import json
import re
import sqlite3
import sys
from pathlib import Path

BASE = Path(r"C:\AI\Platform\MediaVault")
DB_PATH = BASE / "core" / "mediavault.sqlite"
BAK_PATH = BASE / "core" / "mediavault.sqlite.bak_pre_v05_20260419_200638"

# Allow override for sandbox runs.
if len(sys.argv) > 1:
    DB_PATH = Path(sys.argv[1])
if len(sys.argv) > 2:
    BAK_PATH = Path(sys.argv[2])

JUNK_AUTHORS = {"", "(1) Video", "(2) Video"}


def slugify(value: str) -> str:
    """Same rule as ingest_engine.py: lowercase, spaces->_, non-alphanum stripped,
    collapse repeats, trim leading/trailing _."""
    s = value.strip().lower()
    s = re.sub(r"\s+", "_", s)
    s = re.sub(r"[^a-z0-9_]", "", s)
    s = re.sub(r"_+", "_", s)
    return s.strip("_")


def humanize_slug(slug: str) -> str:
    """slug -> Title Case display name (mirrors existing convention)."""
    return slug.replace("_", " ").title()


def main() -> int:
    if not DB_PATH.exists():
        print(f"FATAL: DB not found at {DB_PATH}", file=sys.stderr)
        return 2

    # --- pre-migration: gather verification baselines from backup -------------
    bak_conn = sqlite3.connect(str(BAK_PATH))
    bak_conn.row_factory = sqlite3.Row
    pre_artifact_count = bak_conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0]
    pre_tag_count = bak_conn.execute("SELECT COUNT(*) FROM tags").fetchone()[0]

    # Pick 3 fixed sample IDs across status/storage modes for post-rebuild
    # field-preservation check (same fields will be compared after rebuild).
    sample_ids = [
        "MV-20260419-001",       # released / vaulted
        "MV-HR-20260405-003",    # vault / vaulted
        "MV-HR-20260405-016",    # vault / referenced
    ]
    pre_samples = {}
    for aid in sample_ids:
        row = bak_conn.execute("SELECT * FROM artifacts WHERE id=?", (aid,)).fetchone()
        if row is None:
            print(f"FATAL: backup is missing sample id {aid}", file=sys.stderr)
            return 2
        pre_samples[aid] = dict(row)

    # Author migration source data (snapshot before any writes).
    author_rows = bak_conn.execute(
        "SELECT id, author_name, tags FROM artifacts "
        "WHERE author_name IS NOT NULL AND TRIM(author_name) <> ''"
    ).fetchall()
    bak_conn.close()

    # Build (artifact_id -> author_slug) map (skipping junk).
    artifact_author_slug: dict[str, str] = {}
    for r in author_rows:
        an = r["author_name"]
        if an in JUNK_AUTHORS:
            continue
        slug_body = slugify(an)
        if not slug_body:
            continue
        artifact_author_slug[r["id"]] = f"author:{slug_body}"

    # Distinct author slugs to ensure in vocabulary.
    distinct_author_slugs = sorted(set(artifact_author_slug.values()))
    print(f"[1.1a] {len(artifact_author_slug)} artifacts will gain an author:* pill")
    print(f"[1.1b] distinct author slugs: {distinct_author_slugs}")

    # --- open DB with FK off; begin transaction --------------------------------
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.isolation_level = None  # explicit transaction control
    cur = conn.cursor()
    # journal_mode is per-connection for non-WAL modes and is set here so the
    # migration runs without needing to create an on-disk -journal sidecar file.
    # Atomicity is still guaranteed by sqlite3 within this single transaction.
    cur.execute("PRAGMA journal_mode = MEMORY")
    cur.execute("PRAGMA foreign_keys = OFF")
    cur.execute("BEGIN")

    rollback_reason = None
    try:
        # === 1.1a: append author:<slug> to artifact tags ======================
        affected_count = 0
        for aid, author_slug in artifact_author_slug.items():
            row = cur.execute(
                "SELECT tags FROM artifacts WHERE id=?", (aid,)
            ).fetchone()
            if row is None:
                raise RuntimeError(f"artifact {aid} disappeared during migration")
            try:
                tags = json.loads(row["tags"]) if row["tags"] else []
            except json.JSONDecodeError as e:
                raise RuntimeError(f"artifact {aid} tags JSON malformed: {e}")
            if not isinstance(tags, list):
                raise RuntimeError(f"artifact {aid} tags not a list: {tags!r}")
            if author_slug in tags:
                continue  # already present, dedupe
            tags.append(author_slug)
            cur.execute(
                "UPDATE artifacts SET tags=?, updated_at=datetime('now') WHERE id=?",
                (json.dumps(tags), aid),
            )
            affected_count += 1
        print(f"[1.1a] appended author:* pill to {affected_count} artifacts")
        if affected_count != 16:
            # The brief expects exactly 16 (13 + 2 + 1). A different count means
            # the data shifted under us. Stop.
            raise RuntimeError(
                f"unexpected author migration row count: got {affected_count}, "
                f"brief expects 16"
            )

        # === 1.1b: INSERT vocabulary rows for novel author:* slugs ============
        author_vocab_inserted = 0
        for slug in distinct_author_slugs:
            existing = cur.execute(
                "SELECT 1 FROM tags WHERE slug=?", (slug,)
            ).fetchone()
            if existing:
                continue
            display = humanize_slug(slug.split("author:", 1)[1]) + " (author)"
            # tags table at this point still has v0.4 columns (group_name, no
            # category yet). Insert with group_name=NULL; category gets set in
            # Phase 2.5. is_exclusive will exist after step 1.2 ALTER and
            # default 0; we just record group_name=NULL here.
            cur.execute(
                "INSERT INTO tags(slug, display_name, description, group_name, "
                "is_proposed, usage_count) VALUES (?, ?, NULL, NULL, 0, 0)",
                (slug, display),
            )
            author_vocab_inserted += 1
        print(f"[1.1b] inserted {author_vocab_inserted} new author:* vocab rows")

        # === 1.2: tags table — add category, is_exclusive; rebuild ============
        cur.execute("ALTER TABLE tags ADD COLUMN category TEXT")
        cur.execute(
            "ALTER TABLE tags ADD COLUMN is_exclusive INTEGER NOT NULL DEFAULT 0"
        )
        cur.execute(
            "UPDATE tags SET category='rarity', is_exclusive=1 "
            "WHERE group_name='rarity'"
        )

        # Drop group_name via rebuild.
        cur.execute("DROP INDEX IF EXISTS idx_tags_group")
        cur.execute("DROP INDEX IF EXISTS idx_tags_proposed")
        cur.execute("""
            CREATE TABLE tags_new (
                slug            TEXT PRIMARY KEY,
                display_name    TEXT NOT NULL,
                description     TEXT,
                category        TEXT,
                is_exclusive    INTEGER NOT NULL DEFAULT 0,
                is_proposed     INTEGER NOT NULL DEFAULT 0,
                usage_count     INTEGER NOT NULL DEFAULT 0,
                created_at      TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        cur.execute("""
            INSERT INTO tags_new (slug, display_name, description, category,
                                  is_exclusive, is_proposed, usage_count, created_at)
            SELECT slug, display_name, description, category,
                   is_exclusive, is_proposed, usage_count, created_at
              FROM tags
        """)
        cur.execute("DROP TABLE tags")
        cur.execute("ALTER TABLE tags_new RENAME TO tags")
        cur.execute("CREATE INDEX idx_tags_category ON tags(category)")
        cur.execute("CREATE INDEX idx_tags_proposed ON tags(is_proposed)")

        # === 1.3: artifacts table — drop vestigial columns via rebuild =======
        # Drop existing artifact indexes (will be recreated below).
        for ix in (
            "idx_artifacts_status",
            "idx_artifacts_storage_mode",
            "idx_artifacts_post_date",
            "idx_artifacts_ingest_date",
            "idx_artifacts_parent",
            "idx_artifacts_source_url",
        ):
            cur.execute(f"DROP INDEX IF EXISTS {ix}")

        cur.execute("""
            CREATE TABLE artifacts_new (
                id                      TEXT PRIMARY KEY,
                source_url              TEXT,
                source_platform         TEXT,
                ingest_source           TEXT,
                ingest_date             DATE NOT NULL,
                storage_mode            TEXT NOT NULL DEFAULT 'vaulted'
                                            CHECK(storage_mode IN ('vaulted','referenced','url_only')),
                local_asset_path        TEXT,
                thumbnail_path          TEXT,
                link_status             TEXT CHECK(link_status IN ('live','dead','local-only')),
                parent_artifact_id      TEXT,
                media_type              TEXT,
                post_date               DATE,
                post_date_confidence    TEXT CHECK(post_date_confidence IN
                                            ('extracted','manual','estimated','unknown')),
                capture_date            DATE,
                status                  TEXT NOT NULL DEFAULT 'vault'
                                            CHECK(status IN ('inbox','vault','released','archived')),
                released_at             TEXT,
                released_by             TEXT,
                description_short       TEXT,
                description_long        TEXT,
                extracted_text          TEXT,
                tags                    TEXT NOT NULL DEFAULT '[]',
                confidence_flags        TEXT,
                notes                   TEXT,
                created_at              TEXT NOT NULL,
                updated_at              TEXT NOT NULL,
                FOREIGN KEY (parent_artifact_id) REFERENCES artifacts_new(id) ON DELETE CASCADE
            )
        """)
        cur.execute("""
            INSERT INTO artifacts_new (
                id, source_url, source_platform, ingest_source, ingest_date,
                storage_mode, local_asset_path, thumbnail_path, link_status,
                parent_artifact_id, media_type,
                post_date, post_date_confidence, capture_date,
                status, released_at, released_by,
                description_short, description_long, extracted_text,
                tags,
                confidence_flags, notes, created_at, updated_at
            )
            SELECT
                id, source_url, source_platform, ingest_source, ingest_date,
                storage_mode, local_asset_path, thumbnail_path, link_status,
                parent_artifact_id, media_type,
                post_date, post_date_confidence, capture_date,
                status, released_at, released_by,
                description_short, description_long, extracted_text,
                tags,
                confidence_flags, notes, created_at, updated_at
              FROM artifacts
        """)
        cur.execute("DROP TABLE artifacts")
        cur.execute("ALTER TABLE artifacts_new RENAME TO artifacts")
        cur.execute("CREATE INDEX idx_artifacts_status       ON artifacts(status)")
        cur.execute("CREATE INDEX idx_artifacts_storage_mode ON artifacts(storage_mode)")
        cur.execute("CREATE INDEX idx_artifacts_post_date    ON artifacts(post_date)")
        cur.execute("CREATE INDEX idx_artifacts_ingest_date  ON artifacts(ingest_date)")
        cur.execute("CREATE INDEX idx_artifacts_parent       ON artifacts(parent_artifact_id)")
        cur.execute("CREATE INDEX idx_artifacts_source_url   ON artifacts(source_url)")

        # === 1.5: verification ================================================
        # Row counts.
        post_artifacts = cur.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0]
        if post_artifacts != pre_artifact_count:
            raise RuntimeError(
                f"artifact count drift: was {pre_artifact_count}, now {post_artifacts}"
            )

        post_tags = cur.execute("SELECT COUNT(*) FROM tags").fetchone()[0]
        if post_tags < pre_tag_count or post_tags > pre_tag_count + 3:
            raise RuntimeError(
                f"tag count out of expected range: was {pre_tag_count}, "
                f"now {post_tags} (expected +0..+3)"
            )

        # Columns dropped from artifacts.
        col_names = {row["name"] for row in cur.execute("PRAGMA table_info(artifacts)")}
        for dropped in ("author_name", "tags_permission",
                        "permission_contact", "permission_evidence_path"):
            if dropped in col_names:
                raise RuntimeError(f"column {dropped} survived drop")

        # group_name dropped from tags.
        tag_cols = {row["name"] for row in cur.execute("PRAGMA table_info(tags)")}
        if "group_name" in tag_cols:
            raise RuntimeError("group_name survived drop on tags table")
        for must_have in ("category", "is_exclusive"):
            if must_have not in tag_cols:
                raise RuntimeError(f"tags.{must_have} missing post-migration")

        # Field preservation on 3 sample IDs (compare against pre_samples).
        preserved_fields = [
            "id", "source_url", "source_platform", "ingest_source", "ingest_date",
            "storage_mode", "local_asset_path", "thumbnail_path", "link_status",
            "parent_artifact_id", "media_type",
            "post_date", "post_date_confidence", "capture_date",
            "status", "released_at", "released_by",
            "description_short", "description_long", "extracted_text",
            "confidence_flags", "notes", "created_at",
        ]
        for aid, pre in pre_samples.items():
            post = dict(cur.execute("SELECT * FROM artifacts WHERE id=?", (aid,)).fetchone())
            for f in preserved_fields:
                if pre[f] != post[f]:
                    raise RuntimeError(
                        f"sample {aid} field {f} drifted: "
                        f"pre={pre[f]!r} post={post[f]!r}"
                    )
            # tags preserved (or extended with author:*, never lost).
            try:
                pre_tags = set(json.loads(pre["tags"]))
                post_tags = set(json.loads(post["tags"]))
            except json.JSONDecodeError as e:
                raise RuntimeError(f"sample {aid} tags JSON broken: {e}")
            if not pre_tags.issubset(post_tags):
                missing = pre_tags - post_tags
                raise RuntimeError(f"sample {aid} lost tags: {missing}")

        # Author pill placement.
        for aid, expected_slug in artifact_author_slug.items():
            tags = json.loads(
                cur.execute("SELECT tags FROM artifacts WHERE id=?", (aid,)).fetchone()["tags"]
            )
            if expected_slug not in tags:
                raise RuntimeError(
                    f"author migration miss: {aid} should contain {expected_slug}, "
                    f"got {tags}"
                )

        # No permission:* pills introduced (column dropped without migration).
        bad = cur.execute(
            "SELECT id FROM artifacts WHERE tags LIKE '%permission:%' LIMIT 1"
        ).fetchone()
        if bad:
            raise RuntimeError(f"permission:* pill present on {bad['id']}")

        # FK integrity check.
        fk_violations = cur.execute("PRAGMA foreign_key_check").fetchall()
        if fk_violations:
            raise RuntimeError(f"foreign_key_check failures: {fk_violations}")

        # === COMMIT ===========================================================
        cur.execute("COMMIT")
        cur.execute("PRAGMA foreign_keys = ON")
        print(f"[1.5] verification passed; committed.")
        print(f"  artifacts: {post_artifacts} (was {pre_artifact_count})")
        print(f"  tags:      {post_tags} (was {pre_tag_count}; +{post_tags - pre_tag_count} author rows)")
        return 0

    except Exception as e:
        rollback_reason = str(e)
        cur.execute("ROLLBACK")
        cur.execute("PRAGMA foreign_keys = ON")
        print(f"[FATAL] phase 1 rolled back: {e}", file=sys.stderr)
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
