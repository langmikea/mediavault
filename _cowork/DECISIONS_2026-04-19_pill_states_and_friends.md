# Decisions — 2026-04-19

**Context:** Working session with Claude following `REVIEW_v06.md` and `PILL_STATES_INVESTIGATION.md`. The review surfaced four intent ambiguities in the MediaVault codebase — places where the SPEC, the schema, the handlers, and the frontend had drifted from each other because no one had made the underlying product call. This document records the calls.

**Purpose:** Permanent reference. Before any code work touches these areas, read this first. Before SPEC is updated, read this first. If a future decision seems to contradict one of these, that's a discussion, not a silent override.

**Status:** Decisions are final. Implementation has not started. SPEC has not yet been reconciled.

---

## 1. Pill lifecycle

**Decision:** Three states during review (on / suggested / off). Auto-confirm on save. Session-only — no persistence of the middle state.

**What this means:**
- The enrichment AI proposes tags. Proposed tags land in the "suggested" middle state.
- During inbox review, you can confirm (→ on), reject (→ off), or leave as suggested.
- On save, anything still in the suggested state becomes on. The middle state is a review aid only.
- The artifact persists plain on/off tag associations through `artifact_tags`. No provenance (AI vs manual) is recorded.
- Re-queuing an artifact preserves its current on tags. The AI may re-propose additional ones into the suggested state during re-review.

**Why:** The rich five-state model the code half-implemented (`on_confident`, `on_uncertain`, `off_suspected`, `off_maybe`) encoded nuance that didn't pay for itself at save time — the distinction collapsed anyway once pills persisted. Three states cover the actual review decisions being made (accept, reject, didn't-look-yet) without carrying dead metadata forward.

**Why auto-confirm:** If the AI proposes 10 pills and you only review 3, auto-confirm ships all 10. The tradeoff is accepted: AI tends to land close enough that silent acceptance is cheaper than the per-artifact review cost of mandatory confirm-or-drop. If AI accuracy degrades later, revisit.

**Schema impact:** No `pill_states` column on `artifacts`. Remove any SPEC language that implies one. Frontend stops sending `pill_states` in the save payload.

---

## 2. Slug uniqueness

**Decision:** Global uniqueness. One slug, one tag. Category is descriptive metadata, not part of tag identity.

**What this means:**
- The `tags` table reverts to `slug` as the unique key (which it already is — the composite `(slug, category)` constraint was an addition to revert).
- `hunter_root` cannot simultaneously exist in `bands` and `people`. The current duplicate is a bug to be resolved by merging.
- Renaming a tag to a slug that already exists triggers a merge offer, regardless of category.
- Lookups everywhere key on slug alone.

**Why:** No concrete case was identified where two tags genuinely needed to share a slug. Hunter Root the band vs Hunter Root the person is one entity wearing different category hats, not two tags. Every case that came to mind resolved the same way: same entity, different categorization.

**The forever-tax of composite uniqueness** — having to qualify "which `hunter_root`?" in every lookup, every UI surface, every export — is not worth paying for flexibility with no known use.

**Schema impact:** Revert the composite `UNIQUE(slug, category)` constraint to `UNIQUE(slug)` (restore the primary key behavior). Resolve the existing `hunter_root` duplicate by merging. Restore `ingest_engine.upsert_tag`'s `ON CONFLICT(slug)` clause to correctness.

---

## 3. `is_proposed`

**Decision:** Remove. One-stage vocabulary.

**What this means:**
- A tag exists because an artifact was saved using it. That act is the tag's approval.
- There is no "proposed → accepted" workflow. No curation backlog. No staging area.
- The `is_proposed` column, the `PROPOSED` filter button in the Tag Manager, and the `MARK AS PROPOSED` checkbox in the Create Pill dialog all go away.

**Why:** The proposed/accepted distinction duplicates the inbox's curation role. The inbox already decides what gets saved; the tags carried along for the ride are implicitly approved by that decision. A second curation stage at the tag level adds workflow cost without corresponding clarity.

**Schema impact:** Drop `is_proposed` from `tags`. Simplify the Tag Manager filter row from `ALL / PROPOSED / ACCEPTED / UNUSED` to `ALL / UNUSED`. Remove the checkbox from the Create Pill dialog (which simplifies the layout fix from the v0.6 punchlist — only `EXCLUSIVE WITHIN CATEGORY` remains).

---

## 4. `archived_at`

**Decision:** Ship it. Saved-but-hidden. Always reversible.

**What this means:**
- Artifacts in the vault can be archived. Archiving sets `archived_at` to a timestamp.
- Default vault views filter out artifacts where `archived_at IS NOT NULL`. A toggle reveals them.
- Un-archiving sets `archived_at` back to NULL. One click, no gates beyond "are you sure."
- Archive is a post-save vault operation, not an inbox state. The inbox still has three fates: SCRAP / SAVE / RELEASE.
- Archived artifacts keep their tags, metadata, and file intact. Nothing but the timestamp distinguishes them.

**Why:** "I want to keep this but not show it right now" is a real thought. The alternatives (scrap-then-regret, or leave-in-vault-and-live-with-the-clutter) are both worse. Saved-but-hidden is the simplest model that captures the intent without overlapping with SCRAP or introducing a new state machine.

**Why timestamp-as-flag:** A single `archived_at` column serves both purposes — NULL means not archived, any value means archived at that moment. No separate boolean needed. The timestamp is also useful information (when did I tuck this away?) that costs nothing to keep.

**Schema impact:** Add `archived_at TEXT NULL` to `artifacts`. This is the column SPEC already implied; the migration just needs to actually happen. Add the default view filter on vault queries. Add the archive/unarchive UI entry point in the vault.

---

## 5. Re-queue semantics (clarification, not ambiguity)

**Decision:** Re-queuing an artifact sends it back to the inbox with its current tags preserved. Re-enrichment may propose additional tags into the suggested state. Your prior on/off decisions for persisted tags are kept.

**What this means:**
- Re-queue is not a reset. It's "give me another pass at this."
- The inbox review session that follows starts with all currently-on tags already on.
- If you run enrichment again, new AI suggestions land in the suggested middle state — they don't overwrite your confirmed tags.
- This is consistent with the three-state / auto-confirm model: confirmed is confirmed until you change it.

**Why this is here:** Was briefly mis-stated during the working session as "clean slate." Correcting for the record. This was never actually ambiguous in the code — it's clarified here because the conversation touched it.

---

## What this unlocks

With these decisions landed, the following work becomes specifiable:

1. **SPEC reconciliation.** SPEC is wrong in at least three places (`pill_states` as a column, `is_proposed` as a feature, composite uniqueness). SPEC needs a pass against this document before any code ships.

2. **A v0.7 punchlist** focused on subtraction and reconciliation. The bulk of this work is deletion (`pill_states`, `is_proposed`, composite constraint) plus one small addition (`archived_at`). This is meaningfully smaller than v0.6.

3. **Merge the duplicate `hunter_root` row.** One-time data fix, part of the slug-uniqueness revert. Pick the row to keep (probably the `bands` row based on usage patterns, but verify), move associations, delete the loser.

4. **Handler audit.** The v0.6 review found handlers partially updated for composite uniqueness. Reverting means subtracting those changes. Mechanical but careful work.

Execution order, proposed: SPEC reconciliation first (so the next session has a correct spec to read), then v0.7 punchlist, then implementation.

---

## Review pointers

For the next session that touches any of this:

- `REVIEW_v06.md` — full review; its "Data layer" and "Intent ambiguities" sections were the input for these decisions.
- `PILL_STATES_INVESTIGATION.md` — the deep dive that resolved Q1 and contributed to Q2.
- `PUNCHLIST_v06.md` — historical; item #3 (slug uniqueness per category) is now superseded by the decision in §2 above. Do not execute v0.6 #3 as written. The merge-on-rename flow it describes is still correct — it just applies globally, not per-category.

If a future decision contradicts anything in this document, the contradiction gets discussed explicitly, not absorbed silently. These aren't sacred, but they're not wallpaper either.
