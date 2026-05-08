# MediaVault changelog

Local-only repo. Versions track the SPEC.md decision baselines and the
operator-facing changes between them. Each entry records: what changed,
which files moved, why.

Entries newest first.

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
