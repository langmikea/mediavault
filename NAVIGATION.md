# Navigation — MV (MediaVault)

You are standing in MediaVault. This document orients you to the
larger picture: what this project is, what the other related projects
are, and what the contract is between them. For everything beyond
orientation, follow the pointers at the bottom.

## What this project is

MediaVault (MV) is the portfolio's artifact vault. It is a running
Python HTTP server + SQLite database + HTML/JS operator UI, bound to
`127.0.0.1:51822` on the operator's laptop. It captures, ingests,
catalogs, tags, and retrieves artifacts — photos, URLs, page saves,
YouTube items, transcripts, text extracts — across all of Mike's
projects. MV is infrastructure, not a project of its own; downstream
projects (Hunter Root, the Museum, Genealogy, etc.) consume it. MV is
working and in active use at v0.5.2, with a v0.7 punchlist of
spec-alignment cleanups deferred indefinitely.

## The portfolio

There are three systems, related as follows:

- **MV (MediaVault)** — `C:\AI\Platform\MediaVault\` (this project)
  Running HTTP + SQLite + HTML/JS artifact vault. Source of truth for
  artifacts: capture, intake, tagging, lifecycle, release.

- **Museum** — `C:\AI\Projects\weird-baby-museum\`
  Curation and render layer downstream of MV. A Vite + React +
  Cloudflare Workers site that reads released artifacts from MV and
  presents them as exhibits at weird.baby.

- **YT (YouTube ingest pipeline)** — lives inside the Museum repo at
  `tools/yt-ingest.mjs` and `tools/youtube-ingest-schema.md`.
  Reads YouTube data, produces per-video manifests in the
  `yt_archive/v1` schema, and posts parsed artifacts into MV via
  HTTP POST.

## How they connect

- **YT → MV (ingest)**: YT's capture script writes per-video manifest
  folders under `C:\AI\Projects\Hunter Root\archive\youtube\…\` and
  then calls `POST /api/artifact-register` once per artifact (parent
  `youtube_video_page` first, then `youtube_thumbnail` /
  `youtube_transcript` / optional `youtube_page_save` children, then
  a `youtube_channel_card` once per channel). The route is
  implemented in `core/imgserver_extensions.py` (parent linkage at
  lines 210 and 329) and accepts `parent_artifact_id` directly so no
  manifest reader is needed in MV.
- **MV → Museum (read)**: the Museum reads released artifacts from
  MV's `/db` endpoint (`http://127.0.0.1:51822/db`). The Museum's
  `npm run export-deep-tags` is the current touchpoint, extracting
  Deep Dive tags from released YouTube artifacts.
- **Loopback only**: MV does not bind to a public interface and is
  not reachable from CI or another machine. Everything that touches
  MV runs on the operator's laptop.
- **The MV-side YT contract is documented as design** at
  `_cowork/YT_INGEST_FROM_MUSEUM.md`. The capture script that produces
  manifests has not been written yet; the endpoint contract is the
  stable part.
- **v0.5 limitation worth knowing.** `/api/artifact-register`
  currently requires `local_asset_path` to point at an existing file
  under `C:\AI\`. `url_only` artifacts (parent video page,
  transcript, channel card) don't have a local file — the open
  question of "stub sidecar vs. relax the endpoint" is recorded in
  `_cowork/YT_INGEST_FROM_MUSEUM.md` and not yet resolved.

## Where you should read next

- If you need to act in MV: read `PROJECT.md` for the mental model
  (artifacts, pills, lifecycle, storage modes, attention rules),
  then `SPEC.md` for the canonical decisions, then `CHANGELOG.md`
  for the most recent version's actual landed changes.
- If you need to act in the Museum: go to
  `C:\AI\Projects\weird-baby-museum\NAVIGATION.md` and follow its
  pointers (CLAUDE.md, STATUS.md, docs/MUSEUM_UX.md).
- If you need YT ingest contract details: read
  `_cowork/YT_INGEST_FROM_MUSEUM.md` (MV-side view: endpoints,
  pills, R-rule expectations, v0.5 limitations) and the Museum-side
  schema at `C:\AI\Projects\weird-baby-museum\tools\youtube-ingest-schema.md`.

## Known state (as of 2026-05-14)

- **MV is in v0.5.2.** Three small drifts exist between MV's spec
  document and MV's running code: `artifacts.status` allows the value
  `archived` (the spec says it should be `deleted`); the column
  `tags.is_proposed` is physically present though logically retired;
  tag slug uniqueness is enforced as composite `(slug, category)` not
  global. These drifts are tracked in MV's CHANGELOG as a "Phase-2
  cleanup punchlist," deferred indefinitely.

- **The Museum integrates against MV-as-it-actually-is, not against
  MV's spec.** Two stances were considered:
  - Stance A — wait on MV cleanup. Don't write Museum code that
    reads from MV until the three drifts above (status=archived,
    is_proposed column, composite slug uniqueness) are fixed in MV.
    Museum code ends up cleaner; Museum work is blocked until MV
    cleanup lands.
  - Stance B — adapter layer. When Museum-to-MV integration work
    starts, it proceeds against MV v0.5.2 as-is, with a thin
    adapter layer in the Museum that normalizes the three drifts.
    The adapter does not exist in code yet — it will be written as
    part of the integration work, not before. If MV's punchlist
    ever lands, the adapter simplifies or disappears.

  Stance B was chosen, 2026-05-14. Museum work doesn't block on MV
  cleanup that has no scheduled date.

- **MV is on local-only git.** The repo at
  `C:\AI\Platform\MediaVault\.git` was initialized 2026-05-08, branch
  `master`, no remote ever planned. Closure notes live in
  `_cowork/MV_GIT_INIT_CLOSURE_2026-05-08.md`.

- **Four-state pill enrichment shape lingers in the code.** SPEC.md
  §2.3 collapsed inbox pill states to three session-only values
  (`on` / `suggested` / `off`), but `handle_intake_from_fb_candidate`
  and the enrichment prompt builder still emit the v0.4-era
  four-state shape. STATE.md flags this as expected v0.7 work; it is
  not a Deep Dive blocker but downstream consumers should expect
  mixed shapes if they read `enrichment_json`.

## Current state and what's next

**Updated:** 2026-05-14

**Current state:** MV v0.5.2 is running and stable on
127.0.0.1:51822. Active use continues. No code work currently in
flight.

**What's next:**
- Phase-2 punchlist deferred indefinitely. Three drifts
  (status=archived, is_proposed column, composite slug uniqueness)
  are known and not scheduled. When Museum work needs them fixed,
  revisit.
- YT ingest producer script. The `/api/artifact-register` contract
  is stable on MV's side. The producer (the script that actually
  captures YouTube data and POSTs to that endpoint) hasn't been
  written yet. Currently design-only in
  `_cowork/YT_INGEST_FROM_MUSEUM.md`.

**If nothing's queued:** No items above means there's no work
pre-decided. Don't pick something autonomously — ask Mike what to
work on.

---

*This section is updated by the AI at the end of each working
session. If the date above is older than your current session and
the bullets look stale, flag it to Mike before acting on them.*

## What's not here

This document does not cover:
- How MV works internally — see `PROJECT.md`, `SPEC.md`,
  `WORKFLOW.md`, `MEDIAVAULT_V05_DESIGN.md`.
- Implementation details of the YT-to-MV contract — see
  `_cowork/YT_INGEST_FROM_MUSEUM.md` and the Museum-side
  `tools/youtube-ingest-schema.md`.
- Historical decisions and per-version landed changes — see
  `CHANGELOG.md` and `_cowork/DECISIONS_*.md`.

If a future Claude finds itself needing something not covered by any
document, that's a real gap. Flag it to Mike.
