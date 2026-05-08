# YouTube ingest from `weird-baby-museum` — operator-side context

**Status:** 2026-05-08. Schema lives in the museum repo at `tools/youtube-ingest-schema.md`. This doc is the MV-operator view: what MV will receive, which API path, which pills to expect, which v0.5 limitations apply.

This is design-and-docs only. The capture script that produces these manifests has not been written yet.

## What MV will receive

Per-video manifests in a new schema, `yt_archive/v1`, parallel to the existing `rn_archive/v1` shape. They live under:

```
C:\AI\Projects\Hunter Root\archive\youtube\<channel_slug>\<video_id>\mediavault_manifest.json
```

with sibling folders for `thumbs/`, `snapshots/`, `transcripts/`. A manifest contains one parent and zero-to-three children. A separate channel-scope manifest is emitted once per channel under `_channel/`.

## How the ingest happens

The capture script (planned: `Hunter Root\tools\yt_archive_capture.py`) writes the manifest folder, then calls `POST /api/artifact-register` once per artifact in the manifest. Parent first; the script captures the response's `id` and threads it into each child's `parent_artifact_id` body field.

This is intentionally not an `ingest_engine.py scan --capture-json` flow. That CLI flag is documented in `SPEC.md` line 244 and `WORKFLOW.md` line 66 but does not exist in v0.5 code — the parser at `core/ingest_engine.py:762-783` only accepts `scan|process|status` with no flags, and `scan()` only handles single-post `mv-capture-*.json` files plus drop-zone file extensions. There is no multi-artifact-manifest reader anywhere in v0.5.

The HTTP `/api/artifact-register` route already accepts `parent_artifact_id` directly (`core/imgserver_extensions.py:210, 329`), so no MV patch is needed for parent linkage to work — the capture script is the orchestrator.

## Four artifact types

**`youtube_video_page`** (parent, one per video). `storage_mode: url_only`. `media_type: link`. `extracted_text` carries the video description. `source_url` is the watch URL.

**`youtube_thumbnail`** (child, recommended). `storage_mode: vaulted`. `media_type: photo`. The script writes the JPEG locally and passes the absolute path in `local_asset_path`; MV's existing register flow copies bytes into `catalogs/_assets/`.

**`youtube_transcript`** (child, recommended when available). `storage_mode: url_only`. `media_type: text`. Full transcript in `extracted_text`; no separate file. `notes[]` records the source (`auto_captions`, `community_captions`, `operator_authored`).

**`youtube_page_save`** (child, optional). `storage_mode: vaulted`. `media_type: link`. SingleFile-style HTML snapshot. Skip on routine ingest; reach for it on rare or contentious items.

A separate `youtube_channel_card` artifact (channel-scope, `storage_mode: url_only`) is emitted once per channel and not per video.

## Pills the operator will see

Two namespaces. Don't mix them.

**Parent (`youtube_video_page`) pills:**

`content_kind:<official | live | lyrics | cover>` — the museum's locked variant taxonomy. This is the *only* place `content_kind:` should appear on YT-ingest artifacts. The slug values match the `type` field in the museum's `SPINE.videos[].type` exactly, so cross-references are trivial.

`platform:youtube` (always). `scope:hunter_root` (or whichever project sent the manifest). `author:<artist_slug>` (v0.5 replacement for the dropped `author_name` column).

**Child (`youtube_thumbnail`, `youtube_transcript`, `youtube_page_save`) pills:**

`artifact_kind:<thumbnail | transcript | page_save>` — new namespace, asset-type label. Children deliberately do not carry `content_kind:` — variant is a property of the video, not its thumbnail.

`platform:youtube`, `scope:hunter_root`, `author:<artist_slug>` — same as parent.

**Channel card pills:** `artifact_kind:channel_card`, plus the standard `platform:`, `scope:`, `author:`.

The earlier draft of this schema overloaded `content_kind:` for both purposes. The split was made on 2026-05-08 to keep the museum's variant taxonomy uncontaminated by asset-type values.

**Optional pills the script may propose** (these arrive as `notes[]` entries prefixed `suggest_pill:` rather than as confirmed `tags[]`, so the operator decides): `era:<era_slug>`, `rarity:<level>`, `topic:<topic>`.

## Operator review checklist

When new YT-ingest rows appear in the Inbox, expect three rows (or four if `page_save` was requested) per video plus optionally one channel-card row per new channel.

For each row: confirm `media_type` matches the artifact type (link / photo / text / link respectively). Confirm `storage_mode` matches the type's policy (url_only for parent and transcript and channel card; vaulted for thumbnail and page save). Confirm the four-pill base set is present and that `content_kind:` only appears on the parent. Spot-check `extracted_text` on the parent and transcript for completeness. For `youtube_transcript`, check `notes[]` for `transcript_source:` and treat as draft until verified. For `youtube_page_save`, click through to confirm the snapshot opens cleanly.

R-rule expectations: R1 (social post without `post_date`) should not fire because the script supplies the upload date in `post_date`. R4 (extension capture without `scope` pill) should not fire because the script supplies `scope:` directly. Anything else firing is a script bug — flag it back to the museum side.

Save to Vault as usual. The lifecycle (`vault → released → archived`) is unchanged.

## v0.5 limitations the operator should know about

**No batch register.** The capture script makes one POST per artifact. If the script crashes mid-manifest, the operator will see a partial set in the Inbox. Mitigation: the script writes `mv_id` back into the manifest after each successful register, so re-running the script resumes from where it left off and skips already-registered rows.

**Parent linkage is API-only.** There is no within-manifest `parent_ref` resolution because there is no manifest reader. If the script registers a child before its parent (script bug), the child will arrive in MV with `parent_artifact_id: null` and the operator must fix it manually via the Inbox UI's parent-picker.

**`/api/artifact-register` requires `local_asset_path` to point at an existing file under `C:\AI\` (`imgserver_extensions.py:66, 238`).** For `url_only` artifacts (parent, transcript, channel card) this is awkward because there is no local file. The script will need either to write a tiny stub file (for example, a JSON sidecar containing the metadata) or the register endpoint will need to grow a "no local file" path. This is a blocker for the script implementation — see "Open question" below.

**`is_proposed` and 5-state pills.** The v0.7 punchlist will simplify these, but they don't affect the manifest contract. The script writes `tags[]` as plain slugs, which v0.5 and v0.7 both accept identically.

## Open question

`local_asset_path` is `REQUIRED` for `POST /api/artifact-register` in v0.5. `url_only` artifacts don't have a local file. Two resolutions:

1. The capture script writes a stub sidecar file per `url_only` artifact (e.g., `stubs/<artifact_id>.json` containing the manifest excerpt) and passes that as `local_asset_path`. Pros: no MV patch. Cons: 80% of vault rows end up pointing at metadata stubs, which is noise at the filesystem level even if `storage_mode: url_only` keeps them out of the asset tree semantically.

2. MV grows a `/api/artifact-register-url-only` endpoint, or relaxes the existing endpoint to allow `local_asset_path: null` when `storage_mode: url_only`. Pros: cleaner data model. Cons: an MV patch, however small, that should land before the capture script ships.

Option 2 is the right answer if the capture script is going to be written this iteration. Option 1 is a workaround if MV is frozen for the duration. Decision goes to Mike.

## What's next

The capture script is the next deliverable on the museum side. This MV-side doc gets revisited when the script is in flight or when the open question above resolves.
