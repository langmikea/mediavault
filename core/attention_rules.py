"""
attention_rules.py — MediaVault v0.5

Five hardcoded rules that surface "this artifact is missing something"
warnings in the inbox. Warnings are soft: the operator can save anyway,
the warning just glows next to the relevant control or section.

Rules live here rather than in a DB table because the set is small, stable,
and revisions want code review. Adding a rule is a code edit; no schema
change, no admin UI. YAGNI (design §4.5).

Public surface:
    evaluate_rules(artifact_fields: dict, pill_states: dict,
                   vocab: dict[str, dict]) -> list[str]

`pill_states` maps slug → one of {"on_confident", "on_uncertain",
"off_suspected", "off_maybe"}. Only on_* states count toward "this pill
is on the artifact".

`vocab` maps slug → {"category": str|None, "is_proposed": int}. The
frontend ships this along when it calls the rules engine; we don't open
the DB from here.

The return value is a list of warning slugs, each of the form
"missing_category:<name>" or "missing_field:<name>". The inbox code keys
on the prefix to decide whether to glow a category section (for
missing_category) or a field control (for missing_field).
"""

from __future__ import annotations
import re

# Categories the UI knows how to highlight.
CATEGORY_PEOPLE   = "people"
CATEGORY_BANDS    = "bands"
CATEGORY_SCOPE    = "scope"
CATEGORY_CONTENT  = "content_kind"

SOCIAL_PLATFORMS  = {"facebook", "instagram", "tiktok", "reverbnation"}

# A bigram of Title-Case words, heuristic for "mentions a named person or band".
_TITLECASE_BIGRAM = re.compile(r"\b[A-Z][a-z]+ [A-Z][a-z]+\b")


def _pills_on(pill_states: dict | None) -> set[str]:
    """Return slugs whose pill_state is on_confident or on_uncertain."""
    if not isinstance(pill_states, dict):
        return set()
    return {
        slug for slug, state in pill_states.items()
        if state in ("on_confident", "on_uncertain")
    }


def _pills_in_category(on_slugs: set[str], vocab: dict | None, category: str) -> int:
    """Count `on` pills whose vocab row has the given category."""
    if not vocab:
        return 0
    n = 0
    for slug in on_slugs:
        row = vocab.get(slug)
        if row and row.get("category") == category:
            n += 1
    return n


def evaluate_rules(artifact_fields: dict | None,
                   pill_states: dict | None,
                   vocab: dict | None = None) -> list[str]:
    """Return warning slugs for this artifact's current state.

    Warnings use these prefixes:
      - "missing_field:<name>"      — glow the named field control
      - "missing_category:<name>"   — glow the named pill-wall section
    """
    fields = artifact_fields or {}
    on = _pills_on(pill_states)
    warnings: list[str] = []

    # R1 — social-platform posts should have a post_date.
    platform = (fields.get("source_platform") or "").lower()
    post_date = fields.get("post_date")
    if platform in SOCIAL_PLATFORMS and not post_date:
        warnings.append("missing_field:post_date")

    # R2 — top-level photo/video needs a content_kind pill.
    media_type = (fields.get("media_type") or "").lower()
    parent = fields.get("parent_artifact_id")
    if media_type in ("photo", "video") and not parent:
        if _pills_in_category(on, vocab, CATEGORY_CONTENT) == 0:
            warnings.append(f"missing_category:{CATEGORY_CONTENT}")

    # R3 — description mentions a Title-Case bigram but no people/bands pills.
    desc = " ".join(str(fields.get(k) or "") for k in
                    ("description_short", "description_long", "extracted_text"))
    if _TITLECASE_BIGRAM.search(desc):
        if (_pills_in_category(on, vocab, CATEGORY_PEOPLE) == 0 and
                _pills_in_category(on, vocab, CATEGORY_BANDS) == 0):
            warnings.append("missing_category:people_or_bands")

    # R4 — extension captures should be scoped.
    if (fields.get("ingest_source") or "") == "extension-capture":
        if _pills_in_category(on, vocab, CATEGORY_SCOPE) == 0:
            warnings.append(f"missing_category:{CATEGORY_SCOPE}")

    # R5 — any pill is on but media_type is empty.
    if on and not media_type:
        warnings.append("missing_field:media_type")

    return warnings


__all__ = ["evaluate_rules"]
