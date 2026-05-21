"""
Phase 2.5 — drop the four registry-era columns from ``tags`` and promote
``slug`` to ``PRIMARY KEY``.

Authorization: §5.2 of
``DATA_ARCHITECTURE_SPEC_v2.1-target.md`` (museum repo) + §4.4.G of
``docs/SOURCE_OF_TRUTH_REFACTOR_SCOPING_BRIEF-20260519-220000.md``
(museum repo). Closes §12 Criterion 8 of the source-of-truth refactor.

Pre-state (post-Phase-2.4, 8 columns, cache reconciled with
``artifacts.tags``):

    slug         TEXT    NOT NULL,
    display_name TEXT,
    description  TEXT,
    category     TEXT,
    is_exclusive INTEGER NOT NULL DEFAULT 0,
    is_proposed  INTEGER NOT NULL DEFAULT 0,
    usage_count  INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT

Post-state (4 columns; slug now PRIMARY KEY):

    slug         TEXT    PRIMARY KEY,
    display_name TEXT,
    usage_count  INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT

Five operations inside ONE transaction (``BEGIN IMMEDIATE`` … ``COMMIT``):

  1. DROP the four registry-era indexes
     (``idx_tags_slug_category``, ``idx_tags_slug_when_null_cat``,
     ``idx_tags_category``, ``idx_tags_proposed``). Must precede the
     column drops — SQLite refuses to ``DROP COLUMN`` while an index
     references it.
  2. ``ALTER TABLE tags DROP COLUMN`` x4 (``description``, ``category``,
     ``is_proposed``, ``is_exclusive``). Requires SQLite >= 3.35
     (verified at run start).
  3. CREATE-INSERT-DROP-RENAME a fresh ``tags_new`` with
     ``slug TEXT PRIMARY KEY`` and the three remaining columns; copy the
     69 rows over; drop the old table; rename. SQLite cannot add a
     PRIMARY KEY constraint via ``ALTER TABLE``, so this pattern is the
     standard fix.
  4. Verify post-state in-script: row count 69, ``SUM(usage_count)``
     453, distinct slugs 69, ``EXPLAIN QUERY PLAN`` for a slug lookup
     uses the implicit PK index.
  5. ``COMMIT`` (one transaction throughout).

The script does **not** write ``artifacts.tags`` — the §4.5.1(b)
single-writer rule for ``artifacts.tags`` is unaffected (re-verified
post-migration via ``tools/check_single_tag_writer.py``).

Idempotency:

- Pre-state guard at top of ``main()``: if the live ``tags`` table does
  not match the 8-column pre-state (e.g. the migration already ran),
  the script reports the observed shape and exits non-zero without
  touching anything.
- The five operations are not individually idempotent against an
  already-migrated DB — re-running on a 4-column ``tags`` would error
  at step 2's first ``DROP COLUMN``. The pre-state guard catches this
  before any write.

Workflow (the Cowork-on-Windows FUSE mount workaround, documented in
``docs/PHASE2_4_RUN_REPORT-20260520-171029.md`` §2.4):

    1. cp core/mediavault.sqlite /tmp/mediavault.work.sqlite
    2. python _cowork/v13_phase25_demote_tags_table.py \\
           --db /tmp/mediavault.work.sqlite
    3. verify the migrated /tmp DB
    4. cp /tmp/mediavault.work.sqlite core/mediavault.sqlite
    5. SHA-256 byte-verify the swap

The default DB path (no flag) runs in-place against MV's
``core/mediavault.sqlite`` — not recommended from inside a Cowork
session because the FUSE mount cannot complete SQLite's rollback-
journal delete cleanly mid-commit.

Run from project root:

    python _cowork/v13_phase25_demote_tags_table.py
    python _cowork/v13_phase25_demote_tags_table.py --db /tmp/copy.sqlite
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
DEFAULT_DB = os.path.join(ROOT, "core", "mediavault.sqlite")

# Pre-state expectations. The script bails before any write if any of
# these diverge — matches the brief's audit-on-entry numbers and the
# Phase 2.4 §1.2 ground truth.
EXPECTED_PRE_COLUMNS = [
    ("slug",         "TEXT",    1, None, 0),
    ("display_name", "TEXT",    0, None, 0),
    ("description",  "TEXT",    0, None, 0),
    ("category",     "TEXT",    0, None, 0),
    ("is_exclusive", "INTEGER", 1, "0",  0),
    ("is_proposed",  "INTEGER", 1, "0",  0),
    ("usage_count",  "INTEGER", 1, "0",  0),
    ("created_at",   "TEXT",    0, None, 0),
]
EXPECTED_PRE_INDEXES = {
    "idx_tags_slug_category",
    "idx_tags_slug_when_null_cat",
    "idx_tags_category",
    "idx_tags_proposed",
}
EXPECTED_ROWCOUNT = 69
EXPECTED_USAGE_SUM = 453

INDEXES_TO_DROP = [
    "idx_tags_slug_category",
    "idx_tags_slug_when_null_cat",
    "idx_tags_category",
    "idx_tags_proposed",
]
COLUMNS_TO_DROP = [
    # Order chosen to match the brief; SQLite handles any order once the
    # indexes are gone.
    "description",
    "category",
    "is_proposed",
    "is_exclusive",
]


def _table_columns(conn: sqlite3.Connection, table: str) -> list[tuple]:
    """Return PRAGMA table_info rows, dropping the cid column."""
    return [
        (r[1], r[2], r[3], r[4], r[5])
        for r in conn.execute(f"PRAGMA table_info({table})")
    ]


def _indexes(conn: sqlite3.Connection, table: str) -> set[str]:
    return {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='index' AND tbl_name=? "
            "AND name NOT LIKE 'sqlite_autoindex_%'",
            (table,),
        )
    }


def _pk_index_name(conn: sqlite3.Connection, table: str) -> str | None:
    """Return the implicit PK index name for a table (sqlite_autoindex_*)."""
    for (name,) in conn.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='index' AND tbl_name=? AND name LIKE 'sqlite_autoindex_%'",
        (table,),
    ):
        return name
    return None


def _check_prestate(conn: sqlite3.Connection) -> None:
    """Raise ``SystemExit`` (non-zero) if the DB is not in the expected
    pre-Phase-2.5 state. Verbose on mismatch so the operator can see what
    actually shipped."""
    # SQLite version
    libver = tuple(int(x) for x in sqlite3.sqlite_version.split("."))
    if libver < (3, 35, 0):
        print(
            f"ERROR: sqlite_version {sqlite3.sqlite_version} < 3.35.0; "
            "ALTER TABLE DROP COLUMN unsupported. STOP.",
            file=sys.stderr,
        )
        raise SystemExit(2)

    cols = _table_columns(conn, "tags")
    if cols != EXPECTED_PRE_COLUMNS:
        print("ERROR: tags table does NOT match expected pre-state shape.",
              file=sys.stderr)
        print("  expected:", EXPECTED_PRE_COLUMNS, file=sys.stderr)
        print("  observed:", cols, file=sys.stderr)
        raise SystemExit(3)

    indexes = _indexes(conn, "tags")
    if indexes != EXPECTED_PRE_INDEXES:
        print("ERROR: tags table does NOT match expected pre-state indexes.",
              file=sys.stderr)
        print("  expected:", sorted(EXPECTED_PRE_INDEXES), file=sys.stderr)
        print("  observed:", sorted(indexes), file=sys.stderr)
        raise SystemExit(4)

    rowcount = conn.execute("SELECT COUNT(*) FROM tags").fetchone()[0]
    usage_sum = conn.execute(
        "SELECT COALESCE(SUM(usage_count),0) FROM tags"
    ).fetchone()[0]
    if rowcount != EXPECTED_ROWCOUNT:
        print(f"ERROR: tags rowcount={rowcount}, expected "
              f"{EXPECTED_ROWCOUNT}. STOP.", file=sys.stderr)
        raise SystemExit(5)
    if usage_sum != EXPECTED_USAGE_SUM:
        print(f"ERROR: SUM(usage_count)={usage_sum}, expected "
              f"{EXPECTED_USAGE_SUM}. STOP.", file=sys.stderr)
        raise SystemExit(6)


def _live_distinct_slugs_in_artifacts(conn: sqlite3.Connection) -> set[str]:
    """Distinct slugs in artifacts.tags JSON arrays (the parity reference)."""
    out: set[str] = set()
    for (raw,) in conn.execute(
        "SELECT tags FROM artifacts WHERE tags IS NOT NULL AND tags != ''"
    ):
        try:
            arr = json.loads(raw)
        except Exception:
            continue
        if isinstance(arr, list):
            for s in arr:
                if isinstance(s, str) and s.strip():
                    out.add(s.strip())
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Phase 2.5: demote the tags table to a 4-column cache and "
            "promote slug to PRIMARY KEY."
        )
    )
    parser.add_argument(
        "--db", default=DEFAULT_DB,
        help="SQLite database path (default: %(default)s).",
    )
    args = parser.parse_args(argv)
    db = args.db
    if not os.path.exists(db):
        print(f"ERROR: database not found at {db}", file=sys.stderr)
        return 2
    print(f"operating on: {db}")
    print(f"sqlite_version (library): {sqlite3.sqlite_version}")

    conn = sqlite3.connect(db)
    # Foreign keys are not used on `tags`, but turn them off explicitly
    # for the CREATE-INSERT-DROP-RENAME step — the SQLite docs recommend
    # this whenever a table is recreated under a transaction, even if no
    # FK references it.
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        _check_prestate(conn)
        print("pre-state guard: OK (8 columns, 4 obsolete indexes, "
              f"rowcount=69, SUM(usage_count)=453)")

        # Snapshot the slug set so we can verify post-write the same 69
        # slugs come through unchanged.
        pre_slugs = {r[0] for r in conn.execute("SELECT slug FROM tags")}
        pre_artifacts = _live_distinct_slugs_in_artifacts(conn)
        assert pre_slugs == pre_artifacts, (
            "pre-write cache/artifacts parity broken — STOP "
            f"(only-in-cache={sorted(pre_slugs - pre_artifacts)[:5]}, "
            f"only-in-artifacts={sorted(pre_artifacts - pre_slugs)[:5]})"
        )

        # BEGIN IMMEDIATE — acquire the reserved lock up front, so a
        # concurrent writer fails fast rather than livelocking against
        # a deferred upgrade. Same shape v12_phase24 uses.
        conn.execute("BEGIN IMMEDIATE")

        # ----------------------------------------------------------------
        # Step 1: drop the four registry-era indexes.
        # ----------------------------------------------------------------
        print()
        print("=== Step 1: DROP obsolete indexes ===")
        for ix in INDEXES_TO_DROP:
            conn.execute(f"DROP INDEX IF EXISTS {ix}")
            print(f"  DROP INDEX IF EXISTS {ix}  -> done")

        # ----------------------------------------------------------------
        # Step 2: drop the four registry-era columns.
        # ----------------------------------------------------------------
        print()
        print("=== Step 2: ALTER TABLE tags DROP COLUMN (x4) ===")
        for col in COLUMNS_TO_DROP:
            conn.execute(f"ALTER TABLE tags DROP COLUMN {col}")
            print(f"  ALTER TABLE tags DROP COLUMN {col}  -> done")

        # ----------------------------------------------------------------
        # Step 3: add slug PRIMARY KEY via CREATE-INSERT-DROP-RENAME.
        #   SQLite cannot add a PRIMARY KEY constraint with ALTER TABLE.
        #   The four-step pattern is the SQLite docs' recommendation for
        #   adding constraints to an existing table.
        # ----------------------------------------------------------------
        print()
        print("=== Step 3: CREATE-INSERT-DROP-RENAME for slug PRIMARY KEY ===")
        conn.execute(
            """
            CREATE TABLE tags_new (
                slug         TEXT    PRIMARY KEY,
                display_name TEXT,
                usage_count  INTEGER NOT NULL DEFAULT 0,
                created_at   TEXT
            )
            """
        )
        print("  CREATE TABLE tags_new (slug PRIMARY KEY, ...)  -> done")
        cur = conn.execute(
            "INSERT INTO tags_new (slug, display_name, usage_count, created_at) "
            "SELECT slug, display_name, usage_count, created_at FROM tags"
        )
        copied = cur.rowcount
        print(f"  INSERT INTO tags_new SELECT FROM tags  -> {copied} rows copied")
        conn.execute("DROP TABLE tags")
        print("  DROP TABLE tags  -> done")
        conn.execute("ALTER TABLE tags_new RENAME TO tags")
        print("  ALTER TABLE tags_new RENAME TO tags  -> done")

        # ----------------------------------------------------------------
        # Step 4: verify post-state. All checks run inside the open
        # transaction so a failure rolls everything back.
        # ----------------------------------------------------------------
        print()
        print("=== Step 4: verify post-state ===")

        post_cols = _table_columns(conn, "tags")
        expected_post = [
            ("slug",         "TEXT",    0, None, 1),   # pk=1
            ("display_name", "TEXT",    0, None, 0),
            ("usage_count",  "INTEGER", 1, "0",  0),
            ("created_at",   "TEXT",    0, None, 0),
        ]
        if post_cols != expected_post:
            print("FAIL: post-state column shape mismatch.", file=sys.stderr)
            print("  expected:", expected_post, file=sys.stderr)
            print("  observed:", post_cols, file=sys.stderr)
            raise RuntimeError("post-state column shape mismatch")
        print(f"  table_info: {post_cols}  -> matches 4-col target")

        post_rows = conn.execute("SELECT COUNT(*) FROM tags").fetchone()[0]
        post_distinct = conn.execute(
            "SELECT COUNT(DISTINCT slug) FROM tags"
        ).fetchone()[0]
        post_usage_sum = conn.execute(
            "SELECT COALESCE(SUM(usage_count),0) FROM tags"
        ).fetchone()[0]
        post_slugs = {r[0] for r in conn.execute("SELECT slug FROM tags")}
        print(f"  rowcount         : {post_rows}  (expect 69)")
        print(f"  distinct slugs   : {post_distinct}  (expect 69; PK enforces)")
        print(f"  SUM(usage_count) : {post_usage_sum}  (expect 453)")
        print(f"  slugs preserved  : {post_slugs == pre_slugs}")
        if (post_rows, post_distinct, post_usage_sum) != (
            EXPECTED_ROWCOUNT, EXPECTED_ROWCOUNT, EXPECTED_USAGE_SUM
        ):
            raise RuntimeError("post-state counts mismatch")
        if post_slugs != pre_slugs:
            raise RuntimeError("post-state slug set mismatch")

        # Indexes on the new table — only the implicit PK index.
        post_user_indexes = _indexes(conn, "tags")
        if post_user_indexes:
            print(f"  WARNING: unexpected user indexes on tags: {post_user_indexes}")
            raise RuntimeError("unexpected user indexes after migration")
        pk_ix = _pk_index_name(conn, "tags")
        print(f"  implicit PK index: {pk_ix}")
        if not pk_ix:
            raise RuntimeError("no implicit PK index on tags after migration")

        # EXPLAIN QUERY PLAN for a representative slug lookup — confirm
        # it uses the PK index, not a table scan.
        sample_slug = sorted(post_slugs)[0]
        plan = list(conn.execute(
            "EXPLAIN QUERY PLAN SELECT slug, usage_count FROM tags WHERE slug=?",
            (sample_slug,),
        ))
        print(f"  EXPLAIN QUERY PLAN (slug={sample_slug!r}):")
        for row in plan:
            print(f"    {row}")
        plan_text = " | ".join(str(r) for r in plan)
        uses_pk = ("USING INDEX sqlite_autoindex_tags_" in plan_text
                   or "USING COVERING INDEX sqlite_autoindex_tags_" in plan_text
                   or "USING INTEGER PRIMARY KEY" in plan_text)
        if not uses_pk:
            raise RuntimeError(
                f"slug lookup does not use the PK index; plan: {plan_text}"
            )
        print("  slug lookup uses PK index: yes")

        # ----------------------------------------------------------------
        # Step 5: COMMIT.
        # ----------------------------------------------------------------
        conn.commit()
        print()
        print("=== Step 5: COMMIT  -> done ===")
        print()
        print("Phase 2.5 migration complete.")
        return 0
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
