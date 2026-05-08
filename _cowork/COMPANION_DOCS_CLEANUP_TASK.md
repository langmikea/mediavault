# Follow-up — Companion docs cleanup

**Status:** Small task. Document edits only.
**Follows:** `SPEC_RECONCILIATION_SUMMARY.md` (2026-04-19).
**Scope:** Two files cowork explicitly left alone, flagged for Mike's call. Mike confirmed both should be updated.

---

## Context

The SPEC reconciliation session correctly left `MEDIAVAULT_V05_DESIGN.md` and `STATE.md` untouched and flagged them in the summary. Mike reviewed the summary and confirmed both need updates. Neither change is a rewrite — they're small notes that keep future sessions from treating stale content as current.

---

## Task 1 — Supersede banner on `MEDIAVAULT_V05_DESIGN.md`

**File:** `C:\AI\Platform\MediaVault\MEDIAVAULT_V05_DESIGN.md` (verify path — adjust if the file lives elsewhere under the MediaVault tree).

**What to do:** Add a banner at the very top of the file, before any existing content. Do not modify or remove any existing sections.

**Banner text (use this exactly, adjusting today's date):**

```
---

> **SUPERSEDED IN PART — 2026-04-19**
>
> Sections §§2, 3.4, 3.5, 4.1, 4.4, 6 contain historical design rationale
> that no longer reflects current behavior. For current behavior, read
> `SPEC.md` and `_cowork/DECISIONS_2026-04-19_pill_states_and_friends.md`.
>
> The rest of this document is preserved as a record of v0.5 design thinking,
> valid in its moment.

---
```

**Why this shape:** The banner explicitly names the stale sections (so a future reader knows exactly what to distrust) and points at the two documents that do reflect current state. The "valid in its moment" framing preserves the historical value without implying current authority.

**Do not** rewrite the stale sections. Do not add inline warnings inside each stale section. One banner at the top is enough.

---

## Task 2 — Refresh `STATE.md`

**File:** `C:\AI\Platform\MediaVault\STATE.md` (verify path).

**What to do:** STATE.md is used at the start of sessions for orientation and should reflect *current* state at all times. Its existing "DECISIONS THIS SESSION" block (or equivalent) contradicts the decisions made on 2026-04-19. Two edits:

### Step 2a — Mark the existing block as superseded

Find the existing decisions block (whatever it's currently titled — "DECISIONS THIS SESSION", "RECENT DECISIONS", etc.). Add a short note at the top of that block:

```
> SUPERSEDED by the 2026-04-19 decisions block below. Left in place as
> historical record of the thinking that preceded the review and
> reconciliation pass.
```

Do not delete the old block content. It's history.

### Step 2b — Add a fresh current-state block

Directly above the superseded block, add a new current-decisions block dated today. Structure it the same way STATE.md's existing blocks are structured (match the existing format — don't invent a new format). Content should summarize the four decisions from `DECISIONS_2026-04-19_pill_states_and_friends.md` at a level appropriate for orientation — not full reasoning, just the calls.

Rough content (adapt to STATE.md's house style):

```
## 2026-04-19 — Current decisions

Following REVIEW_v06.md and four intent-ambiguity resolutions:

- **Pill lifecycle:** Three states (on / suggested / off). Auto-confirm on save.
  Session-only — no `pill_states` column.
- **Slug uniqueness:** Global. One slug, one tag. Category is descriptive metadata.
- **`is_proposed`:** Removed. One-stage vocabulary.
- **`archived_at`:** Saved-but-hidden. Always reversible. Real column on artifacts.

Full reasoning: `_cowork/DECISIONS_2026-04-19_pill_states_and_friends.md`
SPEC reconciled same day.

Next: v0.7 punchlist (not yet written).
```

---

## Rules

- Document edits only. No code changes. No schema changes.
- Do not modify any file outside the two named above.
- If either file has moved or doesn't exist where expected, find it (grep under `C:\AI\Platform\MediaVault\`) before deciding it's missing. Only report missing if it genuinely isn't there.
- Before starting, check `C:\AI\BUILD_LOCK.txt`. If unlocked, take the lock with session name "companion docs cleanup". Release when done.
- When finished, do not produce a separate summary document — this task is small enough that a short in-chat confirmation is sufficient. Just tell Mike: which files you edited, a one-line description of each edit, and anything you noticed that was unexpected.

Stop when both files are updated. Do not start the v0.7 punchlist.
