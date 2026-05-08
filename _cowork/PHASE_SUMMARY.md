# MediaVault v0.4 Refactor — Phase Summary

**Operator:** Mike Lang
**Agent:** Claude (Anthropic), Cowork session
**Started:** 2026-04-17 21:30 (build lock taken)
**Finished:** 2026-04-17 (build lock released; see BUILD_LOCK.txt)
**Brief:** `C:\AI\Platform\MediaVault\COWORK_BRIEF.md`
**Design doc:** `C:\AI\Platform\MediaVault\MEDIAVAULT_V04_DESIGN.md`

---

## Phase 1 — Schema migration v0.2 → v0.4 (COMPLETED)

Single-transaction migration over `core/mediavault.sqlite`. Pre-refactor backup
preserved at `core/mediavault.sqlite.bak_v04phase1_20260417_213832`. Migration
logs in `_cowork/migration_log_*.txt`.

What changed in the schema:
- Added `status` (default `inbox`), `storage_mode` (default `vaulted`),
  `parent_artifact_id`, `released_at`, `released_by`, `tags` (JSON array
  default `'[]'`).
- Computed `tags` per row from the 10 legacy `tags_*` columns.
- Inferred `storage_mode` from `link_status` and `local_asset_path`
  (referenced when an external local path was set, vaulted when the file lived
  inside `catalogs/_assets/`, url_only when no local file).
- Inferred `status` from the legacy approval flags (approved → `vault`).
- Migrated the legacy `domain` value into the tags array — every existing
  artifact now carries `hunter_root` as a tag.
- Created `tags` (vocabulary) table and seeded with 106 distinct slugs from
  the legacy `tag_vocabulary.json` and from every distinct slug observed on
  any artifact's tags array. Seeded with `is_proposed=0` (this was a
  deliberate choice — see Decisions §1).
- Created `id_sequence` (date_str PK, last_seq INTEGER) and rebuilt sequences
  from existing IDs.
- Sidecar-to-parent linking: for each sidecar (text extract, metadata blob,
  child image), looked for a parent artifact whose `local_asset_path` shared
  the same filename stem; set `parent_artifact_id` on match.
- Dropped the 10 per-category `tags_*` columns and the `domain` column.
- Renamed the queue table to `ingest_queue` and reorganized columns
  (`queue_id` PK, `ingest_source`, `raw_path`, `source_url`, `queued_at`,
  `status`, `enrichment_json`, `error_message`, `artifact_id`, `updated_at`).

Row counts after migration:
- artifacts: 76
- by status: vault = 76 (all migrated rows landed as vault; nothing is
  released until the operator chooses to release)
- by storage_mode: referenced = 60, vaulted = 16, url_only = 0
- tags vocabulary: 106 (proposed = 0, accepted = 106)
- ingest_queue: 25 rows (mix of `pending` and `keep`)
- artifacts carrying `hunter_root`: 76 (100%)

Schema verification: PASSED. All v0.4 tables present (`artifacts`, `tags`,
`id_sequence`, `ingest_queue`); v0.4 columns on `artifacts` present;
`json_each(artifacts.tags)` queries return correct counts.

Vestigial v0.2 columns retained (not breaking, advisory only):
`link_status`, `tags_permission`, `permission_contact`,
`permission_evidence_path`. Documented in SPEC §6.

---

## Phase 2 — Backend rewrite (`core/imgserver.py`) (COMPLETED)

Full rewrite of the Python backend.

GET routes:
- `/`  → mediavault.html
- `/ping` → liveness
- `/db` → SQLite blob (read-only data layer for the browser via sql.js)
- `/fb` → fb_candidates.html
- `/api/queue` → inbox queue list
- `/api/tags` → tag vocabulary
- `/api/fb-candidates` → FB candidate list
- `/ext/hr_manager_renderer.js` → preserved external renderer (untouched)

GET prefix routes:
- `/image-raw` → screenshot/raw bytes
- `/asset-raw` → vaulted-asset bytes

POST routes (writes — DB never written from the browser directly):
- `/api/intake-upload`, `/api/intake-url`, `/api/intake-from-fb-candidate`
- `/api/queue-update`, `/api/queue-delete`
- `/api/enrich`, `/api/next-id`
- `/api/artifact-save`, `/api/artifact-update`, `/api/artifact-release`,
  `/api/artifact-unrelease`, `/api/artifact-archive`,
  `/api/artifact-delete`, `/api/artifact-requeue`, `/api/artifact-register`
- `/api/thumbgen`
- `/api/tag-create`, `/api/tag-update`, `/api/tag-accept`,
  `/api/tag-reject`, `/api/tag-delete`
- `/api/fb-candidate-save`

Old `imgserver.py` preserved as `core/imgserver.py.old_v02` (43272 bytes).

Smoke test: server starts cleanly, all GET endpoints return 200 with non-empty
payloads; route table prints 9 GET + 22 POST + 2 prefix.

---

## Phase 3 — Frontend rewrite (`mediavault.html`) (COMPLETED)

`hr_manager.html` superseded by `mediavault.html` (66164 bytes). Old file
preserved as `hr_manager.html.old_v02` (72148 bytes).

Three top-level panes (top nav switches between them) plus a gear icon for
Vocab Admin:

- **INBOX** — queue items with status `pending`. Left: viewer (image or URL
  preview). Right: field editor (Identity / Source / Dates / Storage / Tags /
  Structure / Notes). Action bar: **Scrap / Save / Save & Release**.
- **MEDIAVAULT (Vault)** — filter bar (full-text search, date range, status
  multi-select defaulting to `vault + released`, storage_mode multi-select,
  tri-state tag pills, show-children toggle, sort, grid/table toggle), grid
  view with badges (★ released, 📁 vaulted, ↗ referenced, 🔗 url_only),
  sortable table view, detail panel with edit-in-place fields and
  release/unrelease/archive/requeue controls.
- **Vocab Admin** — tag table with accept / reject (3-way modal: remove /
  replace / deprecate) / rename / edit / delete.

Tag picker: applied pills with × to remove, autocomplete input (Enter creates
a proposed tag and applies it), browse panel grouped by `group_name`.

`<script src="/ext/hr_manager_renderer.js">` preserved as required by the
brief. CSS variables (`--gold`, `--bg2`, `--bg3`, `--border`, `--mono`,
`--text`, `--text2`) preserved from v0.2.

Smoke test: `/` returns 66164 bytes (200), all 19 distinct `/api/*` routes
referenced in the page exist in the backend route table.

---

## Phase 4 — Ingest engine (`core/ingest_engine.py`) (COMPLETED)

Full rewrite (~660 lines). CLI surface preserved: `scan`, `process`, `status`.

Removed:
- `DOMAIN_PREFIXES`, `DEFAULT_DOMAIN`
- All `--domain` CLI handling and per-domain prompt branching
- All references to per-category `tags_*` columns

Added:
- `next_id(conn)` — atomic per-day sequence via `id_sequence`. Format:
  `MV-YYYYMMDD-NNN`. Legacy IDs (`MV-HR-…`, `MV-GE-…`) are not rewritten —
  ID stability is more important than cosmetic uniformity.
- `slugify()` and `upsert_tag()` helpers — both used by the enrichment path.
- `queue_capture_json(conn, path)` — drops `domain`, sets `storage_mode` in
  the enrichment blob.
- `extract_exif()` returns a flat `tags_proposed` list (no per-category
  dict keys).
- `process()` uses the single `tags` JSON array.
- `generate_thumbnail(raw_path, artifact_id, enrichment_json)` — thumbs at
  `catalogs/_thumbs/<id>.jpg`.
- `write_exif(thumb_path, artifact_id, description, source_url, tag_slugs)`
  — flat slug list.
- `status()` — breakdown by `status` and `storage_mode` (not `domain`).

Verified by sandboxed run with patched DB path: status command emits the
expected counts (76 vault artifacts, 60 referenced + 16 vaulted, 25 queue
rows).

---

## Phase 5 — FB-to-Inbox bridge (COMPLETED)

`fb_candidates.html` edited to add a "→ Send to MediaVault Inbox" button in
the action group:

- CSS: `#btnSendInbox{background:var(--gold);color:#111;...}` plus a
  `.hidden` utility class.
- HTML: `<button class="act hidden" id="btnSendInbox" onclick="sendToInbox()">…`
- JS: `updateSendInboxBtn(d)` shows the button when `d.status==='accepted'`,
  disables it when `d.graduated` is true. Hooked into `renderCard()`.
- JS: `sendToInbox()` POSTs `{fb_candidate_id: d.id}` to
  `/api/intake-from-fb-candidate`.

Backend endpoint `/api/intake-from-fb-candidate` (already in the route table
from Phase 2): creates a queue row with `ingest_source='fb-candidate'`, marks
the FB candidate `graduated=1`. 404 returned for non-existent candidate ids
(verified during smoke).

Smoke test: `/fb` serves 19158 bytes; 7 references to `btnSendInbox` in the
HTML; one accepted, ungraduated candidate exists right now and the button
will be visible on it.

---

## Phase 6 — Cleanup, docs, smoke test, release (COMPLETED)

### 6.1 Quarantine

Quarantine folder: `D:\AI_OK_TO_DELETE\MediaVault_v04_refactor_20260417\`.
Contains:
- `hr_manager.html.old_v02` (72148 bytes)
- `imgserver.py.old_v02` (43272 bytes)

Source originals (`hr_manager.html.old_v02` and `core/imgserver.py.old_v02`)
**remain in place**. The `mcp__cowork__allow_cowork_file_delete` permission
was declined when requested, so the originals could not be removed from
source. Mike can delete them manually whenever convenient — quarantine
copies are intact.

### 6.2 Documentation refresh

- `PROJECT.md` — rewritten for v0.4. Reframes MediaVault as a review
  workstation + vault. Removes `domain` and "catalog name" language. States
  the four-status lifecycle, three storage modes, flat tags, proposed-tag
  flow.
- `SPEC.md` — bumped to v0.4. Replaces "Domains and Catalogs" with "Tags"
  section. Adds explicit "Storage Mode" and "Lifecycle Status" sections.
  Adds tag-vocabulary section with proposed-tag flow. Adds "Release Flow"
  section. Removes the v0.2 Post Builder section (never built — superseded
  by the release-by-tag workflow). All schema snippets match the actual
  database.
- `STATE.md` — new session entry for the refactor. Decisions log, open
  issues re-scoped for v0.4, resolved-issues list, next-session checklist.
- `WORKFLOW.md` — full rewrite. Documents the new lifecycle and storage
  modes, the four entry points (drop folder / URL paste / capture JSON /
  FB bridge), the Inbox action bar, the Vault filter bar, the tag picker,
  and Vocab Admin.

### 6.3 Smoke test

Performed by spinning up `imgserver.py` in the sandbox against the actual
`core/mediavault.sqlite`.

| Check | Result |
|---|---|
| `/` returns 200 + mediavault.html (66164 bytes) | PASS |
| `/db` returns 200 + sqlite blob (1953792 bytes) | PASS |
| `/db` schema includes artifacts, tags, id_sequence, ingest_queue | PASS |
| `/fb` returns 200 + fb_candidates.html (19158 bytes) | PASS |
| `/ext/hr_manager_renderer.js` returns 200 (7832 bytes) | PASS |
| `/api/queue` returns 25 rows, statuses `pending` + `keep` | PASS |
| `/api/tags` returns 106 vocabulary rows | PASS |
| `/api/fb-candidates` returns 2 candidates, 1 accepted/ungraduated | PASS |
| `artifacts` row count = 76, all carry `hunter_root` tag | PASS |
| `artifacts` storage_mode split = 60 referenced / 16 vaulted | PASS |
| Frontend `/api/*` calls cross-checked against route table | PASS (all 19 referenced endpoints exist) |

Existing-content smoke: vault grid will render 76 artifacts; default filter
of `vault + released` matches all 76; `hunter_root` tag pill returns 76;
`year:2013` returns the expected subset; tag picker dropdown is populated
from the live `/api/tags` response. No mutating tests were performed on
real records.

### 6.4 Build lock

`C:\AI\BUILD_LOCK.txt` flipped from LOCKED to UNLOCKED at end of session
(see file).

### 6.5 This document

`_cowork/PHASE_SUMMARY.md` — you're reading it.

---

## Decisions made during the refactor

1. **All migrated tags seeded as `is_proposed=0`.** Forcing 106 tags into
   "proposed" would have created an unmanageable Vocab Admin queue on day
   one. The 100 tags lacking a `group_name` are still distinguishable in
   the admin and can be tidied incrementally.
2. **Legacy IDs not rewritten.** Existing `MV-HR-YYYYMMDD-NNN` IDs are kept
   as-is; only new artifacts get the v0.4 `MV-YYYYMMDD-NNN` format. ID
   stability beats cosmetic uniformity.
3. **`imgserver_extensions.py` left on the v0.2 schema.** Brief explicitly
   forbade modifying it. Any feature it serves will fail against the v0.4
   DB; logged as an open issue in STATE.md.
4. **Vestigial v0.2 columns kept.** `link_status`, `tags_permission`,
   `permission_contact`, `permission_evidence_path` were not dropped to
   keep the `imgserver_extensions.py` workaround feasible later. They are
   advisory-only and documented in SPEC §6.
5. **Old reference files left in source.** Delete permission was declined;
   leaving them in place is harmless and they exist in quarantine too.
6. **Post Builder removed from the roadmap entirely.** It was never built
   in v0.2 and the release-by-tag flow obviates it.

---

## Open issues for next session

See `STATE.md` for the full list. Headlines:

- `core/imgserver_extensions.py` still references v0.2 schema — decide
  per-feature whether to rewrite or retire.
- Old `*.old_v02` reference files in source — Mike can manually delete.
- Some sidecars may not have matched any parent during Phase 1 linking;
  spot-check via Vault filter and link by hand if any orphans surface.
- Vocab Admin pass — 100 tags currently lack a `group_name`; group them
  for a tidier picker.
- `/ext-status`, `/ext-log`, `/ext-log-dump` diagnostic endpoints in
  imgserver.py — still present, still removable in a cleanup pass.

---

*End of MediaVault v0.4 Refactor Phase Summary*
