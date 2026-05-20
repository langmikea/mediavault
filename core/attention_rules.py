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
                   vocab: dict[str, dict] | None = None) -> list[str]

`pill_states` maps slug -> one of {"on_confident", "on_uncertain",
"off_suspected", "off_maybe"}. Only on_* states count toward "this pill
is on the artifact".

`vocab` is retained as an optional argument for backward compatibility
with v0.5 callers (the frontend was the only one and shipped a
`{slug: {"category": ..., "is_proposed": ...}}` blob). Post-Phase-2.1
of the source-of-truth refactor, namespace metadata lives in the slug
itself (`namespace:value`, per §5.4 of the v2.1-target spec) -
the function no longer reads any field from `vocab`. The parameter is
kept to preserve the call-site signature; new callers should pass None.

The return value is a list of warning slugs, each of the form
"missing_category:<name>" or "missing_field:<name>". The inbox code keys
on the prefix to decide whether to glow a category section (for
missing_category) or a field control (for missing_field).

Note on the warning labels: the prefix "missing_category" is retained
verbatim so the JS port in mediavault.html and any persisted warning
records stay readable. In the post-Phase-2.1 model "category" is the
slug's namespace prefix.
"""

from __future__ import annotations
import re

# Namespace identifiers the UI knows how to highlight. Post-Phase-2.1
# these are namespace values in the §5.4 `vocabulary` registry
# (or, for `bands`, a legacy alias kept so historical warning slugs stay
# readable). Band names migrate to the `people` namespace under the
# v2.1-target model.
NAMESPACE_PEOPLE   = "people"
NAMESPACE_SCOPE    = "scope"
NAMESPACE_CONTENT  = "content_kind"

# Backward-compat aliases for v0.5 callers that imported the old names.
CATEGORY_PEOPLE   = NAMESPACE_PEOPLE
CATEGORY_BANDS    = "bands"   # legacy category; mapped to `people` at the rule.
CATEGORY_SCOPE    = NAMESPACE_SCOPE
CATEGORY_CONTENT  = NAMESPACE_CONTENT

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


def _pills_in_namespace(on_slugs: set[str], namespace: str) -> int:
    """Count `on` pills whose slug carries the given namespace prefix.

    Post-Phase-2.1 of the source-of-truth refactor: namespace lives in
    the slug itself (e.g. ``people:hunter_root``), not in a separate
    metadata dict. The legacy `_pills_in_category(on, vocab, cat)` is
    superseded by this - the legacy `vocab[slug] = {"category": ...}`
    blob is no longer needed because the slug self-describes its
    namespace.
    """
    if not namespace:
        return 0
    prefix = namespace + ":"
    n = 0
    for slug in on_slugs:
        if isinstance(slug, str) and slug.startswith(prefix):
            n += 1
    return n


def evaluate_rules(artifact_fields: dict | None,
                   pill_states: dict | None,
                   vocab: dict | None = None) -> list[str]:
    """Return warning slugs for this artifact's current state.

    Warnings use these prefixes:
      - "missing_field:<name>"      - glow the named field control
      - "missing_category:<name>"   - glow the named pill-wall section

    `vocab` is accepted for backward compat (see module docstring) and
    is ignored - namespace is read from the slug itself.
    """
    del vocab  # see module docstring; kept for signature compatibility.
    fields = artifact_fields or {}
    on = _pills_on(pill_states)
    warnings: list[str] = []

    # R1 - social-platform posts should have a post_date.
    platform = (fields.get("source_platform") or "").lower()
    post_date = fields.get("post_date")
    if platform in SOCIAL_PLATFORMS and not post_date:
        warnings.append("missing_field:post_date")

    # R2 - top-level photo/video needs a content_kind pill.
    media_type = (fields.get("media_type") or "").lower()
    parent = fields.get("parent_artifact_id")
    if media_type in ("photo", "video") and not parent:
        if _pills_in_namespace(on, NAMESPACE_CONTENT) == 0:
            warnings.append(f"missing_category:{NAMESPACE_CONTENT}")

    # R3 - description mentions a Title-Case bigram but no people pills.
    # Under v2.1-target band names live in the `people` namespace, so
    # the legacy "people or bands" disjunct collapses to a single check.
    desc = " ".join(str(fields.get(k) or "") for k in
                    ("description_short", "description_long", "extracted_text"))
    if _TITLECASE_BIGRAM.search(desc):
        if _pills_in_namespace(on, NAMESPACE_PEOPLE) == 0:
            warnings.append("missing_category:people_or_bands")

    # R4 - extension captures should be scoped.
    if (fields.get("ingest_source") or "") == "extension-capture":
        if _pills_in_namespace(on, NAMESPACE_SCOPE) == 0:
            warnings.append(f"missing_category:{NAMESPACE_SCOPE}")

    # R5 - any pill is on but media_type is empty.
    if on and not media_type:
        warnings.append("missing_field:media_type")

    return warnings


__all__ = ["evaluate_rules"]
