# pill_states — Investigation Findings

*Read-only follow-up to `REVIEW_v06.md` data-layer finding. No code changed, no patches applied.*

---

## What it was supposed to do

`pill_states` was intended to be a per-artifact map from `slug` → one of
`on_confident`, `on_uncertain`, `off_suspected`, `off_maybe` — the canonical
storage of the v0.5 five-state inbox pill model (`SPEC.md:85-107`). The flat
`artifacts.tags` array already stores "which pills are on this artifact," but
it collapses `on_confident` and `on_uncertain` into the same bit and loses the
operator's explicit `off_*` overrides entirely. `pill_states` was the lossless
version, supposed to allow a re-queued artifact to come back to the inbox with
the exact same pill wall the operator left.

The feature came in from **both directions at once** during the v0.5 refactor,
but landed in different places:

- The v0.5 design doc originally kept it queue-side only. `MEDIAVAULT_V05_DESIGN.md:166-192` (§3.4 "Add `enrichment_json.pill_states` convention") says, verbatim: "No schema change. The inbox reads pill confidence from a documented structure inside `enrichment_json`… The `pill_states` blob itself is kept on the queue row only; it does not persist past save." That is the design the code actually implements.
- The `SPEC.md` rewrite then promoted it to a real artifacts column — `SPEC.md:106-107` ("persisted into `artifacts.pill_states` for round-trip fidelity across sessions"), `SPEC.md:227` (schema: `pill_states TEXT`), `SPEC.md:456` (v0.4→v0.5 migration note: "add `pill_states` (JSON), `archived_at`"). `WORKFLOW.md:102` and `PHASE_SUMMARY_v05.md:576` repeat the claim.
- The backend shipped the queue-row half only: `imgserver.py:466-483` (FB-candidate intake emits `pill_states` into `enrichment_json`), `imgserver.py:654-671` (`_upgrade_v04_enrichment_to_pill_states()` lifts v0.4 blobs into the v0.5 shape on read), `imgserver.py:678-756` (`handle_enrich` consumes and produces the shape), `ingest_engine.py:209,220` (extension-capture writes `pill_states = {}` to the queue row's enrichment). None of these touch `artifacts`.
- The v0.5 Phase 1 migration (`_cowork/v05_phase1_migration.py:220-252`) did not create a `pill_states` column. `PRAGMA table_info(artifacts)` confirms the live DB has 25 columns, none of them `pill_states`.
- The backend `ARTIFACT_FIELDS` tuple (`imgserver.py:797-805`) does not list it, so `handle_artifact_save` and `handle_artifact_update` silently drop it from every POST body.
- The frontend ships the save half: `mediavault.html:1055` posts `pill_states` alongside `tags`, and `mediavault.html:932-947` knows how to rehydrate from an incoming `enr.pill_states` blob.

So the intent was real, and the backend half went in on the queue side, and the frontend half went in on the save side, and the two halves never meet. The `SPEC.md` text says the meeting point is a column on `artifacts`; the migration that would have built that column was never written.

---

## What's actually happening

This session was read-only, so the characterization below is traced through code paths, not clicked through in the UI. The trace covers both "fresh queue item" and "re-queued artifact" flows:

1. **Fresh item arrives in queue.** `ingest_engine.queue_capture_json()` writes `pill_states = {}` into `enrichment_json` (`ingest_engine.py:209,220`). `handle_intake_from_fb_candidate()` seeds `pill_states` with `on_uncertain` entries for candidate tags + `author:<slug>` (`imgserver.py:470-483`). The `handle_enrich` path can later fill the map with LLM output (`imgserver.py:751-756`).
2. **Operator opens the item.** `populateInboxFields()` at `mediavault.html:942-947` rehydrates `CURRENT_PILL_STATES` from `enr.pill_states`. Full five-state fidelity. This works.
3. **Operator clicks pills.** `togglePill` / `addAppliedTag` / `removeAppliedTag` mutate `CURRENT_PILL_STATES` in memory only.
4. **Save.** `inboxSave` (`mediavault.html:1014-1075`) POSTs `{tags: CURRENT_APPLIED_TAGS, pill_states: {...CURRENT_PILL_STATES}, …}` to `/api/artifact-save`.
5. **Backend drops it.** `handle_artifact_save` (`imgserver.py:820-964`) iterates `ARTIFACT_FIELDS` to decide which keys to write. `pill_states` is not in the tuple, so it is read off the body into no variable and discarded. The `tags` array does reach the DB (collapsed — `on_confident` ∪ `on_uncertain`).
6. **No write-back to the queue row.** There is no handler that updates `ingest_queue.enrichment_json` with operator-edited pill states. `/api/queue-update` (`imgserver.py:509-534`) accepts `enrichment_json` but no frontend caller sends it. So even the *queue-side* copy of pill_states is the pre-edit one.

**On reload the state reverts — but only the operator never sees it revert, because the path that would expose the reversion is the demote-and-reopen path, not the normal save-and-done path.** Specifically:

- Normal save-and-done: saved items leave the inbox. They don't come back. The operator has no surface on which to observe that the nuance is gone.
- Demote via `/api/artifact-requeue` (`imgserver.py:1071-1094`): a new queue row is created with NO `enrichment_json`. `populateInboxFields` takes the `art && Array.isArray(art._tags)` branch at `mediavault.html:937-941`, which reads the artifact's persisted `tags` array and maps **every single slug to `on_confident`**. Any slug that was `on_uncertain` on save comes back as `on_confident` (silently upgraded). Any slug that was `off_suspected` or `off_maybe` is gone entirely — those states never reached the `tags` array, so there is no source from which to resurrect them.

So the answer to "does state revert or persist?" is: **the on/off bit persists (via `tags`), the five-state nuance reverts silently on re-queue and is invisible otherwise.** This is the "shadow-data that never mattered" case the task predicted. The off-side states (`off_suspected`, `off_maybe`) are pure shadow: they exist only inside a single operator session and never touch persistent storage. The on-side nuance (`on_uncertain` vs `on_confident`) is half-shadow: it persists in `enrichment_json` only until the item is saved, then collapses.

---

## Where it lives in code

**Docs (intent vs reality drift):**

| File:line | Role | Accurate? |
|---|---|---|
| `SPEC.md:106-107` | "persisted into `artifacts.pill_states` for round-trip fidelity" | **No.** Column does not exist. |
| `SPEC.md:227` | Schema declaration `pill_states TEXT` on `artifacts` | **No.** Missing from live schema. |
| `SPEC.md:456` | v0.4→v0.5 migration note: "add `pill_states` (JSON), `archived_at`" | **No.** Migration did not add either. |
| `SPEC.md:493-498` | Attention rules function signature `evaluate_rules(…, pill_states, …)` | Yes — in-memory parameter only. |
| `SPEC.md:507` | Mentions `_upgrade_v04_enrichment_to_pill_states()` for backward compat | Yes. |
| `MEDIAVAULT_V05_DESIGN.md:166-192` | §3.4 — queue-row only, "does not persist past save" | Yes. This is the design the code implements. |
| `MEDIAVAULT_V05_DESIGN.md:406,524,543,550,559` | Narrative mentions in attention-rules and enrichment sections | Yes. |
| `WORKFLOW.md:102` | "`pill_states` for round-trip fidelity" | No — repeats SPEC's aspirational claim. |
| `COWORK_BRIEF_v05.md:473,475,581,636,637,684,687` | Design brief | Mixed — describes both queue-side and "round-trip." |
| `PHASE_SUMMARY_v05.md:224,226,228,231,258,268,365,385,463,475,576` | Phase log claims the feature shipped | `:576` explicitly says "added `pill_states` (JSON) and `archived_at`" to the artifacts schema. It did not. |

**Backend — queue-side (works, unrelated to drift):**

- `core/imgserver.py:466-483` — `handle_intake_from_fb_candidate` writes `pill_states` into `ingest_queue.enrichment_json`.
- `core/imgserver.py:556,564,567` — `_build_enrich_prompt_v05` reads `pill_states` from the queue row when composing the LLM prompt.
- `core/imgserver.py:632,651` — prompt template literal instructs the LLM to return pill_states.
- `core/imgserver.py:654-671` — `_upgrade_v04_enrichment_to_pill_states(ej)`. Idempotent. Called on both read and write. Backward compat for v0.4 queue blobs.
- `core/imgserver.py:678,680,702` — `handle_enrich` applies the upgrade on read.
- `core/imgserver.py:751-756` — `handle_enrich` accepts and post-processes pill_states from the LLM response; auto-creates novel slugs as `is_proposed=1`.
- `core/ingest_engine.py:209,220` — `queue_capture_json()` writes `pill_states = {}` into every extension-capture queue row (v0.6 Item 8d C2 deliberately emptied this after dropping `author:*` auto-emission).

**Backend — artifacts-side (this is where the drop happens):**

- `core/imgserver.py:797-805` — `ARTIFACT_FIELDS` tuple. **Silent drop site.** Does not include `pill_states`.
- `core/imgserver.py:820-964` — `handle_artifact_save`. Iterates `ARTIFACT_FIELDS`; never reads `pill_states` from the body.
- `core/imgserver.py:967-1042` — `handle_artifact_update`. Same pattern. Also never reads `pill_states`.

**Backend — in-memory only, not a persistence path:**

- `core/attention_rules.py:13,16,45,47,50,68,77` — `pill_states` is a function parameter; the module never reads or writes the DB. Correct usage.

**Frontend — reads:**

- `mediavault.html:932-947` — `populateInboxFields`. Three-way priority: (1) if re-queued artifact, map `art._tags` → `on_confident` for every slug; (2) else if `enr.pill_states` exists, use it directly; (3) else v0.4 compat via `tags` / `tags_known` / `tags_proposed` / `author_name`. The re-queued-artifact branch is the degradation site.
- `mediavault.html:1022` — inline comment restating the v0.5 applied-tag derivation rule.

**Frontend — writes:**

- `mediavault.html:1055` — `inboxSave` posts `pill_states: {...CURRENT_PILL_STATES}`. **Silent send site** (backend ignores).

**Frontend — in-memory mutations of the state map (not persistence paths):**

- `mediavault.html:1114-1147` — `addAppliedTag`, `removeAppliedTag`, `syncAppliedFromStates`. Mutate `CURRENT_PILL_STATES` in place; don't talk to the server.

**Archaeology (one-offs, not production paths):**

- `_cowork_prep_v05.py:307` — pre-migration audit counting queue rows by enrichment shape. Not a runtime dependency.

**Removal map** (what a minimal "B. Remove" patch would actually touch, in case the decision goes that way):

1. `mediavault.html:1055` — delete the `pill_states:` line from the save payload.
2. `SPEC.md:106-107,227,456` — delete the three false promises about the column.
3. `WORKFLOW.md:102` — match SPEC's text.
4. No code removal needed anywhere else. The queue-side `pill_states` usage (LLM prompt shape, enrichment round-trip, FB-candidate seeding, v0.4 upgrade helper) is independent and working and would be preserved.

---

## Entanglements

From `REVIEW_v06.md` and `MEDIAVAULT_V06_8D_DR.md`, in rough order of how much each bears on the `pill_states` decision:

1. **`MEDIAVAULT_V06_8D_DR.md` Q1.2 — "Do we keep the 5 pill states or simplify?"** — directly dispositive. Mike's own recommendation in the DR is "B. Collapse to 3" (`on_confident`, `on_uncertain`, `off`). If that recommendation stands, `pill_states` still has meaning (it'd carry the confident/uncertain distinction), but the design becomes much cheaper. If Mike instead picks DR option C (collapse to 2: `on` / `off`), `pill_states` becomes exactly redundant with `tags` and the answer is unambiguously B. **You cannot decide `pill_states` without first deciding Q1.2.**
2. **`MEDIAVAULT_V06_8D_DR.md` Q1.1 — "When does a pill click commit to the server?"** — the `pill_states` round-trip only matters for inbox (stage-then-save) semantics. If Mike's own DR recommendation stands (A for vault, C for inbox), then `pill_states` persistence only has to work for the inbox path, which matches today's code. Any other Q1.1 answer changes the shape of what a real `pill_states` column would have to carry.
3. **`REVIEW_v06.md:103-110` — `(slug, category)` composite uniqueness vs global-slug handlers.** The live DB already has one collision (`hunter_root` in both `bands` and `people`) and every handler and the frontend both still treat slug as globally unique. If `pill_states` ships as a column and keys on bare slug (as `CURRENT_PILL_STATES` does today — `mediavault.html:1055`), it will corrupt the vocab's composite-key contract in the same way `artifacts.tags` already does. Option A is not a local fix — it forces a decision on the bigger vocab-layer question. **This is the heaviest entanglement and the strongest argument against A.**
4. **`REVIEW_v06.md:120-124` — `archived_at` has the exact same pattern as `pill_states`.** Declared in `SPEC.md:235` + `:456`, listed in the SPEC-documented v0.5 migration, never added to the actual schema, never set by `handle_artifact_archive`. Not mechanically entangled with `pill_states`, but spiritually: whichever decision you make here will set the precedent for `archived_at`. Address them together for coherence.
5. **`REVIEW_v06.md:217-220` — "Vault detail pill clicks commit immediately; inbox pill clicks stage."** The vault surface uses `/api/artifact-update` per click, which touches `tags` only. If `pill_states` becomes real for inbox, the inbox and vault will persist different subsets of pill information for the same artifact. Either both surfaces need to learn pill_states, or the concept stays inbox-only and the vault's pill vocabulary stays impoverished.
6. **`REVIEW_v06.md:209-212` — inbox save gate blocks on attention-rule warnings.** The gate uses `_pills_on()` semantics (on_confident + on_uncertain). If Q1.2 collapses the state model, the gate's input shape changes. Shares a code path with pill_states; shouldn't be changed independently.
7. **`REVIEW_v06.md:157-161` — `is_proposed` column alive, no live 1-valued rows, UI stripped.** Same pattern (column stayed, concept retired from UI). Whatever decision is taken on `pill_states`, `is_proposed` wants the matching decision so the vocabulary stays coherent.
8. **`REVIEW_v06.md:126-129` — `artifacts.status` CHECK ≠ extensions' `STATUS_ENUM` ≠ SPEC's enum.** Same family of "SPEC drifted past schema, code half-drifted." Not mechanically coupled to `pill_states` but part of the same pattern; a cleanup pass that fixes SPEC-vs-schema drift for `pill_states` should sweep these too.
9. **`REVIEW_v06.md:198-207` — inbox vs Tag Manager pill creation + `CATEGORY_ORDER` mismatch + `scope` category retirement.** Tangential. The vocab that pill_states keys on is already partially decoupled across surfaces. If pill_states becomes real, the "which category does this slug live in?" disagreements get elevated from cosmetic to data-corrupting. See entanglement #3.
10. **`REVIEW_v06.md:278` — explicitly calls out this same question as an open intent ambiguity.** The review's own framing: "Whether that is a bug (missing column) or a design simplification (states were abandoned, docs didn't catch up) is not determinable from the code alone." This investigation is the answer to that sentence.

---

## Recommended decision

**B — Remove.** Low-confidence recommendation; should be confirmed against `MEDIAVAULT_V06_8D_DR.md` Q1.1 + Q1.2 before action.

**Why B:**

- The original v0.5 design in `MEDIAVAULT_V05_DESIGN.md:166-192` explicitly kept `pill_states` queue-side only and discarded it past save. **The code matches that design.** The `SPEC.md` text that promotes it to a persistent column was an edit that the migration never followed through on. Deleting four lines from `SPEC.md` (`:106-107, :227, :456`) plus one line from `mediavault.html:1055` and matching a line in `WORKFLOW.md:102` aligns the documented world with the working one. Adding the column + migration + save/load round-trip + a decision about `(slug, category)` keying is a much bigger lift for a feature nobody seems to miss — no one has complained about losing off_suspected / off_maybe state, or about `on_uncertain` upgrading to `on_confident` on re-queue, because the surface on which that degradation would be visible (re-queue after save) is rarely exercised.
- The `(slug, category)` composite-uniqueness entanglement (entanglement #3) makes option A not a local fix. You cannot ship a working `pill_states` column without first resolving whether the map keys on `slug` or `(category, slug)`, and that decision is a far bigger piece of work than `pill_states` deserves to force.
- Option B is cheap to reverse. If `MEDIAVAULT_V06_8D_DR.md` Q1.2 resolves as "keep all 5 states" and Mike eventually wants real round-trip, re-adding the column + handler + payload field is clean one-phase work. Deleted code is easier to re-add than silent-drift code is to debug — as the task brief notes.

**Why not A (Ship it):**

- Forces the composite-key decision (entanglement #3) as a prerequisite.
- Pre-commits to the 5-state model before `MEDIAVAULT_V06_8D_DR.md` Q1.2 is decided. Mike's own DR recommendation there is to collapse to 3 states, which would make the full 5-state map redundant.
- Cost is real: artifacts column + migration + save handler change + update handler change + load handler change + composite-key decision + test pass; the data being preserved is data Mike hasn't missed.

**Why not C (Defer with TODO):**

- The point of this investigation is to turn silent drift into a decidable question. Leaving the save button lying while adding a comment concedes the "save doesn't save everything" state indefinitely.
- A TODO in `mediavault.html:1055` doesn't travel — it'd get re-discovered as a fresh finding in six months.
- If Mike does want to defer, the honest form is: resolve `MEDIAVAULT_V06_8D_DR.md` Q1.2 first, then come back. Don't need a TODO in code for that; need the DR answered.

**Prerequisite before acting on B:** resolve `MEDIAVAULT_V06_8D_DR.md` Q1.1 + Q1.2. Q1.2 in particular controls whether `pill_states` could ever matter. If Mike intends to keep the full 5-state model AND wants re-queue fidelity, B is wrong and A is correct — but again, A then depends on resolving entanglement #3 first.

**Minimum-surface B patch** (for reference only — do not apply in this session):

1. `mediavault.html:1055` — delete the `pill_states: {...CURRENT_PILL_STATES},` line from the `inboxSave` payload.
2. `SPEC.md:106-107` — rewrite: "Only `on_confident` and `on_uncertain` count toward 'this pill is on the artifact' when the row is saved — those slugs go into `artifacts.tags`. The full state map is **only kept on the queue row's `enrichment_json` until save; it is intentionally not persisted per-artifact** (see `MEDIAVAULT_V05_DESIGN.md` §3.4)."
3. `SPEC.md:227` — delete the `pill_states TEXT` line from the `artifacts` schema block.
4. `SPEC.md:456` — delete "and `pill_states` (JSON)" from the v0.4→v0.5 migration description.
5. `WORKFLOW.md:102` — match the new `SPEC.md:106-107` text.
6. Add a short paragraph to `SPEC.md:447` (the 12.2 migration section) documenting that the v0.5 SPEC rewrite listed `pill_states` as a column and the migration correctly did not add it — the documented intent was reverted, not implemented. Paragraph exists so the next reviewer doesn't re-discover this.

Leave alone:

- `core/imgserver.py:466-483,556-571,632,651,654-671,678-756` — the queue-row / LLM-prompt / backward-compat machinery. That is the design and it works.
- `core/ingest_engine.py:209,220` — `pill_states = {}` emission into extension-capture enrichment. (Arguably remove entirely per "Related findings" below, but not blocking.)
- `core/attention_rules.py` — `pill_states` is an in-memory parameter there, not a persistence claim.
- The frontend's read path at `mediavault.html:942-947` — still needed for fresh queue items and v0.4 compat. Only the save path line needs removal.

---

## Related findings discovered during investigation

Per the task's rules — noted here, not chased.

- **`core/imgserver.py:632` — LLM prompt still asks the model to return `pill_states` in full 5-state shape.** If Q1.2 collapses the state model, the prompt template is lying to the model and wasting tokens. Independent follow-up.
- **`core/ingest_engine.py:209` — writes `pill_states = {}` literally into every extension-capture queue row.** The comment at `:202-208` explains this is a v0.6 Item 8d C2 follow-up (dropping the old `author:*` auto-emission), but the empty-dict is now a load-bearing falsehood: it implies "this enrichment has pill_states info" when it doesn't. Remove entirely, or swap to omission.
- **Two migration cycles (v0.4→v0.5, v0.5→v0.6) both updated `SPEC.md` to claim `pill_states` exists as a column; neither migration added it.** The pattern is wider than `pill_states`: `archived_at` has the same story (entanglement #4), and `artifacts.status` CHECK vs SPEC vs extensions enum have a related pattern (entanglement #8). A follow-up task that compares `SPEC.md`'s schema block to `PRAGMA table_info(artifacts)` after every migration would catch this class of drift at the point of writing, not months later in code review. Worth a separate punchlist item.
- **`/api/queue-update` at `imgserver.py:509-534` accepts `enrichment_json` but no frontend caller ever sends it.** Means even the queue-side `pill_states` store is write-once on ingest — operator edits to pill states never persist anywhere, including the queue row. If option A is ever taken, fixing this (write operator-edited `pill_states` back to `enrichment_json` on save, or on every pill click) is a simpler alternative than a new column, because the queue row already carries the data and the helper `_upgrade_v04_enrichment_to_pill_states` already knows how to read it. Not a finding against current behavior, just a path that wasn't on the table in the task brief's A/B/C.
