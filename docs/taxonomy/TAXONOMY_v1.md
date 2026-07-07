# MediaVault Taxonomy v1 — Namespace Specification (as-built)

**Source of truth:** live `core/mediavault.sqlite` — `vocabulary`, `tags`, `artifacts`.
**Strategy:** Targeted promotion. Identity facets to Tier-1, classification to Tier-2, a small set of
promoted Tier-3 axes, and a flat `attributes` bag for everything else.
**Companions:** `NORMALIZATION_MAP.md` (per-value mapping), `COVERAGE_PROOF.md` (verification run),
`tools/coverage_check.py` (the check).

> **As-built revision 2026-07-07** — rewritten after the vocabulary reconciliation
> (`MV_VOCAB_RECONCILE_PLAN-20260624.md`, migration Stages 0–4; run log
> `MV_VOCAB_MIGRATION_LOG-20260624.md` in the museum repo). This document now **describes the
> reconciled live DB** (293 artifacts, 210 registry slugs, every slug with live usage) rather than an
> unapplied target. Where v1's original model remains a *future* direction (type dedupe,
> artifact_kind/format routing), it is marked TARGET, not fact.

All values below are drawn from the live DB. `cardinality` is per artifact:
**single** = at most one value; **multi** = zero or more values.

---

## Tier 1 — Identity

Who/what the artifact is about. Promoted from the legacy `*:` identity tags.

### `band` (renamed from `bands` — DONE 2026-07-07)
- **Allowed values (live):** `hunter_root` (284), `medusas_disco` (4).
- **Validation:** value must exist in the band catalog; slug is `lower_snake_case`.
- **Cardinality:** multi.
- **Note:** the rename `bands`→`band` was applied in migration Stage 4 (288 payloads, vocabulary row,
  registry slugs; client `BOARD_TOTAL_KEYS` updated in the same commit). The Tier-3 `lineup` value
  `band` (full-band vs solo) is a *different* axis and was not touched — see `lineup`.

### `album`
- **Allowed values (live, 11):** `arkansas`, `crooked_home`, `life_inside_a_wheel`, `medusas_disco`,
  `mimicking_the_sun_like_dandelions`, `orphic_grimoire`, `phone_recordings_ep`, `rarities`,
  `run_with_the_hunt`, `skipping_stones_that_sink_before_theyre_thrown`, `they_finally_cracked_me`.
- The zero-usage stubs (`cracked`, `crooked`, `dandelions`, `skipping`, `wheel`) were **dropped from
  the registry** in Stage 2 (F7).
- **Validation:** value must exist in the album catalog.
- **Cardinality:** multi.

### `song`
- **Allowed values (live):** the song catalog — 78 registered values, all with live usage
  (e.g. `town_rat_heathen`, `quicksand_sinking`, `cookin_in_the_bathroom`, `lampshade`, …; full list =
  `SELECT slug FROM tags WHERE slug LIKE 'song:%'`).
- **Validation:** value must exist in the song catalog.
- **Cardinality:** multi.

### `year`
- **Allowed values (live):** `2017`–`2025` (nine values).
- **Validation:** four-digit year; should agree with `post_date`/`capture_date` when present.
- **Cardinality:** single.

### `people`
- **Allowed values (live, 11):** `alex_aument`, `anders_osborne`, `anthony_procopio`, `chad_cromwell`,
  `david_kalmusky`, `justin_wohlfeil`, `lindsay_lou`, `marc_rogers`, `nick_root`, `tyler`,
  `wynton_huddle`.
- **Validation:** value must exist in the people catalog.
- **Cardinality:** multi.

### `venue`
- **Allowed values (live):** `chameleon_club`, `xl_live`.
- **Validation:** value must exist in the venue catalog.
- **Cardinality:** multi.

*(Also Tier 1 in the live registry: `era` — `breakthrough`, `early_days`, `finding_the_sound`,
`on_the_road`, `recent`, `rwth` — and `topic` — `family`, `gear`, `influences`, `recording`,
`release`, `roots`, `songwriting`, `touring`. Retained as-is; out of scope for the original
promotion pass but live and registered.)*

---

## Tier 2 — Classification

How the artifact is classified. Each Tier-2 facet collapses one or more legacy fields into a single
authoritative namespace.

### `source` — collapse of `source:` tag + `source_platform` column — **APPLIED 2026-07-07 (Stage 3, F6)**
- **Allowed values (live, corrected):** `bandcamp`, `facebook`, `instagram`, `local`, `other`,
  `press`, `reverbnation`, `youtube`.
  - The original v1 set was wrong against live data: it omitted `bandcamp` (79 live) and `press`,
    listed `distrokid` (zero usage — **dropped**, Stage 2) and `tiktok` (stray tag — resolved away by
    the URL-host rule). `web` was folded into `other` (F6).
- **Resolution rule (deterministic, per artifact) — as executed:**
  1. if the `source_url` host maps to a known platform → that value wins (URL is ground truth);
  2. else the `source_platform` column value;
  3. else the `source:` tag value;
  4. exhausted (no URL, NULL column, no tag) → `local` (applied to the 19 vaulted local-drop/cowork
     artifacts: album containers, phone recordings, local drops).
- **Fresh reconciliation at migration time (2026-07-07, 293 artifacts):** **14 tag-vs-column
  disagreements, 0 unresolvable** — 12 were the 2026-06-17 press batch (`web` tag vs `press` column;
  column won), 2 resolved by URL host to `facebook`. The historical figures (brief's "23/6",
  v1-authoring's "3/0") were both stale — superseded by this measurement, recorded in the run log.
- **Post-state:** every artifact has exactly one `source:` tag and it equals `source_platform`
  (293/293). Distribution: youtube 105, bandcamp 79, reverbnation 42, local 31, facebook 16,
  press 12, other 7, instagram 1.
- **Validation:** value ∈ allowed set; exactly one per artifact; tag must equal column.
- **Cardinality:** single.

### `type` — what kind of media object
- **Allowed values (live):** `audio`, `mp3`, `music_video`, `poster`, `video`.
- **TARGET (not yet applied):** the v1 dedupe `audio`+`mp3` → `mp3` remains a future pass; both are
  live today. `music_video` did land (from `unsorted:music-video`, hyphen fixed).
- **Validation:** value ∈ allowed set; single primary `type` per artifact.
- **Cardinality:** single.

---

## Tier 3 — Promoted axes

Promoted out of `unsorted` because they carry real query value. **Registered in the `vocabulary`
table 2026-07-07 (Stage 1, D-h): `event` (tier 3, sort 7), `lineup` (3, 8), `attributes` (3, 9).**

### `event`
- **Allowed values (live):** `advance_tickets`, `event_listing`, `fall_tour`, `live_show`,
  `rehearsal`, `ticketing`, `tour`, `tour_announcement`.
- **Validation:** value ∈ allowed set; `lower_snake_case`.
- **Cardinality:** multi (e.g. a post can be both `tour_announcement` and `advance_tickets`).

### `lineup`
- **Allowed values (live):** `solo`, `band`.
- **Validation:** value ∈ allowed set.
- **Cardinality:** single (an artifact is either a solo or full-band performance/context).

---

## Flat `attributes` bag

Everything else that is not an identity, classification, or promoted axis. A flat, multi-valued bag
of descriptive facets. Values are `lower_snake_case` and deduped.

- **Allowed values (live, 34):** `account_hacked`, `artist_message`, `artist_page`, `common`,
  `defiant`, `digital`, `early_stages`, `early_version`, `family`, `fan`, `fan_cover_song`, `gear`,
  `indieartist`, `lancaster_pa`, `link`, `loss`, `lyme_disease`, `mental_health`, `merch`,
  `milestone`, `new_music`, `notable`, `official`, `personal`, `pre_release`, `promotional_post`,
  `rare`, `released`, `snarky`, `social`, `song_page`, `songwriting`, `tribute`, `unique`.
- `link` joined the bag 2026-07-07: the stray one-occurrence `presentation` namespace was folded in
  (Stage 1, F8) and `presentation` ceased to exist.
- **Validation:** `lower_snake_case`; no value collides with a promoted namespace slug.
- **Cardinality:** multi.

---

## Resolution of the four open / borderline items

v1 holds each in `attributes` with a documented future destination; promotion is a later, ratified
step. Unchanged by the reconciliation:

1. **`artist_page`** → `attributes:artist_page` now. **Reserved:** page-kind, candidate → `type`.
2. **`song_page`** → `attributes:song_page` now. **Reserved:** page-kind, candidate → `type`.
3. **`promotional_post`** → `attributes:promotional_post` now. **Reserved:** candidate → `type`.
4. **`lancaster_pa`** → `attributes:lancaster_pa` now. **Reserved:** geographic, candidate → `geo`.

---

## The `kind` COLUMN (not a tag namespace)

`artifacts.kind` — `CHECK(kind IN ('performance','release','announcement','studio','candid',
'interview','fan'))`; single-select, nullable (146 filled / 147 NULL). This is the canonical "Kind"
axis. **`fact` joins this CHECK set in the later fact workstream** (F10; requires the one table
rebuild, deliberately deferred out of the vocab migration). The Tier-3 `content_kind` tag is a
*different*, media-variant axis — kept per F4, export- and client-coupled (`KIND_RANK`,
`ContentKindBadge`); a rename (candidate `variant`) is a possible later coordinated change.

---

## Retired namespaces — corrected to reality (Stage 6)

**Actually retired (zero live usage, `retired_at` set):**
- `unsorted` — retired 2026-05-19, fully decomposed by this map (48 leftover zero-usage registry
  stubs purged in Stage 2).
- `platform` — retired 2026-05-24, folded into `source`.

**NOT retired — live, with the original v1 routing kept as TARGET only (F5):**
- `content_kind` (175 occurrences) — KEPT per F4; export/client-coupled. Hard blocker until a
  coordinated export+client change.
- `card_kind` (10) — live in payloads/registry; **not registered in the `vocabulary` table** (by
  design this pass); export container-dispatch depends on it. Hard blocker.
- `artifact_kind` (55) — routing (`thumbnail`/`transcript` → `type` reserved) deferred to backlog.
- `format` (24) — routing to `type`/`attributes` deferred to backlog; client `BOARD_TOTAL_KEYS`
  includes it.

**Never-retired flag correction:** `exhibit` had been wrongly marked retired since 2026-05-19 while
sitting on all 293 artifacts and keying export discovery — **un-retired 2026-07-07 (Stage 1, F9).**

`era`/`scope`/`author`/`release_type` retained as-is, out of scope for the promotion pass.
