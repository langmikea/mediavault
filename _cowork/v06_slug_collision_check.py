"""
v0.6 punchlist — Item 3 prep.

Check whether any slug value exists in more than one category in the tags
table. Slug is currently the PRIMARY KEY, so the SQL below can only ever
return one row per slug — but we still scan for the PK column's semantics
to report cleanly. We also print the full tags table so Mike can see the
category distribution at a glance.

Usage (from project root):
    python _cowork/v06_slug_collision_check.py
"""
from __future__ import annotations

import os
import sqlite3
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, os.pardir))
DB = os.path.join(ROOT, "core", "mediavault.sqlite")


def main() -> int:
    if not os.path.exists(DB):
        print(f"DB not found: {DB}", file=sys.stderr)
        return 2

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    # 1. Slug is the PK — verify.
    cols = conn.execute("PRAGMA table_info(tags)").fetchall()
    print("tags columns:")
    for c in cols:
        pk_marker = "  (PK)" if c["pk"] else ""
        print(f"  {c['name']:20s} {c['type']:10s}{pk_marker}")

    # 2. Category histogram.
    print("\ncategory histogram:")
    rows = conn.execute(
        "SELECT IFNULL(category,'<NULL>') AS cat, COUNT(*) AS n "
        "FROM tags GROUP BY IFNULL(category,'<NULL>') ORDER BY cat"
    ).fetchall()
    for r in rows:
        print(f"  {r['cat']:20s} {r['n']:4d}")

    # 3. Any slug appearing in >1 category? (Shouldn't happen under PK
    #    constraint, but this is what we'd want to loosen to so we check.)
    dup_rows = conn.execute(
        "SELECT slug, COUNT(DISTINCT IFNULL(category,'<NULL>')) AS cats "
        "FROM tags GROUP BY slug HAVING cats > 1"
    ).fetchall()
    print(f"\nslugs appearing in multiple categories: {len(dup_rows)}")
    for r in dup_rows:
        print(f"  {r['slug']}  (categories: {r['cats']})")

    # 4. Also: are there slugs that COULD collide after dropping the
    #    `author:` prefix? Item 4 will later rename display names; item 3
    #    opens the door to `author:hunter_root` → `hunter_root`. Check
    #    all namespaced slugs for a same-tail match in any other category.
    prefixed = conn.execute(
        "SELECT slug, category FROM tags WHERE slug LIKE '%:%'"
    ).fetchall()
    tail_map: dict[str, list[tuple[str, str]]] = {}
    all_rows = conn.execute("SELECT slug, category FROM tags").fetchall()
    for r in all_rows:
        tail = r["slug"].split(":", 1)[-1] if ":" in r["slug"] else r["slug"]
        tail_map.setdefault(tail, []).append(
            (r["slug"], r["category"] if r["category"] else "<NULL>")
        )

    print("\nslug-tail collision map (shared tails across slugs):")
    any_shared = False
    for tail, entries in sorted(tail_map.items()):
        if len(entries) > 1:
            any_shared = True
            print(f"  tail={tail!r}")
            for slug, cat in entries:
                print(f"    {slug}  [{cat}]")
    if not any_shared:
        print("  (none — no shared tails)")

    # 5. Full tags dump for Mike's review.
    print("\nfull tags table (sorted by category, slug):")
    for r in conn.execute(
        "SELECT slug, display_name, IFNULL(category,'<NULL>') AS cat, "
        "is_exclusive, is_proposed, usage_count "
        "FROM tags ORDER BY cat, slug"
    ):
        excl = "E" if r["is_exclusive"] else " "
        prop = "P" if r["is_proposed"] else " "
        print(
            f"  [{r['cat']:14s}] {r['slug']:40s} "
            f"{r['display_name']:30s} {excl}{prop} "
            f"u={r['usage_count']}"
        )

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
