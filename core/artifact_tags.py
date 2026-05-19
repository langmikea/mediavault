"""
core/artifact_tags.py
=====================

The ONE coordinated writer for ``artifacts.tags`` per
DATA_ARCHITECTURE_SPEC_v2.1-target.md §4.5 / §4.5.1 (single-writer rule).

No other module may run SQL that writes ``artifacts.tags``. The
§4.5.1(b) grep-check (``tools/check_single_tag_writer.py``) enforces
this and fails the build if a second writer reappears. If you find
yourself wanting to ``UPDATE artifacts ... SET tags = ...`` or
``INSERT INTO artifacts(... tags ...) VALUES (...)`` elsewhere, the
answer is "call ``write_artifact_tags(conn, artifact_id, new_tags)``
instead." See §4.5 for the rationale (the v1.1 §8.4 overwriter bug
that motivated the rule).

Validation is stricter than MV's legacy ``slugify`` — per §3.1 / §3.2:
every tag MUST be namespaced ``namespace:value`` with both parts
non-empty, namespace ``[a-z0-9_]+`` (no hyphen), value ``[a-z0-9_-]+``
(hyphen allowed), exactly one ``:``. Bare slugs are REJECTED via
``TagValidationError``, not silently dropped. That asymmetry to
``slugify`` is intended (see §3.2: writers reject; only consumers drop
defensively as a backstop).
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime
from typing import Iterable


# §3.1 form. The first-colon split is defense-in-depth; the value
# pattern still forbids extra colons inside the value.
_NS_RE = re.compile(r"^[a-z0-9_]+$")
_VAL_RE = re.compile(r"^[a-z0-9_-]+$")


class TagValidationError(ValueError):
    """A tag failed §3.1 form. Carries the offending tag and reason
    so the handler can return a useful 400 to the caller."""

    def __init__(self, tag, reason: str):
        super().__init__(f"invalid tag {tag!r}: {reason}")
        self.tag = tag
        self.reason = reason


def _validate_tag(tag) -> str:
    """Enforce §3.1 form. Raise TagValidationError on any failure.

    Returns the original string unchanged when valid (this function
    does not normalize — callers that want lowercase/whitespace fixups
    should do that before calling)."""
    if not isinstance(tag, str):
        raise TagValidationError(tag, "not a string")
    if ":" not in tag:
        # §3.2: bare slugs are rejected, not silently dropped.
        raise TagValidationError(tag, "bare slug (no namespace:) — §3.1 / §3.2")
    ns, _, val = tag.partition(":")
    if not ns:
        raise TagValidationError(tag, "empty namespace")
    if not val:
        raise TagValidationError(tag, "empty value")
    if ":" in val:
        # §3.1: a value MUST NOT contain ':' — no escaping mechanism exists.
        raise TagValidationError(tag, "value contains ':' (forbidden by §3.1)")
    if not _NS_RE.match(ns):
        raise TagValidationError(tag, f"namespace {ns!r} not [a-z0-9_]+")
    if not _VAL_RE.match(val):
        raise TagValidationError(tag, f"value {val!r} not [a-z0-9_-]+")
    return tag


def validate_artifact_tags(tags) -> list:
    """Pre-validate a tag list per §3.1 and return a deduped, sorted
    canonical list. Raises TagValidationError on any failure (no
    silent drops). Useful when the caller wants the clean tag list
    before calling write_artifact_tags — e.g. to upsert novel vocab
    rows so the usage-count cache update lands on existing rows."""
    return sorted({_validate_tag(t) for t in (tags or [])})


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def write_artifact_tags(conn: sqlite3.Connection,
                        artifact_id: str,
                        new_tags: Iterable) -> dict:
    """The single permitted code path that writes ``artifacts.tags``.

    Parameters
    ----------
    conn : sqlite3.Connection
        Caller-supplied connection. This function does NOT commit —
        the caller controls transaction boundaries so this composes
        inside larger handler transactions (e.g. Vocab Admin sweeps
        that touch many artifacts in one go).
    artifact_id : str
        The MV-style artifact id (``MV-YYYYMMDD-NNN`` or legacy
        ``MV-XX-YYYYMMDD-NNN``). Looked up against ``artifacts.id``.
    new_tags : Iterable
        The complete target tag set for the artifact. Each tag is
        validated against §3.1 (see ``_validate_tag``). Validation
        failure aborts before any write.

    Returns
    -------
    dict
        ``{"added": [...], "removed": [...], "tags": [...]}`` — the
        diff against the existing row plus the final canonical
        (deduped, sorted) tag list.

    Raises
    ------
    TagValidationError
        Any tag in ``new_tags`` failed §3.1 form. No row is written.
        The handler should surface this as a 400 to the caller.
    LookupError
        ``artifact_id`` does not exist in ``artifacts``.

    Side effects
    ------------
    - Writes ``artifacts.tags`` (JSON-encoded sorted list) and
      ``artifacts.updated_at`` for the row.
    - Refreshes the per-slug ``tags.usage_count`` cache for just the
      diff: ``+1`` on each added slug, ``-1`` (floored at 0) on each
      removed slug. The cache is §5.2's demoted usage-count cache.

    Does NOT register novel slugs in the vocabulary. Callers that
    want a novel slug to surface in Vocab Admin (e.g. fresh inbox
    saves, register-endpoint POSTs) should ``upsert_tag(..., is_proposed=1)``
    before calling this writer. Doing the upsert here would couple
    every Vocab Admin sweep to the upsert path, which is wrong —
    sweeps mutate existing vocab and shouldn't auto-create new rows.
    """
    # Validate everything first — abort before any write if any tag fails.
    # §3.2: reject malformed, don't silently drop.
    validated = [_validate_tag(t) for t in (new_tags or [])]

    # Tags are a set (§3.2); the single coordinated writer deduplicates.
    deduped = sorted(set(validated))

    # Diff against current row.
    row = conn.execute(
        "SELECT tags FROM artifacts WHERE id=?", (artifact_id,)
    ).fetchone()
    if row is None:
        raise LookupError(f"artifact {artifact_id!r} not found")
    raw = row[0] if not hasattr(row, "keys") else row["tags"]
    try:
        old_tags = json.loads(raw or "[]")
    except Exception:
        old_tags = []
    old_set = set(old_tags)
    new_set = set(deduped)
    added = sorted(new_set - old_set)
    removed = sorted(old_set - new_set)

    # The ONE write to artifacts.tags in the entire codebase.
    conn.execute(
        "UPDATE artifacts SET tags=?, updated_at=? WHERE id=?",
        (json.dumps(deduped), _now_iso(), artifact_id),
    )

    # Refresh the §5.2 usage-count cache for just the diff.
    # Slugs not in the tags table simply receive 0-row updates, which
    # is correct: this writer doesn't auto-create vocab rows (see
    # docstring) and the cache is recomputable at any time.
    for slug in added:
        conn.execute(
            "UPDATE tags SET usage_count=usage_count+1 WHERE slug=?",
            (slug,),
        )
    for slug in removed:
        conn.execute(
            "UPDATE tags SET usage_count=MAX(0,usage_count-1) WHERE slug=?",
            (slug,),
        )

    return {"added": added, "removed": removed, "tags": deduped}
