"""
migrate_to_v04.py
=================
MediaVault schema migration v0.2 -> v0.4.

Transforms the artifacts table from the 10-column tags_* layout (with a
`domain` column) into the v0.4 layout (flat `tags` JSON array, explicit
`status` and `storage_mode` columns, parent_artifact_id linking, etc).

Reads _cowork/pre_refactor_snapshot.json for sidecar parent candidates.

Usage:
    python core/migrate_to_v04.py

Everything happens in a single transaction. If any verification step
fails, the transaction rolls back and no changes persist.
"""

from __future__ import annotations

import json
import ntpath
import os
import re
import sqlite3
import sys
import shutil
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DEFAULT_DB = BASE / "core" / "mediavault.sqlite"
SNAPSHOT = BASE / "_cowork" / "pre_refactor_snapshot.json"
LOG_DIR = BASE / "_cowork"

VAULTED_ROOT = BASE / "catalogs" / "vaulted"

# DB path can be overridden via CLI arg 1 (used when running against a
# scratch copy and then swapping the file back). If not overridden, we
# operate on the canonical DB in place.
DB = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DB

# ---------------------------------------------------------------------------
# Slug / display-name helpers
# ---------------------------------------------------------------------------

def slugify(value):
    """Normalize a raw tag string to a valid slug, or None if invalid."""
    if value is None:
        return None
    s = str(value).strip().lower()
    if not s:
        return None
    # Any run of dash / slash / backslash / whitespace becomes a single underscore
    s = re.sub(r"[-/\\\s]+", "_", s)
    # Strip any other non [a-z0-9_] characters
    s = re.sub(r"[^a-z0-9_]", "", s)
    # Collapse consecutive underscores and trim ends
    s = re.sub(r"_+", "_", s).strip("_")
    if not s or len(s) > 64:
        return None
    if not re.fullmatch(r"[a-z0-9_]+", s):
        return None
    return s


def display_name_for(slug):
    """Humanize a slug for display. Years pass through; others title-case."""
    if re.fullmatch(r"\d{4}", slug):
        return slug
    return slug.replace("_", " ").title()


RARITY_GROUP = {"common", "notable", "rare", "unique"}
PRESERVATION_GROUP = {"standard", "critical"}


def group_for(slug):
    if slug in RARITY_GROUP:
        return "rarity"
    if slug in PRESERVATION_GROUP:
        return "preservation"
    return None


# ---------------------------------------------------------------------------
# Flatten a raw cell value into a list of slugs
# ---------------------------------------------------------------------------

def flatten_tag_cell(value):
    """Return a list of slugs parsed from one tags_* cell."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        items = list(value)
    else:
        raw = str(value).strip()
        if not raw:
            return []
        items = None
        # JSON array?
        if raw.startswith("["):
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    items = parsed
            except Exception:
                items = None
        if items is None:
            # Comma-separated string? (only split if there's a comma)
            if "," in raw:
                items = [p.strip() for p in raw.split(",")]
            else:
                items = [raw]
    out = []
    for it in items:
        s = slugify(it)
        if s:
            out.append(s)
    return out


# ---------------------------------------------------------------------------
# Sidecar parent picker
# ---------------------------------------------------------------------------

def pick_parent(sidecar_row, candidates):
    """
    Rule:
      1. If only one candidate, pick it (if non-.json).
      2. Determine preferred asset extension from the sidecar's
         tags_content_type (audio -> mp3/wav/..., page -> html/htm,
         lyrics -> txt). Filter candidates to non-.json files first.
      3. Among candidates of the preferred kind, prefer one whose path
         contains the sidecar's parent directory name.
      4. Fallback: first non-.json candidate.
    """
    sc_path = (sidecar_row.get("local_asset_path") or "").lower()
    # Use ntpath so Windows-style paths are parsed correctly on any OS.
    sc_dir = ntpath.dirname(sc_path)
    tct = (sidecar_row.get("tags_content_type") or "").lower()

    if "audio/" in tct:
        pref_exts = (".mp3", ".wav", ".flac", ".m4a", ".ogg")
    elif "lyrics" in tct:
        pref_exts = (".txt",)
    elif "page" in tct or "html" in tct:
        pref_exts = (".html", ".htm")
    else:
        pref_exts = None

    # Drop .json candidates (they would be other sidecars).
    non_json = [
        c for c in candidates
        if c.get("local_asset_path") and not c["local_asset_path"].lower().endswith(".json")
    ]
    if not non_json:
        return None

    def same_dir(cands):
        return [c for c in cands if sc_dir and sc_dir in c["local_asset_path"].lower()]

    if pref_exts:
        pref = [c for c in non_json if c["local_asset_path"].lower().endswith(pref_exts)]
        if pref:
            same = same_dir(pref)
            return (same or pref)[0]["id"]

    same = same_dir(non_json)
    if same:
        return same[0]["id"]

    return non_json[0]["id"]


# ---------------------------------------------------------------------------
# Storage mode determination
# ---------------------------------------------------------------------------

CATALOGS_PREFIX = str(BASE / "catalogs").lower() + os.sep.lower()
# Match by Windows-style prefix too (the DB holds Windows paths).
CATALOGS_PREFIX_WIN = r"c:\ai\platform\mediavault\catalogs"


def compute_storage_mode(local_asset_path, source_url):
    if not local_asset_path:
        if source_url:
            return "url_only"
        return "url_only"
    p = local_asset_path.lower().replace("/", "\\")
    if p.startswith(CATALOGS_PREFIX_WIN):
        return "vaulted"
    return "referenced"


# ---------------------------------------------------------------------------
# Main migration
# ---------------------------------------------------------------------------

def main():
    print(f"[migrate] DB: {DB}")
    print(f"[migrate] Snapshot: {SNAPSHOT}")
    if not DB.exists():
        print("ERROR: DB not found", file=sys.stderr)
        sys.exit(2)
    if not SNAPSHOT.exists():
        print("ERROR: snapshot not found", file=sys.stderr)
        sys.exit(2)

    snap = json.loads(SNAPSHOT.read_text(encoding="utf-8"))

    # Extra backup right before migration
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    extra_backup = DB.with_suffix(DB.suffix + f".bak_v04phase1_{ts}")
    shutil.copy2(DB, extra_backup)
    print(f"[migrate] Backup created: {extra_backup.name}")

    # Ensure vaulted root exists
    VAULTED_ROOT.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=OFF")
    cur = conn.cursor()

    # Pre-compute missing-asset set from the snapshot so we don't depend
    # on the current process actually being able to see the Windows paths.
    missing_ids = {m["id"] for m in snap.get("missing_asset_files", [])}

    try:
        cur.execute("BEGIN")

        # ---- 0. Drop scratch artifacts unrelated to the target schema ----
        cur.execute("DROP TABLE IF EXISTS __test")

        # ---- 1. Create _v4 tables -------------------------------------
        print("[migrate] Creating v4 tables...")
        cur.executescript("""
            DROP TABLE IF EXISTS artifacts_v4;
            DROP TABLE IF EXISTS tags;
            DROP TABLE IF EXISTS id_sequence_v4;
            DROP TABLE IF EXISTS ingest_queue_v4;

            CREATE TABLE artifacts_v4 (
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

                parent_artifact_id      TEXT REFERENCES artifacts_v4(id) ON DELETE CASCADE,
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
                author_name             TEXT,

                tags                    TEXT NOT NULL DEFAULT '[]',

                tags_permission         TEXT,
                permission_contact      TEXT,
                permission_evidence_path TEXT,

                confidence_flags        TEXT,
                notes                   TEXT,
                created_at              TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at              TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE tags (
                slug            TEXT PRIMARY KEY,
                display_name    TEXT NOT NULL,
                description     TEXT,
                group_name      TEXT,
                is_proposed     INTEGER NOT NULL DEFAULT 0,
                usage_count     INTEGER NOT NULL DEFAULT 0,
                created_at      TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE id_sequence_v4 (
                date_str  TEXT PRIMARY KEY,
                last_seq  INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE ingest_queue_v4 (
                queue_id        INTEGER PRIMARY KEY,
                ingest_source   TEXT NOT NULL,
                raw_path        TEXT,
                source_url      TEXT,
                queued_at       TEXT NOT NULL,
                status          TEXT NOT NULL DEFAULT 'pending'
                                    CHECK(status IN ('pending','keep','skip','enriched','approved','failed')),
                enrichment_json TEXT,
                error_message   TEXT,
                artifact_id     TEXT,
                updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
            );
        """)

        # ---- 2. Build tag vocabulary ----------------------------------
        print("[migrate] Building tag vocabulary...")
        tag_cols = [
            "tags_year_era", "tags_content_type", "tags_song_reference",
            "tags_release_stage", "tags_subject", "tags_topic",
            "tags_rarity", "tags_preservation", "tags_keywords",
            # tags_permission kept as column; do not flatten into vocab
        ]

        # Seed with hunter_root
        vocab = {}
        vocab["hunter_root"] = {
            "slug": "hunter_root",
            "display_name": "Hunter Root",
            "description": None,
            "group_name": None,
            "is_proposed": 0,
        }

        # Scan the old artifacts table
        sel_cols = ", ".join(tag_cols)
        for row in cur.execute(f"SELECT {sel_cols} FROM artifacts"):
            for v in row:
                for slug in flatten_tag_cell(v):
                    if slug not in vocab:
                        vocab[slug] = {
                            "slug": slug,
                            "display_name": display_name_for(slug),
                            "description": None,
                            "group_name": group_for(slug),
                            "is_proposed": 0,
                        }

        # Insert into tags table
        for t in vocab.values():
            cur.execute(
                "INSERT INTO tags(slug, display_name, description, group_name, is_proposed, usage_count) "
                "VALUES(?,?,?,?,?,0)",
                (t["slug"], t["display_name"], t["description"], t["group_name"], t["is_proposed"]),
            )
        print(f"[migrate]   seeded {len(vocab)} tag rows")

        # ---- 3. Copy artifacts -----------------------------------------
        print("[migrate] Copying artifacts to v4 layout...")
        old_rows = list(cur.execute("SELECT * FROM artifacts"))
        old_count = len(old_rows)
        print(f"[migrate]   old artifact count: {old_count}")

        for row in old_rows:
            r = dict(row)
            lap = r.get("local_asset_path")
            storage_mode = compute_storage_mode(lap, r.get("source_url"))

            # link_status: carry through the existing value (almost always
            # 'live' in v0.2 data); force 'local-only' for the IDs the prep
            # script already identified as having missing assets on disk.
            # We deliberately do NOT call os.path.exists here — this script
            # may run on a host that cannot see the Windows paths in
            # local_asset_path, which would falsely flag everything as
            # missing. The snapshot is the source of truth.
            link_status = r.get("link_status")
            if r["id"] in missing_ids:
                link_status = "local-only"

            # Build tags array
            tag_slugs = set()
            tag_slugs.add("hunter_root")
            for col in tag_cols:
                for s in flatten_tag_cell(r.get(col)):
                    tag_slugs.add(s)
            tags_json = json.dumps(sorted(tag_slugs))

            cur.execute(
                """INSERT INTO artifacts_v4(
                    id, source_url, source_platform, ingest_source, ingest_date,
                    storage_mode, local_asset_path, thumbnail_path, link_status,
                    parent_artifact_id, media_type,
                    post_date, post_date_confidence, capture_date,
                    status, released_at, released_by,
                    description_short, description_long, extracted_text, author_name,
                    tags, tags_permission,
                    permission_contact, permission_evidence_path,
                    confidence_flags, notes
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    r["id"],
                    r.get("source_url"),
                    r.get("source_platform"),
                    r.get("ingest_source"),
                    r.get("ingest_date"),
                    storage_mode,
                    lap,
                    r.get("thumbnail_path"),
                    link_status,
                    None,  # parent_artifact_id, set next step
                    r.get("media_type_in_post"),
                    r.get("post_date"),
                    r.get("post_date_confidence"),
                    r.get("capture_date"),
                    "vault",
                    None, None,
                    r.get("description_short"),
                    r.get("description_long"),
                    r.get("extracted_text"),
                    r.get("author_name"),
                    tags_json,
                    r.get("tags_permission"),
                    r.get("permission_contact"),
                    r.get("permission_evidence_path"),
                    r.get("confidence_flags"),
                    r.get("notes"),
                ),
            )

        # ---- 4. Sidecar parent linking --------------------------------
        print("[migrate] Linking sidecars to parents...")
        sidecar_rows = {s["id"]: s for s in snap.get("sidecar_rows", [])}
        match_data = snap.get("sidecar_parent_matches", [])
        linked = 0
        unlinked = []
        for m in match_data:
            sid = m["sidecar_id"]
            cands = m.get("parent_candidates", [])
            sc_meta = sidecar_rows.get(sid, {"local_asset_path": "", "tags_content_type": ""})
            parent_id = pick_parent(sc_meta, cands)
            if parent_id and parent_id != sid:
                cur.execute(
                    "UPDATE artifacts_v4 SET parent_artifact_id=? WHERE id=?",
                    (parent_id, sid),
                )
                linked += 1
            else:
                unlinked.append(sid)
        print(f"[migrate]   linked {linked} sidecars; unlinked: {unlinked}")

        # ---- 5. usage_count on tags -----------------------------------
        print("[migrate] Computing tag usage_count...")
        # Use json_each to iterate the tags arrays of every artifact.
        cur.execute("""
            UPDATE tags
               SET usage_count = (
                   SELECT COUNT(*)
                     FROM artifacts_v4 a, json_each(a.tags) t
                    WHERE t.value = tags.slug
               )
        """)

        # ---- 6. Rebuild id_sequence -----------------------------------
        print("[migrate] Rebuilding id_sequence...")
        date_max = {}
        for row in cur.execute("SELECT id FROM artifacts_v4"):
            aid = row["id"]
            m = re.match(r"^MV-(?:[A-Z]{2}-)?(\d{8})-(\d+)$", aid)
            if m:
                ds, seq = m.group(1), int(m.group(2))
                if ds not in date_max or seq > date_max[ds]:
                    date_max[ds] = seq
        for ds, seq in date_max.items():
            cur.execute(
                "INSERT INTO id_sequence_v4(date_str, last_seq) VALUES(?, ?)",
                (ds, seq),
            )
        print(f"[migrate]   {len(date_max)} dates in id_sequence_v4")

        # ---- 7. Migrate ingest_queue ----------------------------------
        print("[migrate] Migrating ingest_queue...")
        q_rows = list(cur.execute("SELECT * FROM ingest_queue WHERE status NOT IN ('skip','failed')"))
        for q in q_rows:
            d = dict(q)
            cur.execute(
                """INSERT INTO ingest_queue_v4(
                    queue_id, ingest_source, raw_path, source_url, queued_at,
                    status, enrichment_json, error_message, artifact_id
                ) VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    d["queue_id"],
                    d.get("ingest_source"),
                    d.get("raw_path"),
                    d.get("source_url"),
                    d.get("queued_at"),
                    d.get("status", "pending"),
                    d.get("enrichment_json"),
                    d.get("error_message"),
                    d.get("artifact_id"),
                ),
            )
        print(f"[migrate]   migrated {len(q_rows)} queue rows (skipped 'skip'/'failed')")

        # ---- 8. Verification ------------------------------------------
        print("[migrate] Verifying...")
        new_count = cur.execute("SELECT COUNT(*) FROM artifacts_v4").fetchone()[0]
        assert new_count == old_count, f"artifact count mismatch: {new_count} vs {old_count}"
        assert old_count == 76, f"expected 76 artifacts, got {old_count}"

        tag_count = cur.execute("SELECT COUNT(*) FROM tags").fetchone()[0]
        assert tag_count > 0, "tags table empty"

        # Every tags column is valid JSON AND every slug exists in tags
        known_slugs = set(r[0] for r in cur.execute("SELECT slug FROM tags"))
        for row in cur.execute("SELECT id, tags FROM artifacts_v4"):
            aid, tj = row["id"], row["tags"]
            try:
                arr = json.loads(tj)
            except Exception as e:
                raise AssertionError(f"artifact {aid} tags not valid JSON: {e}")
            assert isinstance(arr, list), f"artifact {aid} tags not a list"
            for s in arr:
                assert s in known_slugs, f"artifact {aid}: tag '{s}' not in vocab"

        assert 10 <= linked <= 25, f"sidecar link count {linked} outside [10,25] — STOP per brief §10.1"

        # status / storage_mode enum sanity (CHECKs would catch it, but verify explicitly)
        bad_status = cur.execute("SELECT COUNT(*) FROM artifacts_v4 WHERE status NOT IN ('inbox','vault','released','archived')").fetchone()[0]
        assert bad_status == 0, f"{bad_status} rows with bad status"
        bad_storage = cur.execute("SELECT COUNT(*) FROM artifacts_v4 WHERE storage_mode NOT IN ('vaulted','referenced','url_only')").fetchone()[0]
        assert bad_storage == 0, f"{bad_storage} rows with bad storage_mode"

        print(f"[migrate] Verification PASSED. "
              f"artifacts={new_count}, tags={tag_count}, sidecars_linked={linked}")

        # ---- 9. Drop old, rename new ----------------------------------
        print("[migrate] Dropping old tables, renaming v4 -> canonical...")
        cur.executescript("""
            DROP TABLE IF EXISTS post_packages;
            DROP TABLE IF EXISTS artifacts;
            DROP TABLE IF EXISTS ingest_queue;
            DROP TABLE IF EXISTS id_sequence;

            ALTER TABLE artifacts_v4    RENAME TO artifacts;
            ALTER TABLE ingest_queue_v4 RENAME TO ingest_queue;
            ALTER TABLE id_sequence_v4  RENAME TO id_sequence;
        """)

        # ---- 10. Rebuild indexes --------------------------------------
        print("[migrate] Creating indexes...")
        cur.executescript("""
            CREATE INDEX IF NOT EXISTS idx_artifacts_status       ON artifacts(status);
            CREATE INDEX IF NOT EXISTS idx_artifacts_storage_mode ON artifacts(storage_mode);
            CREATE INDEX IF NOT EXISTS idx_artifacts_post_date    ON artifacts(post_date);
            CREATE INDEX IF NOT EXISTS idx_artifacts_ingest_date  ON artifacts(ingest_date);
            CREATE INDEX IF NOT EXISTS idx_artifacts_parent       ON artifacts(parent_artifact_id);
            CREATE INDEX IF NOT EXISTS idx_artifacts_source_url   ON artifacts(source_url);
            CREATE INDEX IF NOT EXISTS idx_tags_group             ON tags(group_name);
            CREATE INDEX IF NOT EXISTS idx_tags_proposed          ON tags(is_proposed);
        """)

        conn.commit()
        print("[migrate] COMMIT OK")

        summary = {
            "old_artifacts": old_count,
            "new_artifacts": new_count,
            "tag_vocab_size": tag_count,
            "sidecars_linked": linked,
            "sidecars_unlinked": unlinked,
            "queue_rows_migrated": len(q_rows),
            "id_sequence_dates": len(date_max),
            "extra_backup": str(extra_backup),
        }
        print(json.dumps(summary, indent=2))
        return summary

    except Exception as e:
        conn.rollback()
        print(f"[migrate] ERROR (rolled back): {e}", file=sys.stderr)
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
