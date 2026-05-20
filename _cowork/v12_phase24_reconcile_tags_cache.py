"""
Phase 2.4 — reconcile the demoted `tags` cache with live `artifacts.tags`.

Authorization: §4.4.F + Phase 2.4 of
``docs/SOURCE_OF_TRUTH_REFACTOR_SCOPING_BRIEF-20260519-220000.md`` (museum
repo), as renegotiated in §6.1 of
``docs/PHASE2A_RUN_REPORT-20260520-162150.md``. Operator decision
(2026-05-20): Option B — drop residue + recompute usage_count from
``artifacts.tags``. End state: every row in ``tags`` corresponds to a
slug actually present in some artifact, and ``usage_count`` matches the
real count.

Scope is deliberately narrow. This script does NOT:
  - touch the schema. Phase 2.5 (the §5.2 ``DROP COLUMN`` operation that
    closes Criterion 8) is a separate session and runs against an
    operator-reviewed migration script.
  - write ``artifacts.tags``. Every operation here targets the demoted
    ``tags`` cache only, so the §4.5.1(b) single-writer rule for
    ``artifacts.tags`` is unaffected (verified independently after
    the run via ``tools/check_single_tag_writer.py``).
  - mutate ``is_proposed`` or ``category`` on the 15 in-both rows.
    Those columns retire in Phase 2.5; leaving them as-is is correct.

The three operations run inside ONE transaction:

  1. DELETE FROM tags WHERE slug NOT IN (live slugs from artifacts.tags)
     — removes the bare-slug residue.
  2. INSERT new rows for each live slug not already cached. ``usage_count``
     starts at 0; step 3 sets the real value.
  3. UPDATE tags SET usage_count = (recomputed count from artifacts.tags)
     using the same ``json_each`` pattern that ``handle_tag_merge`` and
     ``handle_tag_bulk_delete`` use in ``core/imgserver.py`` (lines 1581
     and 1640 respectively — see comments around 1577-1583 documenting it
     as "the §3.2 backstop"). This adapts that pattern for a standalone
     full-table recompute rather than rewriting from scratch.

Idempotent: a second run finds no slugs to delete (cache already clean),
no slugs to insert (all live slugs already present), and the UPDATE just
recomputes to the same values. Safe to re-run.

Run from project root:
    python _cowork/v12_phase24_reconcile_tags_cache.py
    python _cowork/v12_phase24_reconcile_tags_cache.py --db /path/to/copy.sqlite

The optional ``--db`` flag operates against an alternate database path —
used on the 2026-05-20 run to work around the Cowork-on-Windows FUSE
mount's poor support for SQLite commit semantics (the rollback-journal
delete fails with disk I/O error mid-commit, identical class of issue
to the git lock-file workaround PHASE2A §3 documented). Workflow:

    1. cp core/mediavault.sqlite /tmp/mediavault.work.sqlite
    2. python _cowork/v12_phase24_reconcile_tags_cache.py \\
           --db /tmp/mediavault.work.sqlite
    3. cp /tmp/mediavault.work.sqlite core/mediavault.sqlite

The default DB path (no flag) runs in-place against MV.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
DEFAULT_DB = os.path.join(ROOT, "core", "mediavault.sqlite")


def _live_slugs(conn: sqlite3.Connection) -> set:
    """Distinct slugs that appear in any artifact's ``tags`` JSON array.

    Computed in Python (not SQL) so the run-time observation matches the
    run report's audit-on-entry numbers exactly. ``json_each`` over
    ``artifacts.tags`` is used in step 3 for the usage_count recompute
    where SQL is the natural shape.
    """
    out = set()
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
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
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

    conn = sqlite3.connect(db)
    try:
        # Snapshot the pre-write state for the script's own log line.
        pre_rows = conn.execute("SELECT COUNT(*) FROM tags").fetchone()[0]
        pre_distinct = conn.execute(
            "SELECT COUNT(DISTINCT slug) FROM tags"
        ).fetchone()[0]
        cache_slugs_pre = {r[0] for r in conn.execute("SELECT slug FROM tags")}

        live = _live_slugs(conn)
        cache_only = cache_slugs_pre - live
        live_only = live - cache_slugs_pre
        in_both = cache_slugs_pre & live

        print("=== Phase 2.4 reconciliation - pre-write state ===")
        print(f"  tags rows                  : {pre_rows}")
        print(f"  tags distinct slugs        : {pre_distinct}")
        print(f"  artifacts.tags distinct    : {len(live)}")
        print(f"  in both (cache+live)       : {len(in_both)}")
        print(f"  cache-only (residue)       : {len(cache_only)}  (distinct slugs)")
        print(f"  live-only (uncached)       : {len(live_only)}")
        print()

        # One transaction. BEGIN IMMEDIATE acquires the reserved lock up
        # front so a concurrent writer fails fast rather than livelocking
        # against a deferred upgrade.
        conn.execute("BEGIN IMMEDIATE")

        # Step 1: drop the bare-slug residue. Use parameter binding rather
        # than embedding the live-slug set as a literal subquery - the
        # set is closed-form here and a parameterized IN is the readable
        # form. SQLite has a 999-parameter default ceiling; current live
        # is 69, so we are well under.
        if live:
            placeholders = ",".join("?" * len(live))
            cur = conn.execute(
                f"DELETE FROM tags WHERE slug NOT IN ({placeholders})",
                tuple(sorted(live)),
            )
        else:
            cur = conn.execute("DELETE FROM tags")
        deleted = cur.rowcount
        print(f"step 1: DELETE FROM tags WHERE slug NOT IN (live)  -> {deleted} rows deleted")

        # Step 2: insert one row per live-only slug. usage_count starts at 0;
        # step 3 recomputes the real value for every row in tags.
        now = (
            conn.execute("SELECT strftime('%Y-%m-%dT%H:%M:%fZ','now')")
            .fetchone()[0]
        )
        inserted = 0
        for s in sorted(live_only):
            conn.execute(
                "INSERT INTO tags(slug, usage_count, created_at) "
                "VALUES (?, 0, ?)",
                (s, now),
            )
            inserted += 1
        print(f"step 2: INSERT one row per live-only slug          -> {inserted} rows inserted")

        # Step 3: full-table usage_count recompute. Same SQL as
        # ``handle_tag_merge`` (imgserver.py:1581) and
        # ``handle_tag_bulk_delete`` (imgserver.py:1640). The pattern was
        # designed for exactly this shape: every tags row's usage_count
        # equals the number of artifacts whose tags array contains the
        # slug.
        cur = conn.execute(
            "UPDATE tags SET usage_count = ("
            "  SELECT COUNT(*) FROM artifacts a, json_each(a.tags) j "
            "  WHERE j.value = tags.slug)"
        )
        updated = cur.rowcount
        print(f"step 3: UPDATE tags SET usage_count = recompute(*) -> {updated} rows updated")

        conn.commit()

        # Post-commit audit. Same shape as pre-write, run after the
        # transaction so the numbers reflect on-disk state.
        post_rows = conn.execute("SELECT COUNT(*) FROM tags").fetchone()[0]
        post_distinct = conn.execute(
            "SELECT COUNT(DISTINCT slug) FROM tags"
        ).fetchone()[0]
        live_post = _live_slugs(conn)
        cache_post = {r[0] for r in conn.execute("SELECT slug FROM tags")}
        usage_sum = conn.execute("SELECT COALESCE(SUM(usage_count),0) FROM tags").fetchone()[0]
        # Real usage total: sum of len(tags) across all artifacts that
        # have a non-empty tags array. usage_count totals must match.
        real_total = 0
        for (raw,) in conn.execute(
            "SELECT tags FROM artifacts WHERE tags IS NOT NULL AND tags != ''"
        ):
            try:
                arr = json.loads(raw)
            except Exception:
                continue
            if isinstance(arr, list):
                real_total += sum(
                    1 for s in arr if isinstance(s, str) and s.strip()
                )

        print()
        print("=== Phase 2.4 reconciliation - post-write state ===")
        print(f"  tags rows                  : {post_rows}")
        print(f"  tags distinct slugs        : {post_distinct}")
        print(f"  artifacts.tags distinct    : {len(live_post)}")
        print(f"  cache == live              : {cache_post == live_post}")
        print(f"  SUM(usage_count) on tags   : {usage_sum}")
        print(f"  real total tag occurrences : {real_total}")
        print(f"  usage_count totals match   : {usage_sum == real_total}")
        bare = sum(1 for s in cache_post if ":" not in s)
        print(f"  bare-slug rows remaining   : {bare}")
        return 0
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
