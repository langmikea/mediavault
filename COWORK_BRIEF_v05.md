# MediaVault v0.5 — COWORK BRIEF

**You are cowork.** This document tells you exactly what to do. Follow it in
order. The design rationale lives in `MEDIAVAULT_V05_DESIGN.md`; read it if
a step's "why" is unclear, but do not re-litigate decisions.

Every line number, endpoint name, row count, and column name in this brief
was verified against `_cowork/mv_v05_audit_20260419_170757.md`. If your
working reality disagrees with the brief, trust your direct observation over
the brief, tell the operator, and stop.

---

## Hard rules (do not violate)

1. **Keep the build lock** until every phase is complete and smoke tests pass.
   Release only in the final phase.
2. **Backup the DB** before the migration transaction. The prep script
   already did one; confirm it exists before starting Phase 2.
3. **One transaction per schema-level phase.** If the transaction fails,
   roll back, stop, ask the operator.
4. **Do not modify `ext/hr_manager_renderer.js`.** External DOM renderer; not
   ours.
5. **Do not modify `fb_candidates.html`.** FB flow is untouched in v0.5.
6. **Do not delete any file.** Move to `D:\AI_OK_TO_DELETE\MediaVault_v05_refactor_<date>\`.
7. **Do not rewrite legacy `MV-HR-*` IDs.** Identity is permanent. 62 rows
   still carry this format and they stay.
8. **The five-pill-state model is the center of v0.5.** Every UI decision
   serves it. If you find yourself rationalizing a different behavior for
   the inbox, stop and re-read design §2 and §4.

---

## Stop conditions (ask operator — nothing else)

1. The Phase 1 schema migration transaction fails, or any Phase 1.5
   verification count disagrees with the snapshot.
2. The Phase 2 vocabulary cleanup leaves `SELECT COUNT(*) FROM tags`
   outside the 55–70 range predicted by design §9.6.
3. The Phase 6 frontend rewrite cannot preserve the
   `/ext/hr_manager_renderer.js` script tag or the existing CSS variable
   set.

For anything else, use judgment.

---

## Phase 0 — Preflight

**Inputs:**
- `C:\AI\BUILD_LOCK.txt` — must read `LOCKED / Session: MediaVault v0.5 refactor (cowork)`.
- `C:\AI\Platform\MediaVault\_cowork\pre_v05_snapshot_<stamp>.json` — baseline.
- `C:\AI\Platform\MediaVault\_cowork\READINESS_REPORT_v05_<stamp>.md`.
- `C:\AI\Platform\MediaVault\_cowork\mv_v05_audit_20260419_170757.md` — the
  definitive pre-state document.

**Work:**
1. Verify build lock reads LOCKED for this session. If not, stop.
2. Verify the backup file
   `core/mediavault.sqlite.bak_pre_v05_<stamp>` exists and its size equals
   `core/mediavault.sqlite`'s size.
3. Open the snapshot JSON. Cache these baseline numbers — you will re-query
   them in Phase 2 and compare:
   - `counts.artifacts`
   - `counts.tags`
   - `counts.ingest_queue`
   - `parent_links`
   - `released_at_populated`
   - `artifacts_by_status_storage`
   - `vestigial_populated.tags_permission`
   - `vestigial_populated.author_name`
4. Start a new file: `_cowork/PHASE_SUMMARY_v05.md`. You will append to it
   after each phase.

**Output:** preflight OK. No file changes except the empty PHASE_SUMMARY stub.

---

## Phase 1 — Schema migration

**Single transaction. One connection.** If anything fails, rollback and stop.

**Target:** `core/mediavault.sqlite`.

### 1.1 Value-level migrations (before dropping columns)

Only one value migration is needed in v0.5: author_name → author pills.
`tags_permission` is dropped without migration per design §3.1.

a. For every artifact row with a non-junk `author_name`, append
   `author:<slug>` to the `tags` JSON array where `<slug>` is slugified from
   the author_name value. Deduplicate. Junk values to skip:
   - `(1) Video`, `(2) Video`, empty string, whitespace-only.

   Slugification rule (same as `ingest_engine.py` already uses): lowercase,
   spaces to underscore, non-alphanumeric stripped, collapse underscores.
   Expected mappings (confirmed in audit §12):

   | Original | author slug |
   |---|---|
   | `Hunter Root` | `author:hunter_root` |
   | `ElmThree Productions` | `author:elmthree_productions` |
   | `hunterrootofficial` | `author:hunterrootofficial` |

   Expected rows affected: 16 (13 + 2 + 1 = 16, per audit §12; the 2 junk
   rows are skipped). Record the count.

b. For every novel `author:*` slug from (a) that does not exist in the
   `tags` vocabulary, INSERT a vocabulary row with:
   - `slug` = the author slug (`author:hunter_root` etc.)
   - `display_name` = humanized form, strip the `author:` prefix and append
     ` (author)` to disambiguate from non-author pills (e.g.,
     `author:hunter_root` → `Hunter Root (author)`)
   - `category` = `'people'`
   - `is_exclusive` = 0
   - `is_proposed` = 0

### 1.2 Tags table — add category, is_exclusive; migrate group_name

The current `tags` table has `group_name`. v0.5 wants `category` and
`is_exclusive`. Category assignments happen later in Phase 2 after the
vocabulary is cleaned up. Phase 1 just adds the columns and preserves the
one group that survives (`rarity`).

```sql
ALTER TABLE tags ADD COLUMN category TEXT;
ALTER TABLE tags ADD COLUMN is_exclusive INTEGER NOT NULL DEFAULT 0;

-- Preserve the one v0.4 group that survives v0.5.
UPDATE tags SET category='rarity', is_exclusive=1
  WHERE group_name='rarity';

-- Do NOT migrate group_name='preservation' — those slugs (standard, critical)
-- are deleted in Phase 2. No category assignment needed.
```

Drop `group_name` by the SQLite rebuild-and-rename pattern:

```sql
CREATE TABLE tags_new (
    slug            TEXT PRIMARY KEY,
    display_name    TEXT NOT NULL,
    description     TEXT,
    category        TEXT,
    is_exclusive    INTEGER NOT NULL DEFAULT 0,
    is_proposed     INTEGER NOT NULL DEFAULT 0,
    usage_count     INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

INSERT INTO tags_new (slug, display_name, description, category, is_exclusive,
                     is_proposed, usage_count, created_at)
SELECT slug, display_name, description, category, is_exclusive,
       is_proposed, usage_count, created_at
  FROM tags;

DROP TABLE tags;
ALTER TABLE tags_new RENAME TO tags;
CREATE INDEX idx_tags_category ON tags(category);
CREATE INDEX idx_tags_proposed ON tags(is_proposed);
```

Full category assignments happen in Phase 2.4 (after merges and deletions)
so you don't waste work categorizing slugs that are about to be deleted.

### 1.3 Artifacts table — drop vestigial columns

SQLite does not support `DROP COLUMN` on older versions. Use rebuild pattern:

```sql
CREATE TABLE artifacts_new (
    id                      TEXT PRIMARY KEY,
    source_url              TEXT,
    source_platform         TEXT,
    ingest_source           TEXT,
    ingest_date             DATE NOT NULL,
    storage_mode            TEXT NOT NULL DEFAULT 'vaulted'
                                CHECK(storage_mode IN ('vaulted','referenced','url_only')),
    local_asset_path        TEXT,
    thumbnail_path          TEXT,
    link_status             TEXT CHECK(link_status IN ('live','dead','local-only')),
    parent_artifact_id      TEXT,
    media_type              TEXT,
    post_date               DATE,
    post_date_confidence    TEXT CHECK(post_date_confidence IN
                                ('extracted','manual','estimated','unknown')),
    capture_date            DATE,
    status                  TEXT NOT NULL DEFAULT 'vault'
                                CHECK(status IN ('inbox','vault','released','archived')),
    released_at             TEXT,
    released_by             TEXT,
    description_short       TEXT,
    description_long        TEXT,
    extracted_text          TEXT,
    tags                    TEXT NOT NULL DEFAULT '[]',
    confidence_flags        TEXT,
    notes                   TEXT,
    created_at              TEXT NOT NULL,
    updated_at              TEXT NOT NULL,
    FOREIGN KEY (parent_artifact_id) REFERENCES artifacts_new(id) ON DELETE CASCADE
);

INSERT INTO artifacts_new (
    id, source_url, source_platform, ingest_source, ingest_date,
    storage_mode, local_asset_path, thumbnail_path, link_status,
    parent_artifact_id, media_type,
    post_date, post_date_confidence, capture_date,
    status, released_at, released_by,
    description_short, description_long, extracted_text,
    tags,
    confidence_flags, notes, created_at, updated_at
)
SELECT
    id, source_url, source_platform, ingest_source, ingest_date,
    storage_mode, local_asset_path, thumbnail_path, link_status,
    parent_artifact_id, media_type,
    post_date, post_date_confidence, capture_date,
    status, released_at, released_by,
    description_short, description_long, extracted_text,
    tags,
    confidence_flags, notes, created_at, updated_at
  FROM artifacts;

DROP TABLE artifacts;
ALTER TABLE artifacts_new RENAME TO artifacts;

-- Rebuild indexes
CREATE INDEX idx_artifacts_status       ON artifacts(status);
CREATE INDEX idx_artifacts_storage_mode ON artifacts(storage_mode);
CREATE INDEX idx_artifacts_post_date    ON artifacts(post_date);
CREATE INDEX idx_artifacts_ingest_date  ON artifacts(ingest_date);
CREATE INDEX idx_artifacts_parent       ON artifacts(parent_artifact_id);
CREATE INDEX idx_artifacts_source_url   ON artifacts(source_url);
```

Columns dropped: `author_name`, `tags_permission`, `permission_contact`,
`permission_evidence_path`.

### 1.4 Recompute `tags.usage_count`

After all value migrations and merges (Phase 3 also touches these), the
usage counts must match `artifacts.tags` reality. Run at end of Phase 3,
not here — that's when the vocabulary is in its final shape.

### 1.5 Verification (still inside the transaction)

Queries cowork must run and check before committing:

- `SELECT COUNT(*) FROM artifacts` = snapshot `counts.artifacts` (80). Must match.
- Every column listed in `artifacts_new` exists; dropped columns
  (`author_name`, `tags_permission`, `permission_contact`,
  `permission_evidence_path`) are gone.
- Every surviving column keeps its data — pick 3 random IDs, compare all
  preserved fields against the backup DB. Must match.
- `SELECT COUNT(*) FROM tags` ≥ snapshot `counts.tags` (up to 3 new author
  vocab rows may have been added; no permission vocab rows — those are
  not migrated in v0.5).
- For each non-junk `author_name` mapping in Phase 1.1a, confirm the target
  artifact's `tags` JSON now contains the corresponding `author:*` slug.
- Confirm no `permission:*` pills were added to any artifact (the
  `tags_permission` column is dropped without migration).

If any verification fails: rollback, write PHASE_SUMMARY with failure
context, stop.

On success: COMMIT. Append Phase 1 summary to `PHASE_SUMMARY_v05.md`.

---

## Phase 2 — Vocabulary cleanup

**Single transaction.** Run after Phase 1 commits.

Execute design §9.2 (merges), §9.3 (deletions), §9.4 (creates), §9.5
(categorization) in that order. §9.1 is the question-per-category reference
and requires no code.

### 2.1 Merges (design §9.2)

Implement a helper:

```python
def merge_tag(conn, source_slug, target_slug):
    """
    Move all artifact references from source_slug to target_slug.
    Ensure target vocab row exists; create with is_proposed=0 if not.
    Delete source vocab row. Dedupe each affected artifact's tag array.
    """
```

Run the 14 merges from design §9.2. **Specific flag:**

- Merge #3: `runwiththehunt` → `run_with_the_hunt`. Target slug does not
  currently exist — create the vocabulary row first (slug
  `run_with_the_hunt`, display_name `Run With The Hunt`, category `bands`,
  `is_proposed=0`, `is_exclusive=0`).

Merges #17 and #18 from earlier drafts (genre splits) are **not** in this
list. `acoustic_rock` and `psychedelic_rock` stay as-is per operator ruling,
though they're deleted outright in §9.3 because the whole `genre` category
is out of scope.

For each merge, record: source slug, target slug, artifacts affected, new
target usage count. Append to PHASE_SUMMARY.

### 2.2 Deletions (design §9.3)

Remove these slugs from every artifact's `tags` array, then delete the
vocabulary row. Seven groups:

**Dead weight (applied everywhere or nowhere):**
- `standard` (76 uses — applied to every artifact, conveys nothing)
- `critical` (1 use — preservation workflow was never built)

**Year pills (duplicates the date columns):**
- `2019`, `2022`, `2023`, `2024`, `2025`, `2026`

**Visual details (fail the "would I search for this" test):**
- `striped_shirt`, `long_hair`, `brick_wall`, `brick_wall_background`,
  `original_music`

**Song titles (operator ruling: find via full-text search, not pills):**
- `town_rat_heathen`, `quicksand_sinking`,
  `dreaming_up_ways_of_gettin_outta_this_hellhole`,
  `hellhole_perspective_rubble_lyrics`, `my_brothers_bones`, `crooked_home`

**Genres (operator ruling: out of scope for a 2-3-band archive):**
- `rock`, `acoustic`, `jam`, `grunge`, `psychedelic`, `blues`,
  `singer_songwriter`, `acoustic_rock`, `psychedelic_rock`, `indiefolk`,
  `alternative`

**Overly generic or redundant:**
- `show` (21 uses — redundant with `live_show` + `media_type`)
- `song` (2 — redundant with `media_type=audio`)
- `performance` (1 — redundant with `live_show`)
- `quote`, `lyric` (1 each — too generic)
- `venue` (11 — meta-label; specific places go in `places`)

**Workflow provenance:**
- `phase2_recovery` (26 — ingest workflow marker)
- `mp3_only` (after §2.1 merge #9 folds it into `audio`, usage_count=0; delete)

Total: 38 slugs deleted. Roughly 250 pill occurrences removed across artifacts.

### 2.3 Vocabulary creates (design §9.4)

Create these vocab rows with `is_proposed=0`. No artifacts carry them yet
(except `run_with_the_hunt`, which is populated by merge #3 in §2.1 — if
that merge already created this row, skip it here).

| Slug | Display name | Category |
|---|---|---|
| `run_with_the_hunt` | Run With The Hunt | `bands` |
| `seeds` | Seeds | `bands` |
| `music_video` | Music Video | `content_kind` |
| `fan_art` | Fan Art | `content_kind` |
| `memorabilia` | Memorabilia | `content_kind` |

### 2.4 Recompute usage counts

```sql
UPDATE tags SET usage_count = (
    SELECT COUNT(*) FROM artifacts
    WHERE EXISTS (
        SELECT 1 FROM json_each(artifacts.tags) j
        WHERE j.value = tags.slug
    )
);
```

### 2.5 Categorization (design §9.5)

Apply these assignments. Uncategorized slugs keep `category=NULL`.

```sql
-- bands
UPDATE tags SET category='bands' WHERE slug IN
  ('hunter_root','medusas_disco','run_with_the_hunt','seeds');

-- people (hardcoded; author:* pills were already categorized in Phase 1.1b)
UPDATE tags SET category='people' WHERE slug = 'nick_root';

-- places
UPDATE tags SET category='places' WHERE slug = 'lancaster_pa';

-- content_kind
UPDATE tags SET category='content_kind' WHERE slug IN
  ('live_show','tour_announcement','poster','event_listing',
   'song_page','artist_page','promotional_post','rehearsal',
   'cover_song','new_song','tribute','milestone',
   'music_video','fan_art','memorabilia');

-- topic
UPDATE tags SET category='topic' WHERE slug IN
  ('songwriting','songwriting_process','loss','mental_health','lyme_disease');

-- scope
UPDATE tags SET category='scope' WHERE slug IN ('personal','family','fan');

-- rarity (already set in Phase 1.2, but reassert idempotently)
UPDATE tags SET category='rarity', is_exclusive=1 WHERE slug IN
  ('common','notable','rare','unique');
```

Every other surviving slug keeps `category=NULL`. Operator categorizes (or
deletes) them in Vocab Admin at leisure.

### 2.6 Verification

- Every slug in the §2.2 deletion list returns zero rows from
  `SELECT COUNT(*) FROM tags WHERE slug=?`.
- Every artifact's tags array is free of deleted slugs (run `json_each`
  across artifacts, assert no hits against the deletion list).
- Every slug in §2.1 merges has its source removed and target present.
- `SELECT COUNT(*) FROM tags` after cleanup is in the range **55–70**
  (design §9.6 predicts ~62). If outside this range, stop and ask.
- Every pill marked in §2.5 has its `category` set.

On success: COMMIT. Append Phase 2 summary.

---

## Phase 3 — Backend changes

**File:** `core/imgserver.py`.

### 3.1 Fix `handle_artifact_save` for release-immediately (audit §15, line 692)

When `release_now` is True (after an artifact row has been inserted/updated),
also clear the originating queue row. Audit §15 shows both statement shapes
are already in the file:

```python
cur.execute("UPDATE ingest_queue SET artifact_id=?, status=? WHERE queue_id=?",
            (artifact_id, "approved", queue_id))
```

If `release_now`: ensure this UPDATE runs with `status='approved'`, not
`'pending'`. If an inspection of the existing handler shows it is already
calling this update but with a different status value when `release_now` is
True, change the status value to `'approved'`. If the handler is not calling
this update at all on the release path, add the call.

**Do not change behavior when `release_now` is False** — normal
save-to-vault must continue to mark the queue row the same way it does
today (the audit shows today's behavior works; §8a has no stuck rows).

### 3.2 Add two new routes

Add to the `POST_ROUTES` dict in `imgserver.py` (audit §15 shows the dict
at line ~1260):

```python
"/api/tag-merge":       handle_tag_merge,
"/api/tag-bulk-delete": handle_tag_bulk_delete,
```

**`handle_tag_merge`** — body `{source_slug, target_slug}`. Reuses the
`merge_tag` helper from Phase 2. Returns `{ok: True, affected: N}`.

**`handle_tag_bulk_delete`** — body `{slugs: [...]}`. For each slug with
`usage_count=0`, delete. For any slug with usage_count > 0, return 409
with a list of offending slugs and don't delete anything. Returns
`{ok: True, deleted: [slugs], refused: [{slug, usage_count}]}`.

### 3.3 Update the enrichment prompt

`core/ingest_engine.py` or `core/enrich_helper.py` (cowork: check both and
edit wherever the prompt lives; audit §2 lists both). Replace the existing
prompt with design §6 verbatim.

Update the queue-row populator to accept both enrichment shapes:
- If `pill_states` is present: use it directly.
- Else if `tags_year_era` / `tags_content_type` / `tags_subject` etc. are
  present: convert to `pill_states` by flattening all values, mapping each
  to `on_uncertain` (not confident — operator must confirm a v0.4 blob's
  fields).

This conversion runs at inbox-render time, not at migration time — no need
to rewrite the 23 existing v0.4 enrichment blobs in the DB. They stay as
they are; the frontend (Phase 6) asks the backend for a "pills view" that
already normalizes.

Alternative: do the conversion in JS when the inbox loads. Pick whichever
you judge cleaner; the design doesn't require a specific home.

### 3.4 Verification

- Server boots: `python "C:\AI\Platform\MediaVault\core\imgserver.py"`.
- `GET /ping` returns 200.
- `GET /db` returns the updated sqlite blob with the v0.5 schema.
- `POST /api/tag-merge` with a made-up source/target returns 400 for missing
  target (not 500). Smoke, not full integration.
- `POST /api/artifact-save` with `release_immediately: true` against an
  existing queue row marks that queue row as `approved` with the new
  `artifact_id` set (verify by querying `ingest_queue` after).

---

## Phase 4 — imgserver_extensions.py rewrite

**File:** `core/imgserver_extensions.py`. Audit §13 has the full current
source.

### 4.1 Keep handle_asset_raw unchanged

It's schema-agnostic and works.

### 4.2 Rewrite handle_artifact_register

Target behavior: accept a POST body describing an artifact and INSERT into
the v0.5 `artifacts` table.

Remove from current code:

- The `DOMAIN_ENUM` constant.
- The `_next_artifact_id` function's per-domain prefix lookup.
- Every reference to `domain` in the body-parsing code.
- Every reference to the 10 `tags_*` columns.
- The `"standard"` literal written to `tags_preservation`.

Add:

- New `_next_artifact_id(conn)` that uses v0.4 `id_sequence` schema
  (per audit §3: `date_str PK, last_seq INTEGER`). Format: `MV-YYYYMMDD-NNN`.
  Copy the exact logic from `ingest_engine.py`'s `next_id()` (audit §4 in
  PHASE_SUMMARY confirms this function exists).
- Accept optional `tags` param: a JSON array of slugs. Validate each slug
  format `^[a-z0-9_:\-]+$` (colon is permitted because `author:` and
  `permission:` prefixes are legal v0.5 slugs).
- Accept `storage_mode` param with values from v0.5 enum. Default: `vaulted`
  if `local_asset_path` is inside `catalogs/`, else `referenced`.
- Accept `status` param, default `'vault'` (external callers ship directly
  to vault, skipping the inbox — that's the whole point of /artifact-register).

Simplified INSERT:

```python
INSERT INTO artifacts(
    id, source_url, source_platform, ingest_source, ingest_date,
    storage_mode, local_asset_path, thumbnail_path, link_status,
    parent_artifact_id, media_type,
    post_date, post_date_confidence, capture_date,
    status,
    description_short, description_long, extracted_text,
    tags,
    confidence_flags, notes
) VALUES (?, ?, ..., ?)
```

### 4.3 Verification

- `python -m py_compile core/imgserver_extensions.py` passes.
- Server boots.
- `POST /api/artifact-register` with minimal valid body returns 200 with an
  assigned ID. The resulting artifact row is present and well-formed.
- `GET /asset-raw?path=...` still serves a file from a legal root.

---

## Phase 5 — attention_rules.py

**New file:** `core/attention_rules.py`. ~60 lines.

Single public function:

```python
def evaluate_rules(
    fields: dict,           # the artifact-level fields (source_platform, post_date, etc.)
    pill_slugs: set[str],   # currently-ON pill slugs
    vocab: dict,            # slug -> {category, is_exclusive, ...}
) -> list[dict]:
    """Return a list of warnings, each {slug, reason, category}."""
```

Rules per design §4.4 (R1–R5). Warnings are dicts of shape:
`{"slug": "warn:missing_category:people", "reason": "...", "category": "people"}`.

The backend does not persist warnings. They are returned by a new route
`POST /api/enrich-view` which takes `{queue_id}` and returns
`{pill_states, warnings}` — computed live each time the inbox renders a queue
item. (Backend change to Phase 3: add this route.)

Alternatively, move this entirely to the frontend if you judge it cleaner.
The rules are simple enough to run in JS and save a round-trip. Operator
doesn't care which.

---

## Phase 6 — Frontend rewrite

**File:** `mediavault.html` (audit §14 has line references).

### 6.1 Preserve

- `<link>`s for fonts (lines 5-6).
- `<script src="https://cdnjs.cloudflare.com/ajax/libs/sql.js/1.8.0/sql-wasm.js">` (line 7).
- All CSS variables in `:root` (lines 9-16).
- `<script src="/ext/hr_manager_renderer.js"></script>` (line 456) — **must
  stay exactly where it is**, external contract.
- Topbar (lines 233-240) — same structure: INBOX / MEDIAVAULT tabs + gear icon.
- Vault pane (lines 362-419) as-is for now. Additions in 6.3.
- Vocab pane structure (lines 421-446) as-is for now. Additions in 6.4.
- Startup flow (lines 1285-1298) — the ping → sql.js → db → queue → tags
  load order is correct.

### 6.2 Rebuild the Inbox pane (largest change)

Replace the entire `#inboxPane` div (lines 245-360) with a new layout
matching design §4.1. Order matters:

1. **Top action bar** (new, always visible at top of inbox):
   - prev / dropdown / next
   - Scrap / Save / Save & Release buttons
2. **Viewer** (roughly what's there today, lines 253-260, plus the AI bar).
3. **Pill wall** — grouped by category, collapsible sections, 5-state pills.
   This is the new component. See 6.2.1.
4. **Descriptions pane** (collapsed by default) — `<details>` element
   wrapping the existing fields:
   - Short, Long, Extracted text, Notes
   - Source (URL + platform)
   - Dates (post + capture + confidence)
   - Storage (mode + media_type)

**Removed from inbox entirely:**
- ID field (line 266).
- Author field (line 282).
- Parent artifact input (line 351) and the entire Structure section
  (line 348).

### 6.2.1 Pill wall component

A new top-level function:

```js
function renderPillWall(pillStates, warnings, vocab) {
  // pillStates: { slug -> 'on_confident' | 'on_uncertain' | 'off_suspected' | 'off_maybe' }
  // warnings:   [{slug, reason, category}]
  // vocab:      TAGS_BY_SLUG — includes .category, .is_exclusive, .display_name

  // Group by category using the priority order from design §4.3.
  // Render each category as a collapsible section with a summary line.
  // Warnings in a category render at its top with a red bolt icon.
  // Within a category, pill order: on_confident → on_uncertain → off_suspected → off_maybe.
}
```

Click behavior on a pill:
- `on_confident` or `on_uncertain` → set state to OFF locally. Do not save yet.
- `off_suspected` or `off_maybe` → set state to `on_confident` (operator
  override). Do not save yet.
- Warning pill → clicking does nothing; warnings resolve when the
  condition that triggered them is satisfied (usually by adding another pill).

CSS additions needed (reuse existing variables):

```css
.pill             { /* base pill class — similar to existing .tagPill */ }
.pill.on-conf     { background: var(--gold); color: #111; }
.pill.on-unc      { background: var(--gold); color: #111; border: 1px dashed #000; }
.pill.off-sus     { background: transparent; color: var(--gold); border: 1px solid var(--gold); }
.pill.off-may     { background: transparent; color: var(--text2); border: 1px dashed var(--border); opacity: .65; }
.pill.warn        { background: transparent; color: var(--red); border: 1px solid var(--red); animation: warn-pulse 1.5s infinite; }

.pillCategory             { margin-bottom: 12px; }
.pillCategory > summary   { cursor: pointer; font: 600 11px var(--mono); color: var(--gold); letter-spacing: .5px; }
.pillCategory > .pills    { display: flex; flex-wrap: wrap; gap: 4px; padding: 4px 0; }

@keyframes warn-pulse { 50% { opacity: .5 } }
```

The add-pill input sits at the bottom of the pill wall, always visible:

```html
<input type="text" id="pillAdd" placeholder="+ add pill (e.g., lancaster_pa, carsie_blanton)" autocomplete="off">
```

Enter-key behavior: slugify, check vocab, create-proposed if novel, apply
as `on_confident`, re-render.

### 6.2.2 Replacement `inboxSave()` flow

Current behavior (audit §14, line 652) reads `CURRENT_APPLIED_TAGS` and
sends them as the `tags` field. v0.5 reads `pillStates`:

```js
const appliedTags = Object.entries(pillStates)
  .filter(([slug, state]) => state === 'on_confident' || state === 'on_uncertain')
  .map(([slug]) => slug);
```

Send `appliedTags` as `tags` in the `/api/artifact-save` body. Rest of the
request unchanged.

### 6.3 Vault — attach-to-parent modal

Add a new button to the vault detail panel's actions row (audit §14, the
detail panel's `renderDetail` fn at line 1017):

```html
<button onclick="openAttachParentModal(a.id)">⇪ ATTACH TO PARENT</button>
<button onclick="detachParent(a.id)" id="btnDetach" style="...; display: {a.parent_artifact_id ? 'inline-block' : 'none'}">⇪ DETACH</button>
```

`openAttachParentModal(childId)` opens a modal with:
- Search input (filters by description, ID, source_url).
- List of candidate artifact rows (thumbnail + short desc + platform + date).
- Excludes `childId` and any descendant of `childId` (walk parent pointers
  in JS — cheap, only 80 rows).
- Clicking a row calls `/api/artifact-update` with `{id: childId, fields: {parent_artifact_id: row.id}}`.

`detachParent(id)` calls `/api/artifact-update` with
`{id, fields: {parent_artifact_id: null}}`.

### 6.4 Vocab Admin — merge + bulk-delete

Add above the vocab table toolbar (audit §14, lines 423-432):

```html
<button onclick="openMergeModal()">⇔ MERGE</button>
<button onclick="openBulkDeleteModal()">⌫ BULK DELETE</button>
```

**Merge modal:**
- Source slug select (dropdown of all slugs with usage_count > 0).
- Target slug select (dropdown of all slugs).
- Preview "N artifacts currently carry <source>. They will carry <target>
  instead."
- Confirm → POST `/api/tag-merge`.

**Bulk delete modal:**
- Checklist of every slug with usage_count = 0.
- Confirm → POST `/api/tag-bulk-delete`.

### 6.5 Inbox empty-state + intake controls

When `QUEUE.length === 0`, show a centered control block in the viewer
area:

```html
<div class="intake-empty">
  <h2>Queue is empty.</h2>
  <p>Drop a file, paste a URL, or run <code>ingest_engine.py scan</code> from PowerShell.</p>
  <input type="file" id="intakeFile" multiple>
  <input type="text" id="intakeUrl" placeholder="https://...">
  <button onclick="intakeAddUrl()">Add URL</button>
</div>
```

Wire:

- `intakeFile` on change → for each file, POST `/api/intake-upload`
  (multipart form). The backend already accepts this (audit §15 route list).
- `intakeAddUrl()` → POST `/api/intake-url` with `{url}`.

When the queue has items, add a smaller `+` affordance in the top action
bar that opens the same controls as a modal.

### 6.6 Verification

- Server boots, `/` returns the new HTML.
- Inbox pane renders the 25 existing queue rows. Pills appear in groups.
  (With v0.4 enrichment data, every pill shows as `on_uncertain` — that's
  correct per Phase 3.3.)
- Click a pill — state flips, save without releasing, reload — the pill's
  current state persists as a tag on the artifact.
- Save & Release clears the queue row (the bug fix verifies end-to-end).
- Vault renders 80 artifacts (per snapshot). Tri-state pills still work.
- Vault detail attach-to-parent modal: pick a candidate, save, vault grid
  redraws with the new parent-child relationship.
- Vocab admin merge: merge a no-op (pick the same source and target? no —
  pick two made-up slugs and accept the 400). Real merges happened in
  Phase 2; the UI path is just for future cleanup.
- Inbox empty state: scrap every queue row, verify empty state appears.
  Paste a URL, verify new queue row created.

---

## Phase 7 — Docs + cleanup + smoke test

### 7.1 Docs to update

- `SPEC.md` — bump to v0.5. Rewrite sections:
  - §2 Tags — add the pill-state model (five states in inbox; tri-state in
    vault). Note that `category` replaces `group_name`; add `is_exclusive`.
  - §6 Schema — update to v0.5 (drop `author_name`, drop `tags_permission`,
    drop `permission_contact`, drop `permission_evidence_path`).
  - New §X: Attention rules (brief summary, refer to design).
- `STATE.md` — new session entry for v0.5. Decisions locked, new open items,
  resolved items.
- `PROJECT.md` — update the one-paragraph description if "pill-state model"
  changes the project's framing.
- `WORKFLOW.md` — rewrite the Inbox section (new layout, pill clicking,
  warnings).
- `_cowork/PHASE_SUMMARY_v05.md` — final section summarizing every phase,
  every decision, every row count.

### 7.2 Quarantine

Move to `D:\AI_OK_TO_DELETE\MediaVault_v05_refactor_<date>\`:

- `hr_manager.html.old_v02` (if still present at ROOT)
- `core/imgserver.py.old_v02`
- `core/_test.txt`
- `core/screenshot_match.json`
- `core/migrate_to_v04.py`

If delete permission is declined for any of these (as happened in v0.4),
leave the source copies in place. The quarantine copies are the important
ones. Record what happened in PHASE_SUMMARY.

### 7.3 Smoke test

Full matrix from Phase 6.6 plus:

- Server restart — page loads, state is the same.
- Full-text search in vault — existing behavior unchanged.
- Tag picker in vault detail — apply a new pill to an existing artifact,
  it persists.
- Vocabulary admin: accept a proposed tag, rename a tag, reject a tag
  (three-way modal) — all still work.
- `ingest_engine.py status` prints counts that match the DB.

### 7.4 Release build lock

```powershell
Set-Content "C:\AI\BUILD_LOCK.txt" -Value "UNLOCKED`nLast session: MediaVault v0.5 refactor (cowork)`nReleased: <today>`nReleased by: cowork`nOutcome: SHIPPED — see C:\AI\Platform\MediaVault\_cowork\PHASE_SUMMARY_v05.md"
```

Append final summary to PHASE_SUMMARY_v05.md and exit.

---

*End of v0.5 cowork brief.*
