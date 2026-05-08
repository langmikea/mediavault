# COWORK BRIEF — MediaVault v0.4 Refactor

**Version:** 2.0 (supersedes v0.3 brief)
**Date:** 2026-04-17
**From:** Web Claude (design session)
**To:** Cowork
**Reference documents:**
- `MEDIAVAULT_V04_DESIGN.md` — full design spec and rationale (READ FIRST)
- `_cowork/READINESS_REPORT.md` — prep script output
- `_cowork/pre_refactor_snapshot.json` — DB state at prep time

You have full execution authority. The build lock is held in your name, the DB is backed up, dead files are quarantined. Execute all six phases. Only stop for the three conditions in §10.

---

## 0. Before you start

**Read `MEDIAVAULT_V04_DESIGN.md` completely.** Everything below assumes you've read it. The brief is *what*, the design is *why*.

Verify prep ran correctly:
- `C:\AI\BUILD_LOCK.txt` contains `LOCKED` with "cowork" in the session description.
- `core/mediavault.sqlite.bak_v04prep_*` exists.
- `_cowork/pre_refactor_snapshot.json` exists and parses.
- imgserver is NOT running on :51822.

If any of the above is wrong, stop and flag to Mike. Do not attempt to re-prep yourself.

---

## 1. Phase 1 — Schema migration (v0.2 → v0.4)

**Goal:** Transform the DB schema to v0.4 with zero data loss.

### 1.1 Safety

1. Make an additional backup: `core/mediavault.sqlite.bak_v04phase1_<timestamp>`.
2. All migration work happens in a single transaction. If anything fails, ROLLBACK.

### 1.2 Migration script

Write `core/migrate_to_v04.py`. Structure:

1. Connect to DB. Begin transaction.

2. Create new tables alongside old (suffix `_v4`): `artifacts_v4`, `tags`, `id_sequence_v4`, `ingest_queue_v4`. Schema from design doc §3.2.

3. **Build the tag vocabulary first** (before migrating artifacts — artifacts depend on it):
   - Seed `tags` with `('hunter_root', 'Hunter Root', NULL, NULL, 0, 0, now)`.
   - Scan every non-null value across the 10 `tags_*` columns in the old `artifacts` table.
   - For each distinct value:
     - If it's a JSON array (starts with `[`), parse and splat its elements.
     - Slugify: lowercase, replace `-` and spaces with `_`, strip non-alphanumeric.
     - Skip if slug is empty or invalid.
     - Display name: if slug is a 4-digit year, use the year as display. Otherwise title-case the slug with spaces (`live_show` → `Live Show`).
     - Group assignment at migration:
       - `{common, notable, rare, unique}` → `group_name='rarity'`
       - `{standard, critical}` → `group_name='preservation'`
       - All other tags → `group_name=NULL`
     - `is_proposed=0` for all migrated tags.
   - Upsert into `tags` (skip if slug already exists).

4. **Copy artifacts old → new:**
   - For each old row, build a dict of new column values:
     - `id` = old id (preserved).
     - `source_url`, `source_platform`, `ingest_source`, `ingest_date` copied as-is.
     - `storage_mode` determination:
       - If `local_asset_path IS NULL` AND `source_url IS NOT NULL` → `'url_only'`.
       - Elif `local_asset_path` starts with `C:\AI\Platform\MediaVault\catalogs\` → `'vaulted'`.
       - Else → `'referenced'`.
     - `local_asset_path` copied as-is.
     - `thumbnail_path` copied as-is.
     - `link_status`: if `local_asset_path` is set but file doesn't exist on disk, force `'local-only'`. Otherwise copy the existing value (`'live'` in current data).
     - `parent_artifact_id = NULL` initially (set in step 5).
     - `media_type = media_type_in_post` (rename).
     - Dates: `post_date`, `post_date_confidence`, `capture_date` copied.
     - `status = 'vault'` for all 76 rows.
     - `released_at = NULL`, `released_by = NULL`.
     - Descriptions and text fields copied.
     - `author_name` copied.
     - `tags` field: flatten the 10 old `tags_*` columns.
       - For each of `tags_year_era`, `tags_content_type`, `tags_song_reference`, `tags_release_stage`, `tags_subject`, `tags_topic`, `tags_rarity`, `tags_preservation`, `tags_keywords`: if value is a JSON array, splat; else if value is a comma-separated string, split; else treat as single value.
       - Slugify every value using the same rules as tag vocabulary.
       - Skip empty/invalid slugs.
       - Add `'hunter_root'` to every artifact's tag list (all existing rows are HR).
       - Dedupe.
       - Write as `json.dumps(sorted_list_of_slugs)`.
     - `tags_permission` copied through (still a column).
     - `permission_contact`, `permission_evidence_path`, `confidence_flags`, `notes` copied.
     - DROP old columns: `domain`, the 9 flattened `tags_*` columns, `url`, `tinyurl`.
   - INSERT into `artifacts_v4`.

5. **Sidecar parent linking:**
   - Read `_cowork/pre_refactor_snapshot.json` → `sidecar_parent_matches`.
   - For each sidecar with exactly one parent candidate, set `parent_artifact_id` on the new row.
   - For multiple candidates, pick the one whose `local_asset_path` is non-null and does NOT end in `.json`.
   - Zero candidates → leave `parent_artifact_id=NULL`, log.
   - Target: 18 sidecars should end up linked. Flag if the count is <10 or >25.

6. **Update `usage_count` on tags:**
   - For every tag in every artifact's `tags` JSON array, increment the tag's `usage_count`.
   - Do this as a SQL query after all artifacts are inserted, not incrementally.

7. **Rebuild ID sequence:**
   - Extract `YYYYMMDD` from every artifact id (both old `MV-HR-YYYYMMDD-NNN` and the new `MV-YYYYMMDD-NNN` format).
   - Take the max sequence number per date.
   - Insert into `id_sequence_v4`.

8. **Migrate ingest_queue:**
   - Copy rows from old `ingest_queue` to `ingest_queue_v4`.
   - Skip rows where `status IN ('skip', 'failed')` — they're closed.
   - Drop `domain` column in the process.
   - Preserve `queue_id` values.

9. **Verify (all assertions must pass):**
   - `COUNT(*) FROM artifacts_v4` equals old artifact count (76).
   - Every artifact's `tags` column is valid JSON.
   - Every tag in every `tags` column has a corresponding row in `tags`.
   - `COUNT(*) FROM tags` is non-zero.
   - Sidecar parent link count is in range [10, 25].
   - No row has `status` outside the allowed set.
   - No row has `storage_mode` outside the allowed set.

10. **Drop old tables:** `artifacts`, `post_packages`. Rename `*_v4` to canonical.

11. **Rebuild indexes** per design doc §3.2.

12. **Commit.**

### 1.3 Handle the vaulted storage root

Create folder `catalogs/vaulted/` (if not exists). Will be used by new ingests with `storage_mode='vaulted'`. Existing artifacts that were marked `'vaulted'` already live elsewhere under `catalogs/` — don't move them. Future artifacts use `catalogs/vaulted/<YYYY>/<MM>/<artifact_id>.<ext>`.

### 1.4 Run the migration

```
python core/migrate_to_v04.py
```

Capture stdout to `_cowork/migration_log_<timestamp>.txt`. If verification fails, ROLLBACK, restore from `bak_v04phase1_*`, fix migration, re-run.

### 1.5 Deliverable

Clean v0.4 DB with all 76 artifacts migrated, tag vocabulary seeded, sidecars linked. `core/migrate_to_v04.py` stays in repo as reference.

---

## 2. Phase 2 — Backend rewrite

**Goal:** Replace the 828-line `imgserver.py` with a clean version serving 30 routes.

### 2.1 Steps

1. Rename `core/imgserver.py` → `core/imgserver.py.old_v02` (reference copy).

2. Write new `core/imgserver.py`:
   - Imports: single block, no duplicates.
   - Config: paths, port (51822), MIME types, allowed extensions.
   - Utilities: `make_thumbnail()`, `db_conn()`, `send_json()`, `send_error()`, `slugify()`, `validate_tags_json()`.
   - Route dispatch: dict-of-dicts `{method: {path: handler}}` for exact paths. Separate list for prefix routes (`/image-raw`, `/asset-raw`, `/ext/`).
   - Handler functions, one per route.
   - Tag management helper: `upsert_tag(slug, display_name=None, is_proposed=0)` — inserts if missing, updates usage_count.
   - Main block: print route list on startup, bind to 127.0.0.1:51822, open browser.
   - No `run_migrations` function.
   - No duplicate `_ext_log`.
   - No `/ext-log*`, `/ext-status`, `/api/package*`, `/inbox`, `/browser`, `/recrop`, `/intake`, `/api/inbox-count`, `/thumbnail`, `/thumbwrite`, `/scan` routes.

3. Handler specifics (critical behavior):

**`POST /api/artifact-save`** accepts `{queue_id, id, fields, raw_path, release_immediately}`.
- `fields` includes all artifact columns including `tags` (JSON array), `storage_mode`, `media_type`, etc.
- If `storage_mode='vaulted'` and `raw_path` is NOT under `catalogs/vaulted/`, copy the file in and update `local_asset_path` to the new location.
- If `release_immediately=true`, set `status='released'`, `released_at=now`, `released_by='mike'`.
- Else `status='vault'`.
- For every tag in the JSON array:
  - If tag doesn't exist in `tags` table → create it with `is_proposed=1`.
  - Increment `usage_count`.
- INSERT into `artifacts`.
- UPDATE `ingest_queue` SET `artifact_id=id`, `status='keep'` WHERE `queue_id=?`.

**`POST /api/artifact-update`** accepts `{id, fields}`.
- For tag diff: compute added/removed sets. Decrement usage_count on removed tags. Increment on added. Create proposed tags as needed.
- Update row, set `updated_at=now`.

**`POST /api/artifact-release`** accepts `{id}`. Sets `status='released'`, `released_at=now`, `released_by='mike'`.

**`POST /api/artifact-unrelease`** accepts `{id}`. Sets `status='vault'`, `released_at=NULL`, `released_by=NULL`.

**`POST /api/artifact-archive`** accepts `{id}`. Sets `status='archived'`.

**`POST /api/next-id`** accepts `{}`. Increments `id_sequence` for today's date. Returns `{id: "MV-YYYYMMDD-NNN"}`.

**`GET /api/tags`** accepts query params `?proposed_only=0|1`, `?group=<name>`, `?min_usage=<n>`. Returns tag rows.

**`POST /api/tag-create`** accepts `{slug, display_name, description, group_name, is_proposed}`. Validates slug format. Inserts row.

**`POST /api/tag-accept`** accepts `{slug}`. Sets `is_proposed=0`.

**`POST /api/tag-reject`** accepts `{slug, mode, replacement_slug?}`. Modes: `"remove"` (strip from all artifacts, delete tag), `"replace"` (swap to replacement_slug in all artifacts, delete original), `"deprecate"` (leave artifacts alone, mark tag deprecated — add a `deprecated=1` column if needed, or just rely on UI convention).

**`POST /api/tag-update`** accepts `{slug, new_slug?, display_name?, description?, group_name?}`. If `new_slug` given, propagate rename to all artifacts carrying the old slug.

**`POST /api/intake-url`** accepts `{source_url, source_platform?, tags?, description_short?}`. Creates a queue row with `storage_mode='url_only'` implied, `raw_path=NULL`.

**`POST /api/intake-from-fb-candidate`** accepts `{fb_candidate_id}`. See §5.

**`POST /api/enrich`** — see design doc §7 for prompt. Store response in `ingest_queue.enrichment_json`. Any `tags_proposed` in the response get created with `is_proposed=1` and applied to the artifact.

**`GET /fb`** — serve `fb_candidates.html` as-is.

**`GET /api/fb-candidates`** — read `core/fb_candidates.json`, return as JSON.

**`POST /api/fb-candidate-save`** — accept candidate triage state, write to `core/fb_candidates.json`.

4. Smoke test the server: start it, curl `/ping`, `/api/tags`, `/api/queue`. Stop it.

### 2.2 Deliverable

Clean `core/imgserver.py`, ~600–800 lines, 30 routes, no dead code.

---

## 3. Phase 3 — Frontend rewrite

**Goal:** Replace `hr_manager.html` with new `mediavault.html` implementing the two-mode UI from design doc §5.

### 3.1 Steps

1. Rename `hr_manager.html` → `hr_manager.html.old_v02`.

2. Write new `mediavault.html`. Single file with inline CSS and JS.

3. Structure:
   - Top nav: "MediaVault" title + two tab buttons (INBOX, MEDIAVAULT).
   - `#inboxPane` — review workstation (design doc §5.1 INBOX mode).
   - `#vaultPane` — collection view (design doc §5.1 MEDIAVAULT mode).
   - `#vocabPane` — tag vocabulary admin (design doc §5.4), accessed via gear icon.

4. Tag picker component (§5.3):
   - Autocomplete text input.
   - Typing a non-existing slug offers "Add proposed tag."
   - Browse panel groups tags by `group_name` with "Ungrouped" on top.
   - Grouped tags behave as radios on the current artifact (one at a time).
   - Applied tags shown as removable pills above the inputs.
   - Proposed tags visually flagged (dashed border + italic + "proposed" badge).

5. Filter bar in MediaVault mode (§5.2):
   - Full-text search box.
   - Date-from / date-to pickers.
   - Status dropdown (default: "Vault + Released").
   - Storage mode dropdown.
   - Tag pills with tri-state click behavior. Proposed tags visually flagged here too.
   - Grid|Table toggle + sort dropdown.
   - "Show children inline" checkbox.

6. Card styles (grid view):
   - Rectangular, ~280px wide × ~240px tall.
   - Top: thumbnail (via `/image-raw` or `/asset-raw` as routed by the existing renderer.js).
   - Below thumbnail: ID (muted), short desc (1 line), long desc (2 lines clamped), platform + date line, primary-tag chip.
   - Top-right overlay badges: ★ (released), 🔗 (url_only), 📁 (vaulted), ↗ (referenced).

7. Table view:
   - Sticky headers, clickable to toggle ASC/DESC.
   - Columns: `★` · `ID` · `Short Description` · `Platform` · `Date` · `Status` · `Storage`.
   - Active column shows `↑` or `↓`.

8. Detail panel (right side):
   - Full field display.
   - Edit mode toggle.
   - `RELEASE` / `UNRELEASE` button.
   - `ARCHIVE` button.
   - Children section: if this artifact has children in `artifacts` (by parent_artifact_id), list them with thumbnail and click-to-navigate.

9. Vocabulary admin panel:
   - Filter: All / Proposed / Accepted / Deprecated / Unused.
   - Per-tag actions: Accept (proposed only) / Reject (proposed only, three-way chooser) / Rename / Edit (display name, description, group) / Delete (if usage_count=0).
   - "Reject" opens a modal asking: remove from all N artifacts / replace with another tag (picker) / keep but mark deprecated.

10. Preserve:
    - Same CSS variables (`--gold`, `--bg2`, `--bg3`, `--border`, `--mono`, `--text`, `--text2`).
    - Same tab-button style.
    - `<script src="/ext/hr_manager_renderer.js"></script>` tag — the renderer still works on `<img src="/image-raw?path=...">` and `<img src="/asset-raw?path=...">` patterns.
    - sql.js integration reading `/db` for the vault grid/table (read-only; writes still go through API endpoints).

11. Remove everything related to basket, composer, calendar, package scheduling.

12. Update `/` route in `imgserver.py` to serve `mediavault.html`.

### 3.2 Deliverable

Clean `mediavault.html`, ~60–80KB, two modes, no basket, no composer.

---

## 4. Phase 4 — Ingest engine adjustment

**Goal:** Update `core/ingest_engine.py` for v0.4 schema. Light touch, not a rewrite.

### 4.1 Changes

1. Rename column references: `media_type_in_post` → `media_type` everywhere.
2. Remove references to `domain` column. `scan` no longer accepts `--domain`; it just scans and queues.
3. Remove references to `url`, `tinyurl` columns in any INSERT.
4. When inserting a row into `artifacts` directly (process phase), include `storage_mode` — compute based on path:
   - If path is under `catalogs/vaulted/` → `'vaulted'`.
   - If path is under MediaVault's intake/processed → `'referenced'` (the engine moved them there but they're still "in my zone, not owned by MV").
   - Wait — better rule: if a file came through intake and got moved to processed, that's effectively vaulting. Use `'vaulted'`, and copy/move accordingly.
5. When inserting a row with tags, route through the same tag upsert helper as imgserver.
6. Remove all `DOMAIN_PREFIXES` dict and domain-specific logic.

### 4.2 Preserve

- Scan → queue flow.
- Process → thumbnail/EXIF/move flow.
- CLI commands: `scan`, `process`, `status`.
- All the Pillow/HEIC/exiftool machinery.

### 4.3 Deliverable

`core/ingest_engine.py` adjusted and tested via `python core/ingest_engine.py status`.

---

## 5. Phase 5 — FB-to-Inbox bridge

**Goal:** One new endpoint, one new button.

### 5.1 Endpoint

Add `POST /api/intake-from-fb-candidate` to `imgserver.py`:
- Accepts `{fb_candidate_id}`.
- Loads `core/fb_candidates.json`.
- Finds the candidate.
- Creates an `ingest_queue` row:
  - `ingest_source='fb_candidate'`
  - `source_url` = candidate's post URL
  - `raw_path` = any local image saved for the candidate (else NULL)
  - `enrichment_json` = JSON containing any tags the candidate already has, its fact text (as description_long seed), author as author_name, platform='facebook'.
- Marks the candidate as `graduated=true` in fb_candidates.json.
- Returns `{queue_id}`.

### 5.2 Button

Add a button to `fb_candidates.html`'s accepted-candidate UI: "Send to MediaVault Inbox →"
- On click: POST to `/api/intake-from-fb-candidate` with the candidate id.
- On success: toast confirmation, disable button for that candidate.
- On error: show error inline.

### 5.3 Deliverable

Function works end-to-end: click button in /fb → item appears in /api/queue → visible in MediaVault's inbox.

---

## 6. Phase 6 — Cleanup, docs, smoke test

### 6.1 Quarantine

Move `core/imgserver.py.old_v02` and `hr_manager.html.old_v02` (your phase-2 and phase-3 reference backups) to `D:\AI_OK_TO_DELETE\MediaVault_v04_refactor_<date>\`. Prep already handled the rest.

### 6.2 Documentation updates

Update `PROJECT.md`:
- Reframe as review workstation + artifact vault.
- Explicitly state: tags are flat, artist is a tag, status lifecycle is inbox/vault/released/archived.

Update `SPEC.md`:
- Bump version to 0.4.
- Replace Domains section with Tags section.
- Add storage_mode section.
- Add tag vocabulary + proposal flow section.
- Add release flow section.
- Remove Post Builder section (never built).
- Update all schema snippets to match §3.2 of the design doc.

Update `STATE.md`:
- New session entry for 2026-04-17: "MediaVault v0.4 refactor complete. Domain concept eliminated; artist is now a tag. Schema collapsed 10 tags_* columns into one tags JSON array. Status lifecycle added (inbox/vault/released/archived). Storage mode column added. Proposed-tag flow active. FB-to-Inbox bridge live. imgserver rewritten: 30 clean routes. mediavault.html replaces hr_manager.html."
- List any decisions made on ambiguous items.
- List any sidecars that failed to match parents.

Update `WORKFLOW.md`:
- New flow: add files → inbox → review + tag + save → vault → release when ready.
- New: tag vocabulary admin panel.
- New: FB candidates → MediaVault inbox via button.

### 6.3 Smoke test

1. Start `python core/imgserver.py`.
2. Open `http://127.0.0.1:51822/` in browser.
3. INBOX tab:
   - Verify 3 pending queue items from the snapshot render correctly.
   - Pick one. Click SAVE TO VAULT. Verify it moves to vault.
   - Pick another. Click RELEASE. Verify it saves with released status and badge appears in vault.
4. MEDIAVAULT tab:
   - Default filter ("Vault + Released") shows 58 non-sidecar artifacts.
   - Toggle "Show children inline" → count increases to 76.
   - Type `hunter_root` in full-text search → all results (everything is HR-tagged).
   - Type `whiskey` → filters to rows mentioning "Whiskey to the Sun."
   - Click a rarity tag pill → filters.
   - Click again to MUST NOT → opposite filter.
   - Click date range to 2026-04-17 → shows recent imports.
   - Click column headers in table view → sort changes, arrow appears.
   - Click an artifact. In detail panel, click RELEASE → badge appears. Click UNRELEASE → badge disappears.
5. Vocabulary admin:
   - Open via gear icon.
   - Verify migrated tags are visible.
   - Create a test proposed tag. Accept it. Verify badge changes.
   - Reject a different proposed tag with "replace" mode. Verify replacement applies to affected artifacts.
6. FB bridge:
   - Open `/fb`.
   - Pick an accepted candidate.
   - Click "Send to MediaVault Inbox."
   - Verify toast success.
   - Switch to INBOX tab in MediaVault. Verify new queue item is present with pre-filled fields.

7. Stop imgserver.

### 6.4 Release the build lock

`Set-Content C:\AI\BUILD_LOCK.txt "UNLOCKED"` — do this LAST, after smoke test passes.

### 6.5 Final summary

Write `_cowork/PHASE_SUMMARY.md`:
- What shipped per phase.
- Decisions made on ambiguous items.
- Row counts before/after.
- Files quarantined count.
- Sidecars that failed to match parents (list).
- Open issues for next session.

---

## 7. What you must NOT do

- **Do not touch the museum codebase** at `C:\AI\Projects\weird-baby-update\`.
- **Do not modify `core/imgserver_extensions.py`** (unchanged helper module).
- **Do not modify `ext/hr_manager_renderer.js`** (well-designed DOM observer; keep as-is).
- **Do not modify `core/enrich_helper.py`** unless schema changes force it.
- **Do not delete anything** outside the quarantine process. All disposal → `D:\AI_OK_TO_DELETE\`.
- **Do not add features** beyond this brief and the design doc.
- **Do not change the aesthetic.** Same dark gold monospace.
- **Do not rename existing `MV-HR-*` IDs.** They stay as they are forever.

---

## 8. Already-made decisions (do not re-litigate)

All 26 decisions in the design doc's decision ledger (implicitly via §2 "what changed from v0.3 to v0.4") and §9 "what does not change". Key ones:

| Decision | Choice |
|---|---|
| Domain concept | Dropped. Artist is a tag. |
| ID format | `MV-YYYYMMDD-NNN`. No prefix. |
| Existing IDs | Preserved as-is. |
| Status | Column (`inbox`/`vault`/`released`/`archived`). |
| Storage | Column (`vaulted`/`referenced`/`url_only`). |
| Tags | Flat JSON array + `tags` vocabulary table. |
| Tag groups | Vocabulary-level `group_name` (mutually exclusive in UI). |
| Proposed tags | Apply immediately, visually flagged, accept/reject via admin. |
| Reject proposed tag | 3-way chooser: remove / replace / deprecate. |
| Search | Full-text box + structural widgets + tri-state tag pills. |
| Enrichment | Evidence-driven; no hardcoded per-artist prompt. |
| Default storage for new ingests | `vaulted` (per Mike's preference). |
| FB integration | `/fb` stays; add one "Send to Inbox" button. |
| UI name | "MediaVault" / `mediavault.html` |
| Share URLs | Not built now. YAGNI. |
| Permissions | Kept minimal. Not a priority. |

---

## 9. Files you authoritatively create, rewrite, or update

**New:**
- `core/migrate_to_v04.py`
- `mediavault.html`
- `_cowork/PHASE_SUMMARY.md`

**Full rewrite:**
- `core/imgserver.py`

**Updated:**
- `core/ingest_engine.py` (adjustments only)
- `fb_candidates.html` (one new button)
- `PROJECT.md`
- `SPEC.md` (bump to 0.4)
- `STATE.md`
- `WORKFLOW.md`

**Quarantined at Phase 6:**
- `core/imgserver.py.old_v02`
- `hr_manager.html.old_v02`

**Not touched:**
- `core/imgserver_extensions.py`
- `core/enrich_helper.py`
- `ext/hr_manager_renderer.js`
- `core/tag_vocabulary.json` (kept as seed/backup; DB is authoritative now)
- `core/fb_candidates.json` (active data)
- `core/ingest_engine.py` substantially — only the light adjustments above
- Everything under `intake/`, `catalogs/`, `thumbnails/`
- `launch_mediavault.bat`, `open_hr_urls.ps1`
- `C:\AI\Projects\weird-baby-update\`

---

## 10. When to stop and flag

Write to `_cowork/STOP_NOTE.md` and stop if:

1. **Sidecar match count is <10 or >25.** Snapshot predicts ~18. Major deviation means detection logic is wrong or data shifted. Roll back and ask Mike.

2. **Schema migration verification fails.** Row count off, JSON tag arrays invalid, parent FK can't resolve, tag vocab incomplete. Roll back and ask.

3. **Smoke test fails on existing content.** If the new UI + backend can't render the 76 migrated artifacts, something about the migration contract is wrong. Do not ship a broken tool.

For smaller decisions (CSS tuning, utility function details, minor tag display choices) — you have authority. Note them in `PHASE_SUMMARY.md`.

---

## 11. When done

1. `BUILD_LOCK.txt` contains `UNLOCKED`.
2. `_cowork/PHASE_SUMMARY.md` is complete.
3. Post a final message: "MediaVault v0.4 refactor complete. [N-line summary.] Ready for Mike's review."

Walk away clean.
