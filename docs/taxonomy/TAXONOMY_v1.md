# MediaVault Taxonomy v1 — Namespace Specification

**Source of truth:** live `core/mediavault.sqlite` (read-only) — `vocabulary`, `tags`, `artifacts`.
**Strategy:** Targeted promotion. Identity facets to Tier-1, classification to Tier-2, a small set of
promoted Tier-3 axes, and a flat `attributes` bag for everything else.
**Companions:** `NORMALIZATION_MAP.md` (per-value mapping), `COVERAGE_PROOF.md` (verification run),
`tools/coverage_check.py` (the check).

All values below are drawn from the live DB. `cardinality` is per artifact:
**single** = at most one value; **multi** = zero or more values.

---

## Tier 1 — Identity

Who/what the artifact is about. Promoted from the legacy `*:` identity tags.

### `band` (promoted from `bands`)
- **Allowed values (live):** `hunter_root`.
- **Validation:** value must exist in the band catalog; slug is `lower_snake_case`.
- **Cardinality:** multi (an artifact may feature more than one band; today only `hunter_root`).
- **Note:** the legacy namespace was `bands`; v1 renames it to the singular `band`. The Tier-3 `lineup`
  value `band` (as in "full-band vs solo") is a *different* axis — see `lineup`.

### `album`
- **Allowed values (live):** `arkansas`, `crooked_home`, `run_with_the_hunt`, `medusas_disco`,
  `life_inside_a_wheel`, `mimicking_the_sun_like_dandelions`,
  `skipping_stones_that_sink_before_theyre_thrown`, `they_finally_cracked_me`
  (plus zero-usage stubs retained in the catalog: `cracked`, `crooked`, `dandelions`, `skipping`, `wheel`).
- **Validation:** value must exist in the album catalog.
- **Cardinality:** multi.

### `song`
- **Allowed values (live):** the song catalog (~50 values, e.g. `town_rat_heathen`, `quicksand_sinking`,
  `cookin_in_the_bathroom`, `lampshade`, `friendly_fire`, …).
- **Validation:** value must exist in the song catalog.
- **Cardinality:** multi.

### `year`
- **Allowed values (live):** `2019`, `2020`, `2021`, `2022`, `2023`, `2024`, `2025`.
- **Validation:** four-digit year; should agree with `post_date`/`capture_date` when present.
- **Cardinality:** single.

### `people`
- **Allowed values (live):** `nick_root`.
- **Validation:** value must exist in the people catalog.
- **Cardinality:** multi.

### `venue`
- **Allowed values (live):** none yet (namespace reserved in `vocabulary`, no tags assigned).
- **Validation:** value must exist in the venue catalog once populated.
- **Cardinality:** multi.

---

## Tier 2 — Classification

How the artifact is classified. Each Tier-2 facet collapses one or more legacy fields into a single
authoritative namespace.

### `source` — collapse of `source:` tag + `source_platform` column
- **Allowed values (live, authoritative):** `youtube`, `reverbnation`, `facebook`, `instagram`,
  `distrokid`, `tiktok`, `local`, `other`.
- **Resolution rule (deterministic, per artifact):**
  1. if the `source_url` host maps to a known platform → that value wins (URL is ground truth);
  2. else the `source_platform` column value;
  3. else the `source:` tag value.
  The `source:` tag and `source_platform` column are merged into this one field; on conflict the rule
  above decides, and only column-vs-tag conflicts the URL cannot break are flagged for a human.
- **Live reconciliation:** 185 artifacts; 138 carry a `source:` tag; 135 agree with the column; **3
  disagree and all 3 auto-resolve to `facebook`** (URL host = `facebook.com`). 36 artifacts have a
  column value but no tag (column authoritative). See `NORMALIZATION_MAP.md` §2 for the per-artifact plan.
- **Validation:** value ∈ allowed set; exactly one per artifact.
- **Cardinality:** single.
- **⚠ Open item flagged:** the brief expected "23 disagreements / 6 unresolvable"; the live DB shows
  **3 / 0**. v1 follows the live data (source rule). Confirm — see `NORMALIZATION_MAP.md` §4.

### `type` — what kind of media object
- **Allowed values (v1):** `mp3`, `video`, `music_video`, `poster`.
- **Construction from legacy:**
  - `type:audio` + `type:mp3` → **`mp3`** (dedupe; both had usage_count 30 in live data).
  - `type:video` → `video`.
  - `type:poster` → `poster`.
  - **gains `music_video`** from `unsorted:music-video` (after hyphen→underscore noise fix).
  - **Retire** the parallel kind columns by routing each facet:
    - `card_kind` (`card_kind:album`) → not a media type; routes to `attributes` (UI card hint) /
      reserved (`type` for page-kinds in a later pass).
    - `artifact_kind` (`artifact_kind:thumbnail`, `artifact_kind:transcript`) → these are derived/child
      assets; route to `type` where they denote the object (`thumbnail`, `transcript`) and to
      `attributes` otherwise. Held as reserved pending the derived-asset model.
    - `format` (`format:short`) → route to `attributes` (a length/quality facet, not a media type).
- **Validation:** value ∈ allowed set; single primary `type` per artifact.
- **Cardinality:** single.

---

## Tier 3 — Promoted axes

Two cross-cutting axes promoted out of `unsorted` because they carry real query value.

### `event`
- **Allowed values (live, from `unsorted:*`):** `live_show`, `rehearsal`, `tour`, `tour_announcement`,
  `advance_tickets`, `event_listing`, `fall_tour`, `ticketing`.
- **Validation:** value ∈ allowed set; `lower_snake_case`.
- **Cardinality:** multi (e.g. a post can be both `tour_announcement` and `advance_tickets`).

### `lineup`
- **Allowed values (live, from `unsorted:*`):** `solo`, `band`.
- **Validation:** value ∈ allowed set.
- **Cardinality:** single (an artifact is either a solo or full-band performance/context).

---

## Flat `attributes` bag

Everything else from `unsorted:*` that is not an identity, classification, or promoted axis. A flat,
multi-valued bag of descriptive facets. No controlled hierarchy in v1, but values are `lower_snake_case`
and deduped.

- **Allowed values (live, 36 source values → 33 distinct after merges):**
  `account_hacked` (merge of `instagram_hacked`+`hacked_account`), `new_music` (merge of
  `new_music`+`new_song`), `songwriting` (merge of `songwriting`+`songwriting_process`),
  `artist_message`, `common`, `defiant`, `digital`, `early_stages`, `early_version`, `family`, `fan`,
  `fan_cover_song`, `gear`, `indieartist`, `loss`, `lyme_disease`, `mental_health`, `merch`, `milestone`,
  `notable`, `official`, `personal`, `pre_release`, `rare`, `released`, `snarky`, `social`, `tribute`,
  `unique`, and the four **reserved** values below.
- **Validation:** `lower_snake_case`; no value collides with a promoted namespace slug.
- **Cardinality:** multi.

---

## Resolution of the four open / borderline items

The brief deferred four borderline values to "reserved-for-possible-promotion." v1 holds each in
`attributes` with a documented future destination, so nothing is lost and promotion is a later, ratified
step:

1. **`artist_page`** → `attributes:artist_page` now. **Reserved:** page-kind, candidate → `type` once
   the page/object distinction is ratified.
2. **`song_page`** → `attributes:song_page` now. **Reserved:** page-kind, candidate → `type`.
3. **`promotional_post`** → `attributes:promotional_post` now. **Reserved:** page/post-kind, candidate →
   `type`.
4. **`lancaster_pa`** → `attributes:lancaster_pa` now. **Reserved:** geographic, candidate → a future
   `geo` namespace.

These are flagged in `NORMALIZATION_MAP.md` §4 for a human decision in the next pass.

---

## Noise / dedupe fixes applied in v1

- **Hyphen → underscore:** `music-video` → `music_video` (lands in `type`).
- **`type` dedupe:** `audio` + `mp3` → `mp3`.
- **Merged duplicate `attributes`:** `instagram_hacked`/`hacked_account` → `account_hacked`;
  `songwriting`/`songwriting_process` → `songwriting`; `new_music`/`new_song` → `new_music`.

---

## Retired namespaces

The following legacy `vocabulary` namespaces are retired or superseded in v1:
`unsorted` (decomposed by this map), `format` (routed into `type`/`attributes`),
`card_kind`/`artifact_kind`/`content_kind` (routed into `type`/`attributes`/reserved),
`platform` (already retired in DB, folded into `source`), `era`/`exhibit`/`scope`/`author`/`release_type`
retained as-is or out of scope for this targeted promotion pass.
