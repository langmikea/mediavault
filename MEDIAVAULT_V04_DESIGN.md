# MediaVault v0.4 — Design Document

**Decision:** Targeted reconstruction with the data model rebuilt around flat tags.
**Date:** 2026-04-17
**Agent:** Claude (web session, handing to cowork)
**Status:** Design locked. Ready for execution.
**Supersedes:** v0.3 design (the `domains` table concept is dropped).

---

## 1. Core mental model

**MediaVault is a review workstation and a permanent vault for anything worth keeping.**

An **artifact** is one thing worth cataloging: a photo, a URL, a page save, a song, a metadata file, a text extract. Artifacts can link to each other via `parent_artifact_id` — a URL artifact can have child artifacts for its images, its text, its audio — but each child is addressable on its own. You can artifact a URL and stop there, or drill in as deep as you care to.

An artifact has:
- A **lifecycle status** — `inbox` → `vault` → `released` → `archived`. Operational.
- A **storage mode** — `vaulted` (MV owns the bytes), `referenced` (MV points at your file), or `url_only` (no local file). Structural.
- **Dates** — `post_date`, `capture_date`, `ingest_date`. Structural.
- **Descriptions** — short, long, extracted text, media type. Structural.
- **Tags** — a flat JSON array of slugs. Descriptive. Unlimited. Cheap.
- **A parent** — optional. Structural.

**Tags describe.** Columns constrain, drive behavior, or need fast indexed lookup. The test: does this attribute change UI behavior, enforce an invariant, or get queried on the hot path? Yes → column. No → tag.

**Artist is a tag.** So is year. So is rarity. So is `lyme_disease`. So is `hunter_root`. They're all just strings in a flat pool. You tag a photo with `hunter_root, jesse_welles, carsie_blanton, crowd, concert` and it belongs to all those worlds simultaneously. Splitting an artist later is a rename operation, not a schema migration.

**Search is multi-layered.** One full-text box covers description, tags, URL, extracted text. Structural columns (date range, status, storage mode) get dedicated input widgets. Tags get tri-state pills (MUST / MUST NOT / don't care). Tag groups can make pills mutually exclusive.

**The UI layer is separate from the data layer.** The model is flat tags. The input surface is whatever reduces friction — calendars for dates, radios for mutually-exclusive tag groups, sliders for rarity if you want. Widgets write the right tag slugs or column values. The data stays simple.

---

## 2. What changed from v0.3 to v0.4

| Concept | v0.3 | v0.4 |
|---|---|---|
| Artist | Dedicated `domain` column + `domains` lookup table | A tag. No domain concept. |
| ID format | `MV-<prefix>-YYYYMMDD-NNN` | `MV-YYYYMMDD-NNN`. No prefix. |
| Existing `MV-HR-*` IDs | Kept as-is | Kept as-is. Identity is permanent. |
| Storage ownership | Implicit | Explicit `storage_mode` column. |
| 10 `tags_*` columns | 10 separate columns | 1 `tags` JSON array + `tags_permission` kept |
| Tag scoping | By `domain_scope` (per-artist) | By **tag groups** (mutually exclusive sets) + **proposed** flag |
| Release flag | Separate boolean | Part of the `status` lifecycle (`released` is one of four statuses) |
| Enrichment prompt | Per-domain hardcoded | One template, evidence-driven |
| Search UI | Per-category dropdowns | Full-text box + structural widgets + tri-state tag pills |

**v0.3 concepts dropped entirely:** the `domains` table, the `id_prefix` column, domain-scoped tags, per-domain enrichment contexts, the 10 separate `tags_*` columns (except `tags_permission`).

**v0.3 decisions that carry forward:** status lifecycle, parent_artifact_id model, dropping `post_packages`, dropping `url`/`tinyurl`, UI title "MediaVault" (filename `mediavault.html`), 21-route backend surface, sidecar-as-child pattern, targeted reconstruction (not rebuild), all cleanup inventory.

---

## 3. Schema v0.4

### 3.1 Design principles

- `CHECK` constraints belong on operational invariants (status lifecycle, storage_mode, link_status). Not on evolving taxonomies.
- Descriptive metadata → flat tags in a JSON array.
- Operational/structural/hot-query-path attributes → dedicated columns.
- No schema change required to rename, merge, split, or invent tags.
- Tag vocabulary is a lookup table so tags can carry display names, groups, and proposal flags.

### 3.2 Full schema

```sql
-- ============================================================
-- artifacts: one row per thing worth cataloging
-- ============================================================
CREATE TABLE artifacts (
    id                      TEXT PRIMARY KEY,           -- MV-YYYYMMDD-NNN

    -- Source and provenance
    source_url              TEXT,
    source_platform         TEXT,                       -- free text
    ingest_source           TEXT,                       -- free text
    ingest_date             DATE NOT NULL,

    -- Storage
    storage_mode            TEXT NOT NULL DEFAULT 'vaulted'
                                CHECK(storage_mode IN ('vaulted','referenced','url_only')),
    local_asset_path        TEXT,                       -- null for url_only
    thumbnail_path          TEXT,
    link_status             TEXT CHECK(link_status IN ('live','dead','local-only')),

    -- Structure
    parent_artifact_id      TEXT REFERENCES artifacts(id) ON DELETE CASCADE,
    media_type              TEXT,                       -- drives renderer dispatch

    -- Dates (structural; indexed)
    post_date               DATE,
    post_date_confidence    TEXT CHECK(post_date_confidence IN
                                ('extracted','manual','estimated','unknown')),
    capture_date            DATE,

    -- Lifecycle (operational; indexed)
    status                  TEXT NOT NULL DEFAULT 'vault'
                                CHECK(status IN ('inbox','vault','released','archived')),
    released_at             TEXT,                       -- ISO datetime
    released_by             TEXT,

    -- Descriptions (free text)
    description_short       TEXT,
    description_long        TEXT,
    extracted_text          TEXT,
    author_name             TEXT,

    -- Tags — the single flat array of slugs
    tags                    TEXT NOT NULL DEFAULT '[]', -- JSON array, validated on write

    -- Permission (kept from v0.2; minimal workflow today)
    tags_permission         TEXT,                       -- kept as single column
    permission_contact      TEXT,
    permission_evidence_path TEXT,

    -- Audit
    confidence_flags        TEXT,
    notes                   TEXT,
    created_at              TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at              TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_artifacts_status       ON artifacts(status);
CREATE INDEX idx_artifacts_storage_mode ON artifacts(storage_mode);
CREATE INDEX idx_artifacts_post_date    ON artifacts(post_date);
CREATE INDEX idx_artifacts_ingest_date  ON artifacts(ingest_date);
CREATE INDEX idx_artifacts_parent       ON artifacts(parent_artifact_id);
CREATE INDEX idx_artifacts_source_url   ON artifacts(source_url);

-- ============================================================
-- tags: the vocabulary
-- ============================================================
CREATE TABLE tags (
    slug            TEXT PRIMARY KEY,
    display_name    TEXT NOT NULL,
    description     TEXT,
    group_name      TEXT,                               -- mutually-exclusive picker group; null = independent
    is_proposed     INTEGER NOT NULL DEFAULT 0,         -- 1 = visually flagged in UI until accepted
    usage_count     INTEGER NOT NULL DEFAULT 0,         -- denormalized; updated on tag add/remove
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_tags_group    ON tags(group_name);
CREATE INDEX idx_tags_proposed ON tags(is_proposed);

-- ============================================================
-- ID generation (simplified from v0.2 — no per-domain sequence)
-- ============================================================
CREATE TABLE id_sequence (
    date_str  TEXT PRIMARY KEY,                         -- YYYYMMDD
    last_seq  INTEGER NOT NULL DEFAULT 0
);

-- ============================================================
-- ingest_queue: inbox staging area (unchanged from v0.3 except updated_at)
-- ============================================================
CREATE TABLE ingest_queue (
    queue_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ingest_source   TEXT NOT NULL,                      -- free text, no CHECK
    raw_path        TEXT,
    source_url      TEXT,
    queued_at       TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending'
                        CHECK(status IN ('pending','keep','skip','enriched','approved','failed')),
    enrichment_json TEXT,
    error_message   TEXT,
    artifact_id     TEXT,                               -- set when promoted to artifact
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- DROPPED tables (from v0.3 or prior):
--   domains         — never existed; v0.3 concept abandoned
--   post_packages   — was in v0.2; 0 rows; composer dead
--   tag_vocabulary  — v0.3 renamed to `tags`; simpler
-- ============================================================
```

### 3.3 Tag slug format

Slugs are `lowercase_with_underscores`. Display names are whatever you want (e.g., slug `hunter_root` → display `Hunter Root`).

Slug rules enforced at insert time:
- `^[a-z0-9_]+$`
- Length 1–64.
- Unique in `tags` table.

### 3.4 Tag groups

A `group_name` on a tag marks it as mutually exclusive with other tags in the same group. UI implication: a picker group like `{morning, noon, night}` (all with `group_name='time_of_day'`) displays as a radio-button group in input UI. Selecting one implicitly deselects siblings. Data enforcement: the write-tag endpoint checks that an artifact doesn't carry two tags from the same group; if it does, the new one wins, the old sibling is removed, and a warning is logged.

Group membership is vocabulary-level, not schema-level — changing a tag's `group_name` is one UPDATE.

### 3.5 Proposed tags

A tag row with `is_proposed=1` is a tentative addition. Created in two ways:

1. Enrichment proposes a tag Claude didn't find in the existing vocabulary. The tag row is created with `is_proposed=1`, applied to the artifact immediately.
2. You type a new tag slug in the picker that doesn't exist yet. Same behavior: created with `is_proposed=1`, applied.

UI surfaces proposed tags with a visual flag (dashed border, italic display name, "proposed" badge — implementation detail). A vocabulary management panel shows all proposed tags with three affordances:

- **Accept** — flip `is_proposed=0`. Tag becomes normal.
- **Reject** — opens a confirmation: "This tag is on N artifacts. [Remove from all] [Replace with another tag…] [Keep, mark deprecated]." Per your call on Q1.
- **Rename** — change slug and display name, propagate to all artifacts that carry it.

### 3.6 Storage modes

- **`vaulted`** — MediaVault owns the bytes. On save, the source file is copied into `catalogs/vaulted/YYYY/MM/<artifact_id>.<ext>` (year/month folders avoid tens of thousands of files in one directory). Deleting the artifact optionally deletes the vaulted file; MV's default is to soft-delete (status='archived') and leave the file alone.
- **`referenced`** — `local_asset_path` points to a file somewhere you manage (e.g., `C:\AI\Projects\Hunter Root\archive\...`). MV reads it but never moves, copies, or deletes. If the file disappears, `link_status='local-only'` flags missing-asset state.
- **`url_only`** — No local file. `local_asset_path=NULL`. `source_url` is the only reference. `link_status` tracks remote availability.

**Defaults at ingest:**
- File uploaded via inbox UI file picker → `vaulted` (you chose to hand it over).
- File dropped in `intake/drop/` → `vaulted` (per your Q2: for now, vault a copy of everything possible).
- URL entered with no local file → `url_only`.
- `/api/artifact-register` called with a path outside MV's intake folders → `vaulted` (copies in).
- Your existing HR archive files (at `C:\AI\Projects\Hunter Root\archive\...`) — already referenced by 58+ current artifacts — stay `referenced`. Migration does not mass-vault them.

**Override:** the inbox field editor has a storage mode dropdown so you can flip any incoming item before save.

### 3.7 The `tags` column format

JSON array of slug strings. Example: `["hunter_root", "live_show", "2024", "crowd"]`.

Stored as TEXT in SQLite. Validated on write (every element must match `^[a-z0-9_]+$` and exist in the `tags` table). Deduplicated on write.

Searches use SQLite JSON operators: `json_each(tags)` for iteration, `EXISTS (SELECT 1 FROM json_each(tags) WHERE value = ?)` for membership.

Full-text search is a simple `LIKE` across a concatenated string (for now): `(description_short || ' ' || description_long || ' ' || tags || ' ' || IFNULL(extracted_text,'') || ' ' || IFNULL(source_url,''))`. If performance becomes a problem (76 artifacts today; FTS5 virtual table is trivial to add later when it matters).

---

## 4. Migration from v0.2 schema to v0.4

### 4.1 Source data

- `artifacts` table, 76 rows, with 10 `tags_*` columns and `domain='hunter_root'`.
- 18 rows are sidecar metadata artifacts that should link to parents.
- 18 rows have `local_asset_path` pointing to files that no longer exist on disk.
- `post_packages` table, 0 rows.
- `url` and `tinyurl` columns on artifacts, almost always NULL.

### 4.2 Migration steps (all in one transaction)

1. **Backup DB** with timestamp (belt and suspenders; prep script already did one).

2. **Create new tables alongside old:** `artifacts_v4`, `tags`, `id_sequence_v4`, `ingest_queue_v4`.

3. **Build the starter tag vocabulary** by scanning existing data:
   - Insert `('hunter_root', 'Hunter Root', NULL, 0, 0)` — seed the one artist who has rows.
   - Scan every non-null value across the 10 `tags_*` columns. Each distinct value becomes a tag row. Display name is a title-cased humanization of the slug unless obvious (`2024` → display `2024`, no change; `live-show` → slug `live_show`, display `Live Show`).
   - Tag group assignments at migration:
     - `{common, notable, rare, unique}` → `group_name='rarity'`.
     - `{standard, critical}` → `group_name='preservation'`.
     - Year-like values (four-digit numbers, era strings) → **not** grouped (you might want multiple years on one artifact, e.g., "written in 2019, released in 2022").
     - Everything else → `group_name=NULL` (independent).
   - All migrated tags get `is_proposed=0` (accepted by default — they're from real data).

4. **Copy each artifact row from old to new:**
   - `status='vault'` for all (they've been reviewed).
   - `media_type = media_type_in_post` (rename).
   - `storage_mode='referenced'` for rows whose `local_asset_path` is outside `C:\AI\Platform\MediaVault\catalogs\` (HR archive files, etc).
   - `storage_mode='vaulted'` for rows whose `local_asset_path` is inside `catalogs/`.
   - `storage_mode='url_only'` for rows where `local_asset_path IS NULL` and `source_url IS NOT NULL`.
   - For rows with missing asset files: `link_status='local-only'`, keep `local_asset_path` (it's still accurate metadata about where the file was).
   - Build the `tags` array by flattening the 10 `tags_*` columns. Parse any values that look like JSON arrays (e.g., `'["2025"]'`, `'["live-show","gear"]'`) and splat their contents. Dedupe. Prepend `hunter_root` to every artifact's tags (they're all HR). Write as JSON.
   - Copy `tags_permission` through as-is (kept as column).
   - Drop `domain`, the other 9 `tags_*` columns, `url`, `tinyurl`.
   - Update `usage_count` on every tag by counting artifact membership.

5. **Sidecar parent linking:** for each row where the old `tags_content_type` contained `metadata_json`, find its parent by matching `source_url` on a non-`.json`-path sibling. Set `parent_artifact_id` on the sidecar. Log any that fail to match.

6. **ID sequence rebuild:** scan all artifact IDs, extract `YYYYMMDD` portion, rebuild `id_sequence_v4` with the highest sequence used per date. Existing `MV-HR-*` IDs keep their format; only new IDs use the new `MV-YYYYMMDD-NNN` format.

7. **Ingest queue migration:** copy `ingest_queue` rows 1:1 into `ingest_queue_v4`, drop the `domain` column along the way. Skip rows with `status='skip'` or `status='failed'` (97 rows) — they're closed and won't be acted on.

8. **Verify:**
   - Count(artifacts_v4) == count(old artifacts) == 76.
   - Every non-null `tags_*` value from the old schema appears in the new `tags` table.
   - Every artifact's `tags` column is valid JSON.
   - Every tag in every `tags` column exists as a row in `tags`.
   - Sidecar parent count is in the range [10, 25] (flag outside that range).

9. **Drop old tables:** `artifacts`, `post_packages`. Rename `*_v4` → canonical names.

10. **Rebuild indexes.** Commit transaction.

### 4.3 Missing asset files

The 18 rows with `local_asset_path` pointing to missing files get `link_status='local-only'` and `storage_mode='referenced'`. They're not lost; they're flagged. You decide per row whether to re-ingest, re-reference, or archive.

---

## 5. UI redesign — mediavault.html

### 5.1 Two modes

**INBOX mode** — the review workstation.

Layout:
- Left: large image viewer with crop tool (existing renderer handles non-image artifacts via DOM upgrade).
- Right: field editor, scrollable.
- Top: queue progress (`3 of 17`), item selector dropdown.
- Bottom action bar: `✗ SCRAP` · `← PREV` · `NEXT →` · `✓ SAVE TO VAULT` · `★ RELEASE`.

Fields in editor (vertical scroll, logical groups):
- **Identity:** description_short, description_long, extracted_text, author_name, notes.
- **Source:** source_url, source_platform (free text), source_platform (suggested values from existing platforms as datalist).
- **Dates:** post_date (date picker), post_date_confidence (radio: extracted/manual/estimated/unknown), capture_date.
- **Storage:** storage_mode (dropdown: vaulted/referenced/url_only, default per §3.6), media_type (dropdown from existing distinct values + free-text fallback).
- **Tags:** tag picker (see §5.3).
- **Structure:** parent_artifact_id (searchable dropdown — type to find an existing artifact; null by default).

`★ RELEASE` = save with `status='released'` in one click. Equivalent to `✓ SAVE TO VAULT` + immediate release.

**MEDIAVAULT mode** — the reviewed collection.

Layout:
- Top: filter bar (see §5.2).
- Middle: card grid OR table (toggle).
- Right (when an item is selected): detail panel with full fields, sidecar children list, and release/unrelease/archive buttons.

Grid view: rectangular cards (taller than square). Each card shows thumbnail top, then ID, short desc (1 line), long desc (clamped 2 lines), source platform + post_date, primary tag chip, and badges (★ released, 🔗 url_only, 📁 vaulted, ↗ referenced).

Table view: columns `★` · `ID` · `Short Description` · `Platform` · `Date` · `Status` · `Storage`. Click column header to sort ASC/DESC. Active column shows arrow.

Sidecars (children) are hidden by default in both views. A "Show children inline" checkbox reveals them. The parent's detail panel always shows its children under a "Children (N)" section regardless.

### 5.2 Filter bar (MediaVault mode)

Single row of controls, in order:

1. **Full-text search box** — one input. Searches across description_short, description_long, tags, extracted_text, source_url. Live-updates.
2. **Date range** — two date pickers (from / to) operating on `post_date`. Includes rows with null post_date when both are cleared.
3. **Status filter** — dropdown: All / Inbox / Vault / Released / Archived. Default "Vault + Released" (reviewed content).
4. **Storage mode filter** — dropdown: All / Vaulted / Referenced / URL only.
5. **Tag pills** — below the top row. Horizontally scrolling row of tag chips. Each chip is tri-state:
   - click 1 → `+` green (MUST include)
   - click 2 → `−` red (MUST NOT include)
   - click 3 → off (don't care)
   - Pills show usage_count as a subscript. Proposed tags shown with dashed border.
6. **GRID | TABLE toggle** — right side.
7. **Sort dropdown** — grid view only.

Tag group interaction: when a tag with a group is selected (`+`), other tags with the same group hide. Deselecting unhides.

### 5.3 Tag picker (Inbox editor)

Two input modes:

**Fast input:** a single text box with autocomplete. Type a few letters, existing tags pop up, enter adds. Typing a non-existing slug offers "Add proposed tag `<slug>`" — accepts immediately with `is_proposed=1`.

**Browse:** a panel showing all existing tags grouped by `group_name` (and "ungrouped" at the top), with counts. Click to toggle on the artifact. Grouped tags behave as radios — clicking one deselects siblings on this artifact.

Currently-applied tags show above both inputs as removable pills.

### 5.4 Vocabulary management

A small admin panel, accessible from a gear menu in the MediaVault mode toolbar. Lists all tags with usage_count and is_proposed. Filters: All / Proposed / Accepted / Unused.

Actions per tag:
- **Accept** (proposed only) → sets `is_proposed=0`.
- **Reject** (proposed only) → opens a three-way chooser: remove from all artifacts / replace with another tag / keep but mark deprecated.
- **Rename** → new slug + display name, propagates to all artifacts.
- **Edit** → change display name, description, group_name.
- **Delete** → only if `usage_count=0`.

### 5.5 Aesthetic

Unchanged. Dark monospace, gold accents. Same CSS variables. Same tab-button style.

---

## 6. Backend redesign — imgserver.py

### 6.1 Route surface

| Method | Route | Purpose |
|---|---|---|
| GET | `/` | Serves `mediavault.html` |
| GET | `/ping` | Liveness |
| GET | `/db` | Serves the SQLite file as binary (sql.js in browser reads this) |
| GET | `/image-raw?path=` | Serves image files |
| GET | `/asset-raw?path=` | Serves non-image files |
| GET | `/ext/hr_manager_renderer.js` | Serves the renderer JS |
| GET | `/fb` | Serves fb_candidates.html |
| GET | `/api/queue` | List ingest_queue rows |
| GET | `/api/tags` | List tags (with filters: proposed_only, group, min_usage) |
| GET | `/api/fb-candidates` | FB candidates data (kept — feeds fb_candidates.html) |
| POST | `/api/intake-upload` | Multipart upload → queue row |
| POST | `/api/intake-url` | Add a URL-only artifact to queue |
| POST | `/api/intake-from-fb-candidate` | Graduate a FB candidate into the MV inbox |
| POST | `/api/queue-update` | Update queue row (enrichment_json, status) |
| POST | `/api/queue-delete` | Delete queue row |
| POST | `/api/enrich` | Vision/evidence enrichment proxy |
| POST | `/api/next-id` | Generate next `MV-YYYYMMDD-NNN` |
| POST | `/api/artifact-save` | Promote queue row → artifact (status=vault or status=released) |
| POST | `/api/artifact-update` | Edit an existing artifact |
| POST | `/api/artifact-release` | status='released' |
| POST | `/api/artifact-unrelease` | status='vault' |
| POST | `/api/artifact-archive` | status='archived' |
| POST | `/api/artifact-delete` | Hard delete (admin) |
| POST | `/api/artifact-requeue` | Send artifact back to queue |
| POST | `/api/artifact-register` | Direct artifact registration (from imgserver_extensions) |
| POST | `/api/thumbgen` | Regenerate thumbnail |
| POST | `/api/tag-create` | Create a new tag (with optional is_proposed flag) |
| POST | `/api/tag-update` | Rename, change display name, change group_name |
| POST | `/api/tag-accept` | is_proposed=0 |
| POST | `/api/tag-reject` | Three modes: remove / replace / deprecate |
| POST | `/api/tag-delete` | Only if usage_count=0 |
| POST | `/api/fb-candidate-save` | Persist FB candidate triage state |

Total: 30 routes. Larger than v0.3's 21 because the tag-management API is a real surface now, and the FB integration stays. Still cleaner than the v0.2 sprawl of 28 routes where half were dead.

### 6.2 Removed routes (same as v0.3 cleanup)

`/ext-status`, `/ext-log`, `/ext-log-dump` (retired extension diagnostics), `/api/packages*` (composer dead), `/inbox`, `/browser`, `/recrop` (dead references), `/intake` (duplicate of intake-upload), `/api/inbox-count` (UI computes from queue), `/thumbnail` (duplicate of image-raw), `/thumbwrite` (merged into artifact-save), `/scan` (CLI only).

### 6.3 Structural cleanup

- Single copy of every function. No duplicate `_ext_log`.
- Single import block. No duplicate imports.
- Route dispatch: dict-based (`{(method, path): handler}`) with a separate prefix-match list for path-prefix routes (`/image-raw`, `/asset-raw`, `/ext/`).
- No `run_migrations` function — schema is managed by explicit migration scripts.
- Tag writes go through a helper that validates slug format, upserts to the `tags` table, and updates `usage_count`.

### 6.4 Enrichment endpoint

`POST /api/enrich` accepts `{queue_id}`. The server:

1. Loads the queue row.
2. Loads any referenced image bytes for vision.
3. Loads the current tag vocabulary.
4. Builds the prompt (see §7).
5. Calls Claude.
6. Parses the response. Any tags proposed that aren't in the vocabulary get created with `is_proposed=1` and applied.
7. Writes enrichment_json back on the queue row.
8. Returns the result for the UI.

### 6.5 FB-to-Inbox bridge

`POST /api/intake-from-fb-candidate`:
- Accepts `{fb_candidate_id}`.
- Reads from `core/fb_candidates.json` (existing store).
- Creates an `ingest_queue` row with:
  - `ingest_source='fb_candidate'`
  - `source_url` = FB post URL
  - `raw_path` = any local image saved for the candidate (if present)
  - `enrichment_json` pre-populated with the candidate's triage fields (tags already assigned, fact text, author) so the inbox review skips already-done work.
- Optionally marks the FB candidate row as "graduated" in fb_candidates.json.
- Returns the new queue_id.

`fb_candidates.html` gets a new button in its accept flow: "Send to MediaVault Inbox." One click, artifact lands in the queue with pre-filled fields.

---

## 7. Enrichment prompt

One template. Assembled per-artifact from whatever evidence is present.

```
You are cataloging an artifact for a creative archive. Here is what is known:

Source URL: {source_url or "none"}
Source platform: {source_platform or "unknown"}
Capture date: {capture_date or "unknown"}
Existing tags: {comma-separated existing slugs or "none"}
Existing description: {description_short or "none"}
Extracted text: {extracted_text or "none"}
Images attached: {N}

Tag vocabulary available:
{list of accepted tag slugs with their descriptions, one per line}

Based on the evidence, return a JSON object with:
  "description_short":   one sentence, what the artifact is
  "description_long":    2-4 sentences with detail
  "post_date":           YYYY-MM-DD if extractable from evidence, else null
  "post_date_confidence": "extracted" | "manual" | "estimated" | "unknown"
  "media_type":          one of: photo | video | audio | link | text | artwork | mixed | other
  "tags_known":          array of slugs from the vocabulary above that apply
  "tags_proposed":       array of new slugs you want to add to the vocabulary
                         (lowercase_with_underscores; propose sparingly,
                         prefer known tags)
  "notes":               anything unusual or worth a human's attention

Respond with ONLY the JSON object.
```

**No hardcoded context about any particular artist.** If the artifact is already tagged `hunter_root`, that tag is in "Existing tags" and the model weighs it. If the image clearly shows a Hunter Root concert poster, the model proposes `hunter_root` as a tag. Context is evidence-driven.

---

## 8. Cleanup inventory

All paths relative to `C:\AI\Platform\MediaVault\` unless absolute.

**Quarantine to `D:\AI_OK_TO_DELETE\MediaVault_v04_refactor_<date>\`:**

- Empty stub DBs: `mediavault.sqlite` (0 bytes at root), `mediavault.db` (0 bytes).
- All `.bak*` files: `STATE.md.bak`, `hr_manager.html.bak_*`, `core/imgserver.py.bak*` (4 files), `core/ingest_engine.py.bak*` (4 files), `core/mediavault.sqlite.bak_*`, `core/mediavault_backup_*`, `capture-extension/*.bak*` (3 files), `ui/mediavault_browser.html.bak`, `ui/mediavault_inbox.html.bak*` (2 files), `ui/recapture_navigator.html`.
- Root one-shot patch scripts: `fix_ai_final.py`, `fix_ai_func.py`, `fix_ai_func2.py`, `fix_ai_preprocess.py`, `fix_queue.py`, `patch_ai.py`, `check_enriched.py`, `check_item.py`, `check_queue.py`, `check_queue2.py`.
- Core one-shot patch scripts: `core/patch_capture.py`, `core/patch_comments.py`, `core/patch_comments2.py`, `core/patch_comments3.py`, `core/patch_image.py`, `core/patch_scan.py`, `core/patch_scan2.py`, `core/fix3.py`, `core/check3.py`, `core/dump_paths.py`, `core/migrate_ingest_source.py`.
- Retired extension: `capture-extension/` (entire folder).
- Debug scripts folder contents (keep README.md only): `debug_scripts/*` except README.

**KEEP — small operational utilities (previously flagged for quarantine, now preserved):**
- `scrap_all.py` — queue bulk-skip tool, 9 lines, useful.
- `core/analyze_captures.py` — debug query for extension captures, 12 lines, useful.

**KEEP — core runtime:**
- `core/imgserver.py` (rewritten by cowork)
- `core/ingest_engine.py` (adjusted, not rewritten)
- `core/imgserver_extensions.py` (unchanged)
- `core/enrich_helper.py`
- `core/db_setup.py` (obsolete but don't touch during this refactor; Mike can quarantine later if desired)
- `ext/hr_manager_renderer.js` (unchanged)
- `core/tag_vocabulary.json` (kept as seed/backup; DB is now authoritative)
- `core/fb_candidates.json` (active data)
- `fb_candidates.html` (kept; gets one new button)

**KEEP — docs:**
- `PROJECT.md`, `SPEC.md`, `STATE.md`, `WORKFLOW.md` (all updated by cowork), `MediaVault_RS-001_v0.2.docx` (historical record; kept).

**KEEP — infrastructure:**
- `intake/` (entire tree, including unprocessed files).
- `catalogs/` (entire tree; add `catalogs/vaulted/` subtree for the new vaulted storage root).
- `thumbnails/` (entire tree).
- `launch_mediavault.bat`.
- `open_hr_urls.ps1`.

**~45 files quarantined.** (Down from v0.3's ~50 because three utilities got reprieves.)

---

## 9. What does NOT change

- sql.js in browser, reading `/db` as binary.
- `ext/hr_manager_renderer.js` DOM-observer renderer.
- `core/imgserver_extensions.py` helper module.
- `core/ingest_engine.py` CLI (`scan`, `process`, `status`) — schema adjustments only.
- Port 51822, localhost-only binding.
- Dark gold monospace aesthetic; CSS variables.
- Existing `MV-HR-*` IDs — preserved permanently.
- The 76 artifacts themselves — all migrated, none lost.
- `fb_candidates.html` — still works the same, just gains one new button.

---

## 10. Cowork execution order

Phases, in order:
1. **Schema migration** (v0.2 → v0.4). Transactional, verified, rollback-ready.
2. **Backend rewrite.** New `imgserver.py` with 30 clean routes.
3. **Frontend rewrite.** New `mediavault.html` with Inbox + MediaVault modes, full filter bar, tag picker, vocabulary panel.
4. **Ingest engine adjustment.** Light touch: rename `media_type_in_post` → `media_type`, drop `domain` references, default `storage_mode='vaulted'` for new ingests.
5. **FB bridge.** Add the one endpoint and the button in fb_candidates.html.
6. **Cleanup + docs + smoke test.**

Full step-by-step in `COWORK_BRIEF.md`.
