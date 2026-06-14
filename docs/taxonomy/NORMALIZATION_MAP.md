# NORMALIZATION MAP — MediaVault Taxonomy v1

**Scope:** maps every live `unsorted:*` tag value to its v1 destination namespace, exactly once.
**Source of truth:** live `core/mediavault.sqlite` (read-only), `tags` table + `artifacts.tags`.
**Generated against:** 47 distinct `unsorted:*` values (identical set in `tags` registry and in `artifacts.tags`).
**Companion spec:** `TAXONOMY_v1.md`. **Verification:** `tools/coverage_check.py` parses the table below and diffs it against the live DB.

> The mapping table in section 1 is machine-readable. `coverage_check.py` extracts every row whose
> first cell is a `` `unsorted:<slug>` `` literal and reads the second cell as the v1 destination.
> Do not change the column order without updating the parser.

---

## 1. The 47 `unsorted:*` values → v1 destination (each exactly once)

| Source value | v1 destination | Disposition | Notes |
|---|---|---|---|
| `unsorted:advance_tickets` | `event:advance_tickets` | promote → event | Tier-3 event axis |
| `unsorted:event_listing` | `event:event_listing` | promote → event | Tier-3 event axis |
| `unsorted:fall_tour` | `event:fall_tour` | promote → event | Tier-3 event axis |
| `unsorted:live_show` | `event:live_show` | promote → event | Tier-3 event axis |
| `unsorted:rehearsal` | `event:rehearsal` | promote → event | Tier-3 event axis |
| `unsorted:ticketing` | `event:ticketing` | promote → event | Tier-3 event axis |
| `unsorted:tour` | `event:tour` | promote → event | Tier-3 event axis |
| `unsorted:tour_announcement` | `event:tour_announcement` | promote → event | Tier-3 event axis |
| `unsorted:band` | `lineup:band` | promote → lineup | Tier-3 lineup axis (NOT the `band` identity namespace) |
| `unsorted:solo` | `lineup:solo` | promote → lineup | Tier-3 lineup axis |
| `unsorted:music-video` | `type:music_video` | promote → type (noise fix) | hyphen→underscore; `type` gains `music_video` |
| `unsorted:hacked_account` | `attributes:account_hacked` | merge → attributes | merged with `instagram_hacked` |
| `unsorted:instagram_hacked` | `attributes:account_hacked` | merge → attributes | merged with `hacked_account` (canonical: `account_hacked`) |
| `unsorted:new_music` | `attributes:new_music` | merge → attributes | canonical of `new_music`/`new_song` |
| `unsorted:new_song` | `attributes:new_music` | merge → attributes | merged into `new_music` |
| `unsorted:songwriting` | `attributes:songwriting` | merge → attributes | canonical of `songwriting`/`songwriting_process` |
| `unsorted:songwriting_process` | `attributes:songwriting` | merge → attributes | merged into `songwriting` |
| `unsorted:artist_page` | `attributes:artist_page` | flat (RESERVED) | reserved-for-promotion: page-kind → `type` in a later pass |
| `unsorted:song_page` | `attributes:song_page` | flat (RESERVED) | reserved-for-promotion: page-kind → `type` in a later pass |
| `unsorted:promotional_post` | `attributes:promotional_post` | flat (RESERVED) | reserved-for-promotion: page-kind → `type` in a later pass |
| `unsorted:lancaster_pa` | `attributes:lancaster_pa` | flat (RESERVED) | reserved-for-promotion: → `geo` namespace in a later pass |
| `unsorted:artist_message` | `attributes:artist_message` | flat → attributes | |
| `unsorted:common` | `attributes:common` | flat → attributes | |
| `unsorted:defiant` | `attributes:defiant` | flat → attributes | tone/sentiment |
| `unsorted:digital` | `attributes:digital` | flat → attributes | |
| `unsorted:early_stages` | `attributes:early_stages` | flat → attributes | |
| `unsorted:early_version` | `attributes:early_version` | flat → attributes | |
| `unsorted:family` | `attributes:family` | flat → attributes | |
| `unsorted:fan` | `attributes:fan` | flat → attributes | |
| `unsorted:fan_cover_song` | `attributes:fan_cover_song` | flat → attributes | |
| `unsorted:gear` | `attributes:gear` | flat → attributes | |
| `unsorted:indieartist` | `attributes:indieartist` | flat → attributes | |
| `unsorted:loss` | `attributes:loss` | flat → attributes | |
| `unsorted:lyme_disease` | `attributes:lyme_disease` | flat → attributes | |
| `unsorted:mental_health` | `attributes:mental_health` | flat → attributes | |
| `unsorted:merch` | `attributes:merch` | flat → attributes | |
| `unsorted:milestone` | `attributes:milestone` | flat → attributes | |
| `unsorted:notable` | `attributes:notable` | flat → attributes | |
| `unsorted:official` | `attributes:official` | flat → attributes | |
| `unsorted:personal` | `attributes:personal` | flat → attributes | |
| `unsorted:pre_release` | `attributes:pre_release` | flat → attributes | |
| `unsorted:rare` | `attributes:rare` | flat → attributes | |
| `unsorted:released` | `attributes:released` | flat → attributes | |
| `unsorted:snarky` | `attributes:snarky` | flat → attributes | tone/sentiment |
| `unsorted:social` | `attributes:social` | flat → attributes | |
| `unsorted:tribute` | `attributes:tribute` | flat → attributes | |
| `unsorted:unique` | `attributes:unique` | flat → attributes | |

**Row count: 47.** Namespace tally — `event` 8, `lineup` 2, `type` 1, `attributes` 36.
Three merge-pairs collapse to a shared canonical, so the 36 `attributes` rows resolve to 33 distinct destination slugs.

---

## 2. Source collapse — `source:` tag + `source_platform` column → one authoritative `source`

**Rule (deterministic):** the authoritative `source` is resolved per artifact in this order —
1. if the `source_url` host maps to a known platform, that wins (the URL is ground truth);
2. else the `source_platform` column value;
3. else the `source:` tag value.
A row is **auto-resolvable** when (1) or the column/tag agree; it is **flagged for a human** only when the column and tag disagree *and* the URL host does not disambiguate.

**Live reconciliation (185 artifacts):**

- 138 artifacts carry a `source:` tag. 135 agree with `source_platform`. **3 disagree.**
- 36 artifacts have a `source_platform` value but no `source:` tag (column is authoritative — not a conflict).
- 35 artifacts have a column value outside the `source` vocabulary (`facebook` ×16, `local` ×12, `other` ×7); these are adopted into the v1 `source` vocabulary (see `TAXONOMY_v1.md` §source).

**The 3 disagreements — all auto-resolve to `facebook` (URL host = `facebook.com`, agreeing with the column; the tag is the outlier):**

| Artifact | column | tag | URL host | Auto-resolved `source` | Basis |
|---|---|---|---|---|---|
| `MV-HR-20260405-008` | facebook | distrokid | facebook.com | `facebook` | URL+column agree; drop errant `source:distrokid` |
| `MV-HR-20260405-011` | facebook | distrokid | facebook.com | `facebook` | URL+column agree; drop errant `source:distrokid` |
| `MV-HR-20260405-014` | facebook | instagram | facebook.com | `facebook` | URL+column agree; drop errant `source:instagram` |

**Result: 3 conflicts, all 3 deterministically resolved, 0 left unresolvable.**

> ⚠️ **DISCREPANCY WITH BRIEF — needs Mike's eyeball.** The locked brief states "23 disagreements,
> 6 the recon couldn't auto-resolve." The **live DB does not support those counts**: the authoritative
> column-vs-tag comparison yields **3** disagreements (all auto-resolvable), not 23, and **0** unresolvable,
> not 6. The brief's 23/6 appear to derive from an earlier snapshot/recon rather than the current live DB.
> Per the source rule (derive only from live `mediavault.sqlite`), this map reflects the live numbers.
> See the flagged list §4.

---

## 3. Noise / dedupe fixes (applied above)

| Fix | From | To | Kind |
|---|---|---|---|
| Hyphen → underscore | `unsorted:music-video` | `type:music_video` | normalize slug |
| Type dedupe | `type:audio` + `type:mp3` | `type:mp3` | collapse (Tier-2 `type`; see TAXONOMY §type) |
| Merge dupes | `unsorted:instagram_hacked` + `unsorted:hacked_account` | `attributes:account_hacked` | merge |
| Merge dupes | `unsorted:songwriting` + `unsorted:songwriting_process` | `attributes:songwriting` | merge |
| Merge dupes | `unsorted:new_music` + `unsorted:new_song` | `attributes:new_music` | merge |

Note: `type:audio`+`type:mp3` is a Tier-2 `type`-namespace dedupe (both have usage_count 30 in live data); it is documented here for completeness but is not one of the 47 `unsorted:*` rows.

---

## 4. Flagged for a human eye

1. **Brief-vs-live source-count discrepancy (HIGH):** brief says 23 disagreements / 6 unresolvable;
   live DB shows 3 / 0. Confirm whether the v1 source-collapse should follow live data (as built here)
   or whether an older recon set should be re-imported. *Recommended: follow live data.*
2. **`MV-HR-20260405-008`** — `source:distrokid` tag contradicts `facebook` column + `facebook.com` URL. Auto-resolved to `facebook`; confirm the DistroKid tag was a mis-tag, not a cross-post origin.
3. **`MV-HR-20260405-011`** — same pattern as above. Auto-resolved to `facebook`.
4. **`MV-HR-20260405-014`** — `source:instagram` tag contradicts `facebook` column + `facebook.com` URL. Auto-resolved to `facebook`; confirm not a genuine IG cross-post.
5. **`MV-HR-20260405-010`** — `source_platform = other`, no `source:` tag, URL `theticketing.co`. Adopted as `source:other`; consider a dedicated `ticketing` source value if these recur.
6. **4 reserved attribute values** — `artist_page`, `song_page`, `promotional_post` (page-kinds, candidate → `type`) and `lancaster_pa` (candidate → a future `geo` namespace). Held in `attributes` for v1; promote in a later pass once `type`/`geo` rules are ratified.
