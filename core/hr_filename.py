"""HR-archive filename grammar parser.

Path A only. The HR RN-archive tool (`tools/rn_archive_extract.py` in
the Hunter Root repo) drops files into `intake/drop/` with names of
the shape::

    actor__album__kind__title.<ext>

where:
  * `actor`       — the ReverbNation account slug (e.g. ``medusasdisco``).
  * `album`       — either a song-cluster folder slug
                    (e.g. ``park-bench-pigeons_19361978``) or the
                    sentinel ``_artist`` for artist-level artifacts.
  * `kind`        — the cluster role (``page_save``, ``audio``,
                    ``cover_art``, ``artist_photo``, …).
  * `title`       — the original web title, with characters that
                    aren't filesystem-safe replaced by ``_``. May
                    contain runs of multiple underscores. Extension
                    included.

The fields are joined by ``__`` (two underscores). When `album` is
``_artist`` (leading underscore), the boundary between actor and
album shows up as ``___`` (three underscores) in the flattened name,
but a ``split('__', 3)`` followed by ``rstrip('_')`` on the actor
field handles both shapes uniformly.

This module emits suggested tag slugs into
``ingest_queue.enrichment_json.tags_proposed`` at queue time. The
emission vocabulary is anchored on the operator's existing
HR-cluster artifacts (MV-HR-20260416-001 … -014) so the suggestions
match the historical convention exactly. The mapping tables below
encode that convention.

Anchored references — do not drift without operator approval:
  * `docs/INGEST_BEHAVIOR_AUDIT-20260522-182616.md` §5.1 M5 (the
    mechanical bucket M5 belongs to).
  * `docs/CANONICAL_VOCABULARY.md` for the Tier 1/2/3 partition
    that determines where each emitted namespace surfaces in
    visitor-facing pill columns.
"""
from pathlib import Path
from typing import List

# Always-emitted tags per actor. Keys are the ReverbNation account
# slugs as they appear in the leading filename field. Values are
# the tag slugs the operator's existing HR-cluster artifacts carry
# in MV today (verified 2026-05-22 against live mediavault.sqlite at
# HEAD 74298a8: MV-HR-20260416-001..014 and MV-HR-20260416-008).
HR_ACTOR_TAGS = {
    "hunterroot2":    ["people:hunter_root", "source:reverbnation", "unsorted:solo"],
    "medusasdisco":   ["people:hunter_root", "source:reverbnation", "album:medusas_disco"],
    "runwiththehunt": ["people:hunter_root", "source:reverbnation", "album:run_with_the_hunt"],
}


def _kind_tags(kind: str, album_field: str) -> List[str]:
    """Tags derived from the `kind` field. Returns [] for kinds
    whose live-data precedent doesn't establish a kind-specific
    tag (cover_art, artist_photo) — those default to operator
    inbox triage per the audit brief §5.1 M5."""
    if kind == "page_save":
        # _artist sentinel (with or without the leading underscore the
        # filename flattening preserves) → artist-page; otherwise the
        # second field is a song-cluster slug → song-page.
        if album_field.lstrip("_") == "artist":
            return ["unsorted:artist_page"]
        return ["unsorted:song_page"]
    if kind == "audio":
        # Matches MV-HR-20260416-008's tag set exactly.
        return ["type:audio", "type:mp3"]
    # cover_art / artist_photo / unknown: no kind-specific tag emitted.
    # The operator's existing JPG artifacts in MV (e.g. MV-20260419-003)
    # tag visual cluster role manually in the inbox rather than
    # mechanically at ingest. See M5 run report for the audit trail.
    return []


def parse_hr_filename(name: str) -> List[str]:
    """Return a list of tag slugs to propose for the given filename,
    or [] if the name does not match the HR cluster grammar (so the
    caller can no-op without further checks)."""
    parts = name.split("__", 3)
    if len(parts) != 4:
        return []
    actor = parts[0].rstrip("_")
    if actor not in HR_ACTOR_TAGS:
        return []
    album_field = parts[1]
    kind = parts[2]
    out = list(HR_ACTOR_TAGS[actor])  # copy to avoid mutating the table
    out.extend(_kind_tags(kind, album_field))
    return out
