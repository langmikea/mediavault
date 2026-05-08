"""
v0.6 Item 3 — DB schema migration.

Goal: relax `tags` uniqueness from "slug is globally unique" (current PK)
to "slug is unique *within* a category" (composite uniqueness).

Why: rename `author:hunter_root` -> `hunter_root` in category `people` is
currently rejected because `hunter_root` already exists in category
`bands`. After this migration both rows can coexist.

Strategy (SQLite has no `ALTER TABLE DROP PRIMARY KEY`):
  1. Backup live DB.
  2. Verify no cross-category slug collisions.
  3. Rebuild table:
       - Drop the slug PK.
       - Make slug NOT NULL (still required).
       - Keep category nullable (matches v0.5 contract).
       - Add UNIQUE(slug, category) — composite uniqueness.
       - Add a partial unique index for the "category IS NULL" slot so
         we can't store two `(slug, NULL)` rows.
  4. Recreate every existing index (idx_tags_category, idx_tags_proposed).
  5. Verify row count, sample rows, and that the constraint behaves.

Idempotent guard: aborts if it detects the constraint already exists.

Run from project root:
    python _cowork/v06_phase3_migration.py
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import sys
from datetime import datetime

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
DB = os.path.join(ROOT, "core", "mediavault.sqlite")


def _backup() -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = os.path.join(ROOT, "core", f"mediavault.sqlite.bak_pre_v06_{ts}")
    shutil.copy2(DB, dst)
    print(f"  backed up to {dst}")
    return dst


def _has_constraint(conn: sqlite3.Connection) -> bool:
    """True if the new composite-unique index already exists."""
    row = conn.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='index' AND name='idx_tags_slug_category'"
    ).fetchone()
    return row is not None


def _check_collisions(conn: sqlite3.Connection) -> int:
    rows = conn.execute(
        "SELECT slug, COUNT(DISTINCT IFNULL(category,'')) AS cats "
        "FROM tags GROUP BY slug HAVING cats > 1"
    ).fetchall()
    if rows:
        print("  ERROR: cross-category slug collisions exist:")
        for r in rows:
            print(f"    {r[0]} (categories: {r[1]})")
    return len(rows)


def _table_sql(conn: sqlite3.Connection, name: str) -> str | None:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row[0] if row else None


def _index_sqls(conn: sqlite3.Connection, table: str) -> list[tuple[str, str]]:
    return list(conn.execute(
        "SELECT name, sql FROM sqlite_master "
        "WHERE type='index' AND tbl_name=? AND sql IS NOT NULL",
        (table,),
    ))


def main() -> int:
    if not os.path.exists(DB):
        print(f"DB not found: {DB}", file=sys.stderr)
        return 2

    # 1. Backup.
    print("STEP 1 — backup")
    _backup()

    # 2 + 3 + 4 — single transaction.
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("PRAGMA journal_mode = MEMORY")

    print("STEP 2 — pre-migration checks")
    cols_before = [c["name"] for c in conn.execute("PRAGMA table_info(tags)")]
    print(f"  tags cols: {cols_before}")
    n_before = conn.execute("SELECT COUNT(*) FROM tags").fetchone()[0]
    print(f"  row count: {n_before}")
    print(f"  pre-migration table sql:")
    for line in (_table_sql(conn, "tags") or "").splitlines():
        print(f"    {line.strip()}")

    if _has_constraint(conn):
        print("  composite unique index already present — migration is a no-op.")
        conn.close()
        return 0

    n_collide = _check_collisions(conn)
    if n_collide:
        conn.close()
        print("ABORT: resolve the collisions above and re-run.")
        return 3
    print("  no cross-category collisions ✓")

    print("STEP 3 — rebuild tags table")
    try:
        conn.execute("BEGIN")
        # Capture indexes for later reapply (only the user-defined ones; the
        # PK-derived ones disappear with the table.)
        existing_indexes = [
            (n, sql) for (n, sql) in _index_sqls(conn, "tags")
            if not n.startswith("sqlite_autoindex_")
        ]
        print(f"  user-defined indexes to recreate: "
              f"{[n for n, _ in existing_indexes]}")

        conn.execute("""
            CREATE TABLE tags_new (
                slug         TEXT    NOT NULL,
                display_name TEXT,
                description  TEXT,
                category     TEXT,
                is_exclusive INTEGER NOT NULL DEFAULT 0,
                is_proposed  INTEGER NOT NULL DEFAULT 0,
                usage_count  INTEGER NOT NULL DEFAULT 0,
                created_at   TEXT
            )
        """)
        conn.execute("""
            INSERT INTO tags_new (
                slug, display_name, description, category,
                is_exclusive, is_proposed, usage_count, created_at
            )
            SELECT slug, display_name, description, category,
                   COALESCE(is_exclusive, 0),
                   COALESCE(is_proposed, 0),
                   COALESCE(usage_count, 0),
                   created_at
            FROM tags
        """)
        n_copied = conn.execute("SELECT COUNT(*) FROM tags_new").fetchone()[0]
        if n_copied != n_before:
            raise RuntimeError(f"row drift: {n_before} -> {n_copied}")
        print(f"  copied {n_copied} rows into tags_new")

        conn.execute("DROP TABLE tags")
        conn.execute("ALTER TABLE tags_new RENAME TO tags")

        # Composite uniqueness: (slug, category). UNIQUE in SQLite treats NULLs
        # as distinct, so we add a separate partial index to forbid two
        # (slug, NULL) rows.
        conn.execute(
            "CREATE UNIQUE INDEX idx_tags_slug_category ON tags(slug, category)"
        )
        conn.execute(
            "CREATE UNIQUE INDEX idx_tags_slug_when_null_cat "
            "ON tags(slug) WHERE category IS NULL"
        )
        print("  added UNIQUE(slug, category) and the null-category partial index")

        # Recreate the v0.5 secondary indexes if they were present.
        wanted_secondary = {
            "idx_tags_category":
                "CREATE INDEX IF NOT EXISTS idx_tags_category ON tags(category)",
            "idx_tags_proposed":
                "CREATE INDEX IF NOT EXISTS idx_tags_proposed ON tags(is_proposed)",
        }
        for name, sql in wanted_secondary.items():
            conn.execute(sql)
            print(f"  ensured index: {name}")

        # 5. Verification before COMMIT.
        print("STEP 4 — verification")
        cols_after = [c["name"] for c in conn.execute("PRAGMA table_info(tags)")]
        if cols_after != cols_before:
            raise RuntimeError(
                f"column drift: {cols_before} -> {cols_after}"
            )
        print(f"  tags cols unchanged: {cols_after}")

        n_after = conn.execute("SELECT COUNT(*) FROM tags").fetchone()[0]
        if n_after != n_before:
            raise RuntimeError(f"row drift: {n_before} -> {n_after}")
        print(f"  row count unchanged: {n_after}")

        # Constraint behavior: try to insert a same-category dup; expect failure.
        sample = conn.execute(
            "SELECT slug, category FROM tags WHERE category IS NOT NULL LIMIT 1"
        ).fetchone()
        if sample:
            try:
                conn.execute(
                    "INSERT INTO tags(slug, display_name, category) VALUES(?,?,?)",
                    (sample["slug"], "dup-test", sample["category"]),
                )
                raise RuntimeError(
                    "UNIQUE(slug, category) DID NOT REJECT the duplicate insert"
                )
            except sqlite3.IntegrityError:
                pass
            print(f"  ✓ rejected dup ({sample['slug']!r}, {sample['category']!r})")
        else:
            print("  (no non-null-category sample available for dup test)")

        # And the cross-category insert should succeed.
        if sample:
            other_cat = "v06_test_cross_cat_check"
            conn.execute(
                "INSERT INTO tags(slug, display_name, category) VALUES(?,?,?)",
                (sample["slug"], "cross-cat-test", other_cat),
            )
            n_with = conn.execute(
                "SELECT COUNT(*) FROM tags WHERE slug=?", (sample["slug"],)
            ).fetchone()[0]
            print(f"  ✓ accepted cross-category dup; {sample['slug']!r} now in "
                  f"{n_with} categories")
            conn.execute(
                "DELETE FROM tags WHERE slug=? AND category=?",
                (sample["slug"], other_cat),
            )
            print(f"  cleaned cross-category test row")

        # Foreign key check (artifacts.parent_artifact_id -> artifacts.id is the
        # only FK in the schema, but check is cheap).
        fkv = conn.execute("PRAGMA foreign_key_check").fetchall()
        if fkv:
            raise RuntimeError(f"foreign_key_check produced violations: {fkv}")
        print("  PRAGMA foreign_key_check clean ✓")

        conn.commit()
        print("COMMIT ✓")
    except Exception as e:
        conn.rollback()
        print(f"ROLLBACK: {type(e).__name__}: {e}")
        conn.close()
        return 1

    # Post-commit summary.
    print("\nPost-commit:")
    for line in (_table_sql(conn, "tags") or "").splitlines():
        print(f"  {line.strip()}")
    print(f"  indexes:")
    for n, sql in _index_sqls(conn, "tags"):
        print(f"    {n}: {sql}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
