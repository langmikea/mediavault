# MediaVault changelog

## v0.5.8 — 2026-05-25

vocab: register three previously-unregistered namespaces per audit
§6.1 T7 + §9.8 operator decisions (locked 2026-05-24). Single
BEGIN IMMEDIATE / 3 INSERTs / post-verify / COMMIT against
`vocabulary` via `_cowork/mv_register_unregistered_v1.py`.

Vocabulary INSERTs (final post-state in parens):

  - `era`          tier=1, sort_order=7  (after bands which took
                                          sort_order=6 in v0.5.6;
                                          §9.5 × §9.8 reconciliation
                                          shifts era to 7), display
                                          name "Era".
  - `format`       tier=2, sort_order=3  (after source=1, type=2),
                                          display name "Format".
  - `release_type` tier=2, sort_order=4  (after format=3), display
                                          name "Release Type".

Post-state tier ordering verified end-to-end on host DB:

  tier-1: year=1, album=2, song=3, venue=4, people=5, bands=6, era=7
  tier-2: source=1, type=2, format=3, release_type=4

Pre-write backup:
`core/backups/bak_pre_t7_vocab_20260525T180605Z.sqlite`
(1,953,792 bytes; pre-write sha256 matched live DB; pre-write
PRAGMA integrity_check=ok; post-write integrity_check=ok).

Sandbox-write path (deviation from v0.5.7 script template, banked
as a CLAUDE.md follow-up): COMMIT against the virtiofs-mounted DB
threw `disk I/O error` on the first attempt — the M1 §7.2 symptom.
Recovered cleanly: byte-identical sha256 confirmed no pages had
been rewritten, the orphan rollback journal was removed, and the
write was re-run via the v0.5.7 pattern (copy host DB to a /tmp
work copy, transact there, write back). The atomic rename step
needed a copy-then-`os.replace`-within-host-fs variant because the
sandbox `/tmp` is tmpfs (different filesystem from the virtiofs
mount), so the v0.5.7 script's direct `os.replace(WORK_DB,
HOST_DB)` got `EXDEV`. The final swap used `shutil.copy2` to
`<host>.t7_tmp` followed by `os.replace` within the host
filesystem — same atomicity guarantee, cross-device-safe.

Unblocks T3 (tag-group ordering by tier + sort_order in MV's
`/api/tags` and the Museum's `buildDimensions`). Tag values
populate organically as artifacts emit them; no backfill needed.
The `vocabulary` table now declares era, format, release_type as
known namespaces with stable tier/sort_order — downstream
consumers can rely on the registry instead of the
`TIER_BY_NAMESPACE` fallback heuristic.

Reversibility: the pre-write backup restores prior state. Re-
running `_cowork/mv_register_unregistered_v1.py` against the
current DB detects the post-write state at the pre-flight count
assertion (era/format/release_type all present) and aborts
cleanly without re-applying.

## v0.5.7 — 2026-05-25

vocab(exhibit): backfill `exhibit:hunter_root` across all 178 artifacts
(Scope C per operator decision 2026-05-25). 21 already carried the tag
(no-op for those); 157 had it added. `tags` registry reconciled:
exhibit:hunter_root usage_count 19 → 178 (pre-state had a 2-row
registry drift vs actual usage; the post-write count matches reality).

DB changes (single BEGIN IMMEDIATE / post-verify / COMMIT, via
`_cowork/mv_exhibit_backfill_20260525T103322Z.py`):

  - `artifacts.tags` JSON arrays: 157 rows rewritten — each gets
    `exhibit:hunter_root` appended, then set-deduped and re-sorted
    alphabetically (matches the existing convention; preserves the
    v0.5.6 pattern of sorted, deduped tag arrays). `updated_at`
    refreshed on each rewritten row.
  - `tags` dictionary: row `exhibit:hunter_root` (display_name=
    'Exhibit:Hunter Root', pre-state usage_count=19) updated to
    usage_count=178. No INSERT — the row already existed from the
    Phase v5-6 seed (v0.5.2, 2026-05-11).

Pre-write backup: `core/backups/bak_pre_exhibit_backfill_20260525T103322Z.sqlite`
(1,953,792 bytes; PRAGMA integrity_check=ok on post-write file).

Unblocks `tools/export-artifacts.mjs` (museum repo) which filters by
`exhibit:hunter_root`. Before this backfill the 34 today-released
artifacts that lacked the exhibit tag would not appear in the per-
exhibit JSON. After the backfill the museum's regenerated JSON carries
54 artifacts (55 released minus 1 cluster-sibling excluded by the
script's `parent_artifact_id IS NULL` filter — MV-HR-20260416-014, an
audio child of MV-HR-20260416-011, whose parent relationship was set
on 2026-05-24T21:44:20Z).

Reversibility: the pre-write backup restores prior state. Re-running
`_cowork/mv_exhibit_backfill_20260525T103322Z.py` against the current
DB detects the post-backfill state (0 artifacts lack the tag) at the
pre-flight count assertion and aborts cleanly without re-applying.

Future automation: T8 (audit §6.4) — HR acquisition tooling will
auto-emit `exhibit:hunter_root` on every captured artifact alongside
the existing `bands:`/`scope:`/`source:` tags. This backfill is the
one-time catch-up for the historical artifacts captured before T8
lands.

Museum-side companion commit: `data: regen hunter_root.json with 54
released artifacts` (museum repo).

## v0.5.6 — 2026-05-24

schema(vocab): register `bands:` as tier-1 namespace (sort_order=6,
display_name="Bands"); migrate all 81 `people:hunter_root` instances
to `bands:hunter_root`; ensure bands:hunter_root present on every
artifact in the broader HR-exhibit cluster (93 scope:hr artifacts).
Per audit §9.4 (locked 2026-05-24) — Bands gets its own tier-1
namespace; Hunter Root migrates from people: semantics to bands:
semantics. R3 validator's
`countInCategory('people')==0 && countInCategory('bands')==0`
disjunct in mediavault.html is correct as-written for the
post-migration dual-category world (per V1B Tagging-S1 §2.1
reconciliation).

DB changes (single BEGIN IMMEDIATE / post-verify / COMMIT, via
`Hunter Root/_cowork/mv_bands_migration_20260524T210249Z.py`):

  - `vocabulary`: INSERT row (namespace='bands', display_name='Bands',
    tier=1, sort_order=6, retired_at=NULL). Tier-1 sort sequence is
    now: year=1, album=2, song=3, venue=4, people=5, bands=6.
  - `artifacts.tags` JSON arrays: 173 rows rewritten — 80 REPLACE_ONLY
    (people:hr → bands:hr, no scope on those older FB / ReverbNation
    captures), 1 REPLACE_BOTH (`MV-20260523-089` "Straitlaced" — has
    both), 92 ADD_ONLY (scope-present, adds bands:hr). Tag arrays
    sorted, deduped; `updated_at` refreshed.
  - `tags` dictionary: row `people:hunter_root` deleted (usage_count
    81 → 0; mirrors v0.5.5 platform:youtube delete-on-zero pattern).
    Row `bands:hunter_root` inserted (display_name='Bands:Hunter Root',
    usage_count=173, created_at populated).

Pre-write backups:

  - `core/backups/bak_pre_bands_migration_20260524T205823Z.sqlite`
    (pre-§1: pristine pre-everything snapshot).
  - `core/backups/bak_pre_bands_backfill_20260524T214419Z.sqlite`
    (pre-§3: post-vocab-INSERT, pre-tag-rewrite snapshot).

Acquisition-side tooling (HR repo, same session, separate commit):
`tools/yt_archive_capture.py` adds `BANDS_SLUG="bands:hunter_root"`
to `COMMON_STATIC_TAGS` — every parent + child emitted by future
captures carries bands:hunter_root automatically (alongside the
existing scope/source/author tags). No `people:hunter_root` emission
existed post-V1A/V1B; the migration's REPLACE path applied only to
older Facebook / ReverbNation captures from before the V1A cleanup.

Museum-side: `docs/TAGGING_SYSTEM_AUDIT-20260524T155635Z.md` §6.1 T1
gets a supersession note (§9.4 reverses §6.1 T1's "drop bands half of
R3" wording; the R3 disjunct is correct as-written). Separate Museum
commit.

Reversibility: the matching pre-§3 backup restores prior state.
Re-running `_cowork/mv_bands_migration_20260524T210249Z.py` against
the current DB is idempotent — its pre-flight detects POST-MIGRATION
state and exits clean rather than re-applying.

T7 (era / format / release_type vocab registration) is the next §6.4
sequencing item. The internal §9.5 × §9.8 tension over era's
sort_order=6 vs bands at sort_order=6 surfaces there.

## v0.5.5 — 2026-05-24

schema(vocab): collapse `platform:` namespace into `source:`; retire
`platform` (re-retired). One-shot reconciliation per the YT acquisition
follow-on v1B session
(`Hunter Root/_cowork/YT_FOLLOWON_V1B_RUN_REPORT-*.md`).

This is a partial reversal of v0.5.4's Option-A revival, scoped to the
single namespace that had a clean live equivalent. The YT vocabulary
alignment brief's §3 (Option B mapping) already flagged
`platform:youtube → source:youtube` as the only **Clean** of the five
mappings — Option A was chosen because the OTHER four (scope, author,
content_kind, artifact_kind) had no clean live home, not because the
`platform:` mapping itself was contentious. Operator framing on
2026-05-24 (paraphrased): *"Why is YT a Platform, and TikTok et al are
Sources? They're doing the same job."*

The other four revived namespaces (`scope`, `author`, `content_kind`,
`artifact_kind`) **remain revived**. Option A still stands for them.

DB changes (atomic transaction; BEGIN IMMEDIATE / post-verify / COMMIT):

  - `artifacts.tags` JSON arrays: 93 rows rewritten — every
    `platform:youtube` instance replaced with `source:youtube`
    (set-deduped, sorted; `updated_at` refreshed).
  - `tags` dictionary: row `platform:youtube` (usage_count=93) deleted;
    new row `source:youtube` (display_name='Source:Youtube',
    usage_count=93) inserted. No prior `source:youtube` row existed.
  - `vocabulary.platform.retired_at` set to `2026-05-24T15:04:30.000Z`.

Reconciliation script: `Hunter Root/_cowork/mv_vocab_reconcile_v1B.py`
(one-shot; idempotent re-runs are safe — they detect already-reconciled
state and exit clean). Pre-write backup at
`core/backups/mediavault_pre-vocab-reconcile-v1B-20260524T150430Z.sqlite`.

Acquisition-side tooling (HR repo, same session): `yt_archive_capture.py`
now emits `source:youtube` instead of `platform:youtube`, and also adds
`type:video` to the parent's static tag set (Mike's Problem B — the
`type:` namespace at tier 2 is the canonical "this is a video" tag and
was being skipped while only `content_kind:variant` was emitted).
Album-name tag fidelity also fixed (album: tag now uses the SPINE
display title, e.g. `album:they_finally_cracked_me`, matching how
`song:` already used full track titles).

The reconciliation does not touch the other 11 active vocabulary
namespaces. Reversibility: the same script run in inverse (manual SQL —
`UPDATE vocabulary SET retired_at=NULL WHERE namespace='platform'` and
re-rewriting the tag arrays the other way) would restore. Not currently
scripted because the operator has the inverse from v0.5.4.

## v0.5.4 — 2026-05-23

schema(vocab): revive five tier-3 namespaces previously retired
2026-05-19, per the YT/MV vocabulary alignment decision (Option A) in
`weird-baby-museum/docs/YT_VOCABULARY_ALIGNMENT-20260523T171458Z.md`
at museum HEAD `5ad4a34`.

The 2026-05-19T01:06:41Z retirement (v0.5.2-era cleanup) had set
`retired_at` on `platform`, `scope`, `author`, `content_kind`, and
`artifact_kind` — all tier-3, the "specialized / proposed" tier. That
retirement was contemporaneous with the broader Phase 2.5 column
demotion (v0.5.3) and pre-dated the YT acquisition layer's needs
becoming concrete. The HR acquisition scoping brief
(`weird-baby-museum/docs/HR_ACQUISITION_SCOPING_BRIEF-20260523-154141.md`
§1.4, §4.1) surfaced the resulting drift between MV's vocabulary
registry and `tools/youtube-ingest-schema.md` v1.1 (museum repo), which
specifies these five namespaces verbatim in its per-artifact pill
matrix. Both contract documents had diverged silently — POSTs continued
to validate against §3.1 namespace:value grammar (the 3 already-ingested
2026-05-18 YT artifacts demonstrate this) but the registry no longer
listed the namespaces as blessed.

Five `UPDATE vocabulary SET retired_at = NULL` per §6.2 of the
alignment brief. Sort orders and display names preserved (already
present in the rows; the original retirement only touched `retired_at`).
The post-revive tier-3 set: `unsorted=1 (retired)`, `author=2`,
`platform=3`, `scope=4`, `artifact_kind=5`, `content_kind=6`. The gap
at sort=1 left by `unsorted` remaining retired is harmless and accepted
per brief §6.3 (option b). The 12 existing tag instances across the
3 May-18 YT artifacts (platform/scope/author=3 each, artifact_kind=2,
content_kind=1) remain unchanged.

No schema-document edits, no acquisition-tooling edits — Option A's
trade-off design. The decision is reversible: the same UPDATE with a
new timestamp re-retires all five if the cleanup direction reasserts.

Backup discipline: pre-write backup at
`core/backups/bak_pre_vocab_revival_20260523T184027Z.sqlite` (SHA-256
`3410342d24bdf998d287d6889e0ed46d48da9ca2212e5ff7c82badc7b8636e96`,
byte-identical to the pre-write DB). Post-write `PRAGMA
integrity_check` passes. DB write executed via the standard
sandboxed-write pattern (M1 §7.2): working copy in `/tmp/`,
transactional UPDATE there with `BEGIN IMMEDIATE` + in-txn pre-flight
count gate + rowcount gate + in-txn post-verify gate, then byte-swap
back to live path. Live-DB SHA-256 post-swap
`eff1ee634576167e569abbdd4f5329950ecf2a5a00a44121a2399671a99bb047`;
size unchanged at 1,953,792 bytes.

Unblocks the HR acquisition brief's §6.4 first work item: "YT bulk
channel-walk acquisition v1." The five revived namespaces are also the
template for future non-YT acquisition (IG / TT / FB / web) — they
accept additional values without further vocabulary edits.

Out of scope, per brief §7: the sort-order renumber at tier-3 (§6.3
option a); the `exhibit:` and `unsorted:` retirement reviews (their
own coherence questions); the `era:rwth` missing-vocabulary-row; the
`credit:` namespace approval from HR brief §9.3 (separate Ops
prerequisite). Naming note: this entry uses the backup-filename
pattern `core/backups/bak_pre_<purpose>_<UTCstamp>.sqlite` (recent
Phase B/C convention) rather than the brief §6.1 alternative form
`core/mediavault.sqlite.bak_pre-yt-vocab-revive-<utcstamp>.sqlite` —
file content is identical, only the path differs. Run report:
`_cowork/VOCAB_REVIVAL_RUN_REPORT-20260523T184027Z.md`.

## v0.5.3 — 2026-05-20

schema(phase-2.5): drop four registry-era columns from `tags`, promote
`slug` to PRIMARY KEY — closes §12 Criterion 8 of the museum's
data-architecture refactor.

The `tags` table is the per-value usage-count cache (post-§5.2 demotion
in the source-of-truth refactor). Phase 2.5 retires the four columns
the demoted cache no longer carries:

  - `description` — never tracked per-tag in the new model; descriptive
    prose for a namespace lives in the §5.4 `vocabulary` registry.
  - `category` — namespace metadata now travels in the slug itself
    (`bands:hunter_root` rather than a `bands` row + value column).
  - `is_exclusive` — per-tag exclusivity is not part of the post-
    refactor model.
  - `is_proposed` — the proposed/accepted curation workflow was retired
    on 2026-04-19 (one-stage vocabulary, per `_cowork/DECISIONS_2026-04-19
    _pill_states_and_friends.md`); the column lingered in the live
    schema until this commit.

In the same migration `slug` was promoted from `TEXT NOT NULL` to
`TEXT PRIMARY KEY`, replacing the v0.5-era composite-`(slug, category)`
uniqueness with the global "one slug, one row" guarantee the v0.5
reconciliation banner already declared (see top of SPEC.md). The four
obsolete indexes — `idx_tags_slug_category`,
`idx_tags_slug_when_null_cat`, `idx_tags_category`, `idx_tags_proposed`
— were dropped at the same time; slug lookups now use the implicit
`sqlite_autoindex_tags_1` (PK index), confirmed via `EXPLAIN QUERY
PLAN`.

Pre-state: 69 rows, `SUM(usage_count)=453`, 8 columns, 4 obsolete
indexes (per `docs/PHASE2_4_RUN_REPORT-20260520-171029.md` §4).
Post-state: 69 rows, `SUM(usage_count)=453`, 4 columns (`slug
PRIMARY KEY, display_name, usage_count, created_at`), implicit PK
index only. Row counts and the per-slug `usage_count` parity with
`artifacts.tags` are unchanged. §4.5.1(b) single-writer check
(`tools/check_single_tag_writer.py`) passes post-migration (30 files
scanned, 0 violations).

Patch landed by `_cowork/v13_phase25_demote_tags_table.py`. Single
SQLite transaction, five steps: (1) drop the four obsolete indexes,
(2) `ALTER TABLE tags DROP COLUMN` x4, (3) `CREATE-INSERT-DROP-RENAME`
to add the `slug PRIMARY KEY` constraint (SQLite cannot add a PK
constraint via `ALTER TABLE`), (4) verify post-state (row counts,
`SUM(usage_count)`, `EXPLAIN QUERY PLAN` slug-lookup index use),
(5) `COMMIT`. Requires SQLite >= 3.35 for `DROP COLUMN`; verified
3.37.2 at run time.

Backup discipline: pre-write backup at
`core/backups/mediavault.pre-phase25-20260520-234155.sqlite` (SHA-256
`0a6456ebf460368d404f4c17d6dfe57ee704a2e66c96cac5bd1f5f6dbb9ccb33`,
byte-identical to the pre-migration DB). A second snapshot was taken
immediately before the live-DB swap
(`core/backups/mediavault.pre-phase25-swap-20260520-234607.sqlite`,
same SHA — confirmed pristine between Phase 2.4's commit and the
Phase 2.5 swap). Both files are untracked working-tree noise (the
`core/backups/` gitignore follow-up from Phase 2.4 §5 is still open).

Migration ran against `/tmp/mediavault.phase25.sqlite` (a copy on the
VM's native ext4) per the Cowork-on-Windows FUSE-mount workaround
documented in `docs/PHASE2_4_RUN_REPORT-20260520-171029.md` §2.4. Live
`core/mediavault.sqlite` was overwritten via `cp` and SHA-256
byte-verified against the `/tmp` source post-swap.

Doc updates in this commit: SPEC.md §6 schema block (4-column shape)
+ new §6.5 retirement subsection; STATE.md headline-changes and
DECISIONS sections marked SUPERSEDED / REALIZED; NAVIGATION.md
"Known state" and "What's next" sections marked RESOLVED; this
CHANGELOG entry. Code-comment updates in `core/imgserver.py`
(`vocab_row_for_slug` ~line 234, `upsert_tag` ~line 280,
`handle_tag_create` ~line 1314) and `core/ingest_engine.py`
(`upsert_tag` ~line 106) rewording the v0.5 "accepted-and-ignored"
notes to reflect that the doomed columns are no longer in the schema
at all. `core/attention_rules.py:22` was left alone (already correct).

Run report: `docs/PHASE25_RUN_REPORT-20260520-234155.md` mirrors the
format of `docs/PHASE2_4_RUN_REPORT-20260520-171029.md`.

Out of scope, logged for follow-up: (1) SPEC.md §2 pill conceptual
model still describes `category` and `is_exclusive` as pill properties
— now a UI grouping concept delivered through namespaced slugs rather
than dedicated schema columns; a §2 prose pass is non-blocking and
worth a separate doc-only commit. (2) `core/backups/` is still not in
`.gitignore` (carried over from Phase 2.4 §5). (3) Phase 3
(`media_type` enum cleanup) remains separately scoped and is not on
the Criterion-8 critical path. (4) The Museum repo's working tree has
a cosmetic staged-delete vs. untracked pair on
`docs/PHASE2A_RUN_REPORT-20260520-162150.md` (file SHA matches HEAD);
not touched by Phase 2.5 since the Museum repo isn't modified by this
phase. (5) The doc-sweep portion of this commit was rebuilt in /tmp
+ cp after the Edit-tool path hit the documented Cowork-on-Windows
FUSE-mount truncation pattern (Phase 0 / Phase 1 / Phase 2A symptom);
this is the same pattern Phase 2.4 §2.4 recommends defaulting to.

## v0.5.2 — 2026-05-19

docs(spec): correct SPEC.md lifecycle/archive sections to match running
code — §12 Criterion 5 of the Museum data-architecture BUILD.

SPEC.md described archive two ways that the code never implemented: a
nullable `archived_at` timestamp orthogonal to `status`, plus a phantom
`deleted` status value. The running system has neither — `/api/artifact-archive`
sets `status='archived'`, the live CHECK constraint is
`('inbox','vault','released','archived')`, and `archived_at` (added in
v0.5.1 to satisfy a museum-side reader) is written and read by nothing.

Ten edits to SPEC.md, doc-only, no code or schema change: §4.1 rewritten
to `status='archived'` with a historical note retiring `archived_at`;
the v0.5 reconciliation preamble, §6 status comment + schema annotation,
§8.1/§8.2 vault filters, §10 Lifecycle + Archive rows, §12.2 migration
note, and the §14 hard rule all corrected. `deleted` removed from the
spec enum to match the live CHECK.

Path A (spec follows code) was chosen over Path B (build the
`archived_at` mechanism) per a read-only investigation: Path A is
doc-only; Path B would reverse the 2026-05-14 Stance-B decision and
modify a running v0.5.2 system. Backup: SPEC.md.pre-criterion5-20260519-151254.

Out of scope, logged for follow-up: (1) `STATUS_ENUM` in
`imgserver_extensions.py` still lists `archived` and `deleted` — a third
enum copy in code; (2) `handle_artifact_delete` hard-deletes a DB row —
worth checking against the §14 no-hard-delete rule; (3) PROJECT.md /
STATE.md / WORKFLOW.md repeat the retired `archived_at` claim and need a
doc pass; (4) MV NAVIGATION.md "What's next" is stale post-Criterion 5.


Local-only repo. Versions track the SPEC.md decision baselines and the
operator-facing changes between them. Each entry records: what changed,
which files moved, why.

Entries newest first.

## v0.5.2 — 2026-05-11

chore(test): phase v5-6 Ops seed — tag and release the Reverend
artifact (`MV-20260510-001`).

Operator-testing-deferred-to-Ops: Mike declined to do the curation pass
manually for the Phase v5-6 export+render verification, so this seeding
script substitutes. The goal is to put real Phase v5-6-shaped tag data
on MV-20260510-001 so the museum's export+render pipeline can be
exercised end-to-end against a released artifact carrying the new
`exhibit:`, `mood:`, `motif:`, `theme:`, and `era:` namespaces.

Patch landed by `_cowork/v08_phase_v5_6_seed_reverend.py`:

  - appends six slugs to the artifact's `tags` JSON array
    (`exhibit:hunter_root`, `mood:snarky`, `mood:defiant`,
    `motif:pink-hats`, `theme:resistance`, `era:arkansas`),
    preserving the four existing slugs;
  - creates matching rows in the `tags` vocabulary table with
    category and display_name set (column list built dynamically
    from `PRAGMA table_info` so the live `is_proposed` column —
    still physically present even though SPEC §6 has removed it —
    is populated with `0`);
  - flips `status` from `vault` to `released` and stamps
    `released_at` with the current UTC timestamp.

Single transaction, single Python file, no MV code changes (no edits
to `mediavault.html`, `imgserver.py`, `imgserver_extensions.py`,
`attention_rules.py`, etc.). Idempotent — re-running detects existing
state and reports "no new tags to add," "no new vocabulary entries,"
and "already released" with no row-count change.

Out of scope: any other artifact; the museum side of the export+render
pipeline; the spec-vs-live `is_proposed` drift (the column is still in
the live schema but the script tolerates either).

## v0.5.1 — 2026-05-11

schema: add `archived_at TEXT` column to the `artifacts` table.

Aligns the live SQLite schema with SPEC.md §6, which has declared
`archived_at` since the v0.5 spec reconciliation but where the column
was never actually present in `core/mediavault.sqlite`. The drift
surfaced for the third time during the Phase v5-3 / v5-4 live test as
the museum-side export script's loud diagnostic (v5.1 Patch 8 in
`weird-baby-museum/docs/deep-dive-review/SPEC_DRAFT_v5_1.md`) fired:
"expected column `archived_at` on artifacts, not present". The right
fix is to add the column rather than continue working around it.

Patch landed by `_cowork/v07_add_archived_at_column.py`:

  ALTER TABLE artifacts ADD COLUMN archived_at TEXT;

Default is `NULL` for all 85 existing rows (correct: they are not
archived). SPEC §4.1 documents `archived_at` as "saved-but-hidden,
always reversible", so `NULL` is the natural "not archived" sentinel
and matches the convention used by `released_at`. The script is
idempotent — re-running after the column exists is a no-op.

Out of scope, deferred: reconciling the live `status` CHECK constraint
(`'inbox','vault','released','archived'`) against the SPEC enum
(`inbox|vault|released|deleted`). That broader status-enum drift
remains on the Phase-2 cleanup punchlist; this commit is the single
column addition that unblocks the museum-side export script.

## v0.5.1 — 2026-05-08 (continued)

docs: git-init closure report from session 2026-05-08 a