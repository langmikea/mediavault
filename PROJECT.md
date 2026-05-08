# MediaVault — Platform Project
**Stored:** C:\AI\Platform\MediaVault\PROJECT.md
**Created:** 2026-03-31
**Last major refactor:** 2026-04-19 (v0.5)
**Operator:** Mike Lang
**Agent:** Claude (Anthropic)

> **Reconciled 2026-04-20** against
> `_cowork/DECISIONS_2026-04-19_pill_states_and_friends.md` alongside
> SPEC.md. The "Core mental model" below reflects the decisions doc:
> three session-only pill states (not five persisted), one-stage
> vocabulary (no proposed/accepted split), global slug uniqueness, and
> `archived_at` as the canonical saved-but-hidden flag. Implementation
> of these corrections is the v0.7 punchlist.

## What This Is
A **review workstation** and a **permanent vault** for anything worth keeping.
Shared infrastructure for capturing, ingesting, cataloging, and retrieving media
artifacts across all of Mike's projects. Not a project itself — consumed by projects.

## Core mental model (v0.5)

An **artifact** is one thing worth cataloging: a photo, a URL, a page save, a song,
a metadata file, a text extract. Artifacts can link via `parent_artifact_id` — a
URL artifact can have children for images, text, and audio — but each child is
addressable on its own.

An artifact has:
- A **lifecycle status** — `inbox` → `vault` → `released` (or `deleted`).
  Archive is orthogonal: a nullable `archived_at` timestamp, not a status
  value.
- A **storage mode** — `vaulted` (MV owns the bytes), `referenced` (MV points at
  your file), `url_only` (no local file).
- **Dates** — `post_date`, `capture_date`, `ingest_date`, plus
  `archived_at` when tucked away.
- **Descriptions** — short, long, extracted text, media type. (Author is a pill,
  not a column — see below.)
- **Tags** — slugged labels grouped into categories. Descriptive. Unlimited. Cheap.
- **A parent** — optional, attached from the vault detail panel (not on intake).

**Pills are categorized.** Each pill belongs to a category (`bands`, `people`,
`places`, `content_kind`, `topic`, `scope`, `rarity`, or `null`). Within a
category, pills can be marked `is_exclusive=1` so the operator can only have one
on at a time (e.g. only one `rarity` value). **Slug uniqueness is global** —
one slug, one tag. Category is descriptive, not identifying.

**Three-state pill model (inbox, session-only).** During review, every pill
is in one of: `on` (confirmed), `suggested` (AI proposed, awaiting a glance),
or `off`. The operator clicks to flip. On save, anything still in `suggested`
is auto-confirmed — the middle state is a review aid only. Nothing about
review state is persisted on the artifact; `artifacts.tags` stores plain
on/off associations.

**Tri-state pills (vault filter).** When filtering the vault, each pill is `off`,
`MUST` (artifact must carry this pill), or `MUST NOT`. Click cycles the state.

**Author convention.** Author is no longer a column. Use a pill in the `author:`
namespace, e.g. `author:carsie_blanton`. The frontend slugifier accepts a single
namespace prefix.

**One-stage tag vocabulary.** Any slug typed in the picker or returned by
enrichment that isn't in the vocabulary is created immediately and applied to
the artifact. There is no proposed/accepted lifecycle — saving an artifact is
the tag's approval. The Vocab Admin panel is the single place where tags get
renamed, merged, rejected, edited, or bulk-deleted.

**Archive.** An artifact in the vault can be archived (set `archived_at` to
a timestamp). Default vault views hide archived rows; a toggle reveals them.
Un-archive is one click. Archived rows keep tags, metadata, and file bytes
intact — only the timestamp changes.

**Attention rules (R1-R5).** Five hardcoded rules in `core/attention_rules.py`
surface "this artifact is missing something" warnings in the inbox. Warnings
are soft — the operator can save anyway. See SPEC.md §X.

## Spec
`SPEC.md` (this folder) — canonical, bumped to v0.5.
`MEDIAVAULT_V05_DESIGN.md` — the full design rationale for v0.5 (pill-state
model, category-scoped exclusivity, attention rules).
`MEDIAVAULT_V04_DESIGN.md` — prior design, still useful as historical ref.
Historical reference: `MediaVault_RS-001_v0.2.docx`.

## Done When
MediaVault is infrastructure. It is never "done." Phases define completion
milestones. The v0.4 refactor (2026-04-17) collapsed 10 `tags_*` columns into
one flat tags array, eliminated the `domain` concept, and introduced explicit
`status` and `storage_mode` columns. The v0.5 refactor (2026-04-19) renamed
`group_name` → `category`, added `is_exclusive` at the pill level, dropped
`author_name` / `tags_permission` / `permission_contact` /
`permission_evidence_path` columns, moved author to the `author:<slug>`
pill convention, added attention rules (R1-R5), and added merge /
bulk-delete / attach-to-parent UI.

The 2026-04-19 decisions (see `_cowork/DECISIONS_2026-04-19_pill_states_and_friends.md`)
correct four v0.5 overreaches that will land as the v0.7 punchlist:
collapse the pill review model from five persisted states to three
session-only states, drop `is_proposed` (one-stage vocabulary), revert
composite `(slug, category)` uniqueness to global slug uniqueness, and
properly wire `archived_at` as saved-but-hidden.

## Projects That Consume This
- Hunter Root — primary driver. All 76 existing artifacts carry the `hunter_root` tag.
- Any new creative project — just tag its artifacts and filter by that tag.
- Genealogy — planned.
- What_Mike_Knows — excluded for now; revisit if integration is low-friction.
