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
