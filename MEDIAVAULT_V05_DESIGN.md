---

> **SUPERSEDED IN PART — 2026-04-19**
>
> Sections §§2, 3.4, 3.5, 4.1, 4.4, 6 contain historical design rationale
> that no longer reflects current behavior. For current behavior, read
> `SPEC.md` and `_cowork/DECISIONS_2026-04-19_pill_states_and_friends.md`.
>
> The rest of this document is preserved as a record of v0.5 design thinking,
> valid in its moment.

---

# MediaVault v0.5 — Design Document

**Decision:** Targeted UX reconstruction. Schema almost unchanged. Inbox reworked
around pills-as-a-view-onto-facts. Vocabulary curated, not re-migrated.

**Date:** 2026-04-19
**Agent:** Claude (web session, handing to cowork)
**Status:** Design locked pending operator sign-off on §9 merge list.
**Supersedes:** v0.4 design (shipped 2026-04-17).
**Grounded in:** `_cowork/mv_v05_audit_20260419_170757.md` — every number in this
document comes from that audit, not memory.

---

## 1. The model correction

v0.4 shipped with the model "tags are data." v0.4 was wrong.

Tags are a **UI view onto facts**. The pill is the contract with the operator.
What's stored underneath is implementation detail.

This reframes the inbox: it is not a data-entry form, it is a **triage
surface**. The operator asks three questions and nothing else:

1. Do the ON pills look right and complete for how I'd find this again someday?
2. Do the OFF-but-shown pills trigger an "oh yeah, that too" reaction?
3. Are all WARNING pills resolved?

Yes / yes / yes → ship.

**The "would I search for this someday" test is what gives a pill the right to
exist.** Named people, bands, places, content types, years, venues — these
pass. Visual details like `striped_shirt`, `long_hair`, `brick_wall` fail.
Cheech and Chong passes because it's Cheech and Chong; Joe and some other guy
doesn't.

The audit surfaced that v0.4's enrichment was permissive enough to create all
three of `striped_shirt`, `long_hair`, and `brick_wall` as accepted tags. The
fix is not a re-migration. It's (a) a tighter enrichment prompt going forward,
and (b) a one-shot curated cleanup that the operator reviews before it runs.

---

## 2. Five pill states (inbox) vs. tri-state (vault)

The inbox pill has **five states**. The vault filter pill has **three**. Same
underlying fact, different display job.

### 2.1 Inbox pill states

| State | Meaning | Look |
|---|---|---|
| `ON-confident` | Enrichment is sure this applies. | Filled gold. No outline. |
| `ON-uncertain` | Enrichment thinks yes, wants a glance. | Filled gold, dashed outline. |
| `OFF-suspected` | Strong hint; not applied unless the operator clicks. | Empty, gold outline, gold text. |
| `OFF-maybe` | Weak hint; still shown because the category is relevant. | Empty, dim outline, dim text. |
| `WARNING` | An expected category is empty. Resolve before saving. | Red outline, red bolt icon, pulsing. |

Clicking `ON-*` turns it OFF. Clicking `OFF-*` turns it `ON-confident`
(operator override — the moment the human chooses it, it's confirmed).
Warnings disappear when the condition that produced them is satisfied.

### 2.2 Vault filter states (unchanged from v0.4)

| State | Meaning |
|---|---|
| `off` | Don't care. |
| `MUST` | Artifact must carry this tag. |
| `MUST NOT` | Artifact must not carry this tag. |

Clicking cycles `off → MUST → MUST NOT → off`.

### 2.3 Why two display models?

Inbox and vault do different work. Inbox is *curation* — did the AI get it
right, and what's missing? Vault is *retrieval* — narrow this haystack down.
Retrieval doesn't need five states; it needs fast boolean combinators. Curation
needs nuance — "I'm sure about this," "I'm guessing about this," "this is
missing and you should care."

The data underneath is the same: `artifacts.tags` JSON array, plus a per-queue
`enrichment_json` blob that carries confidence annotations. No schema change
for the pill model.

---

## 3. Schema changes

Schema is **almost unchanged from v0.4**. Three edits, zero migrations of
artifact-level data beyond a column drop and a value migration.

### 3.1 Drop `tags_permission` (vestigial v0.2 column) — no migration

Audit §5: column exists, 36 rows populated, one distinct value: `not-requested`.

**Drop the column without migrating the signal.** Operator ruling: if
permissions ever become a real workflow, they'll need more structure than a
single pill (who was asked? when? what did they say?), and the current
one-value column doesn't give us that. Preserving it as a pill would add a
category that never answers a search question. Clean drop.

`permission_contact` and `permission_evidence_path` are also dropped (0 rows
each per audit §5 — pure dead weight).

### 3.2 Drop `author_name` column, migrate to pills

Audit §12: 18 rows populated, 5 distinct values. Distribution:

- `Hunter Root` × 13
- `ElmThree Productions` × 2
- `hunterrootofficial` × 1
- `(1) Video` × 1
- `(2) Video` × 1

`(1) Video` and `(2) Video` are junk — they're Facebook's "1 video / 2 videos"
UI labels scraped as author names. Drop those values at migration. The other
three map cleanly to `author:hunter_root`, `author:elmthree_productions`,
`author:hunterrootofficial`.

**Why the `author:` prefix:** `hunter_root` already exists as a band pill
(the band Hunter Root plays in). `author:hunter_root` is a distinct pill
meaning "Hunter Root is the credited author of this artifact." Author pills
use the `author:` prefix in the slug. Display name drops the prefix. The
vocabulary table's `category='people'` groups them visually with other
people pills (currently just `nick_root`).

So the 13 rows with author "Hunter Root" get the `author:hunter_root` pill
appended. The 2 ElmThree rows get `author:elmthree_productions`. The 1
hunterrootofficial row gets `author:hunterrootofficial`. Operator may
later merge author pills in Vocab Admin if desired (e.g.,
`author:hunterrootofficial` → `author:hunter_root` if they agree that's
the same identity); v0.5 does not auto-merge, respecting the operator's
explicit arm's-length stance around identity conflation.

### 3.3 Add `tags.category` and rename `group_name`'s meaning

The audit shows `group_name` on v0.4's `tags` table was used for **mutual
exclusion** — 6 tags have it set, dividing into `preservation` (`standard`,
`critical`) and `rarity` (`common`, `notable`, `rare`, `unique`).

v0.5 wants `group_name` to mean **visual grouping** (people / bands / media
type / places / content type / era). These are two different concerns and
trying to overload one column confused v0.4's picker into showing everything
ungrouped.

**Split into two columns:**

- `category` TEXT NULLABLE — browsing group. Values: `bands`, `people`,
  `places`, `content_kind`, `topic`, `scope`, `rarity`, or NULL. Display-only.
  Nothing in code constrains which categories may exist; new ones can be
  added by setting `category='<new_name>'` in Vocab Admin. See §9.1 for the
  question each category answers.
- `is_exclusive` INTEGER DEFAULT 0 — when 1, pills in the same `category`
  behave as radio buttons (one-of). Replaces v0.4's implicit exclusivity via
  `group_name`.

`group_name` column is removed. Old values migrate: tags with `group_name=
'rarity'` get `category='rarity'` and `is_exclusive=1`. Tags with
`group_name='preservation'` are deleted outright (§9.3) — the whole
preservation concept is retired.

All other tags start with `category=NULL` and `is_exclusive=0`. The cleanup
script (§9.5) assigns categories during its pass. Vocab Admin lets the
operator change category at any time.

### 3.4 Add `enrichment_json.pill_states` convention

No schema change. The inbox reads pill confidence from a documented structure
inside `enrichment_json`:

```json
{
  "description_short": "...",
  "pill_states": {
    "hunter_root":         "on_confident",
    "live_show":           "on_confident",
    "venue:musikfest":     "on_uncertain",
    "2024":                "off_suspected",
    "concert":             "off_maybe"
  },
  "warnings": ["missing_category:people"],
  ...
}
```

When an artifact is saved to vault, pills with state `on_confident` or
`on_uncertain` or any operator-overridden state become entries in
`artifacts.tags`. Everything else is discarded. The `pill_states` blob itself
is kept on the queue row only; it does not persist past save.

Audit §10 key-name inventory: no existing queue enrichment uses `pill_states`
or `warnings`, so there is no collision to resolve.

### 3.5 Final v0.5 schema

```sql
-- artifacts: one row per thing worth cataloging
CREATE TABLE artifacts (
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

    parent_artifact_id      TEXT REFERENCES artifacts(id) ON DELETE CASCADE,
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
    -- author_name DROPPED in v0.5; values migrated to author:* pills.

    tags                    TEXT NOT NULL DEFAULT '[]',   -- JSON array of slugs

    -- tags_permission DROPPED in v0.5 without migration (see §3.1).
    -- permission_contact DROPPED in v0.5 (0 rows on disk).
    -- permission_evidence_path DROPPED in v0.5 (0 rows on disk).
    -- confidence_flags stays; still 0 rows but reserved for future attention signals.

    confidence_flags        TEXT,
    notes                   TEXT,
    created_at              TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at              TEXT NOT NULL DEFAULT (datetime('now'))
);

-- tags: vocabulary
CREATE TABLE tags (
    slug            TEXT PRIMARY KEY,
    display_name    TEXT NOT NULL,
    description     TEXT,
    category        TEXT,                  -- renamed from group_name; browsing label
    is_exclusive    INTEGER NOT NULL DEFAULT 0,
    is_proposed     INTEGER NOT NULL DEFAULT 0,
    usage_count     INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Unchanged:
--   id_sequence       — per-day MV-YYYYMMDD-NNN counter
--   ingest_queue      — status ∈ {pending, keep, skip, enriched, approved, failed}
```

### 3.6 What is deliberately NOT changed

- `artifacts.id` format. Legacy `MV-HR-*` IDs remain as-is (62 rows, per
  audit §9). New IDs continue using `MV-YYYYMMDD-NNN` (audit §11 shows
  MV-20260419-001 through -004 already exist).
- `link_status`. 76 rows populated with `live` or `local-only`. Active signal.
  Keep.
- `media_type`. 73 rows populated. Drives renderer dispatch. Keep.
- `post_date_confidence`. 80 rows populated. Legitimate signal. Keep.
- `capture_date`. 76 rows populated. Keep.
- `confidence_flags`. Empty everywhere but semantically reserved for
  field-level warnings (distinct from pill-level warnings). Keep.

---

## 4. Inbox reworked

### 4.1 The triage layout (top to bottom, priority order)

```
┌─ Top action bar ──────────────────────────────────────────────────┐
│  ← prev   [dropdown: which queue item]   next →    2 of 25        │
│                                                                   │
│  [✗ SCRAP]              [✓ SAVE]   [★ SAVE & RELEASE]             │
└───────────────────────────────────────────────────────────────────┘
┌─ Viewer (image / video / URL preview) ──────────────────────────┐
│                                                                 │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
┌─ Pill wall (grouped, collapsible) ──────────────────────────────┐
│  BANDS (2 on, 1 suspected)                                      │
│    [Hunter Root] [Medusa's Disco]  ·  ⟨Run With The Hunt⟩       │
│                                                                 │
│  ⚠ PEOPLE — likely missing                                      │
│    ⟨author:elmthree_productions⟩                                 │
│                                                                 │
│  CONTENT_KIND (0 on, 2 maybes)                                  │
│    ⟨Live Show⟩ ⟨Tour Announcement⟩                               │
│                                                                 │
│  PLACES (1 on)                                                  │
│    [Lancaster PA]                                                │
│                                                                 │
│  SCOPE (empty, collapsed) ▸                                     │
│                                                                 │
│  RARITY (1 on, exclusive)                                       │
│    [Notable]  ·  ⟨Common⟩ ⟨Rare⟩ ⟨Unique⟩                        │
│                                                                 │
│  UNCATEGORIZED                                                  │
│    [fan] [acoustic]                                              │
│                                                                 │
│  [people ▼] [+ type to add a pill         ] Enter               │
└─────────────────────────────────────────────────────────────────┘
┌─ Storage & dates (collapsed; click to expand) ──────────────────┐
│  ▸ media_type: photo    ▸ storage: vaulted    ▸ post: 2025-10-10│
└─────────────────────────────────────────────────────────────────┘
┌─ Descriptions (collapsed by default) ───────────────────────────┐
│  ▸ Short  ▸ Long  ▸ Extracted text  ▸ Notes  ▸ Source URL       │
└─────────────────────────────────────────────────────────────────┘
```

Legend: `[filled]` = ON-confident, `[filled+dashed]` = ON-uncertain,
`⟨outline⟩` = OFF-suspected, `⟨dim⟩` = OFF-maybe, `⚠` = WARNING.
Empty categories collapse to a single `▸` line.

### 4.2 Changes from v0.4's inbox layout

Audit §14a established the v0.4 section order: `Identity → Source → Dates →
Storage → Tags → Structure`. Each section currently appears as a `.sectionHead`
in the right panel. Action bar is at the bottom (line 354).

v0.5 reorders around attention:

| v0.4 order | v0.5 order | Rationale |
|---|---|---|
| Action bar at bottom | **Top action bar, always visible** | Actions are the reason the screen exists. They should be reachable at any scroll position. |
| ID field at top of Identity | **Hidden in inbox** | Audit §11 shows IDs like `MV-20260419-001` — machine keys, unparseable to a human. Shown muted in vault detail only. |
| Identity section first | **Pill wall first**, descriptions below | Pills are the triage signal; descriptions are context. Operator sees pills, decides, maybe expands descriptions. |
| Structure section (free-text parent input, line 351) | **Removed from inbox entirely** | Parent linking belongs in vault detail where the operator can actually see candidate parents. |
| Author field (line 282) | **Removed from inbox** | Becomes a pill (§3.2). |
| Storage section | **Kept but collapsed** | Audit §11 shows 60 referenced + 20 vaulted. Storage mode matters, but defaults are usually right. Collapsed unless abnormal. |
| Dates section | **Kept but collapsed** | Same logic. Post date matters but usually the enrichment nails it (`post_date_confidence='extracted'` on 80 rows per audit §5). |
| Tag picker (applied pills + autocomplete + browse) | **Pill wall with grouped categories, 5 states** | The main UX rebuild. |

### 4.3 Pill categories and their priority order

Categories appear top-to-bottom in the pill wall in this fixed order. Priority
is "how often the operator needs to check/fix this category" — highest first.
Each category answers exactly one question (§9.1 spells out which).

1. **bands** — which band is this? Most-used category in this archive;
   correction most common here (misidentification between HR solo and
   predecessor bands).
2. **people** — which named person is this? Includes `author:*` pills.
3. **content_kind** — what kind of artifact is this? The operator's
   primary search axis for "find me all tour announcements."
4. **places** — what physical place is this?
5. **topic** — what is this about?
6. **scope** — which of my personal worlds can claim this? `personal`,
   `family`, `fan`.
7. **rarity** — how rare? Exclusive (one value).
8. **uncategorized** — any pill without a category, including all the
   surviving-but-uncategorized slugs from v0.4. Operator categorizes (or
   deletes) from Vocab Admin at leisure.

Collapsed categories show a one-line summary ("BANDS — 2 on, 1 suspected"),
expandable with a click. On first inbox entry all categories start expanded;
after save they remember their collapsed state per operator preference in
`localStorage`. Empty categories (no pills and no warnings) are hidden
entirely — don't clutter the wall with empty sections.

`media_type` is **not** in the list — it's a column, rendered as a fixed
control in the collapsed Storage section below the pill wall. Driving
renderer behavior is different work from "search by pill."

### 4.4 Adding pills — one global control

Below the pill wall, a single add-pill control:

```
[category ▼] [type slug here                          ] [Enter]
```

- Category dropdown: the 7 categories plus "uncategorized" (default).
- Text input: slugifies on Enter. If the slug exists in vocabulary, pill
  applies as `on_confident`. If novel, vocabulary row created with
  `is_proposed=1` and `category` set to the dropdown's value, pill applies
  as `on_confident` with dashed border until accepted in Vocab Admin.

One control. Not per-section. Keeps the wall clean and the add-flow
unambiguous — operator picks category, types slug, done.

### 4.5 Required-pill rules (hardcoded, v0.5)

Start with five rules. They produce WARNING pills when their condition fires
and the category is empty. Warnings are soft — operator can save anyway;
warning just glows.

| Rule | When fires | Warning |
|---|---|---|
| R1 | `source_platform` is a social platform (facebook, instagram, tiktok, reverbnation) and `post_date` is NULL | Field-level warning on the date control (not a pill) |
| R2 | `media_type` is photo or video, and the artifact is top-level (no parent) | Warn: `missing_category:content_kind` |
| R3 | Description mentions names in title-case (heuristic: capitalized bigrams) and zero `people` or `bands` pills are on | Warn: `missing_category:people_or_bands` |
| R4 | `ingest_source` is `extension-capture` and zero `scope` pills are on | Warn: `missing_category:scope` |
| R5 | Artifact has any pill at all but `media_type` column is null | Field-level warning on media_type control |

Rules live in `core/attention_rules.py` as a small module. Single function:
`evaluate_rules(artifact_fields, pill_states) -> list[warning_slug]`. No DB
table, no admin UI. Adding a rule is a code edit. YAGNI on the rules table.

---

## 5. Vault — small additions

Vault is mostly unchanged. Filter bar, grid/table toggle, detail panel, badges
all work. The audit §14 confirms the tri-state pill logic at line 869. Keep
all of that.

### 5.1 New: "Attach to parent" in detail panel

Replaces the inbox free-text parent input (v0.4 line 351, removed). In vault
detail, a single button: `[⇪ ATTACH TO PARENT]`. Click opens a modal with:

- Text search box (searches `description_short`, `description_long`,
  `source_url`, `id`).
- Live-filtered list of candidate parents: thumbnail, short description,
  source platform, post date. Clicking one sets `parent_artifact_id`.
- Filter excludes the current artifact and any descendant of it (no cycles).
- "Detach from parent" button if `parent_artifact_id` is already set.

Backend: reuses `/api/artifact-update` with `{parent_artifact_id: "..."}`.
Already exists, already works. No new endpoint.

### 5.2 New: Vocab Admin merge tool

v0.4 Vocab Admin has Accept / Rename / Reject (three-way) / Edit / Delete.
v0.5 adds **Merge** as a primary verb.

Merge UI:
- Source tag (the one going away).
- Target tag (the one absorbing the source's usage).
- Preview: "N artifacts currently carry `<source>`. After merge, those N will
  carry `<target>` instead."
- Confirm → backend does: for every artifact whose `tags` JSON contains
  `source`, replace `source` with `target` (and dedupe). Decrement
  `source.usage_count`, increment `target.usage_count`. Delete the `source`
  row.

Backend: new endpoint `POST /api/tag-merge` — `{source_slug, target_slug}`.

### 5.3 New: Vocab Admin bulk delete

Selection checkboxes on each vocab row. Multi-select. `[DELETE SELECTED]`
button acts as v0.4's single-row delete loop. Refuses to delete any row with
`usage_count > 0` (same rule as today, per audit's dump of
`handle_tag_delete` at line 1217).

Backend: new endpoint `POST /api/tag-bulk-delete` — `{slugs: [...]}`.

---

## 6. Enrichment prompt rewritten

The new prompt enforces the "would I search for this someday" test and emits
per-pill confidence.

```
You are cataloging an artifact for Mike's personal creative archive
("MediaVault"). Your job is to propose pills — short tags that help Mike
re-find this artifact later when he's browsing by topic, not by ID.

A pill earns its place by answering YES to:

    Would Mike plausibly want to locate this artifact again by this fact?

PASS: named people (Hunter Root, Carsie Blanton); bands; venues (Musikfest,
    Bearsville Theater); cities; content types (live_show, tour_announcement,
    song_page, poster); years; album/song titles.

FAIL: visual details (striped_shirt, long_hair, brick_wall, red_bandana);
    generic descriptors that are better left to description_long
    (acoustic_performance when there's already live_show); adjectives
    (beautiful, bright); anonymous subjects ("Joe and some other guy" — skip
    him; "Cheech and Chong" — keep them).

Categories (use to place pills; see below for the question each answers):
    bands, people, places, content_kind, topic, scope, rarity.

What each category is for:
    bands        — which band is this? (Hunter Root, Medusa's Disco)
    people       — which named individual? (author:* pills live here)
    places       — what physical place? (lancaster_pa)
    content_kind — what kind of artifact? (live_show, poster, tour_announcement,
                   music_video, fan_art, memorabilia)
    topic        — what is this about? (songwriting, lyme_disease)
    scope        — which of Mike's worlds can claim this? (personal, family, fan)
    rarity       — how rare? exclusive; one of common/notable/rare/unique.

Do NOT propose:
    - year pills (post_date is a separate field below)
    - song titles (find-via-search, not pills)
    - genre pills (out of scope for this archive)
    - preservation pills (retired concept)

Evidence provided:
    Source URL:         {source_url}
    Source platform:    {source_platform}
    Capture date:       {capture_date}
    Existing pills:     {existing_tags_comma_separated}
    Existing desc:      {description_short}
    Extracted text:     {extracted_text}
    Images (if any):    {N attached}

Existing vocabulary (slugs + display names you may reuse):
    {vocab_list}

Return ONE JSON object:

    {{
      "description_short": "one sentence",
      "description_long": "2-4 sentences with detail",
      "post_date": "YYYY-MM-DD or null",
      "post_date_confidence": "extracted|manual|estimated|unknown",
      "media_type": "photo|video|audio|link|text|mixed|other",

      "pill_states": {{
        "<slug>": "on_confident" | "on_uncertain" | "off_suspected" | "off_maybe"
      }},

      "warnings": ["missing_category:<name>"],
      "notes": "anything unusual"
    }}

Rules:
- `on_confident`: the evidence directly supports this pill (the image
  shows the band, the URL is the artist's page, etc.).
- `on_uncertain`: the evidence suggests this pill but you want Mike to
  eyeball it.
- `off_suspected`: this pill probably applies based on context, but the
  evidence isn't in-frame enough to commit. Show it so Mike can click it.
- `off_maybe`: weaker hint. Show it only if it's a useful prompt.
- Do NOT propose visual-detail pills. If you notice a striped shirt, put
  it in `description_long`, not in pills.
- Prefer vocabulary slugs. If a novel slug is clearly needed, put it in
  `pill_states` anyway — the system auto-creates it as proposed.
```

Differences from v0.4's prompt (audit has the v0.4 blob in §10; key names
inventoried in §10 end):

- v0.4 emitted `tags_known` and `tags_proposed` as flat arrays. v0.5 emits a
  single `pill_states` map keyed by slug.
- v0.4 had no confidence concept. v0.5 has four confidence tiers.
- v0.4 had no concept of "off-but-shown" pills. v0.5 uses `off_suspected` and
  `off_maybe` to populate the pill wall with clicks-away suggestions.
- v0.4 prompt had no "would Mike search for this" test. v0.5 leads with it.
- v0.4 prompt accepted visual-detail pills implicitly. v0.5 explicitly forbids
  them.

Backward compatibility: the 23 existing queue rows have enrichments in v0.4
format. v0.5's queue-row populator reads both formats. When `pill_states` is
absent but `tags_known`/`tags_proposed` are present, every known tag becomes
`on_uncertain` (conservative — force operator to confirm) and every proposed
tag becomes `on_uncertain` as well. No data is lost.

---

## 7. Bug fix: `/api/artifact-save` with `release_immediately`

Audit §8a shows no stuck data in production: zero rows with `status='pending'`
and `artifact_id IS NOT NULL`. The released-in-inbox bug is real in the code
path but hasn't produced corrupt data yet.

Audit §15 shows the handler's one reference to `release_immediately` is at
line 692 of `imgserver.py`:

```python
release_now = bool(body.get("release_immediately"))
```

The fix: when `release_now` is True, `handle_artifact_save` must also issue
`DELETE FROM ingest_queue WHERE queue_id=?` or `UPDATE ingest_queue SET
status='approved', artifact_id=?` before returning. Audit §15 shows both
statement shapes are already present in `imgserver.py`, so this is a
one-line-of-logic fix, not new machinery.

**No data migration needed** (audit §8a confirms). Just fix the code.

---

## 8. Bug fix: `imgserver_extensions.py`

Audit §13 dumps the file in full. Two handlers:

- `handle_artifact_register` — broken against v0.4 schema. References
  `domain`, all 10 old `tags_*` columns, `tags_preservation`. Audit §5
  confirms `tags_preservation` never existed on disk; `domain` was dropped
  at v0.4 migration.
- `handle_asset_raw` — schema-agnostic. Serves files. Works today.

`handle_artifact_register` gets rewritten to match the v0.4+ schema:

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
) VALUES (...)
```

`tags` comes in as a JSON array (matching the column). `tags_*` per-category
params are dropped from the request schema. `domain` is dropped from the
request schema. `_next_artifact_id()` is rewritten to use `MV-YYYYMMDD-NNN`
via the v0.4 `id_sequence` table (audit §3 shows the schema: `date_str PK,
last_seq INTEGER`).

`DOMAIN_ENUM` and the per-domain prefix mapping are deleted.

`handle_asset_raw` is untouched.

Audit §16 confirms `/api/artifact-register` is not called by the frontend.
It's called externally — by the WB Capture Chrome extension and the
ReverbNation preservation pipeline (per Mike's memory file). Fixing it
restores those integrations.

---

## 9. Vocabulary cleanup — the specific merge list

The audit's §6 is the full 106-tag vocabulary sorted by usage. §7 surfaced
only one obvious bucket (`medusasdisco`/`medusas_disco`). That's a weakness
of stem-only matching. Reading the full list yields the actual mess.

**This list is your review gate before cowork runs any cleanup.** If you
disapprove anything, say which and I amend before deploy.

### 9.1 Categories — the 8 buckets and the question each answers

Every category earns its place by answering one specific question an operator
would ask of an artifact. No question → no category.

| Category | Question | Exclusive? |
|---|---|---|
| **bands** | Which band is this? | No (one show, two bands) |
| **people** | Which named person is this? | No |
| **places** | What physical place is this? | No |
| **content_kind** | What kind of artifact is this, structurally? | No |
| **topic** | What is this about? | No |
| **scope** | Which of my personal worlds can claim this? | No |
| **rarity** | How rare is this in my collection? | **Yes** |

Categories deliberately NOT created, and why:

- **`era`** / year pills — dates live in the `post_date`, `capture_date`,
  `ingest_date` columns. The vault filter bar has a date-range picker
  (audit §14 confirms). Year-as-pill is v0.2 legacy; deleted in §9.3.
- **`songs`** / **`albums`** — too fine-grained. Finding a specific song's
  material goes through full-text search against `extracted_text` and
  `description_long`. Operator ruling: "Relating to albums and songs as a
  tag is too detailed. Find it via search."
- **`genre`** — not worth the classification work for an archive built
  around 2-3 acts in the same sonic neighborhood. Operator ruling. The 11
  genre slugs in v0.4 get deleted in §9.3.
- **`preservation`** — `standard` on 76 artifacts and `critical` on 1 conveys
  no information because "everything is standard" means the tag does no
  work. Deleted in §9.3. If preservation-level becomes a real workflow it
  gets a column, not a pill.
- **`permission`** — the column `tags_permission` had one value
  (`not-requested`) on 36 rows. Dropping the column is enough; no pill
  migration (see §3.1 — the pill-migration step is removed from Phase 1).
- **`media_type`** — is a column, not a pill category. It drives the
  renderer (`<img>` vs `<audio>` vs `<video>`). Inbox exposes it as a
  fixed-option control; vault filter has it as a dropdown.

### 9.2 Merges — source → target

| # | Source slug | Target slug | Reason | Uses |
|---|---|---|---|---|
| 1 | `hunter` | `hunter_root` | Same person, fragmented. Audit §6: 31 vs. 77. | 31 → adds to 77 |
| 2 | `medusasdisco` | `medusas_disco` | Stem dup. Canonicalize to the spaced form (matches `hunter_root` convention). | 6 → adds to 1 |
| 3 | `runwiththehunt` | `run_with_the_hunt` *(create new)* | Same fix as #2. Target slug does not exist; cleanup creates it. | 33 → moves |
| 4 | `pre_solo_run_with_the_hunt` | `run_with_the_hunt` | "Pre-solo" is provenance, not a search-worthy fact. Every RWTH artifact is pre-solo by definition. | 33 → merges |
| 5 | `pre_solo_medusas_disco` | `medusas_disco` | Same reason as #4. | 6 → merges |
| 6 | `hunterroot2` | `hunter_root` | Duplicate Instagram handle reference. | 2 → merges |
| 7 | `audio_audio_file` | `audio` | Ingest-provenance leakage — `audio/audio-file` was a v0.2 `tags_content_type` value. | 15 → merges |
| 8 | `audio_metadata_json` | `audio` | Same leakage. | 13 → merges |
| 9 | `mp3_only` | `audio` | Phase 2 workflow marker, not search-worthy. | 26 → merges |
| 10 | `reverbnation_artist_page_metadata_json` | `reverbnation` | Composite slug from ingest. | 3 → merges |
| 11 | `reverbnation_artist_page_page_save_html` | `reverbnation` | Composite slug from ingest. | 3 → merges |
| 12 | `reverbnation_song_page_lyrics_txt` | `reverbnation` | Composite slug from ingest. | 2 → merges |
| 13 | `reverbnation_song_page_metadata_json` | `reverbnation` | Composite slug from ingest. | 2 → merges |
| 14 | `reverbnation_song_page_page_save_html` | `reverbnation` | Composite slug from ingest. | 2 → merges |

Note: `hunterrootofficial` as an author value from §3.2 author migration
creates a new pill `author:hunterrootofficial`. Operator may later choose
to merge that into `author:hunter_root` via Vocab Admin. Not auto-merged
here — different surface (Instagram handle vs. stage name) and the operator
explicitly flagged arm's-length caution around identity conflation.

### 9.3 Deletions

All pills listed here are stripped from every artifact's tags array and
then removed from the vocabulary.

**Dead weight — "standard" applied to everything:**

| Slug | Uses | Reason |
|---|---|---|
| `standard` | 76 | Applied to every artifact. Conveys no information. |
| `critical` | 1 | The preservation-level workflow was never built. |

**Year pills (duplicates the date columns):**

| Slug | Uses | Reason |
|---|---|---|
| `2019` | 1 | `post_date`, `capture_date`, `ingest_date` are columns. |
| `2022` | 2 | — |
| `2023` | 4 | — |
| `2024` | 2 | — |
| `2025` | 21 | — |
| `2026` | 1 | — |

**Visual-detail pills (fail the "would I search for this someday" test):**

| Slug | Uses | Reason |
|---|---|---|
| `striped_shirt` | 1 | Visual detail. |
| `long_hair` | 1 | Visual detail. |
| `brick_wall` | 1 | Visual detail. |
| `brick_wall_background` | 1 | Visual detail. |
| `original_music` | 1 | Meaningless — almost everything is original music. |

**Song titles (operator ruling: find via search, not pills):**

| Slug | Uses |
|---|---|
| `town_rat_heathen` | 3 |
| `quicksand_sinking` | 2 |
| `dreaming_up_ways_of_gettin_outta_this_hellhole` | 2 |
| `hellhole_perspective_rubble_lyrics` | 2 |
| `my_brothers_bones` | 1 |
| `crooked_home` | 1 |

**Genres (operator ruling: out of scope for a 2-3-band archive):**

| Slug | Uses |
|---|---|
| `rock` | 7 |
| `acoustic` | 2 |
| `jam` | 5 |
| `grunge` | 5 |
| `psychedelic` | 5 |
| `blues` | 2 |
| `singer_songwriter` | 3 |
| `acoustic_rock` | 5 |
| `psychedelic_rock` | 1 |
| `indiefolk` | 2 |
| `alternative` | 5 |

**Overly generic / redundant with content_kind or media_type:**

| Slug | Uses | Reason |
|---|---|---|
| `show` | 21 | Redundant with `live_show` and `media_type`. |
| `song` | 2 | Redundant with `media_type=audio`. |
| `performance` | 1 | Redundant with `live_show`. |
| `quote` | 1 | Too generic at one use. |
| `lyric` | 1 | Too generic at one use. |
| `venue` | 11 | Meta-label ("this is a venue"). Specific places go in `places`. |

**Workflow provenance (how it arrived, not what it is):**

| Slug | Uses | Reason |
|---|---|---|
| `phase2_recovery` | 26 | Ingest workflow marker. |
| `mp3_only` | *merged in #9* | After merge, zero uses, delete. |

### 9.4 Vocabulary creates (new pills introduced)

| Slug | Category | Why now |
|---|---|---|
| `run_with_the_hunt` | `bands` | Target of merge #3. |
| `seeds` | `bands` | Operator-requested. Hunter's pre-Medusa band. No artifacts carry yet. |
| `music_video` | `content_kind` | Operator-requested. |
| `fan_art` | `content_kind` | Operator-requested. |
| `memorabilia` | `content_kind` | Operator-requested. |

### 9.5 Category assignments

Applied to every surviving tag. Uncategorized slugs keep `category=NULL`
and appear in the "uncategorized" section of the pill wall; operator
categorizes (or deletes) them in Vocab Admin at leisure.

- **bands:** `hunter_root`, `medusas_disco`, `run_with_the_hunt`, `seeds`
- **people:** `nick_root`, every `author:*` pill
- **places:** `lancaster_pa`
- **content_kind:** `live_show`, `tour_announcement`, `poster`, `event_listing`,
  `song_page`, `artist_page`, `promotional_post`, `rehearsal`, `cover_song`,
  `new_song`, `tribute`, `milestone`, `music_video`, `fan_art`, `memorabilia`
- **topic:** `songwriting`, `songwriting_process`, `loss`, `mental_health`,
  `lyme_disease`
- **scope:** `personal`, `family`, `fan`
- **rarity:** `common`, `notable`, `rare`, `unique` — `is_exclusive=1`
- **Everything else** → `category=NULL`

### 9.6 Expected end state

Start: 106 tags.
Plus creates (§9.4): +5 → 111.
Minus merges (§9.2 eliminates 14 source slugs): -14 → 97.
Minus deletions (§9.3 — 2 dead weight + 6 years + 5 visual + 6 songs + 11
genres + 6 generic + 2 provenance = 38 slugs): -38 → **~59 tags**.
Plus author pills created during §3.2 migration (3 distinct values):
+3 → **~62 tags**.

After §9.5 categorization: roughly 30 tags in the 7 non-exclusive
categories, 4 in the exclusive rarity category, rest uncategorized.

Pill occurrences removed from artifacts: roughly 250 across the 80
artifacts (mostly `standard` at 76, year pills at 31, `show` at 21,
`phase2_recovery` at 26, and the various merge sources).

Undoable via the `.bak_pre_v05_<stamp>` DB backup the prep script makes.
Vocab Admin handles anything that surfaces later.

---

## 10. Intake-upload and intake-url — the live gap

Audit §16 revealed `/api/intake-upload`, `/api/intake-url`, and `/api/thumbgen`
are served by `imgserver.py` but **never called by `mediavault.html`**. This
isn't a dead route to delete; it's a UI gap.

Today, the only way artifacts enter the inbox is:
- CLI: `ingest_engine.py scan` reads `intake/drop/` and creates queue rows.
- FB bridge: `fb_candidates.html` → `/api/intake-from-fb-candidate`.
- External: the WB Capture Chrome extension (hitting `/api/artifact-register`,
  which is currently broken per §8).

Operator has no in-app way to say "here's a file I want in the inbox" or
"here's a URL, ingest it." That's a genuine hole.

**v0.5 adds two controls to the Inbox tab's empty-state view** (and a small
"+" button to the top action bar when the queue has items):

- **Drop file** — HTML `<input type="file" multiple>` that POSTs to
  `/api/intake-upload` (already exists on backend, verified audit §15 route
  table). Creates queue rows.
- **Paste URL** — text input + "add" button that POSTs to `/api/intake-url`
  (same).

Both backends already exist and are verified present in the route table.
No new backend work. Frontend gets ~40 lines of code.

### 10.1 `/api/thumbgen`

Leave server-side. It's a utility — regenerates a thumbnail for a given
artifact. No UI need right now (thumbnails are generated on ingest). Not
called from anywhere; not harmful. Keep, document, don't wire.

---

## 11. FB bridge — clarification

Audit §16 shows `/api/intake-from-fb-candidate`, `/api/fb-candidates`, and
`/api/fb-candidate-save` are not called from `mediavault.html`. This is
**correct and expected**: these routes serve `fb_candidates.html`, which is
a separate page hosted by the same server at `/fb`. Not a bug.

No changes in v0.5 to the FB flow.

---

## 12. File operations summary

Changed:

- `core/mediavault.sqlite` — migrate: add `author:*` pills to rows with
  non-junk `author_name`; drop `author_name`, `tags_permission`,
  `permission_contact`, `permission_evidence_path` columns; rename
  `tags.group_name` → `tags.category`; add `tags.is_exclusive`. Run the
  §9.2/§9.3/§9.4/§9.5 merge/delete/create/categorize pass.
- `core/imgserver.py` — fix save-and-release (§7), add `/api/tag-merge` and
  `/api/tag-bulk-delete` endpoints.
- `core/imgserver_extensions.py` — rewrite `handle_artifact_register` for
  v0.4+ schema (§8). Delete `DOMAIN_ENUM`, `_next_artifact_id` rewritten.
- `core/ingest_engine.py` — update the enrichment prompt (§6). Update
  the queue-row populator to read both v0.4 and v0.5 enrichment shapes.
- `core/attention_rules.py` — new file, ~60 lines. Five rules per §4.4.
- `mediavault.html` — largest change. Inbox pane rebuilt around pill wall,
  top action bar, hidden ID, collapsed descriptions below pills, parent input
  removed. Vault gets attach-to-parent modal. Vocab Admin gets merge and
  bulk-delete. Intake-upload and intake-url controls added.

Unchanged:

- `core/ingest_engine.py` CLI (`scan`, `process`, `status`).
- `ext/hr_manager_renderer.js` (external, do not modify).
- Port 51822, single-DB-file pattern, sql.js read path, asset roots.
- 62 legacy `MV-HR-*` artifact IDs.
- `fb_candidates.html` — completely untouched.

Quarantine to `D:\AI_OK_TO_DELETE\MediaVault_v05_refactor_<date>\`:

- `hr_manager.html.old_v02` (audit §2 confirms still in source, 72,148 bytes).
- `core/imgserver.py.old_v02` (audit §2 confirms still in source, 43,272 bytes).
- `core/_test.txt` (audit §2: 0 bytes, leftover).
- `core/screenshot_match.json` (audit §2: 2 bytes, empty).
- `core/migrate_to_v04.py` (v0.4 migration, shipped, no longer relevant).

Do not touch without explicit operator instruction:

- `core/mediavault.sqlite.bak_v04phase1_20260417_213832` — the v0.4 pre-migration
  backup. Leave exactly where it is.
- `core/enrich_queue.json`, `core/enrich_results.json` — operator's working
  data.
- `core/tag_vocabulary.json` — seed file, harmless backup of pre-migration
  vocabulary.

---

## 13. Execution phases (for the cowork brief)

Numbering here matches `COWORK_BRIEF_v05.md` phase numbers (0-7). The DB
backup is done by the prep script before cowork starts, hence the work
begins at Phase 0 (preflight).

0. **Preflight** — verify build lock is held in cowork's name, confirm the
   pre-v0.5 DB backup exists, read the snapshot, cache baseline numbers for
   post-refactor verification.
1. **Schema migration** — value-level migration first (add `author:*` pills
   from non-junk `author_name` values), then column drops, rename
   `group_name → category`, add `is_exclusive`. Single transaction.
2. **Vocabulary cleanup** — run §9.2 merges, §9.3 deletions, §9.4 creates,
   §9.5 categorization. Recompute usage counts. Single transaction.
3. **Backend** — fix `handle_artifact_save` save-and-release (§7). Add
   `/api/tag-merge` and `/api/tag-bulk-delete`. Update enrichment prompt
   (§6). Optionally add `/api/enrich-view` if the warnings logic lives
   server-side.
4. **`imgserver_extensions.py` rewrite** — rewrite `handle_artifact_register`
   against v0.5 schema (§8). Keep `handle_asset_raw` unchanged. Separate
   phase from §3 so it can be verified independently.
5. **Attention rules** — new `core/attention_rules.py` module (§4.4).
6. **Frontend** — rebuild inbox pane around the pill wall, move action bar
   to top, hide ID, collapse descriptions below pills, remove parent input.
   Add vault attach-to-parent modal. Add Vocab Admin merge and bulk-delete.
   Add intake-upload/intake-url empty-state controls. Preserve CSS
   variables, renderer script tag, topbar structure.
7. **Docs + cleanup + smoke test** — update `SPEC.md` to v0.5, `STATE.md`
   new session entry, `WORKFLOW.md` inbox section rewrite. Quarantine per
   §12. Full smoke matrix. Write `_cowork/PHASE_SUMMARY_v05.md`. Release
   build lock.

---

## 14. What this design does not cover

- Sidecar auto-linking beyond v0.4's one-shot pass. The 3 unlinked sidecar
  candidates (audit §9a) are handled by operator via the new vault
  attach-to-parent UI. No heuristic re-run.
- HEIC GPS extraction (carried-forward open issue from STATE.md). Separate
  concern; ingest engine work, not v0.5.
- Hash-based dedup on intake-upload (carried-forward). Separate concern.
- `mediavault_recrop.html` (carried-forward broken tool). Not in scope.
- Absorbing `fb_candidates.html` into `mediavault.html` — backlog item.

---

*End of v0.5 design doc.*
