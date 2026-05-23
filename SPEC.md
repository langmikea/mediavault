# MediaVault — Requirements Specification
**Version:** 0.5
**Date:** 2026-04-19
**Status:** DECISIONS LOCKED (post v0.5 refactor)
**Operator:** Mike Lang
**Agent:** Claude (Anthropic)
**Stored:** C:\AI\Platform\MediaVault\SPEC.md (canonical)
**Supersedes:** v0.4 (MEDIAVAULT_V04_DESIGN.md, retained for reference) and v0.2 (MediaVault_RS-001_v0.2.docx)
**Companion design doc:** MEDIAVAULT_V05_DESIGN.md

> **Reconciled 2026-04-20** against
> `_cowork/DECISIONS_2026-04-19_pill_states_and_friends.md`. Four intent
> ambiguities from the v0.6 review were resolved; this spec has been
> subtracted accordingly. Headline changes: pill review collapses to
> three session-only states (no `pill_states` column, no persistence of
> the middle state); `is_proposed` and the proposed/accepted tag
> lifecycle are gone (one-stage vocabulary — saving an artifact implicitly
> approves its tags); slug uniqueness is global (one slug, one tag — no
> composite `(slug, category)` constraint). Implementation of
> these corrections is the v0.7 punchlist; read the decisions doc before
> editing any area this spec touches.

---

## 1. What This System Is

MediaVault is a **review workstation** and a **permanent vault** for artifacts Mike wants to keep. It is shared infrastructure for capturing, ingesting, cataloging, and retrieving media artifacts across all of Mike's personal and creative projects. It is not itself a project — projects consume from it.

The system exists because one problem kept appearing in three places independently: you accumulate artifacts, you cannot find them when you need them, and there is no reliable connection between an asset and the work product that should use it. MediaVault solves this once.

### 1.1 Primary Use Cases

- **Review.** Freshly-arrived items land in the Inbox. The operator reviews, tags, and decides each one's fate (save to vault, release as a finished item, or scrap).
- **Vault browse.** Any previously-saved artifact can be surfaced by tag, date, search, or storage mode — fast.
- **Provide source material to projects.** Hunter Root, Genealogy, and future creative work pull from the vault by tag filter.

### 1.2 What MediaVault Is Not

- Not a social media tool. It does not post.
- Not a backup system. Originals may be deleted after ingest (when `storage_mode = vaulted`).
- Not a What_Mike_Knows knowledge graph. Facts and claims are a separate concern.
- Not a replacement for any active project. Projects consume from it; they do not merge into it.

---

## 2. Pills (v0.5) — replaces "Tags"

MediaVault holds one shared database. There are no per-domain tables and no
per-domain prompts. Everything an artifact belongs to is expressed through
**pills**.

The word "pill" replaces "tag" throughout the v0.5 UI; the underlying
database still has a `tags` array column for backward compatibility. Read
"pill" and "tag" as interchangeable except where the spec distinguishes
them.

### 2.1 Pills Are Categorized

A pill is a string slug, optionally with a single `namespace:` prefix.
Examples:

    ["hunter_root", "year_2013", "song_atomic_7", "rare",
     "live_show", "early_version", "author:carsie_blanton"]

Each pill row in the `tags` table belongs to a **category**. Categories:

- `bands` — musical acts and artist groupings.
- `era` — artist career chapters (e.g., for Hunter Root: seeds, medusas, solo).
- `people` — individual humans.
- `places` — venues, geographies.
- `content_kind` — kind of thing it is (live_show, studio_photo, interview).
- `topic` — subject matter (legal_case, release_notes, wedding).
- `platform` — where the artifact lives (instagram, tiktok, reverbnation, distrokid).
- `rarity` — rare, uncommon, common. (Typically exclusive.)
- `null` — uncategorized.

A pill may also be marked `is_exclusive=1`: within its category, only one
exclusive pill can be on at a time (the picker enforces this — turning one
on drops any sibling exclusives). Rarity is the usual case.

`author:<slug>` pills are the canonical way to record an artifact's
author — the old `author_name` column was dropped in v0.5.

### 2.2 Pill Vocabulary (the `tags` table)

The `tags` table is the single source of truth for known slugs. Columns:

| Column | Type | Description |
|---|---|---|
| slug | TEXT PK | Canonical string. Lowercase, `_` separators, optional `namespace:` prefix (one colon). **Globally unique** — one slug, one tag. Category is descriptive metadata, not part of tag identity. Renaming a tag to a slug that already exists triggers a merge offer regardless of category. |
| display_name | TEXT | How the pill reads in the UI. |
| description | TEXT | Free description for the admin. Nullable. |
| category | TEXT | One of `bands`, `era`, `people`, `places`, `content_kind`, `topic`, `platform`, `rarity`, or NULL. |
| is_exclusive | INTEGER 0/1 | 1 = only one pill with this category can be on simultaneously. |
| usage_count | INTEGER | Count of artifacts currently carrying this pill. |
| created_at | TEXT | Insert timestamp. |

A tag exists in the vocabulary because an artifact was saved using it.
That act is the tag's approval; there is no separate "proposed → accepted"
workflow. See §2.5.

### 2.3 Three-State Pill Model (inbox, session-only)

During inbox review, every pill is in one of three states per artifact:

| State | Visual | Meaning |
|---|---|---|
| `on` | Solid gold | Confirmed on this artifact. |
| `suggested` | Solid gold, dashed inner border | Proposed by AI; operator hasn't confirmed yet. |
| `off` | Outline / absent | Not on this artifact. |

Plus an orthogonal WARNING render (red animated border) driven by the
attention rules (§12.5); warnings are visual, not a fourth state.

Clicking a pill flips its state:
- `on` → `off`.
- `suggested` → `on` (explicit operator confirm) on first click; a second
  click removes it (→ `off`).
- `off` → `on` (explicit operator override).

**The state model is session-only.** It exists to aid inbox review and is
not persisted anywhere — there is no `pill_states` column on `artifacts`
and no `pill_states` key in the save payload. On save, the artifact
persists plain on/off associations through `artifacts.tags`:

- `on` pills and any still-`suggested` pills are **auto-confirmed** and
  written to `artifacts.tags`.
- `off` pills are omitted.
- No provenance (AI vs manual) is recorded. A tag on an artifact is just
  a tag on an artifact.

Auto-confirming the `suggested` state is a deliberate tradeoff: the AI
tends to land close enough that silent acceptance is cheaper than the
per-artifact review cost of mandatory confirm-or-drop. If the AI proposes
10 pills and the operator only reviews 3, all 10 ship. Revisit if AI
accuracy degrades.

### 2.4 Tri-State Pill Filter (vault)

In the Vault tag bar, each pill is `off`, `MUST` (artifact must carry it),
or `MUST NOT`. Click cycles through the three states. Combined with text
search, status, storage mode, and date range, this is the canonical way to
browse the vault.

### 2.5 Novel-Pill Flow (one-stage vocabulary)

Any pill typed into the picker (or returned by enrichment) that is not
already in the vocabulary is inserted immediately and applied to the
artifact. There is no "proposed → accepted" workflow, no curation
backlog, no staging area: a tag exists because an artifact was saved
using it, and that act is the approval.

The **Vocab Admin** panel is the single place where tag housekeeping
happens. Per-pill controls:

- **Rename** — change `display_name` or `slug` (slug rename rewrites every
  artifact's `tags` array). If the new slug collides with an existing
  tag, the UI offers a **merge** instead of blocking — the same merge
  flow described below.
- **Reject** — three modes: `remove`, `replace`, `deprecate` (same as v0.4).
- **Edit** — adjust `category`, `is_exclusive`, or `description`.
- **Merge** — move every artifact carrying pill A onto pill B, then
  delete A. POST `/api/tag-merge`.
- **Bulk Delete** — checklist of pills with `usage_count=0`; confirm,
  then POST `/api/tag-bulk-delete`.

The Tag Manager filter row is `ALL / UNUSED` — the previous `PROPOSED`
/ `ACCEPTED` split is gone with the column.

---

## 3. Storage Mode

Every artifact carries one of three `storage_mode` values. This replaces the older conflation of "local vs web" in v0.2.

| Mode | Meaning | Typical case |
|---|---|---|
| `vaulted` | MediaVault owns the bytes. Original has been copied into `catalogs/_assets/` and can be considered canonical. | Screenshots, HEICs dropped into `intake/drop/`, curated fan captures. |
| `referenced` | A file exists on disk but MediaVault only holds a **pointer** (`local_asset_path`). The bytes stay where they are. | Large videos, files on external drives, existing folders Mike does not want duplicated. |
| `url_only` | No local file at all. Only `source_url`. The catalog record is the preservation artifact. | Dead-link-in-waiting Instagram posts, press articles, Bandcamp pages. |

Storage mode is explicit on the record, selectable in the inbox editor, and a filter facet in the vault. A single parent URL artifact may be `url_only` while its child extract (a downloaded image, a text transcript) is `vaulted` — they are independent records linked by `parent_artifact_id`.

**API contract for `local_asset_path`** (`POST /api/artifact-register`). The path field is conditionally required by `storage_mode`: required when `storage_mode` is `vaulted` or `referenced`; optional (may be null or omitted) when `storage_mode` is `url_only`. When a path is provided in the `url_only` case it is still validated normally — the file must exist and must live under one of the allowed asset roots (`C:\AI`). Operators may legitimately reference an existing snapshot from a `url_only` artifact, and the safety check stands.

---

## 4. Lifecycle Status

Every artifact carries exactly one lifecycle `status`:

| Status | Meaning |
|---|---|
| `inbox` | New arrival, not yet reviewed. Default on creation. |
| `vault` | Reviewed, tagged, and saved. The default "home" for a kept artifact. |
| `released` | Explicitly marked as a finished, fully-realized item. (Highlighted with a ★ badge in the vault grid.) |

The inbox has three fates: SCRAP / SAVE / RELEASE. Archive is not an
inbox state — it's a post-save vault operation (see §4.1).

Transitions:

- `inbox` → `vault` — operator clicks **Save** in the Inbox editor.
- `inbox` → (removed) — operator clicks **Scrap**; the record is deleted.
- `inbox` → `released` — operator clicks **Save & Release** (one step: save to vault, then mark released).
- `vault` ↔ `released` — toggle from the Vault detail panel.

### 4.1 Archive (`status='archived'`)

Archive is **saved-but-hidden**. Always reversible.

- Archiving sets `status` to `archived`. No timestamp column is updated;
  `released_at` / `released_by` are preserved, so an archived row
  remembers whether it had been released.
- Un-archiving is not currently exposed in the UI. Restoring an archived
  row requires manually flipping `status` back to `vault` or `released`
  with a DB tool.
- Default vault views filter out artifacts where `status='archived'`.
  A "Show archived" toggle in the vault filter bar reveals them.
- Archived artifacts keep their tags, metadata, and file bytes intact.
  Nothing but the status value distinguishes them from any other vault row.
- The archive entry point lives in the vault detail panel.

Historical note: SPEC v0.5 originally specified `archived_at TEXT NULL`
as the canonical archive signal — a nullable timestamp orthogonal to
`status`. The column was added to the live schema in v0.5.1
(`_cowork/v07_add_archived_at_column.py`) to satisfy a museum-side
reader, but the archive handler was never migrated and no MV code reads
or writes the column. The 2026-05-14 decision (`NAVIGATION.md`) was to
leave the running code as-is and have the Museum adapter normalize the
drift. This spec ratifies that decision: `archived_at` is **retired** —
physically present in the schema, never written, never read (see §6).

---

## 5. Intake Channels

### 5.1 Drop / Screenshot Folder

- Watch folder: `C:\Users\macun\OneDrive\Pictures\Screenshots\`
- Additional drop folder: `C:\AI\Platform\MediaVault\intake\drop\`
- Operator initiates ingest manually. `ingest_engine.py scan` queues items into the inbox.
- Claude reads each screenshot via vision during enrichment: extracts URL, visible post date, author, body text, media type, and proposes tags.
- Operator reviews in the Inbox pane — edits any flagged fields, sets storage mode, confirms tags, then saves or releases.

### 5.2 URL Ingest

- Operator pastes a URL into the Inbox UI, or a URL artifact is created from a FB candidate bridge (see §5.4).
- Claude fetches page metadata where possible (title, description, OG image for thumbnail).
- No content downloaded unless the operator chooses `storage_mode = vaulted` and Claude performs the extract; otherwise the record stays `url_only`.

### 5.3 Bulk Capture JSON

- `ingest_engine.py scan --capture-json <file>` consumes a captured JSON manifest from an external fetch tool and creates inbox records. Used for migration and for large web captures.

### 5.4 FB Candidates Bridge

Accepted candidates in the `fb_candidates` view (Hunter Root's parallel review queue) may be sent to the MediaVault Inbox with a single click. `POST /api/intake-from-fb-candidate` creates a queue item and marks the candidate graduated. This is the primary way fan captures enter the vault.

---

## 6. Catalog Record Schema

One record per artifact. All fields stored in SQLite. The canonical schema snippet (mirrors §3.2 of the design doc):

    CREATE TABLE artifacts (
      id                       TEXT PRIMARY KEY,
      status                   TEXT NOT NULL DEFAULT 'inbox',   -- inbox|vault|released|archived
      storage_mode             TEXT NOT NULL DEFAULT 'vaulted', -- vaulted|referenced|url_only

      source_url               TEXT,
      source_platform          TEXT,
      ingest_source            TEXT,
      ingest_date              DATE,
      capture_date             DATE,
      post_date                DATE,
      post_date_confidence     TEXT,

      description_short        TEXT,
      description_long         TEXT,
      extracted_text           TEXT,
      media_type               TEXT NOT NULL                    -- photo|video|audio|link|text|mixed|other (canonical set per §6.6; CHECK enforced 2026-05-23)
                                   CHECK(media_type IN ('photo','video','audio','link','text','mixed','other')),

      local_asset_path         TEXT,
      thumbnail_path           TEXT,
      parent_artifact_id       TEXT,

      tags                     TEXT NOT NULL DEFAULT '[]',      -- JSON array of slugs currently "on"

      link_status              TEXT,   -- advisory only

      notes                    TEXT,
      confidence_flags         TEXT,                            -- JSON
      released_at              TEXT,
      released_by              TEXT,
      archived_at              TEXT,                            -- retired; present, never written/read (see §4.1)
      created_at               TEXT NOT NULL,
      updated_at               TEXT NOT NULL,
      FOREIGN KEY (parent_artifact_id) REFERENCES artifacts(id)
    );

    CREATE TABLE tags (
      slug          TEXT    PRIMARY KEY,    -- one slug, one row; namespace lives in the slug itself
      display_name  TEXT,
      usage_count   INTEGER NOT NULL DEFAULT 0,
      created_at    TEXT
    );

    CREATE TABLE id_sequence (
      date_str  TEXT PRIMARY KEY,    -- YYYYMMDD
      last_seq  INTEGER NOT NULL
    );

    CREATE TABLE ingest_queue (
      queue_id        INTEGER PRIMARY KEY AUTOINCREMENT,
      ingest_source   TEXT,
      raw_path        TEXT,
      source_url      TEXT,
      queued_at       TEXT NOT NULL,
      status          TEXT,           -- pending|processed|error
      enrichment_json TEXT,           -- JSON
      error_message   TEXT,
      artifact_id     TEXT,           -- null until saved to vault
      updated_at      TEXT
    );

### 6.1 Identity

New artifacts use the format `MV-YYYYMMDD-NNN`. The `id_sequence` table guarantees uniqueness per day; sequences reset each day. Legacy records migrated from v0.2 retain their original `MV-<PREFIX>-YYYYMMDD-NNN` IDs (the prefix is now meaningless — stability of IDs takes priority over cosmetic rename). The `domain` concept itself is retired.

### 6.2 Parent / Child

`parent_artifact_id` is nullable and self-referential. A URL artifact can have child records for its extracted image, its text transcript, its poster — each is a first-class artifact with its own tags, storage mode, and lifecycle. The default vault grid hides children unless "Show children" is toggled on.

### 6.3 Tags Column

A JSON array of slugs. Always present (default `'[]'`). Duplicate slugs are normalized away by the saver. Search uses `json_each(tags)`.

### 6.4 Confidence Flags

JSON array of field names Claude flagged as uncertain during enrichment. The Inbox editor highlights these fields; when the operator touches and saves, the flag clears.

### 6.5 Retired `tags` Columns

Historical note: SPEC v0.5 defined four additional columns on the
`tags` table — `description`, `category`, `is_exclusive`, and
`is_proposed`. They were retired by **Phase 2.5** of the source-of-truth
refactor on **2026-05-20**
(`_cowork/v13_phase25_demote_tags_table.py`) and physically dropped
from the live schema. In the same migration `slug` was promoted from
`TEXT NOT NULL` to `TEXT PRIMARY KEY`, replacing the v0.5-era composite
`(slug, category)` uniqueness with the global "one slug, one row"
guarantee the v0.5 reconciliation banner already declared (see top of
this file).

Namespace metadata (the legacy role of `category`) now lives in slugs
themselves — `bands:hunter_root` rather than a `bands` row in a
separate column — per §5.4 of the museum repo's
`DATA_ARCHITECTURE_SPEC_v2.1-target.md` and the §5.4 `vocabulary`
registry that holds the namespace prose. Per-tag exclusivity
(`is_exclusive`) and the proposed/accepted curation workflow
(`is_proposed`) are not part of the post-refactor model. Free-form
per-tag description (`description`) similarly has no home in the
demoted cache; descriptive prose for a namespace lives in
`vocabulary`, not on individual tag rows.

See `CHANGELOG.md` v0.5.3 and
`docs/PHASE25_RUN_REPORT-20260520-*.md` for the migration record.

---

### 6.6 — `media_type` canonical set (resolved 2026-05-23)

The canonical set is **`{photo, video, audio, link, text, mixed, other}`** —
seven values, enforced by `CHECK(media_type IN (...))` on the `artifacts`
table since 2026-05-23 (operator-approved Option A: `NOT NULL CHECK`,
"fail-loud on future bugs that forget media_type"). The same set is
mirrored in the MV validator at `core/imgserver_extensions.py:107`
(`MEDIA_TYPE` constant).

**Historical drift, now resolved:** prior to the 2026-05-22/23 cleanup
arc, the live `artifacts` table contained rows with `media_type='text-only'`
(22), `media_type='mixed'` (3), and `media_type IS NULL` (4) in addition
to values in the canonical set. The drift between the documented set, the
validator set, and live data was documented in this section as a known
out-of-scope deferral. The pre-resolution Shape A discipline ("align
SPEC.md with the *target* set, surface the drift honestly in prose, and
leave the runtime untouched until the matching schema and data work is
green-lit") is preserved as the playbook for any future drift-then-resolve
sequence.

**Resolution timeline (all 2026-05-22/23):**

- **M7 + O5** (operator-locked decisions per audit brief §4.3): 22 `text-only`
  rows normalized to `link`; 3 `mixed` rows per-row decided
  (`MV-HR-20260405-010` and `-034` → `link`;
  `MV-HR-20260416-008` → `audio`). See
  `_cowork/M7_RUN_REPORT-20260522T234721Z.md`.
- **M6 + O4**: 4 `NULL` rows normalized; 2 mechanical (`.MOV` → `video`,
  `.jpg` → `photo`) + 2 operator-confirmed FB extension captures
  → `link`. See `_cowork/M6_RUN_REPORT-20260523T012144Z.md`.
- **CHECK constraint migration** (table-rebuild; this section's locked state):
  added `NOT NULL CHECK(media_type IN canonical_set)` via SQLite
  table-rebuild. See `_cowork/CHECK_RUN_REPORT-20260523T134500Z.md`.

**Post-cleanup distribution** (88 artifacts, all canonical):
`link` (33), `photo` (26), `audio` (16), `video` (11), `text` (2). Zero
NULL, zero `text-only`, zero `mixed` (the deprecated-but-allowed value
`mixed` has 0 live rows; new artifacts default to specific types per the
M1 `_infer_media_type` extension dispatch).

The audit brief that drove the resolution is
`C:\AI\Projects\weird-baby-museum\docs\INGEST_BEHAVIOR_AUDIT-20260522-182616.md`
(§4 covers the taxonomy question; §4.3 step 3 covers the CHECK constraint).
The brief's §4.3 trilogy (step 1: SPEC.md update; step 2: normalize live
data; step 3: CHECK constraint) is now complete — this section update
closes step 1.

## 7. Thumbnail Specification

- Format: JPEG, max 400px on longest edge, quality 85
- HEIC sources: converted to JPEG before thumbnail generation
- Video sources: first frame extracted as thumbnail
- `url_only` sources: OG image fetched if available; fallback to a platform icon + domain label
- Filename mirrors record ID: `MV-20260417-001.jpg`
- Stored in: `C:\AI\Platform\MediaVault\catalogs\_thumbs\`
- EXIF/XMP embedding via `exiftool`: short description, flat tags list, source URL, and record ID written to thumbnail on generation
- `exiftool` required. One-time install: `winget install exiftool`

---

## 8. Browser UI

Served by `imgserver.py` at `http://localhost:51822/`. The main HTML is `mediavault.html`, which reads `/db` as a read-only SQLite blob via `sql.js` and performs all writes through JSON API endpoints.

### 8.1 Panes

| Pane | Description |
|---|---|
| **Inbox** | Queue of items with `status='inbox'`. Left: viewer (image or URL preview). Right: field editor (Identity, Source, Dates, Storage, Tags, Structure) and an action bar — **Scrap / Save / Save & Release**. |
| **MediaVault** (Vault) | Browsable vault. Filter bar, grid or table, and a detail panel. Default filter: `status IN (vault, released)`, children hidden. A toggle reveals archived rows. |
| **Vocab Admin** | Table of tags in vocabulary. Filter row: `ALL / UNUSED`. Per-pill controls: Rename / Reject (remove, replace, deprecate) / Edit / Delete / Merge. Top-bar tools: Merge, Bulk Delete. |

### 8.2 Vault Filter Bar

- Full-text search (short / long description, extracted text, source URL, notes)
- Date range (capture or post date)
- Status multi-select (default: vault + released)
- Storage mode multi-select
- Pill pills — **tri-state**: off / MUST / MUST NOT
- Show children toggle
- **Show archived** toggle (default off — the default view hides rows where `status='archived'`)
- Sort dropdown
- Grid / table view toggle

### 8.3 Badges

- ★ `released`
- 📁 `vaulted`
- ↗ `referenced`
- 🔗 `url_only`

### 8.4 Pill Wall (inbox) and Tag Picker (vault)

**Inbox pill wall.** The primary tagging UI. Vocabulary is grouped by
`category` into collapsible `<details>` sections (order: people, bands,
places, content_kind, topic, platform, rarity, uncategorized). Each pill
renders in its current session state (`on`, `suggested`, `off`) per §2.3.
Click flips. Category sections with a warning from the attention rules
glow red on the summary line.

An add-pill input at the bottom autocompletes against vocabulary. Pressing
Enter on a novel slug creates the tag in the vocabulary and applies it
as `on`. The slugifier accepts one `namespace:` prefix. Since global slug
uniqueness holds, there is never ambiguity about which `foo` the operator
meant — one slug, one tag.

**Inbox descriptions** are collapsed by default under a `<details>` element
below the pill wall. They're secondary; the pill wall and the viewer are
what the operator's eye lands on first.

**Vault detail tag picker** (unchanged from v0.4 mechanics) — applied-pill
row + autocomplete + browse grouped by category.

### 8.5 Inbox action bar

The Scrap / Save / Save & Release buttons are at the **top** of the inbox
right panel in v0.5 (moved up from the bottom), so they're always visible
as the operator scrolls.

### 8.6 Attach-to-parent (vault)

The vault detail panel's Actions row has an **Attach to parent** button that
opens a searchable modal of candidate artifacts. The candidate list excludes
self and all descendants (walked via JS). Selecting a candidate sets the
artifact's `parent_artifact_id` via `/api/artifact-update`.

### 8.7 Vocab Admin — merge + bulk delete

- **Merge** modal: pick a source pill (usage_count > 0) and a target pill.
  Preview shows the affected artifact count. Confirm → POST `/api/tag-merge`
  (`{source_slug, target_slug}`). Every artifact carrying the source gains
  the target (no duplication); the source pill row is then deleted.
- **Bulk Delete** modal: checklist of every pill with `usage_count = 0`.
  All / None quick toggles. Confirm → POST `/api/tag-bulk-delete`
  (`{slugs: [...]}`).

---

## 9. Release Flow

Releasing an artifact is the explicit act of saying "this is a finished item I want to keep prominently." It is not automatic.

- From **Inbox**: the action bar's **Save & Release** button saves as vault and flips status straight to `released`.
- From **Vault detail**: the **Release** / **Unrelease** toggle flips between `vault` and `released`.
- The `released_at` timestamp is written when the transition happens.
- Released artifacts are highlighted with ★ in the vault grid and are surfaced by default in filters.
- Release is reversible. It does not disable edits. It does not forbid re-tagging.

The previous "Post Builder" concept — automatic usage logging per post — is removed. No such tool was ever built. If a project needs to know which artifacts it has used, it can read the vault by tag.

---

## 10. Architecture Decisions (Locked, v0.5)

| Decision | Choice | Rationale |
|---|---|---|
| Backend | `imgserver.py` (Python `BaseHTTPRequestHandler`) serves JSON APIs and static assets. Browser reads `/db` as a binary SQLite blob via `sql.js`. | No heavy framework. Read path stays WASM-fast. Write path is explicit and auditable. |
| Pill model | Three session-only states during inbox review (`on`, `suggested`, `off`); auto-confirm on save. Tri-state filter in vault (off / MUST / MUST NOT). Vocabulary holds `category` + `is_exclusive`. No persistence of review state — `artifacts.tags` stores plain on/off associations only. | Three states cover the actual review decisions (accept, reject, didn't-look-yet) without carrying dead metadata forward. The five-state model encoded nuance that collapsed anyway once pills persisted. |
| Author convention | `author:<slug>` pill instead of an `author_name` column. | Authors are pills like everything else. The `namespace:` slug prefix keeps them visually grouped and sortable. |
| Tag lifecycle | One stage. A tag exists in the vocabulary because an artifact was saved using it. No `is_proposed` column, no proposed/accepted distinction. Novel slugs typed in the picker are inserted immediately and applied to the artifact. | The inbox already decides what gets saved; the tags carried along for the ride are implicitly approved. A second curation stage at the tag level adds workflow cost without corresponding clarity. |
| Slug uniqueness | Global. One slug, one tag. Category is descriptive metadata, not part of tag identity. | No concrete case was identified where two tags genuinely needed to share a slug. The forever-tax of qualifying "which `hunter_root`?" in every lookup isn't worth paying for flexibility with no known use. |
| Storage mode | Explicit `storage_mode` column with three values. | `url_only`, `referenced`, and `vaulted` are all legitimate and need distinct UI affordances. |
| Lifecycle | Explicit `status` column with values (`inbox`, `vault`, `released`, `archived`). `released` is separate from `vault`. Archive is a status value. | Every other status scheme conflated "in vault" with "featured". Separating them makes the release act meaningful. The orthogonal-timestamp archive design in earlier spec drafts was never wired into the code; the status-value model is what runs. |
| Archive | `status='archived'` on `artifacts`. Default vault views filter it out; a "Show archived" toggle reveals it. Un-archive is not currently exposed in the UI — manual DB edit required. | "I want to keep this but not show it right now" is a real thought. Saved-but-hidden via a status value was the implementation that shipped; it does not overlap with SCRAP. |
| IDs | `MV-YYYYMMDD-NNN`, per-day counter in `id_sequence(date_str PK, last_seq)`. | No more prefix baked into the ID — domain is a pill. |
| Attention rules | Hardcoded R1-R5 in `core/attention_rules.py`. Soft warnings only. | The set is small, stable, and revisions want code review. No admin UI. YAGNI. |
| FB candidates | Separate table and UI; the bridge button creates an inbox queue item. | Keeps the hunter-root-specific review queue simple; MediaVault stays general. |
| DOM renderer | `ext/hr_manager_renderer.js` is untouched. | External integration, not owned by MediaVault. |
| Deletes | Files moved to `C:\AI_OK_TO_DELETE\`. | Workspace rule: never hard-delete. |

---

## 11. File System Layout

```
C:\AI\Platform\MediaVault\
  core\
    mediavault.sqlite            — single database (all artifacts, vocabulary, queue)
    ingest_engine.py             — intake pipeline, thumbnail generator, EXIF writer
    imgserver.py                 — HTTP server: static files + JSON APIs + /db blob
    imgserver_extensions.py      — artifact-register + asset-raw endpoints (v0.5 rewrite)
    attention_rules.py           — R1-R5 soft-warning rules (§12.5)
  catalogs\
    _assets\                     — vaulted bytes
    _thumbs\                     — generated thumbnails (all artifacts, one pool)
  ext\
    hr_manager_renderer.js       — external DOM-observer renderer (do not modify)
  intake\
    drop\                        — local file drop zone
    processed\                   — originals after ingest, before confirmed delete
  mediavault.html                — main UI (Inbox + Vault + Vocab Admin)
  fb_candidates.html             — FB candidate review + bridge to inbox
  PROJECT.md
  SPEC.md                        — canonical spec (this file)
  STATE.md
  WORKFLOW.md
  MEDIAVAULT_V04_DESIGN.md       — historical
  MEDIAVAULT_V05_DESIGN.md       — current
```

---

## 12. Migration

### 12.1 v0.2 → v0.4 (2026-04-17)

Performed in one transaction. Collapsed the 10 `tags_*` columns into one
flat `tags` JSON array, added `status` / `storage_mode` / `parent_artifact_id`,
retired `domain` as a schema concept, introduced the proposed-tag workflow,
rebuilt `id_sequence`, and attempted sidecar-to-parent linking. Full details
in `_cowork/PHASE_SUMMARY.md`.

### 12.2 v0.4 → v0.5 (2026-04-19)

Performed in two transactions.

**Schema migration (Phase 1).** Rebuild-and-rename pattern:
1. `PRAGMA journal_mode = MEMORY` (sandbox-safe).
2. Create `artifacts_new` with the v0.5 column set: drop `author_name`,
   `tags_permission`, `permission_contact`, `permission_evidence_path`;
   add `archived_at`. (Historical record. `archived_at` was later
   retired — see §4.1 — though the column physically remains.)
3. `INSERT … SELECT` all rows; synthesize `author:<slug>` pills from
   existing `author_name` values into the artifact's `tags` array and into
   `tag_vocabulary`.
4. Rebuild `tags` table with `category`/`is_exclusive`.
5. Rebuild `id_sequence` on the `(date_str, last_seq)` shape.
6. Atomic rename.

Historical note: v0.5 as shipped also added a `pill_states` JSON column
that was removed during the 2026-04-19 reconciliation — pill states are
session-only now. The v0.7 punchlist drops the column.

**Vocabulary cleanup (Phase 2).** Normalize categories (merge
duplicates / alias cases), mark `rarity` pills as exclusive, re-compute
`usage_count`, and synthesize `author:<slug>` pills for every distinct
author seen.

Row counts and the pre-refactor snapshot are in
`_cowork/PHASE_SUMMARY_v05.md`.

---

## 12.5 Attention Rules (R1-R5)

New in v0.5. Lives in `core/attention_rules.py`. Five hardcoded rules surface
"this artifact is missing something" warnings in the inbox. Warnings are
**soft** — the operator can save anyway; the warning just glows next to the
relevant control or section header.

| Rule | Condition | Warning |
|---|---|---|
| R1 | `source_platform` is a social platform (`facebook`, `instagram`, `tiktok`, `reverbnation`) and `post_date` is empty | `missing_field:post_date` |
| R2 | `media_type` is `photo` or `video`, and no `parent_artifact_id`, and zero `content_kind` pills are on | `missing_category:content_kind` |
| R3 | Any of the description fields contains a Title-Case bigram (`/\b[A-Z][a-z]+ [A-Z][a-z]+\b/`) and zero `people` AND zero `bands` pills are on | `missing_category:people_or_bands` |
| R4 | `ingest_source = 'extension-capture'` and zero `scope` pills are on | `missing_category:scope` |
| R5 | At least one pill is on and `media_type` is empty | `missing_field:media_type` |

Public function:

    evaluate_rules(artifact_fields: dict,
                   pill_states: dict,
                   vocab: dict[str, dict]) -> list[str]

`pill_states` is the session-only in-memory state map from the inbox
review UI (slug → one of `on` / `suggested` / `off`). Pills in `on` or
`suggested` count as "on" for rule evaluation — matching the
auto-confirm-on-save semantics from §2.3. `vocab` maps slug →
`{category}` so the rules engine doesn't open the DB; the frontend ships
the slice along with the call.

Adding a rule is a code edit + code review. No schema change, no admin UI.

---

## 13. Known Tradeoffs

- Old reference files may remain on disk (`hr_manager.html.old_v02`, `core/imgserver.py.old_v02`, `core/_test.txt`, `core/screenshot_match.json`, `core/migrate_to_v04.py`) because the workspace's delete permission was not requested during the v0.5 refactor. They are copied into `D:\AI_OK_TO_DELETE\MediaVault_v05_refactor_20260419\` for quarantine.
- v0.4-era enrichment data in `ingest_queue.enrichment_json` uses `tags_known` / `tags_proposed` / `author_name`. The inbox populator reads both v0.4 and v0.5 enrichment shapes and projects them into the in-memory three-state session map — old rows need no re-write.
- The inbox empty-state intake controls (brief §6.5) were deferred. PowerShell + capture folders still work for intake; just no in-UI "drop a file / paste a URL" affordance when the queue is empty.

---

## 14. Hard Rules

- All work in `C:\AI`.
- MediaVault lives in `C:\AI\Platform\` — not `Projects\`.
- No hard deletes — move to `C:\AI_OK_TO_DELETE\`.
- Pills carry a `category` and an `is_exclusive` flag. No per-domain schema.
- Slug uniqueness is global — one slug, one tag. Category is descriptive, not identifying.
- Author is a pill (`author:<slug>`), not a column.
- One-stage tag vocabulary: saving an artifact implicitly approves its tags. No `is_proposed` column, no curation backlog.
- Pill review states (`on` / `suggested` / `off`) are session-only — not persisted on the artifact.
- `status` and `storage_mode` are explicit on every record. Archive is `status='archived'`.
- Attention rules are code (`core/attention_rules.py`); changing them is a code edit.
- `ingest_engine.py` owns intake; `imgserver.py` owns serving. Nothing else writes to the DB.
- `ext/hr_manager_renderer.js` is external — never modified from MediaVault.
- exiftool is required on the host.

---

## 15. What This Spec Does Not Cover

- Build implementation details — see `STATE.md` and `_cowork/PHASE_SUMMARY_v05.md` phase by phase.
- Design rationale — see `MEDIAVAULT_V05_DESIGN.md`.
- Day-to-day operator flow — see `WORKFLOW.md`.
- What_Mike_Knows knowledge graph — separate project.
- Hunter Root fan-group post schedule — governed by Hunter Root STATE.md.

---
*End of MediaVault Requirements Spec v0.5*
