# SPEC Reconciliation Summary — 2026-04-20

**Reconciled against:** `_cowork/DECISIONS_2026-04-19_pill_states_and_friends.md`
**Performed by:** Claude (Cowork session "SPEC reconciliation")
**Build lock:** held for the duration; released on completion.
**Scope:** document edits only. No code, schema, or handler changes.

---

## Files edited

### 1. `SPEC.md`

- Added a dated reconciliation note at the top pointing at the decisions
  doc and summarizing the four corrections.
- **§2.1** — removed the "replaces v0.4's cosmetic `group_name`"
  parenthetical.
- **§2.2 Pill Vocabulary** — removed the `is_proposed` row from the tags
  table; dropped the "Replaces v0.4 `group_name`" caption on the category
  column; added an explicit global-slug-uniqueness note on the `slug`
  row; added a tail paragraph stating that a tag exists because an
  artifact was saved using it (no proposed/accepted workflow).
- **§2.3** — replaced the **Five-State Pill Model (inbox)** wholesale
  with a **Three-State Pill Model (inbox, session-only)** per decisions
  §1. Called out explicitly: no `pill_states` column, no `pill_states`
  key in the save payload, auto-confirm on save, no provenance recorded.
- **§2.5 Proposed-Pill Flow** → retitled **Novel-Pill Flow (one-stage
  vocabulary)**. Removed all `is_proposed` references. Added the
  rename-triggers-merge note. Stated the Tag Manager filter row is
  `ALL / UNUSED`.
- **§4 Lifecycle Status** — removed `archived` from the status enum;
  added a clarifying sentence that the inbox has three fates
  (SCRAP / SAVE / RELEASE) and archive is a post-save vault operation;
  removed the `vault ↔ archived` transitions from the table since they
  no longer describe status changes.
- **§4.1 Archive (`archived_at`)** — new subsection per decisions §4:
  timestamp-as-flag, always reversible, default views filter
  `archived_at IS NOT NULL`, entry point lives in the vault detail
  panel, archived rows keep tags/metadata/file intact.
- **§6 Catalog Record Schema** — dropped the `pill_states TEXT` column
  from the `artifacts` table; dropped the `is_proposed INTEGER` column
  from the `tags` table; added a comment on `tags.slug` affirming
  global uniqueness; updated the `status` comment to omit `archived`.
- **§8.1 Panes** — Vault default filter now described as
  `status IN (vault, released)` AND `archived_at IS NULL`, with a toggle
  to reveal archived; Vocab Admin pane description rewritten to drop
  "separated into proposed and accepted" and describe the new
  `ALL / UNUSED` filter row and per-pill controls.
- **§8.2 Vault Filter Bar** — added a **Show archived** toggle (default
  off).
- **§8.4 Pill Wall** — pill-state rendering updated from five states to
  three (`on` / `suggested` / `off`); novel-slug behavior stated as
  "created immediately and applied as `on`" (no `is_proposed=1`); added
  the "one slug, one tag" disambiguation note.
- **§10 Architecture Decisions** — rewrote three rows and added two:
  - Pill model — now describes three session-only states and
    auto-confirm-on-save; spells out that `artifacts.tags` stores plain
    on/off associations.
  - Tag lifecycle (new row) — one stage; saving implicitly approves.
  - Slug uniqueness (new row) — global, one slug one tag.
  - Lifecycle — status values now `inbox | vault | released | deleted`;
    explicit note that archive is orthogonal via `archived_at`.
  - Archive (new row) — saved-but-hidden, default-hidden, reversible.
- **§12.2 v0.4 → v0.5 migration** — removed the "add `pill_states`
  (JSON)" bullet from the phase-1 column list; removed the "from old
  `group_name` semantics where possible" parenthetical. Added a
  historical note clarifying that v0.5 as shipped did create a
  `pill_states` column, which the v0.7 punchlist drops.
- **§12.5 Attention Rules** — reworded the public-function description
  so `pill_states` is identified as the session-only in-memory review
  state map, not a persisted column; removed the `is_proposed` field
  from the `vocab` slice description; updated the "on" criterion to
  `on` or `suggested` (matching the auto-confirm-on-save rule).
- **§13 Known Tradeoffs** — rewrote the v0.4 backward-compat bullet so
  it no longer references a `_upgrade_v04_enrichment_to_pill_states`
  function or persistence of pill states; now describes projecting old
  shapes into the in-memory three-state map.
- **§14 Hard Rules** — replaced the "Proposed pills are applied
  immediately; Vocab Admin is the cleanup path" rule with four new
  rules: global slug uniqueness, one-stage vocabulary, session-only
  pill review states, and archive-via-`archived_at`-flag.

### 2. `PROJECT.md`

- Added a dated reconciliation note at the top.
- **Core mental model (v0.5)** — rewrote the pill-state paragraph
  (five-state → three-state session-only, auto-confirm-on-save, no
  persistence); rewrote "Proposed pills" as **One-stage tag
  vocabulary**; added a global-slug-uniqueness sentence; added a new
  **Archive** paragraph describing `archived_at`; updated the lifecycle
  status bullet (archive is no longer in the status enum).
- **Done When** — removed "introduced the proposed-tag workflow" from
  the v0.4 line; removed "introduced the five-state inbox pill model"
  from the v0.5 line; added a paragraph summarizing the four v0.7
  subtractions that land the decisions doc.

### 3. `WORKFLOW.md`

- Added a dated reconciliation note at the top.
- **The lifecycle** — removed `archived` from the status diagram and
  enum; added a paragraph explaining archive as a separate flag
  (`archived_at`) with a "Show archived" toggle.
- **Pill states (inbox)** → retitled **Pill states (inbox, session-only)**.
  Collapsed the five-state table to three (`on` / `suggested` / `off`);
  rewrote the click-flip behavior; stated explicitly that the state is
  not saved and that `suggested` auto-confirms on save; removed the
  "pill_states for round-trip fidelity" sentence.
- **Adding a new pill** — rewrote so novel slugs create the tag
  immediately and apply it as `on` (no `is_proposed=1`, no "proposed"
  label); added a sentence on global slug uniqueness.
- **Author convention** — changed the auto-synthesized state from
  `on_uncertain` to `suggested`.
- **Save to Vault** action description — dropped "persists the full
  pill state map" and stated that session state is not persisted;
  clarified that on + suggested are both written to `artifacts.tags`.
- **Detail panel buttons** — Archive / Requeue → Archive / Unarchive;
  clarified that archive sets/clears `archived_at` and leaves status
  alone.
- **Vocab Admin** — removed the `proposed / accepted` status column and
  the Accept control; added the `ALL / UNUSED` filter row; noted that
  rename collisions offer a merge.
- **Common flows** — updated the "50 screenshots" flow to match the new
  auto-confirm semantics; added a new "tuck this away" flow for
  archive; updated the bulk-delete flow to say "UNUSED" instead of
  "proposed pills."

---

## Files reviewed but NOT edited

These are in the MediaVault tree and carry overlapping language, but
editing them felt like overreach — they're historical records or
rationale documents, not current-intent specifications. Flagging here so
Mike can decide whether any need a pass.

- **`MEDIAVAULT_V05_DESIGN.md`** — explicitly listed as SPEC's
  "Companion design doc" in the SPEC header, and called out in
  PROJECT.md and README.md as live reference material. Several sections
  are now stale against the decisions doc: §2 (five pill states vs
  three), §3.4 (`enrichment_json.pill_states` convention — the
  convention survives as session-only but the framing is off), §3.5
  (final schema still shows `is_proposed` and doesn't show
  `archived_at`), §4.1 (pill-wall layout uses the five-state legend),
  §4.4 (add-pill creates with `is_proposed=1`), §6 (enrichment prompt
  emits `pill_states` into a persisted shape). If Mike wants this doc
  kept truthful going forward, it wants a proper pass; if he treats it
  as a v0.5 historical record, a single superseding note at the top
  would be enough. I didn't do either without instruction.
- **`STATE.md`** — describes v0.5 as shipped. The **DECISIONS THIS
  SESSION** block says "Pill states are per-artifact, not per-vocab. The
  vocab row holds category + exclusivity; the artifact holds the state
  map," which directly contradicts the new decisions doc. The **Headline
  changes** block describes the five-state model. Since STATE.md is a
  rolling session log, the natural fix is a new session entry that
  records the 2026-04-19 corrections; that'll happen when v0.7 work
  starts. For now it reads as a stale snapshot.
- **`README.md`** — v0.5 package README. Describes the five-state pill
  model under "What v0.5 changes" and references `group_name → category`.
  Historical deploy notes — probably fine to leave.
- **`COWORK_BRIEF_v05.md`** — v0.5 execution brief for the cowork
  session that shipped v0.5. Historical.
- **`COWORK_BRIEF.md`** — v0.4-era brief. Full of `group_name` and
  `is_proposed=1`. Historical.
- **`MEDIAVAULT_V04_DESIGN.md`** — v0.4 historical design doc.
- **`_cowork/PHASE_SUMMARY*.md`, `_cowork/PILL_STATES_*`,
  `_cowork/REVIEW_v06.md`, `_cowork/PUNCHLIST_v06.md`,
  `_cowork/mv_v05_audit_*`** — `_cowork/` historical artifacts; the
  decisions doc itself points at REVIEW_v06 and PILL_STATES_INVESTIGATION
  as inputs. Not touched.

---

## Surprises / contradictions / things that want Mike's eyes

1. **The `archived` status value was redundant with the `archived_at`
   column.** Before reconciliation, SPEC's artifacts table had both
   `status ∈ {..., archived, ...}` AND an `archived_at TEXT` column, and
   the lifecycle section described `vault ↔ archived` transitions. The
   decisions doc §4 clearly treats archive as a column-level flag
   (`archived_at IS NOT NULL`) independent of status — archived rows
   should keep their prior status. I removed `archived` from the status
   enum in SPEC so the two models stop fighting. **But the decisions
   doc doesn't explicitly say to drop `archived` from the status enum**;
   that's my inference from the "saved-but-hidden, keep status intact"
   framing. Worth a sanity-check: is status remaining `vault` during
   archive what Mike intended, or does he want archive to flip status
   as well? If the former, the v0.7 punchlist will have to migrate any
   existing `status='archived'` rows back to `vault` and also drop
   `archived` from any CHECK constraints in code.

2. **Composite `(slug, category)` uniqueness was never in SPEC.** The
   decisions doc §2 says to remove composite uniqueness language from
   SPEC, but SPEC only ever had `slug TEXT PRIMARY KEY` — the composite
   constraint was a code-level addition that never made it into the
   spec. Nothing to subtract here; I added an affirmative
   global-uniqueness note to §2.2 and §14 to preclude it being added
   back. The actual constraint in code is the v0.7 punchlist's job.

3. **`_upgrade_v04_enrichment_to_pill_states()` (§13, pre-edit).** The
   original bullet referenced a function by name that was presumably
   written around the now-removed `pill_states` persistence. I
   rephrased the bullet to describe the correct in-memory behavior,
   but the function name itself lives in code and will want renaming
   when the column is dropped. Noting here; not a spec-edit concern.

4. **`evaluate_rules(..., pill_states, vocab)` parameter names (§12.5).**
   The attention-rules function takes a parameter named `pill_states`.
   With the persisted column gone, that name is a little confusing —
   it's now the in-memory session map. I documented it that way but
   didn't propose a rename. Code can keep the name or rename to
   `pill_review_state`, `session_pills`, or similar. Flagging in case
   the v0.7 punchlist touches this file.

5. **The MEDIAVAULT_V05_DESIGN.md question** (see "Files reviewed but
   NOT edited"). The decisions doc calls for SPEC reconciliation, but
   PROJECT.md, WORKFLOW.md, and V05_DESIGN.md all cover overlapping
   ground. I reconciled the first two because they describe
   current-intent in the same register as SPEC. I stopped short of
   V05_DESIGN because it's framed as a rationale doc for a shipped
   refactor, and rewriting rationale after the fact felt off. Open
   question for Mike: should V05_DESIGN carry a superseding note at
   the top (minimal, safe, my recommendation), get a surgical pass
   on the stale sections (§2, §3.4, §3.5, §4.1, §4.4, §6), or be
   left alone as a historical snapshot?

6. **The "5-state → 3-state" name shift.** The decisions doc §1 names
   the three states **on / suggested / off**. The v0.5 code and
   comments use `on_confident / on_uncertain / off_suspected / off_maybe`
   everywhere. I used `on / suggested / off` throughout SPEC, PROJECT,
   and WORKFLOW. This is a spec-level rename that will flow into code
   during v0.7. If Mike prefers different names (`on / proposed / off`
   or `on / ai_suggested / off`) flag it before the punchlist lands.

7. **v0.7 punchlist referenced but not written.** The decisions doc
   explicitly defers the v0.7 punchlist; my reconciled SPEC and
   related docs describe the intended end-state post-v0.7. Until v0.7
   lands, the spec is ahead of the code. This is the stated plan
   ("SPEC reconciliation first, so the next session has a correct
   spec to read") but worth stating plainly: anyone reading the SPEC
   between now and v0.7 shipping will see a description that the
   running system doesn't yet match.

---

## Verification

Grepped all three edited files for residue of the removed concepts
(`pill_states`, `is_proposed`, `on_confident`, `on_uncertain`,
`off_suspected`, `off_maybe`, `group_name`, `five.state`, composite
uniqueness language). Remaining hits are all explicit statements of
absence ("no `pill_states` column", "No `is_proposed` column") or
references inside the reconciliation notes at the top of each doc.
Clean.
