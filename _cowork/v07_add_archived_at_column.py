"""
Schema migration: add `archived_at` column to the `artifacts` table.

Aligns MediaVault's live SQLite schema with SPEC.md §6, which has long
declared:

    archived_at              TEXT,

immediately after `released_by`. The column was missing from the running
core/mediavault.sqlite database, which surfaced for the third time during
the Phase v5-3 / v5-4 live test as the museum-side export script's loud
diagnostic (v5.1 Patch 8) — "expected column archived_at, not present" —
fired correctly against MV. The right fix is to add the column rather
than keep working around its absence.

What this does:

  ALTER TABLE artifacts ADD COLUMN archived_at TEXT;

Existing rows get `archived_at = NULL`, which is correct: they are not
archived. SPEC §4.1 documents `archived_at` as "saved-but-hidden, always
reversible", so NULL is the natural "not archived" sentinel and matches
the convention used by `released_at`.

Scope is deliberately narrow. This script does NOT:
  - reconcile the live `status` CHECK constraint
    (`'inbox','vault','released','archived'`) against the SPEC's enum
    (`inbox|vault|released|deleted`). That is the broader Phase-2 enum
    drift cleanup, deferred.
  - touch any other column, index, or trigger.
  - modify museum-side code or schema.

Idempotent: if `archived_at` already exists on `artifacts`, the script
reports "no changes" and exits 0 without writing.

Run from project root:
    python _cowork/v07_add_archived_at_column.py
"""
from __future__ import annotations

import os
import sqlite3
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
DB = os.path.join(ROOT, "core", "mediavault.sqlite")


def _columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]


def main() -> int:
    if not os.path.exists(DB):
        print(f"ERROR: database not found at {DB}", file=sys.stderr)
        return 2

    conn = sqlite3.connect(DB)
    try:
        cols = _columns(conn, "artifacts")
        if "archived_at" in cols:
            print("no changes: artifacts.archived_at already present")
            return 0

        total_before = conn.execute(
            "SELECT COUNT(*) FROM artifacts"
        ).fetchone()[0]
        print(f"  artifacts rows before migration: {total_before}")

        print("  applying: ALTER TABLE artifacts ADD COLUMN archived_at TEXT")
        conn.execute("ALTER TABLE artifacts ADD COLUMN archived_at TEXT")
        conn.commit()

        cols_after = _columns(conn, "artifacts")
        if "archived_at" not in cols_after:
            print("ERROR: column did not appear after ALTER", file=sys.stderr)
            return 3

        total_after = conn.execute(
            "SELECT COUNT(*) FROM artifacts"
        ).fetchone()[0]
        null_after = conn.execute(
            "SELECT COUNT(*) FROM artifacts WHERE archived_at IS NULL"
        ).fetchone()[0]
        print(f"  artifacts rows after migration:  {total_after}")
        print(f"  rows with archived_at IS NULL:   {null_after}")

        if total_before != total_after:
            print("ERROR: row count changed across ALTER", file=sys.stderr)
            return 4
        if null_after != total_after:
            print(
                "ERROR: some rows have non-NULL archived_at after ALTER",
                file=sys.stderr,
            )
            return 5

        print("OK: artifacts.archived_at added; all existing rows are NULL")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
