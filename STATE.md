## WHERE WE ARE

Session 2026-04-19 — v0.5 REFACTOR SHIPPED:

The MediaVault v0.5 refactor is complete. See `MEDIAVAULT_V05_DESIGN.md` for
the full rationale and `_cowork/PHASE_SUMMARY_v05.md` for what shipped per
phase (0 through 7).

Headline changes (v0.4 → v0.5):

- **Vocab:** `tags.group_name` (cosmetic label) → `tags.category` (one of
  `bands`, `people`, `places`, `content_kind`, `topic`, `scope`, `rarity`,
  or `null`). Added `tags.is_exclusive` (0/1) for per-category exclusivity.
- **Five-state inbox pill model.** Per-artifact pill state during review:
  `on_confident`, `on_uncertain`, `off_suspected`, `off_maybe`. Only `on_*`
  states count toward "this pill is on" when saving and when running
  attention rules. The vault filter remains tri-state (off / MUST / MUST NOT).
- **Author is a pill.** The `author_name` column was dropped. The convention
  is an `author:<slug>` pill, e.g. `author:carsie_blanton`. The slugifier
  (Python + JS) accepts one optional `namespace:` prefix.
- **Permission fields dropped.** `tags_permission`, `permission_contact`,
  `permission_evidence_path` removed from the schema (never used).
- **Parent moves out of intake.** Parent is attached from the vault detail's
  new "Attach to parent" modal (searchable candidate list, self + descendants
  excluded). Removed from the inbox form.
- **Attention rules (R1-R5).** New module `core/attention_rules.py`
  surfaces soft warnings in the inbox. R1 social-post needs `post_date`;
  R2 top-level photo/video needs a `content_kind` pill; R3 Title-Case
  bigram in description but no `people` or `bands` pill; R4 extension
  capture without `scope` pill; R5 any pill on but `media_type` empty.
  Warnings glow controls/section headers — operator can save anyway.
- **Vocab admin UX.** Added Merge (source→target) and Bulk Delete (checklist
  of `usage_count=0` pills) actions. Create/Edit modals use the new
  category dropdown + exclusivity checkbox.
- **ID generator** now lives in `id_sequence(date_str PK, last_seq)` — one
  row per day. Format unchanged: `MV-YYYYMMDD-NNN`.
- **Queue status 'approved'** is now set when a row is saved-and-released
  through the inbox (fix for a v0.4 bug where `release_now=True` from the
  inbox left the queue row in limbo).

Row counts after v0.5 migration (matches pre-refactor snapshot):
- artifacts: 80 (vault + released)
- pills in vocabulary: see PHASE_SUMMARY_v05 Phase 2 log
- inbox queue: 25 pending at refactor time
- author:* pills: 14 synthesized from prior author_name values

Preserved reference copies (renamed, not modified):
- `hr_manager.html.old_v02`
- `core/imgserver.py.old_v02`
- `core/_test.txt`
- `core/screenshot_match.json`
- `core/migrate_to_v04.py`

Quarantine folder: `D:\AI_OK_TO_DELETE\MediaVault_v05_refactor_20260419\`
holds duplicates of all five files above. Delete permission was not
requested during the refactor (per the brief's instruction to mirror v0.4
behavior) — source copies remain; quarantine copies are canonical if Mike
ever wants them gone.

## OPEN ISSUES — MEDIAVAULT (re-scoped for v0.5)

- [ ] **Inbox intake empty-state UI** (brief §6.5) — the queue-empty viewer
      still shows plain text. The spec's `<input type="file">` +
      `intakeAddUrl()` controls were deferred. Non-blocking: ingest still
      works via PowerShell (`ingest_engine.py scan`) and capture folders.
- [ ] **Warning pill rendering in-category.** R1-R5 surface today as field
      glows + per-category warning glyphs on the `<summary>`. The
      `.pill.warn` CSS class is wired but no rule renders an inline warning
      pill yet. Cosmetic upgrade.
- [ ] Zero-usage pills (`fan_art`, `memorabilia`, `music_video`, `seeds`) —
      kept in vocab as placeholders. Bulk-delete pending Mike's call.
- [ ] Sidecar-to-parent linking — some sidecars could not be auto-matched;
      attach-to-parent modal now provides a manual path.
- [ ] GPS location not surfacing for HEIC files in inbox UI (carried over).
- [ ] Hash-based dedup on intake-upload (carried over).
- [ ] `mediavault_recrop.html` still targets the old API stack — rewrite
      against v0.5 endpoints.

## DECISIONS — 2026-04-19

Following REVIEW_v06.md and four intent-ambiguity resolutions:

- **Pill lifecycle.** Three states (on / suggested / off). Auto-confirm on
  save. Session-only — no `pill_states` column.
- **Slug uniqueness.** Global. One slug, one tag. Category is descriptive
  metadata.
- **`is_proposed`.** Removed. One-stage vocabulary.
- **`archived_at`.** Saved-but-hidden. Always reversible. Real column on
  artifacts.
  *(SUPERSEDED 2026-05-19 — Criterion 5: the column was added but
  never wired up; the running archive handler always set
  `status='archived'`. The doc is now corrected to match the code.
  `archived_at` is retired — present in the schema, never written,
  never read. See `SPEC.md` §4.1.)*

Full reasoning: `_cowork/DECISIONS_2026-04-19_pill_states_and_friends.md`
SPEC reconciled same day.

Next: v0.7 punchlist (not yet written).

## Version control

Initialized 2026-05-08. Repo at `C:\AI\Platform\MediaVault\.git`,
**local-only — no remote configured, none planned.** MediaVault holds
operator content (catalogs/, intake/) alongside source on the same machine;
pushing to a hosted remote was never the model and never will be.

**What's tracked vs ignored.** See `.gitignore` for the canonical list.
Tracked: source code (Python, JS), HTML UIs, design and process docs
(this file, SPEC.md, README.md, PROJECT.md, WORKFLOW.md, the
MEDIAVAULT_V0X_DESIGN docs, COWORK_BRIEF and COWORK_BRIEF_v05, the v0.2
RS docx), session artifacts in `_cowork/` (decision records, briefs,
audits, one-shot patch scripts, migration logs, run logs), tests/, the
current CHANGELOG. Ignored: runtime SQLite (and journal/wal/shm), all
`*.sqlite.bak_*`, all `*.pre_v0*` and `*.bak_pre_*` backup siblings,
`*.old_v02` preserved-reference copies (quarantine duplicates already
exist at `D:\AI_OK_TO_DELETE\`), `catalogs/` (vault content),
`intake/` (inbound queue), `thumbnails/` (runtime cache),
`__pycache__/`, OS noise.

**Commit convention.** Every code, schema, or doc change gets a commit.
Runtime state changes (DB writes from the running server, vault ingests,
intake queue churn, regenerated thumbnails) do not — they're ignored
and don't show up in `git status`. CHANGELOG.md is the human-readable
version log alongside `git log`; bump it for any operator-visible
change to API contracts, schema, or workflow.

**Branches.** Optional. For multi-file changes that want a checkpoint
before merging, branch off master, commit incrementally, then merge
(fast-forward or `--no-ff`, your call). No PR machinery, no review
gate — this is a single-operator local repo. Use hyphenated branch
names; the FUSE-mount sandbox can't create slashed names.

**Cowork sandbox.** When working from inside a cowork session, expect
to need `mcp__cowork__allow_cowork_file_delete` permission on `.git/`
before any git op that uses lock files (every commit / index write).
FUSE writes can stale-cache config files; the workaround is the
rm-then-write Python pattern from `_cowork/`-style scripts. Set
`core.autocrlf = false` (already in `.git/config`) — don't let git
rewrite line endings on the FUSE round-trip.

**Known-failing tests.** `_cowork/v06_tag_create_test.py` has
pre-existing failures from before this repo. Tracked-but-known.
Do not fix mechanically without v0.7 punchlist context.

