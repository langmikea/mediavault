# MediaVault Full Codebase Review

*Read-only review against the v0.6-shipped code on disk at 2026-04-20. Scope
covers `C:\AI\Platform\MediaVault\` excluding `wb_capture_ext`. No patches.*

## Summary

The data layer is the weakest link. The v0.6 schema change that allowed the
same slug in multiple categories (`UNIQUE(slug, category)`) was migrated
successfully, but no handler in `core/imgserver.py` was taught to think in
`(slug, category)` pairs — every `WHERE slug=?` and every frontend lookup
still treats slug as globally unique, and the DB already has one collision
(`hunter_root` exists in both `bands` and `people`) that exercises this
tacit assumption daily. SPEC and code disagree on the `artifacts` column set
(SPEC promises `pill_states` and `archived_at`; neither exists on disk) and
on the `ingest_queue.status` vocabulary. There is a visible tangle in
`core/` between what's live (`imgserver.py`, `imgserver_extensions.py`,
`ingest_engine.py`, `attention_rules.py`) and what's vestigial
(`db_setup.py`, `migrate_to_v04.py`, `enrich_helper.py`, `rethumb.py`,
`analyze_captures.py`, `tag_vocabulary.json`, `batch_enrich.py`,
`backfill_dates.py`). The three UI surfaces (Inbox, Vault, Vocab) mostly
agree on the pill vocabulary they read, but agree less on who creates pills
and under what rules, and the FB-candidates surface has two broken
integration points that would never show up unless an operator actually
tried them.

---

## Findings

### Architecture

- **Two `slugify` implementations in the Python layer, one in JS, all claiming v0.5 semantics**
  - `core/imgserver.py:125`, `core/imgserver_extensions.py:115`, `core/ingest_engine.py:122`, `mediavault.html:728`.
  - Four roughly-equivalent copies. imgserver.py and imgserver_extensions.py are ~95% identical (the latter uses `_SLUG_RE` at the end; the former uses `SLUG_RE`); `ingest_engine.py`'s copy omits the regex validation step entirely. The JS copy is a hand-port.
  - The comment at `imgserver_extensions.py:61`-ish explicitly says the extension module stays import-free of imgserver.py "by design", which is the reason for the double-Python copy. The `ingest_engine.py` copy has no such justification. Divergence is inevitable.

- **`display_name_for` logic implemented three different ways**
  - `core/imgserver.py:152` uses `display_name_for(slug)` — preserves 4-digit years, else title-cases underscores.
  - `core/ingest_engine.py:113` uses `" ".join(w.capitalize() for w in slug.split("_"))` — no year branch.
  - `core/imgserver_extensions.py:304` inlines `s.replace("_", " ").title()` — uses `str.title()` not `.capitalize()`, which changes the behaviour of all-caps substrings (`"MIKE"` → `"Mike"` both ways but `"HR"` → `"Hr"` in extensions, `"HR"` in imgserver's `.title()` form).
  - Three places, three shapes. The pill wall surfaces whichever one the latest writer chose.

- **`core/db_setup.py` describes the v0.2 schema and is still on disk**
  - `core/db_setup.py:17-90`.
  - Creates `artifacts` with `domain`, `author_name`, `tags_year_era`, `tags_permission`, `permission_contact`, `permission_evidence_path`, `post_usage_log`, etc. — all of which are either dropped from the live schema or were never present in v0.4/v0.5/v0.6.
  - The `next_id(conn, domain)` function on line 98 uses the pre-v0.4 `(domain, date_str)` composite PK that the live `id_sequence` table no longer has.
  - Running this script against the current DB would not be catastrophic (it uses `CREATE TABLE IF NOT EXISTS`), but the file reads as an authoritative schema source to any fresh reader.

- **`core/migrate_to_v04.py` survives in the live `core/` directory**
  - `core/migrate_to_v04.py` (whole file, 589 lines).
  - Referenced in `STATE.md:52` as a "preserved reference" and quarantined at `D:\AI_OK_TO_DELETE\MediaVault_v05_refactor_20260419\` per `PHASE_SUMMARY_v05.md:604`, but the source copy is still in `core/`. Grep hits on `group_name`, `author_name`, and `tags_permission` in this file surface alongside live matches.

- **`core/enrich_helper.py` still SELECTs the dropped `domain` column**
  - `core/enrich_helper.py:28-30`.
  - `export_queue()` does `SELECT queue_id, domain, ingest_source, raw_path, source_url FROM ingest_queue` — `domain` was removed in v0.4. Any invocation raises `sqlite3.OperationalError: no such column: domain`.
  - `import_results()` on the same file does work; the two halves don't fail together.

- **`core/rethumb.py` selects `WHERE domain='hunter_root'`**
  - `core/rethumb.py:7`.
  - Dead on arrival against the current schema.

- **`core/analyze_captures.py` decodes `author_name` out of enrichment JSON**
  - `core/analyze_captures.py:6`.
  - Not broken — `author_name` still appears in v0.4-era `enrichment_json` blobs — but the script's purpose is inspection output; its author column will read `"?"` for every post captured after v0.5 dropped the field from the capture shape.

- **`core/tag_vocabulary.json` is referenced as a path and never read**
  - `core/tag_vocabulary.json` (whole file) and `core/ingest_engine.py:39` (`VOCAB_PATH = BASE / "core" / "tag_vocabulary.json"`).
  - Grep finds no reads of `VOCAB_PATH`. The JSON itself still declares the v0.2 world: `domains` list, `tag_categories` with `permission`/`preservation` groups, `id_format` with per-domain prefix mapping.
  - `SPEC.md:506` and `MEDIAVAULT_V05_DESIGN.md:920` acknowledge the file as a "harmless seed/backup", but the unused variable in `ingest_engine.py` implies it might still be live.

- **`batch_enrich.py` sends the v0.2 prompt shape**
  - `batch_enrich.py:22-41`.
  - Its prompt explicitly asks the model to return `author_name`, `media_type_in_post`, `tags_year_era`, `tags_content_type`, `tags_subject`, `tags_topic`, `tags_song_reference`, `tags_keywords` — every one of which is dropped or renamed. The import endpoint it calls (`/enrich`, not `/api/enrich`) also doesn't match any route in `imgserver.py`.
  - Together with `backfill_dates.py` (which imports `ai_preprocess` from `ingest_engine` and is at least internally consistent), these are the historical post-process helpers. Neither is referenced by live code paths.

- **`handle_artifact_save` (1637 lines deep) does three things that arguably belong separately**
  - `core/imgserver.py:820`.
  - It owns: the queue→artifact promotion (INSERT branch), in-place mutations when the artifact already exists (UPDATE branch, added in v0.6 item 8d), optional file copy into the vaulted root, automatic slug creation for novel pills, and marking the queue row `approved`/`keep`. The branching is correct but the function reads as five separate jobs; `handle_artifact_update` (line 967) also mutates artifacts and does its own tag-delta + usage-count work, so there are now two places maintaining the same invariants.
  - Usage counts are adjusted in `handle_artifact_save` only when `tags_supplied` (line 948), but `handle_artifact_update` does the same bookkeeping independently at line 1012.

- **The `/api/thumbgen` endpoint is defined but not invoked from any live surface**
  - `core/imgserver.py:1097` (`handle_thumbgen`), `core/imgserver.py:1535` (route registration).
  - Grep across `mediavault.html`, `fb_candidates.html`, and `ext/hr_manager_renderer.js` returns zero calls to `/api/thumbgen`. The thumbnail pipeline for items saved through the inbox relies on `ingest_engine.py process` being run manually from PowerShell.
  - Related: `/api/artifact-save` does not generate a thumbnail after vaulting the file (the copy at line 849 is a byte copy, not a thumb). Items saved through the inbox have no thumbnail until `ingest_engine.process()` runs, and `process()` only picks up queue rows where `status='approved'` (set only on save-and-release, not on save-to-vault).

- **Thumbnail output paths differ by source**
  - `core/imgserver.py:58` — `/api/thumbgen` writes to `BASE/thumbnails/inbox/<id>.jpg`.
  - `core/ingest_engine.py:598-600` — `generate_thumbnail` writes to `BASE/catalogs/_thumbs/<id>.jpg`.
  - On-disk today (from the file listing at review time) thumbnails live at `BASE/catalogs/hunter_root/_thumbs/<HR-ID>.jpg` (a legacy pre-v0.4 location). Nothing writes there now; nothing reads from the other two paths.

- **`ARTIFACT_FIELDS` tuple governs both save and update paths, but fields drift silently**
  - `core/imgserver.py:797-805`.
  - `handle_artifact_save` and `handle_artifact_update` both loop `ARTIFACT_FIELDS` to decide what to write. Adding a field to the schema requires a manual edit here; dropping a field from the schema requires another. `pill_states` (declared in `SPEC.md:228` and sent from the frontend at `mediavault.html:1055`) is not in the tuple, so it is silently dropped on every save.

- **`INTAKE_DIR` and `DROP_DIR` are different folders used by different code**
  - `core/imgserver.py:59` — `INTAKE_DIR = BASE/intake/inbox` (used by `handle_intake_upload`).
  - `core/ingest_engine.py:40` — `DROP_DIR = BASE/intake/drop` (used by `scan()`).
  - A file uploaded through the `/api/intake-upload` endpoint lands in `intake/inbox/` and is queued directly. A file dropped into `intake/drop/` is picked up by `ingest_engine.scan()`. No handler watches both. The UI today has no upload control (the empty-state intake was deferred per `STATE.md:62`), so `INTAKE_DIR` is unused.

### Data layer

- **Schema allows `(slug, category)` uniqueness; every handler and the frontend assume slug is globally unique**
  - Schema: `idx_tags_slug_category UNIQUE(slug, category)` + partial `idx_tags_slug_when_null_cat UNIQUE(slug) WHERE category IS NULL`. No `PRIMARY KEY` on `tags`.
  - The DB already has one collision: a row-count dump at review time shows `hunter_root` exists both in category `bands` (usage=79) and category `people` (usage=0).
  - `core/imgserver.py:1210` (`handle_tag_update`): `conn.execute("SELECT * FROM tags WHERE slug=?", (slug,)).fetchone()` — if two rows share the slug, `fetchone()` returns one arbitrarily; the rename/edit acts on a potentially different row than the user clicked.
  - `core/imgserver.py:1292` (`handle_tag_accept`), `:1322` (`handle_tag_reject` deprecate-path), `:1361` (reject delete), `:1379` (`handle_tag_delete`), `:1407` (merge-target existence check), `:1428` (merge-source delete), `:1482` (bulk-delete row delete), `:1293` (legacy usage bump), `:1354` (replace-mode usage transfer) — all are `WHERE slug=?` against a table that no longer considers slug unique.
  - `mediavault.html:827` — `TAGS_BY_SLUG = {}; TAG_LIST.forEach(t => TAGS_BY_SLUG[t.slug] = t);` — last row wins. The UI cannot display two different `hunter_root` rows simultaneously.
  - `mediavault.html:1200-1205` (`renderPillWall`) iterates `TAG_LIST` and groups by category, so both rows DO render — one pill in `bands`, one in `people` — but `togglePill('hunter_root')` at line 1311 keys `CURRENT_PILL_STATES['hunter_root']`, so clicking one toggles the other. The accumulated view at line 1238 also keys by slug and shows both rows as applied.
  - `artifacts.tags` arrays store plain slugs (`"hunter_root"`), not `(category, slug)` pairs, so there is no data-layer path to disambiguate which of the two `hunter_root` rows an artifact means.

- **`pill_states` is promised in spec, sent by the client, never persisted**
  - `SPEC.md:228` declares `pill_states TEXT` on the `artifacts` table.
  - Actual DB schema: no `pill_states` column (confirmed via `PRAGMA table_info(artifacts)`).
  - `mediavault.html:1055` — `inboxSave` builds `fields.pill_states = {...CURRENT_PILL_STATES}` in the save payload.
  - `core/imgserver.py:797-805` — `ARTIFACT_FIELDS` tuple does not include `pill_states`, so `handle_artifact_save` silently drops the key. The `tags` array (on_confident + on_uncertain only) is the only thing that reaches the DB.
  - On reload, `populateInboxFields` at `mediavault.html:937` rebuilds `CURRENT_PILL_STATES` from `artifact._tags`, setting every slug to `on_confident`. The `on_uncertain` distinction is lost across a reload.
  - `MEDIAVAULT_V05_DESIGN.md` and `PHASE_SUMMARY_v05.md:576` both treat `pill_states` as a v0.5 deliverable. It landed in the spec but not in the schema or the handler.

- **`archived_at` is promised in spec, not in schema, and `handle_artifact_archive` doesn't set it**
  - `SPEC.md:235` declares `archived_at TEXT`.
  - Actual schema: no such column.
  - `core/imgserver.py:1045`: `def handle_artifact_archive(h): _set_status(h, "archived")`. `_set_status` at line 1019 updates `status` and `updated_at` only.
  - `SPEC.md:171` describes the archive flow as `vault → archived` but says nothing about a timestamp. The design doc is the asymmetry.

- **`artifacts.status` CHECK excludes `deleted`; `imgserver_extensions.STATUS_ENUM` includes `deleted`**
  - Actual schema: `CHECK(status IN ('inbox','vault','released','archived'))`.
  - `core/imgserver_extensions.py:81`: `STATUS_ENUM = {"vault", "released", "archived", "deleted"}`. Contains `deleted` (DB would reject it), omits `inbox` (DB would accept it). `handle_artifact_register` validates against this set at line 260 and rejects any client that sends `status='inbox'` through that endpoint.
  - `SPEC.md:206` schema comment says `inbox|vault|released|archived|deleted` — same 5 values the enum advertises. Code, schema, and spec all give different answers to "what can status be?"

- **`ingest_queue.status` vocabulary drifts three ways**
  - Actual schema: `CHECK(status IN ('pending','keep','skip','enriched','approved','failed'))`.
  - `SPEC.md:266` schema comment: `pending|processed|error`.
  - `mediavault.html:812` (`loadQueue`) filters to `ACTIVE = {'pending','enriched'}`.
  - `core/imgserver.py:953` sets `queue_status = "approved" if release_now else "keep"` on save.
  - `core/ingest_engine.py:575` sets `status='failed', error_message='recycled'` after successfully recycling skipped files. Confusing — the file was skipped on purpose, not failed.
  - `core/ingest_engine.py:681` sets `status='failed', error_message='file-moved'` after successfully moving the original. Same pattern: success recorded as failure, with a disambiguating error_message.
  - Live DB has 33 `keep` rows and 1 `skip` row that will never move because the UI never displays them and no background task transitions them.

- **`handle_tag_reject` deprecate mode writes `category='deprecated'`**
  - `core/imgserver.py:1321`: `"UPDATE tags SET category='deprecated' WHERE slug=?"`.
  - `SPEC.md:123` describes deprecate as "keep but hide from picker; existing artifacts retain the pill."
  - The renderer at `mediavault.html:1200-1205` groups by `category`, so `deprecated` becomes a visible category in the pill wall's "rest" bucket (sorted alphabetically after `CATEGORY_ORDER`). Nothing hides it.
  - `handle_enrich` at `imgserver.py:706`-`707` does filter `category != 'deprecated'` out of the vocab sent to the LLM, so the model doesn't see deprecated tags. That's the only place the deprecation has effect.

- **`usage_count` is maintained by three different paths**
  - Incremental: `adjust_tag_usage` in `imgserver.py:193` is called from `handle_artifact_save:949` and `handle_artifact_update:1012`, and a bump-only call at `imgserver_extensions.py:348` on register.
  - On delete: `handle_artifact_delete:1063` decrements by iterating the artifact's tags.
  - Full recompute: `handle_tag_merge:1431` and `handle_tag_bulk_delete:1484` run `UPDATE tags SET usage_count = (SELECT COUNT(*) FROM artifacts a, json_each(a.tags) j WHERE j.value = tags.slug)`.
  - `handle_tag_update` rename path (line 1236-1260) copies the old row's `usage_count` onto the new slug and deletes the old — it does not recompute and doesn't use `adjust_tag_usage`, but since the artifact's tag array is rewritten there's no drift. Still, the pattern is the only counter-change path that doesn't go through either of the other two mechanisms.

- **`ingest_engine.upsert_tag` uses `ON CONFLICT(slug) DO NOTHING`, which no longer matches any constraint**
  - `core/ingest_engine.py:114-118`.
  - The v0.6 migration dropped the old `slug` PRIMARY KEY. The new unique indexes are `(slug, category)` and the partial `slug WHERE category IS NULL`. `ON CONFLICT(slug)` without a matching constraint raises `sqlite3.OperationalError: ON CONFLICT clause does not match any PRIMARY KEY or UNIQUE constraint`.
  - Grep across the file shows `upsert_tag` is defined (`:106`) but never called within `ingest_engine.py`. It's dead code that would crash if woken.

- **`is_proposed` is a live column with 0 live values**
  - DB row count at review time: every vocab row has `is_proposed=0`. The concept still exists in: `handle_tag_create` accepts the parameter (`imgserver.py:1169`), `handle_tag_accept` still exists (`:1286`), `upsert_tag` still takes the param (`:181`), the SPEC (`:83,:117,:206`) still describes proposed-pill semantics, and `mediavault.html:1339`-`1345` conditionally renders a "(proposed)" suffix in the pill-add autocomplete, but…
  - `mediavault.html:2125` removes the ACCEPT/REJECT column from Vocab Admin entirely ("every tag is just a tag now", per the comment at `:639`).
  - `mediavault.html:1297`-`1300` (`pillHtml`) explicitly "dropped the 'proposed' visual flag and tooltip suffix."
  - The surface turned off the feature but the column, the write path (tag-create still accepts `is_proposed`), and the read paths (`filter by proposed_only=1` at `imgserver.py:354`) are all still live.

- **Slug rename in `handle_tag_update` writes a new row without category uniqueness check against the source's OTHER categories**
  - `core/imgserver.py:1219-1244`.
  - The rename path computes `new_category = body.get("category", row["category"])`, then checks for a collision only at `(new_slug, new_category)` (line 1221-1225). If the caller sends `new_slug` with no `category` override, and `row["category"]` is NULL, the check passes even when a row at `(new_slug, "bands")` already exists — creating a second row keyed to an index that hasn't been hit.
  - The live constraint is two UNIQUE indexes (one composite, one partial for NULL). Insertion would ultimately be rejected by the appropriate index, but the 409 path expects the lookup query to find the collision first. A miss there hands the exception back to the dispatch 500-handler at `imgserver.py:1582` ("handler error: ...") instead of the structured 409 the frontend handles at `mediavault.html:2339`.

- **`handle_enrich` auto-creates novel slugs with no category**
  - `core/imgserver.py:761` — `upsert_tag(conn, s, is_proposed=1)` on every unfamiliar slug the model returned.
  - `upsert_tag` at `:177` passes `category=None` by default.
  - `handle_tag_create` at `:1167` explicitly refuses category-less creation with a 400. Two pill-creation paths, two contracts. The enrich path silently seeds the vocab with uncategorized rows; the create endpoint rejects them.
  - Same pattern in `handle_artifact_save:856` — novel tags become `is_proposed=1` with no category — and `imgserver_extensions.py:300` on register.

- **`handle_tag_merge` silently auto-creates the target**
  - `core/imgserver.py:1407`: `if not conn.execute(... WHERE slug=? ...).fetchone(): upsert_tag(conn, target)`.
  - Creates a category-less, display-nameless target if the caller asks to merge into a non-existent pill. Harmless if the caller checked, but this is the same hole as the enrich/save paths — category is never required, and operators lose the category they might have expected.

- **`/api/tag-merge` has inconsistent body shapes across callers**
  - `core/imgserver.py:1394`-`1398` accepts `{sources: [...], target}`.
  - `mediavault.html:2411` posts `{source_slug: src, target_slug: tgt}`.
  - `mediavault.html:2289` posts `{sources:[oldSlug], target:targetSlug}` — the correct shape — from the merge-offer modal.
  - `_cowork/v06_item4_cleanup.py` hits the right shape at `:86`.
  - The `submitMerge()` modal path (`mediavault.html:2405`) would 400 on a real call (handler rejects `source_slug` as unknown, asks for `sources` list and `target`). Reading the button behavior at `:2391`: clicking MERGE in the classic modal returns a no-op error because the payload is the wrong shape. This is the Vocab Admin's top-bar ⇔ MERGE button.

- **`confidence_flags` is a JSON column but nothing builds or consumes it**
  - Schema: `confidence_flags TEXT` (no default).
  - `SPEC.md:284` describes the flow: "Claude flagged as uncertain during enrichment. The Inbox editor highlights these fields."
  - Grep shows `confidence_flags` in `migrate_to_v04.py` (copied through), `imgserver.py:804` (carried in ARTIFACT_FIELDS), and `imgserver_extensions.py:339` (bound on register). No code writes it from enrichment. No code reads it to render a glow.
  - The current uncertainty mechanism is `attention_rules.py` (soft warnings) + the five-state pill model (pill-level uncertainty). The field-level `confidence_flags` idea was never wired up.

- **`post_usage_log` column was promised in v0.2 and never existed in v0.4+**
  - `core/db_setup.py:50` declares the column.
  - `SPEC.md:389` explicitly retires the Post Builder concept. Still, the db_setup file is on disk.
  - No live reader/writer. Pure archaeology, bundled with db_setup.py above.

### Surface consistency

- **Inbox pill creation and Tag Manager pill creation are distinct code paths with different contracts**
  - Inbox path: `mediavault.html:1329-1424` (`setupPillAdd`). Typing a novel slug and pressing Enter now requires picking one of the `CATEGORY_ORDER` rows from the dropdown; the Enter-without-highlight branch at line 1392-1397 refuses to create.
  - Tag Manager path: `mediavault.html:2225-2253` (`openTagCreateModal` / `submitTagCreate`). Uses the Category `<select>` populated by `categoryOptionsHtml` — which includes any category present in the vocab (line 2219-2220), so custom/legacy categories like `scope` or `deprecated` are selectable even though `CATEGORY_ORDER` only lists the six "real" ones.
  - Both paths POST to the same endpoint (`/api/tag-create`), but the Tag Manager can create tags in categories the inbox can't.

- **`CATEGORY_ORDER` in the frontend does not match the categories currently in the DB**
  - `mediavault.html:706`: `const CATEGORY_ORDER = ['people', 'bands', 'places', 'content_kind', 'topic', 'rarity'];`
  - Live DB has categories: `topic` (25), `content_kind` (19), `bands` (4), `rarity` (4), `scope` (3), `people` (2), `places` (1).
  - `scope` is explicitly removed from the frontend pick list (`mediavault.html:702`-`706`, and `computeWarnings` R4 was removed at line 1182-1184), but three `scope:*` rows remain. The comment says they "render in the 'topic' category via the fallback," but the fallback at `renderPillWall` groups strictly by `t.category`, so scope rows render under a `scope` category block in the "rest" bucket — not under `topic`.
  - `attention_rules.py` still has `CATEGORY_SCOPE = "scope"` and R4 is fully defined at `:101`-`:104`. The Python rules engine will emit `missing_category:scope` for any extension capture with no scope pill; the JS port on the frontend won't. Any caller that runs the Python evaluator (no callers exist today) disagrees with the browser.

- **Inbox save gate disagrees with the attention rules module it claims to mirror**
  - `mediavault.html:1024`-`1039` (`inboxSave`) blocks save when `computeWarnings()` returns any `missing_category:*` warning, AND blocks save when no pill is `on_confident`.
  - `SPEC.md:479`-`488` describes R1-R5 as "soft warnings" — operator can save anyway. `WORKFLOW.md:139` repeats: "Warnings are soft. You can save anyway."
  - The inbox converted soft warnings into hard gates. The frontend comment at `:1024`-`:1028` ("Mike's rule: Items are to remain in INBOX until adequately tagged") records the intent change; the SPEC and WORKFLOW docs were not updated.

- **The inbox "Open URL" button opens the input's current value, not the saved one**
  - `mediavault.html:1007`-`1013` (`openInboxSourceUrl`). Comment is explicit and documents this choice; noting it here because the vault detail's URL chip (line 1818-1824) opens the *saved* `source_url`. Same user action ("click the URL"), two different semantics depending on surface. Both surfaces are intentional; worth seeing as a pair.

- **Vault detail pill clicks commit immediately; inbox pill clicks stage**
  - Inbox: `togglePill` at `mediavault.html:1311` mutates `CURRENT_PILL_STATES` in memory. Nothing hits the server until `inboxSave`.
  - Vault: `toggleTagOnArtifact` at `mediavault.html:1727`-`1744` calls `/api/artifact-update` on every click.
  - This divergence is called out as an unresolved design question in `MEDIAVAULT_V06_8D_DR.md:11`-`70` (Q1.1). Neither surface warns the user about the difference.

- **The inbox pill wall and the vault detail tag list have different visual languages for the same pill**
  - Inbox: five-state pill CSS at `mediavault.html:163-172` (`on-conf`, `on-unc`, `off-sus`, `off-may`, `warn`), grouped by category, clickable-to-cycle.
  - Vault detail: flat `.tagPill` from `mediavault.html:113`-`116`, rendered only for slugs currently on the artifact (`a._tags`), with a `.unselected` dim/strike variant only added client-side after a click. No category grouping.
  - Applied tags appear in completely different visual containers across the two panes. An operator learning the inbox pill vocabulary does not find the same pills represented the same way in the vault.

- **The FB-candidates frontend posts to a GET-only route**
  - `fb_candidates.html:307`: `fetch(SRV+'/api/fb-candidates', {method:'POST', ...})` from `persist()`, which is called after every Accept / Reject / field edit.
  - `core/imgserver.py:1514` registers `/api/fb-candidates` as a GET route only. POST would hit the dispatcher's 404 path at `:1592`.
  - `persist()` catches the failure and toasts "Save failed: ...". In practice: accepting or rejecting a candidate in the FB UI updates in-memory state and UI, but the next refresh loses every change because the server never wrote anything. Observed consequence: the `graduated=true` flag does persist, but only because `handle_intake_from_fb_candidate` in `imgserver.py:500` mutates `fb_candidates.json` server-side when an accepted candidate is sent to the inbox.
  - The real save endpoint is `/api/fb-candidate-save` (`imgserver.py:1543`, `handle_fb_candidate_save` at `:1495`), which expects a full `{candidates: [...]}` array replacement. No frontend calls it.

- **The FB-candidates bookmarklet points at a route that doesn't exist**
  - `fb_candidates.html:467`: bookmarklet opens `http://127.0.0.1:51822/fb-capture?...`.
  - Grep finds `/fb-capture` only in `core/imgserver.py.old_v02:219`. Current `imgserver.py` has no such route.
  - A user clicking the bookmarklet from any Facebook page opens a blank popup talking to a 404.

- **`handle_ping` reports `version: "0.4"` against a v0.6 codebase**
  - `core/imgserver.py:279` returns `{"ok": True, "ts": ..., "version": "0.4"}`.
  - `server_version = "MediaVault/0.5"` at `:1561`, startup banner at `:1606` says `v0.5`. File header comment at `:2` says `v0.4`.
  - No client reads `/ping.version` today; `mediavault.html:2542` only checks `r.ok`. Worth noting because a diagnostic that says "version 0.4" on a v0.6 DB is a cursed debugging aid.

- **`SOURCE_PLATFORM` whitelist is not in sync with the attention rules' social-platform set**
  - `core/imgserver_extensions.py:73`: `{"instagram", "youtube", "facebook", "bandcamp", "press", "local", "other", "reverbnation"}`.
  - `core/attention_rules.py:39`: `SOCIAL_PLATFORMS = {"facebook", "instagram", "tiktok", "reverbnation"}` — includes `tiktok`, excludes everything the extensions validator recognises outside that overlap.
  - `/api/artifact-save` does not validate platform at all — it accepts anything the inbox input accepts.
  - `/api/artifact-register` validates against the extensions set and rejects `tiktok` outright.
  - Two endpoints into the same column, two different opinions about what's valid.

- **Inbox retains `fAuthor` and `fParentId` as hidden inputs for "compat"**
  - `mediavault.html:526-527`. Neither is read anywhere; grep shows only the empty setters in `clearInboxRight`.
  - Per `PHASE_SUMMARY_v05.md:438`, these were kept as hidden empty inputs "for compat with auto-assign flow" during the v0.5 refactor. The auto-assign flow is `inboxSave` at line 1017-1021 (`fId` — not `fAuthor`/`fParentId`). Safe to remove, kept out of caution.

- **`mediavault.html:586`-`593` keeps the old tag picker as `display:none` dead UI**
  - Legacy `tagPicker` / `appliedPills` / `tagInputBox` block. `renderAppliedPills` at `:1103` still runs and writes to `#appliedPills` on every pill change; the element is hidden but the work happens. `setupTagAutocomplete` at `:1455` wires event handlers to an invisible input. No harm, but inbox pill-change latency pays a small tax for nothing.

- **The `/api/artifact-register` endpoint refuses to update existing rows**
  - `core/imgserver_extensions.py:284-293` — 409 on existing id. Contract: register is for new rows only.
  - `fb_candidates.html` doesn't call it. `mediavault.html` doesn't call it. Grep for `/api/artifact-register` returns zero live callers in this codebase.
  - The Chrome extension (out of scope per review prompt) presumably uses it. Noted so a future reader doesn't assume it's dead.

- **Every content field on the inbox form is sent as `null` when blank; the save handler treats `null` as "leave alone"**
  - `mediavault.html:1040-1057`: `source_url: document.getElementById('fSourceUrl').value || null`, `description_short: document.getElementById('fShortDesc').value || null`, etc.
  - `core/imgserver.py:919-921` (UPDATE branch): `if v is None: continue # explicit null from a blank form field — skip`.
  - For a fresh save (INSERT branch at `:933`-`:944`): the same null propagates to `scalar.get(k)`, becomes `NULL` in the column.
  - So on first save, blanks become NULL in the DB. On a resave through demote-edit-save, blanks are treated as "don't overwrite." The behavior differs on path.
  - This is called out explicitly in the code comment (`:893-904`), but the asymmetry between fresh-save and update-save is real: you can set a field to empty only the first time.

---

## Intent ambiguities

- **What is the resolution for the `(slug, category)` schema change?** The migration at `_cowork/v06_phase3_migration.py` executed successfully and the DB now allows composite uniqueness. `PUNCHLIST_v06.md:70`-`98` describes this as a blocker to renaming `author:hunter_root → hunter_root`. But the handler code does not disambiguate by category anywhere. Two plausible reads:
  - The v0.6 cleanup was supposed to delete the `author:*` pills before the composite constraint became load-bearing, so in practice two same-slug rows rarely coexist. The existing `hunter_root`-in-two-categories row is a leftover of the `author:hunter_root → hunter_root` rename, and is the only example in the DB.
  - The schema change was always meant to be followed by a code change (every `WHERE slug=?` query becomes `WHERE slug=? AND category=?`, artifacts store `"category:slug"` or a pair), and that follow-up never got written.
  - Today both readings are consistent with the files on disk.

- **What persistence model do pill states (`pill_states`) actually need?** `SPEC.md:229` names a column that doesn't exist; `mediavault.html:1055` sends data that gets dropped; `PHASE_SUMMARY_v05.md` claims this shipped; `MEDIAVAULT_V06_8D_DR.md:10-67` explicitly re-opens the question ("when does a click become real?") with four options. The code's answer to that question is currently "tags only, `on_confident` and `on_uncertain` collapse to the same bit." Whether that is a bug (missing column) or a design simplification (states were abandoned, docs didn't catch up) is not determinable from the code alone.

- **Is `is_proposed` alive or dead?** Schema column still exists; `handle_tag_accept` still works; `is_proposed=1` can still be set by the enrich path and by register. But the Vocab Admin UI was stripped of the ACCEPT/REJECT column (`mediavault.html:2116`) and `pillHtml` was updated to ignore the flag visually. The backend still treats the concept as real; the UI treats it as obsolete. Either the column should be dropped or the UI should re-surface it. Today no row has `is_proposed=1`, so the decision has no user-visible cost yet.

- **What should `status='keep'` mean long-term?** The v0.6 comment at `imgserver.py:953` treats `keep` as "saved to vault, not released, queue row retained for ingest-dedup." The v0.5 `PHASE_SUMMARY_v05.md:202` treats `approved` as the analogous state for the release path. `loadQueue` hides both. `ingest_engine.process()` only acts on `approved`, not `keep`, so the two paths diverge on whether a saved-but-not-released item gets a thumbnail. Either all saves should move to the same status, or `process()` should act on both.

- **`scope` — is it retired or just hidden?** `mediavault.html:702-706` comment says yes-retired with fallback; `attention_rules.py:39,:101` still uses it; three `scope:*` rows remain in live DB. The frontend ships R4 code commented out; the Python module still implements R4. If any future integration (extension, batch enrichment, schedule task) runs the Python rules engine, its answer for R4 will disagree with the browser's.

- **What is the intended separation between `imgserver.py` and `imgserver_extensions.py`?** The header comment at `imgserver_extensions.py:1-49` treats extensions as a module that extends imgserver without modifying it. At the time (v0.2), that made sense: `handle_artifact_register` was the extension for non-image ingest. In v0.5 the file was rewritten in place (per `PHASE_SUMMARY_v05.md:291-354`), so the "never modify" promise is already broken. The current split is arbitrary: two of the extensions module's functions (`handle_artifact_register`, `handle_asset_raw`) could equally live in imgserver, and imgserver's `handle_thumbgen`/`handle_image_raw` could equally live here. The boundary keeps the extensions module import-free of imgserver (hence duplicate slugify, duplicate enum whitelists) — that's the only remaining architectural signal, and it's load-bearing only if that import-freedom is still a goal.

---

## Things that look deliberate and correct

- **`handle_artifact_save`'s distinction between "caller didn't mention this field" (preserve) and "caller sent null/empty" (skip) on the UPDATE branch** — `core/imgserver.py:893-922`. This comes with a long, accurate comment explaining why the alternative catastrophically broke MV-HR-20260405-003 in 8d testing. The logic is subtle; the ledgering is appropriate.

- **`_upgrade_v04_enrichment_to_pill_states` defensive lift** — `core/imgserver.py:654-671`. Backward compat for v0.4-era `tags_known`/`tags_proposed` blobs that still sit in the `ingest_queue.enrichment_json` column. Idempotent, and called both on read and on write so a single v0.4 row flows through the v0.5 UI without needing a migration.

- **The startup order in `mediavault.html:2570-2577`** — `loadTags` explicitly runs before `loadQueue` and `loadDb` because the pill-wall renderer is sensitive to an empty `TAG_LIST`. The comment at `:2563-2569` describes the exact failure mode this avoids (pills ghosting into `__uncategorized__` on the first render).

- **The single-scroll layout in `#inboxRight`** — `mediavault.html:73-82`. Explicit comment rejects an earlier dual-scroll design and explains the UX reason (Mike saw both scrollbars and asked "Dbl scroller?"). Worth preserving.

- **The partial unique index for `(slug, NULL)`** — `_cowork/v06_phase3_migration.py:171-174` creates `idx_tags_slug_when_null_cat`, because SQLite's composite UNIQUE considers NULLs distinct (so `(slug, NULL)` pairs would not otherwise be unique). A reader who hasn't tripped over this SQLite quirk might see the partial index as redundant — it isn't.

- **`handle_asset_raw` range support** — `core/imgserver_extensions.py:385-425`. Implements HTTP Range for `<audio>` scrubbing, an actual requirement surfaced by the renderer's audio widget. The minimal implementation is correct and worth not simplifying.

- **Path-safety gate on every asset-serving route** — `ALLOWED_ASSET_ROOTS` in `imgserver.py:204` and `ASSET_ROOTS` in `imgserver_extensions.py:66-68`. Both refuse anything outside `C:\AI\`. The duplication is intentional (extensions module stays import-free) and the values match.

- **`PRAGMA foreign_keys=ON` in `db_conn()`** — `imgserver.py:79`. `artifacts.parent_artifact_id → artifacts.id ON DELETE CASCADE` only behaves that way if foreign keys are enabled per-connection; SQLite defaults to OFF. This is the one line that makes the delete-cascades-children behaviour real.

- **The comment block at `core/imgserver.py:864-875`** — documents why `handle_artifact_save` previously crashed on demote-then-save (SQLite evaluates NOT NULL before PK UNIQUE, which is why the error surfaced as `created_at` rather than a PK collision). Future readers will thank whoever left this.

- **`ingest_queue` uses `status='failed'` for both scrapped-and-moved and approved-and-moved rows** — `core/ingest_engine.py:575,681`. On first read this looks wrong (successful moves recorded as failures). But the combination `status='failed'` + `error_message='file-moved'` is the engine's "terminal state, no further action" marker, and the two statuses the frontend cares about (`pending`, `enriched`) stay clean. The naming is unfortunate; the mechanism is consistent.

