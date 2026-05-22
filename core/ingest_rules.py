"""Configurable ingest rules per audit brief §5.2.

Each rule in this module is small, stable, and reviewable. The
operator-locked-rule pattern (PHASEC §7.4) applies: comments cite
the date, the brief section, and the authority for each mapping.
Future-Claude does not re-litigate.

Currently landed:
  C1 — path-based exhibit:* (this module, 2026-05-22)
  C2 — tag-based era:* (this module, 2026-05-22)

Reserved for future C-bucket commits (will land in this module or
adjacent helper modules as the work warrants):
  C3 — HEIC transcoding policy (audit §5.2; ingest-time JPEG primary)
  C4 — sibling-cluster parent_artifact_id auto-link (audit §5.2;
       likely a scan()-time second pass, not a per-file rule)
  C5 — auto-release policy (audit §5.2; default stays manual)

Wiring entry point: core/ingest_engine.py:queue_item() calls
apply_all_rules(raw_path, hr_tags) and unions the result into
enrichment_json.tags_proposed.
"""
from typing import List

from hr_filename import HR_ACTOR_TAGS  # noqa: E402 -- shared HR cluster actor table


# C1 — path-based exhibit:* tag.
# Brief §5.2 verbatim:
#   intake/drop/<any-HR-shape-cluster> → exhibit:hunter_root
#   intake/drop/yt-staging/<any>       → exhibit:hunter_root
#   anything else                      → no exhibit tag (operator in inbox)
#
# "HR-shape cluster" is whatever core/hr_filename.parse_hr_filename
# returns non-empty for. This module never re-parses; it consumes the
# parser's result via the hr_tags argument.
HR_INTAKE_YT_STAGING = "intake/drop/yt-staging/"


def apply_exhibit_rule(raw_path: str, hr_tags: List[str]) -> List[str]:
    """Return exhibit:* tags to apply. Empty list = no exhibit tag."""
    if hr_tags:
        return ["exhibit:hunter_root"]
    # Normalize backslashes (Windows host paths) for substring match.
    if HR_INTAKE_YT_STAGING in str(raw_path).replace("\\", "/"):
        return ["exhibit:hunter_root"]
    return []


# C2 — tag-based era:* mapping.
# Brief §5.2 verbatim mapping (the only three):
#   album:run_with_the_hunt → era:rwth
#   album:medusas_disco     → era:medusas
#   album:seeds             → era:seeds
#   otherwise               → no era
#
# HR solo-era albums (cracked, wheel, dandelions, skipping, arkansas,
# crooked) are intentionally NOT mapped to era:solo — the brief's
# "otherwise no era" clause is explicit. The operator can extend this
# mapping later (one-line table edit) if HR solo albums should
# auto-tag era:solo at ingest time.
#
# Verified 2026-05-22 against live mediavault.sqlite at HEAD 9d8d9ca:
# only the runwiththehunt set (15 of 88 artifacts) currently carries an
# era:* tag (all era:rwth), and the album:* slugs in live data are
# {run_with_the_hunt, medusas_disco, arkansas}. C2 will fire for the
# first two; arkansas correctly receives no era.
ALBUM_TO_ERA = {
    "album:run_with_the_hunt": "era:rwth",
    "album:medusas_disco":     "era:medusas",
    "album:seeds":             "era:seeds",
}


def apply_era_rule(existing_tags: List[str]) -> List[str]:
    """Return era:* tags derived from album:* tags in existing_tags.
    Empty list if no album:* tag matches the mapping."""
    out: List[str] = []
    for t in existing_tags:
        e = ALBUM_TO_ERA.get(t)
        if e and e not in out:
            out.append(e)
    return out


def apply_all_rules(raw_path: str, hr_tags: List[str]) -> List[str]:
    """Union of C1 + C2 emissions for a single queueable file. The
    caller is responsible for deduplicating against any tags already
    in enrichment_json.tags_proposed."""
    return apply_exhibit_rule(raw_path, hr_tags) + apply_era_rule(hr_tags)


# ─────────────────────────────────────────────────────────────────────────────
# C4 — Sibling-cluster parent_artifact_id auto-link
# ─────────────────────────────────────────────────────────────────────────────
# Brief §5.2 C4: "For HR-shape clusters (M5's parse hits), elect the
# page_save HTML as the parent (storage_mode='referenced'), link the
# audio + cover_art siblings to it. Or elect the audio file as parent
# if no page_save exists. Policy: one rule per filename shape."
#
# Forward-only scope: identifies HR clusters from artifacts.local_asset_path
# basename (using the M5 filename grammar). Artifacts whose basename has
# been renamed during vaulting (e.g. MV-id.ext under catalogs/vaulted/)
# are not matched — by-design narrow scope per the brief's "M5's parse
# hits" wording. The 23 existing HR archive artifacts (which use HR
# directory structure rather than flattened basenames) are not in C4 scope;
# a separate _cowork/ backfill script can handle them later if desired.
#
# Parent election priority — page_save first (the canonical cluster head
# per the brief), then audio (fallback when no page_save in cluster),
# then cover_art, then artist_photo, then anything else.
KIND_PRIORITY = ("page_save", "audio", "cover_art", "artist_photo")


def _hr_cluster_key(local_asset_path):
    """Return (actor, album_field, kind) tuple identifying this
    artifact's HR cluster, or None if the basename does not match
    M5's actor__album__kind__title.<ext> filename grammar.

    Normalises Windows backslashes so paths from either OS parse.
    """
    if not local_asset_path:
        return None
    basename = str(local_asset_path).replace("\\", "/").rsplit("/", 1)[-1]
    parts = basename.split("__", 3)
    if len(parts) != 4:
        return None
    actor = parts[0].rstrip("_")
    if actor not in HR_ACTOR_TAGS:
        return None
    return (actor, parts[1], parts[2])


def link_hr_siblings(conn):
    """C4 main entry point. For each HR cluster in artifacts where
    siblings exist, elect a parent (page_save > audio > cover_art >
    artist_photo > other) and set parent_artifact_id on the others.

    Idempotent: only touches artifacts whose parent_artifact_id IS NULL.
    Respects existing linkages (any already-parented sibling is left alone;
    the un-parented siblings still elect a parent among themselves).

    Returns (linked_count, clusters_processed_count).
    """
    clusters = {}
    for r in conn.execute(
        "SELECT id, parent_artifact_id, local_asset_path FROM artifacts"
    ):
        key = _hr_cluster_key(r["local_asset_path"])
        if key is None:
            continue
        actor, album_field, kind = key
        clusters.setdefault((actor, album_field), []).append(
            (r["id"], kind, bool(r["parent_artifact_id"]))
        )

    linked = 0
    processed = 0
    kind_rank = {k: i for i, k in enumerate(KIND_PRIORITY)}
    for cluster_key, members in clusters.items():
        if len(members) < 2:
            continue
        # Sort by kind priority; the parent is the first unparented member.
        members.sort(key=lambda m: kind_rank.get(m[1], 99))
        parent_id = None
        for m_id, m_kind, m_has_parent in members:
            if not m_has_parent:
                parent_id = m_id
                break
        if parent_id is None:
            continue  # every member already parented; nothing to do
        processed += 1
        for m_id, m_kind, m_has_parent in members:
            if m_id == parent_id or m_has_parent:
                continue
            conn.execute(
                "UPDATE artifacts SET parent_artifact_id=? "
                "WHERE id=? AND parent_artifact_id IS NULL",
                (parent_id, m_id),
            )
            linked += 1
    conn.commit()
    return (linked, processed)
