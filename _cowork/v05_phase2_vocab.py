"""
v05_phase2_vocab.py
===================
MediaVault v0.5 — Phase 2 vocabulary cleanup.

Single transaction. Executes design §9.2–§9.5 in order.

  2.1  Merges (14 items, per design §9.2). Merge #3 creates the target
       vocab row before it runs.
  2.2  Deletions (38 slugs, per design §9.3).
  2.3  Vocabulary creates (5 slugs, per design §9.4). run_with_the_hunt
       already exists after merge #3, so that create is a no-op.
  2.4  Recompute usage_count from JSON.
  2.5  Categorization (per design §9.5). author:* pills are swept into
       category='people' alongside nick_root — the brief's SQL only
       listed nick_root because it assumed Phase 1.1b had set author:*
       categories, but Phase 1's ordering made that impossible
       (category column didn't exist until 1.2), so the sweep lives
       here instead. This is a judgment call documented in PHASE_SUMMARY.
  2.6  Verification. tags count must land in 55–70 (§9.6 predicts ~62).
       If outside that range, rollback and stop (brief §Stop conditions 2).
"""

from __future__ import annotations
import json
import sqlite3
import sys
from pathlib import Path

BASE = Path(r"C:\AI\Platform\MediaVault")
DB_PATH = BASE / "core" / "mediavault.sqlite"

if len(sys.argv) > 1:
    DB_PATH = Path(sys.argv[1])


# --- §9.2 merges: (source, target, reason for the summary log) -------------
MERGES: list[tuple[str, str, str]] = [
    ("hunter",                                 "hunter_root",        "same person, fragmented"),
    ("medusasdisco",                           "medusas_disco",      "stem dup (canon = spaced form)"),
    ("runwiththehunt",                         "run_with_the_hunt",  "stem dup (target created just-in-time)"),
    ("pre_solo_run_with_the_hunt",             "run_with_the_hunt",  "provenance-as-tag"),
    ("pre_solo_medusas_disco",                 "medusas_disco",      "provenance-as-tag"),
    ("hunterroot2",                            "hunter_root",        "duplicate handle reference"),
    ("audio_audio_file",                       "audio",              "ingest-provenance leakage"),
    ("audio_metadata_json",                    "audio",              "ingest-provenance leakage"),
    ("mp3_only",                               "audio",              "phase-2 workflow marker"),
    ("reverbnation_artist_page_metadata_json", "reverbnation",       "composite slug from ingest"),
    ("reverbnation_artist_page_page_save_html","reverbnation",       "composite slug from ingest"),
    ("reverbnation_song_page_lyrics_txt",      "reverbnation",       "composite slug from ingest"),
    ("reverbnation_song_page_metadata_json",   "reverbnation",       "composite slug from ingest"),
    ("reverbnation_song_page_page_save_html",  "reverbnation",       "composite slug from ingest"),
]

# Merge #3 special-case: this target does not yet exist in vocab. Create it
# before the merge runs with these properties.
MERGE3_TARGET_PREWARM = ("run_with_the_hunt", "Run With The Hunt", "bands", 0, 0)
# tuple: (slug, display, category, is_exclusive, is_proposed)

# --- §9.3 deletions ---------------------------------------------------------
DELETIONS: list[str] = [
    # Dead weight
    "standard", "critical",
    # Year pills
    "2019", "2022", "2023", "2024", "2025", "2026",
    # Visual detail
    "striped_shirt", "long_hair", "brick_wall", "brick_wall_background",
    "original_music",
    # Song titles
    "town_rat_heathen", "quicksand_sinking",
    "dreaming_up_ways_of_gettin_outta_this_hellhole",
    "hellhole_perspective_rubble_lyrics", "my_brothers_bones", "crooked_home",
    # Genres
    "rock", "acoustic", "jam", "grunge", "psychedelic", "blues",
    "singer_songwriter", "acoustic_rock", "psychedelic_rock", "indiefolk",
    "alternative",
    # Overly generic / redundant
    "show", "song", "performance", "quote", "lyric", "venue",
    # Workflow provenance
    "phase2_recovery", "mp3_only",
]

# --- §9.4 creates: (slug, display, category) -------------------------------
CREATES: list[tuple[str, str, str]] = [
    ("run_with_the_hunt", "Run With The Hunt", "bands"),
    ("seeds",             "Seeds",             "bands"),
    ("music_video",       "Music Video",       "content_kind"),
    ("fan_art",           "Fan Art",           "content_kind"),
    ("memorabilia",       "Memorabilia",       "content_kind"),
]

# --- §9.5 categorization ---------------------------------------------------
CATEGORY_ASSIGNMENTS: dict[str, list[str]] = {
    "bands": ["hunter_root", "medusas_disco", "run_with_the_hunt", "seeds"],
    # people: nick_root + every surviving author:* slug (swept in code below).
    "people": ["nick_root"],
    "places": ["lancaster_pa"],
    "content_kind": [
        "live_show", "tour_announcement", "poster", "event_listing",
        "song_page", "artist_page", "promotional_post", "rehearsal",
        "cover_song", "new_song", "tribute", "milestone",
        "music_video", "fan_art", "memorabilia",
    ],
    "topic": ["songwriting", "songwriting_process", "loss",
              "mental_health", "lyme_disease"],
    "scope": ["personal", "family", "fan"],
    "rarity": ["common", "notable", "rare", "unique"],  # already set in §1.2
}


def apply_tag_replace(
    cur: sqlite3.Cursor, source: str, target: str | None
) -> int:
    """Walk every artifact whose tags contain `source`. Remove source; if
    target given, add target (dedupe). Return number of artifacts touched."""
    rows = cur.execute(
        "SELECT id, tags FROM artifacts WHERE tags LIKE ?",
        (f'%"{source}"%',),
    ).fetchall()
    touched = 0
    for r in rows:
        tags = json.loads(r["tags"])
        if source not in tags:
            # JSON-LIKE spurious match (e.g., substring of another slug).
            continue
        new_tags = [t for t in tags if t != source]
        if target and target not in new_tags:
            new_tags.append(target)
        if new_tags != tags:
            cur.execute(
                "UPDATE artifacts SET tags=?, updated_at=datetime('now') "
                "WHERE id=?",
                (json.dumps(new_tags), r["id"]),
            )
            touched += 1
    return touched


def vocab_exists(cur: sqlite3.Cursor, slug: str) -> bool:
    return cur.execute("SELECT 1 FROM tags WHERE slug=?", (slug,)).fetchone() is not None


def main() -> int:
    if not DB_PATH.exists():
        print(f"FATAL: DB not found at {DB_PATH}", file=sys.stderr)
        return 2

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.isolation_level = None
    cur = conn.cursor()
    cur.execute("PRAGMA journal_mode = MEMORY")
    cur.execute("PRAGMA foreign_keys = OFF")
    cur.execute("BEGIN")

    summary: dict[str, object] = {
        "merges": [], "deletions": [], "creates": [], "skipped_creates": [],
    }

    try:
        pre_tag_count = cur.execute("SELECT COUNT(*) FROM tags").fetchone()[0]

        # --- 2.1 merges ------------------------------------------------------
        # Pre-create merge #3 target before the merge fires.
        if not vocab_exists(cur, MERGE3_TARGET_PREWARM[0]):
            cur.execute(
                "INSERT INTO tags(slug, display_name, description, category, "
                "is_exclusive, is_proposed, usage_count) VALUES (?, ?, NULL, ?, ?, ?, 0)",
                MERGE3_TARGET_PREWARM,
            )
            print(f"[2.1] pre-created merge #3 target: {MERGE3_TARGET_PREWARM[0]}")

        for i, (src, tgt, reason) in enumerate(MERGES, start=1):
            if not vocab_exists(cur, tgt):
                # Defensive: create a stub. No merge in this list except #3
                # should hit this branch — the others' targets pre-exist.
                cur.execute(
                    "INSERT INTO tags(slug, display_name, description, "
                    "category, is_exclusive, is_proposed, usage_count) "
                    "VALUES (?, ?, NULL, NULL, 0, 0, 0)",
                    (tgt, tgt.replace("_", " ").title()),
                )

            touched = apply_tag_replace(cur, src, tgt)

            if vocab_exists(cur, src):
                cur.execute("DELETE FROM tags WHERE slug=?", (src,))
                deleted = True
            else:
                deleted = False

            # New target usage count (approximate: artifacts currently holding target).
            target_usage = cur.execute(
                "SELECT COUNT(*) FROM artifacts WHERE tags LIKE ?",
                (f'%"{tgt}"%',),
            ).fetchone()[0]

            summary["merges"].append({
                "n": i, "source": src, "target": tgt,
                "artifacts_touched": touched,
                "target_usage_preview": target_usage,
                "source_vocab_deleted": deleted,
                "reason": reason,
            })
            print(f"[2.1] merge #{i}: {src} → {tgt} · touched={touched} · "
                  f"target_usage≈{target_usage}")

        # --- 2.2 deletions ---------------------------------------------------
        for slug in DELETIONS:
            touched = apply_tag_replace(cur, slug, target=None)
            deleted = False
            if vocab_exists(cur, slug):
                cur.execute("DELETE FROM tags WHERE slug=?", (slug,))
                deleted = True
            summary["deletions"].append({
                "slug": slug,
                "artifacts_touched": touched,
                "vocab_deleted": deleted,
            })
            print(f"[2.2] delete {slug}: touched={touched} vocab_deleted={deleted}")

        # --- 2.3 creates -----------------------------------------------------
        for slug, disp, cat in CREATES:
            if vocab_exists(cur, slug):
                summary["skipped_creates"].append(slug)
                print(f"[2.3] create {slug}: already exists, skipping")
                continue
            cur.execute(
                "INSERT INTO tags(slug, display_name, description, category, "
                "is_exclusive, is_proposed, usage_count) VALUES (?, ?, NULL, ?, 0, 0, 0)",
                (slug, disp, cat),
            )
            summary["creates"].append({"slug": slug, "category": cat})
            print(f"[2.3] create {slug} ({disp}, category={cat})")

        # --- 2.4 recompute usage counts -------------------------------------
        cur.execute("""
            UPDATE tags SET usage_count = (
                SELECT COUNT(*) FROM artifacts
                WHERE EXISTS (
                    SELECT 1 FROM json_each(artifacts.tags) j
                    WHERE j.value = tags.slug
                )
            )
        """)
        print("[2.4] usage_count recomputed")

        # --- 2.5 categorization ---------------------------------------------
        for cat, slugs in CATEGORY_ASSIGNMENTS.items():
            if not slugs:
                continue
            placeholders = ",".join(["?"] * len(slugs))
            params: list[object] = [cat] + slugs
            if cat == "rarity":
                cur.execute(
                    f"UPDATE tags SET category=?, is_exclusive=1 "
                    f"WHERE slug IN ({placeholders})",
                    params,
                )
            else:
                cur.execute(
                    f"UPDATE tags SET category=? WHERE slug IN ({placeholders})",
                    params,
                )

        # Author:* pills → category='people'. (See §2.5 judgment call note.)
        cur.execute(
            "UPDATE tags SET category='people' "
            "WHERE slug LIKE 'author:%' AND (category IS NULL OR category='')"
        )
        print("[2.5] category assignments applied (including author:* → people)")

        # --- 2.6 verification -----------------------------------------------
        # (a) deleted slugs absent from vocab
        for slug in DELETIONS:
            if vocab_exists(cur, slug):
                raise RuntimeError(f"deletion did not remove vocab row for {slug}")
        # (b) no artifact's tags contain any deleted slug
        for slug in DELETIONS:
            hit = cur.execute(
                "SELECT id FROM artifacts WHERE tags LIKE ? LIMIT 1",
                (f'%"{slug}"%',),
            ).fetchone()
            if hit:
                # Confirm it's not a JSON-LIKE false positive.
                art_tags = json.loads(
                    cur.execute("SELECT tags FROM artifacts WHERE id=?",
                                (hit["id"],)).fetchone()["tags"]
                )
                if slug in art_tags:
                    raise RuntimeError(
                        f"artifact {hit['id']} still carries deleted slug {slug}"
                    )
        # (c) merge sources gone, targets present
        for src, tgt, _ in MERGES:
            if vocab_exists(cur, src):
                raise RuntimeError(f"merge source {src} vocab row not deleted")
            if not vocab_exists(cur, tgt):
                raise RuntimeError(f"merge target {tgt} vocab row missing")
            hit = cur.execute(
                "SELECT id FROM artifacts WHERE tags LIKE ? LIMIT 1",
                (f'%"{src}"%',),
            ).fetchone()
            if hit:
                art_tags = json.loads(
                    cur.execute("SELECT tags FROM artifacts WHERE id=?",
                                (hit["id"],)).fetchone()["tags"]
                )
                if src in art_tags:
                    raise RuntimeError(
                        f"artifact {hit['id']} still carries merged source {src}"
                    )
        # (d) total tags count in 55–70
        post_tag_count = cur.execute("SELECT COUNT(*) FROM tags").fetchone()[0]
        if not (55 <= post_tag_count <= 70):
            # Stop condition 2: outside design §9.6 band.
            raise RuntimeError(
                f"STOP-CONDITION-2: tags count {post_tag_count} is outside "
                f"the design §9.6 55–70 band. Rolling back."
            )
        summary["pre_tag_count"] = pre_tag_count
        summary["post_tag_count"] = post_tag_count
        # (e) every categorized slug has category set
        for cat, slugs in CATEGORY_ASSIGNMENTS.items():
            for s in slugs:
                row = cur.execute(
                    "SELECT category FROM tags WHERE slug=?", (s,)
                ).fetchone()
                if not row:
                    # Slug may have been deleted — skip (e.g., if operator later
                    # removes a category target, that's fine).
                    continue
                if row["category"] != cat:
                    raise RuntimeError(
                        f"slug {s} expected category={cat}, got {row['category']!r}"
                    )
        # author:* pills get people
        bad_authors = cur.execute(
            "SELECT slug FROM tags WHERE slug LIKE 'author:%' AND category <> 'people'"
        ).fetchall()
        if bad_authors:
            raise RuntimeError(f"author:* slugs not categorized as people: "
                               f"{[r['slug'] for r in bad_authors]}")

        fk_violations = cur.execute("PRAGMA foreign_key_check").fetchall()
        if fk_violations:
            raise RuntimeError(f"foreign_key_check failures: {fk_violations}")

        cur.execute("COMMIT")
        cur.execute("PRAGMA foreign_keys = ON")

        print()
        print(f"[2.6] verification passed; committed.")
        print(f"  tags:  {pre_tag_count} → {post_tag_count} (within 55–70).")

        # Dump summary as JSON for PHASE_SUMMARY append.
        out_path = DB_PATH.parent.parent / "_cowork" / "phase2_summary.json"
        out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(f"  summary json -> {out_path}")
        return 0

    except Exception as e:
        try:
            cur.execute("ROLLBACK")
        except sqlite3.OperationalError:
            pass
        cur.execute("PRAGMA foreign_keys = ON")
        print(f"[FATAL] phase 2 rolled back: {e}", file=sys.stderr)
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
