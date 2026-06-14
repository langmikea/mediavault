#!/usr/bin/env python3
"""coverage_check.py — verify the v1 normalization map covers every live `unsorted:*` value.

Diffs docs/taxonomy/NORMALIZATION_MAP.md against the live MediaVault SQLite DB:
  * every live `unsorted:*` value is mapped exactly once   (0 missing)
  * every mapped value still exists in the live DB         (0 phantom)
  * no value is mapped twice                               (0 dupes)
  * prints the namespace tally of destinations

Usage:
    python3 tools/coverage_check.py [DB_PATH]
    MEDIAVAULT_DB=/path/to/mediavault.sqlite python3 tools/coverage_check.py

DB path resolution: positional arg > $MEDIAVAULT_DB > ./core/mediavault.sqlite (repo default).
Exit code 0 = PASS, 1 = FAIL.
"""
import os
import re
import sys
import json
import sqlite3
from collections import Counter

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAP_PATH = os.path.join(REPO_ROOT, "docs", "taxonomy", "NORMALIZATION_MAP.md")

# Matches a markdown table row whose first cell is `unsorted:<slug>` and whose
# second cell is the v1 destination, e.g.:
#   | `unsorted:live_show` | `event:live_show` | promote | ... |
ROW_RE = re.compile(r"^\|\s*`unsorted:([^`]+)`\s*\|\s*`([^`]+)`\s*\|")


def resolve_db_path(argv):
    if len(argv) > 1 and argv[1].strip():
        return argv[1].strip()
    env = os.environ.get("MEDIAVAULT_DB", "").strip()
    if env:
        return env
    return os.path.join(REPO_ROOT, "core", "mediavault.sqlite")


def load_map(map_path):
    """Return dict: source_slug -> destination. Tracks duplicate source keys."""
    if not os.path.exists(map_path):
        raise SystemExit(f"FAIL: normalization map not found: {map_path}")
    mapping = {}
    dupes = []
    with open(map_path, encoding="utf-8") as fh:
        for line in fh:
            m = ROW_RE.match(line.rstrip("\n"))
            if not m:
                continue
            src, dest = m.group(1).strip(), m.group(2).strip()
            if src in mapping:
                dupes.append(src)
            mapping[src] = dest
    return mapping, dupes


def load_db_values(db_path):
    """Distinct `unsorted:*` slugs from the live DB (tags registry + artifacts.tags)."""
    if not os.path.exists(db_path):
        raise SystemExit(f"FAIL: database not found: {db_path}")
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        cur = con.cursor()
        vals = set()
        # 1) vocabulary/tags registry
        for (slug,) in cur.execute("SELECT slug FROM tags WHERE slug LIKE 'unsorted:%'"):
            vals.add(slug.split(":", 1)[1])
        # 2) per-artifact tags (JSON arrays) — belt and suspenders
        for (tags,) in cur.execute("SELECT tags FROM artifacts WHERE tags LIKE '%unsorted:%'"):
            try:
                for t in json.loads(tags or "[]"):
                    if isinstance(t, str) and t.startswith("unsorted:"):
                        vals.add(t.split(":", 1)[1])
            except (ValueError, TypeError):
                continue
        return vals
    finally:
        con.close()


def main():
    db_path = resolve_db_path(sys.argv)
    mapping, dupes = load_map(MAP_PATH)
    db_values = load_db_values(db_path)

    map_keys = set(mapping)
    missing = sorted(db_values - map_keys)        # live values with no mapping
    phantom = sorted(map_keys - db_values)        # mapped values not in live DB
    tally = Counter(dest.split(":", 1)[0] for dest in mapping.values())

    def rel(p):
        try:
            return os.path.relpath(p, REPO_ROOT)
        except ValueError:
            return p

    print("MediaVault taxonomy v1 — coverage check")
    print("=" * 48)
    print(f"DB path           : {rel(db_path)}")
    print(f"Map path          : {rel(MAP_PATH)}")
    print(f"Live unsorted:*    : {len(db_values)}")
    print(f"Mapped values      : {len(map_keys)}")
    print(f"Mapped exactly once: {'yes' if not dupes else 'NO -> ' + ', '.join(dupes)}")
    print(f"Missing (unmapped) : {len(missing)}" + (f" -> {missing}" if missing else ""))
    print(f"Phantom (not in DB): {len(phantom)}" + (f" -> {phantom}" if phantom else ""))
    print("-" * 48)
    print("Namespace tally (destinations):")
    for ns in sorted(tally):
        print(f"  {ns:<12} {tally[ns]}")
    print("-" * 48)

    ok = (not missing) and (not phantom) and (not dupes) and len(db_values) == len(map_keys)
    if ok:
        print(f"RESULT: PASS  ({len(map_keys)} values, all mapped exactly once, 0 missing, 0 dupes)")
        return 0
    print("RESULT: FAIL")
    return 1


if __name__ == "__main__":
    sys.exit(main())
