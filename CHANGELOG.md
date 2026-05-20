# MediaVault changelog

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

docs: git-init closure report from session 2026-05-08 absorbed into
`_cowork/MV_GIT_INIT_CLOSURE_2026-05-08.md` (was a transient session
output; now under version control).

## v0.5.1 — 2026-05-08

api: allow `local_asset_path` null when `storage_mode` is `url_only`.

Driven by the YouTube-ingest design (see
`_cowork/YT_INGEST_FROM_MUSEUM.md`). YT-ingest manifests register three
or four artifacts per video; three of them — the `youtube_video_page`
parent, the `youtube_transcript` child, and the `youtube_channel_card` —
have `storage_mode: url_only` and no local bytes to point at. The
pre-patch `/api/artifact-register` rejected those because
`local_asset_path` was unconditionally required.

Patch landed by `_cowork/v07_artifact_register_url_only_patch.py`. Three
contiguous edits in `core/imgserver_extensions.py`:

  1. Docstring rewritten so `local_asset_path` is documented as REQUIRED
     when `storage_mode` is `vaulted` or `referenced`, OPTIONAL when
     `storage_mode == 'url_only'`. `media_type` becomes REQUIRED in the
     body when `local_asset_path` is omitted (no file to infer from).

  2. Validation block updated: skip the file-exists / under-`ASSET_ROOTS`
     check when `local_asset_path` is null/missing AND
     `storage_mode == 'url_only'`. When a path IS provided in the
     url_only case it is still validated normally — operators may
     legitimately reference an existing snapshot from a url_only
     artifact and the safety check stands.

  3. INSERT-VALUES line: bind `local_asset_path` as nullable instead of
     coercing through the existing path-normalize helper.

Spec sync landed by `_cowork/v07_spec_url_only_doc_patch.py`:
`SPEC.md §3 Storage Mode` gained the API contract paragraph that
formalizes the conditional-required rule.

Test added: `tests/test_artifact_register_url_only.py` covers the
url_only-with-no-path success path, the url_only-with-valid-path
success path, and the vaulted-with-no-path failure path. Pre-existing
`_cowork/v06_tag_create_test.py` failures are unrelated and remain on
the v0.7 punchlist.

This patch shipped without any git history. This CHANGELOG entry is the
retroactive record. From this point forward every code/schema/doc change
gets a real commit; runtime state changes (DB writes, vault ingests,
intake queue churn) do not.

## v0.5 — 2026-04-19

Refactor shipped. See `MEDIAVAULT_V05_DESIGN.md` for the full rationale,
`_cowork/PHASE_SUMMARY_v05.md` for the per-phase build log, and
`STATE.md` for the headline change list.

Predates this repo. No commit history exists for the v0.5 build
itself — the initial commit on this branch absorbs the v0.5-shipped
state as the baseline.
