# MediaVault — Day-to-Day Workflow (v0.5)

This is the operator's flow. For the requirements spec see `SPEC.md`. For the
design rationale see `MEDIAVAULT_V05_DESIGN.md`.

> **Reconciled 2026-04-20** against
> `_cowork/DECISIONS_2026-04-19_pill_states_and_friends.md`: pill review
> is now three session-only states (`on` / `suggested` / `off`) with
> auto-confirm on save; novel pills are applied immediately with no
> proposed/accepted workflow.
>
> **Updated 2026-05-19** (post-Criterion 5): the `archived_at` claim
> above was superseded — archive is `status='archived'`, not a
> timestamp column. The `archived_at` column is retired (present in
> the schema, never written, never read). See `SPEC.md` §4.1.

---

## Starting the system

Double-click **MediaVault** on your desktop. The server starts and the UI
opens in your browser at `http://localhost:51822/`.

The UI has three panes, switched from the top nav:

- **INBOX** — items awaiting review
- **MEDIAVAULT** — the vault itself (everything already saved)
- **⚙ Vocab Admin** — gear icon, top right

---

## The lifecycle

Every artifact lives in exactly one status:

    inbox  →  vault  →  released

- `inbox` — new arrival, not reviewed yet
- `vault` — reviewed, tagged, kept
- `released` — explicitly marked as a finished item (★ badge)

Any vault or released row can also be **archived** — `status` flips to
`archived` and the row is hidden from default views until you toggle
"Show archived" on the filter bar. Archive is reversible with one
click (un-archive flips `status` back to `vault` or `released`).

And carries one storage mode:

- `vaulted` — MediaVault owns the bytes (copied into `catalogs/_assets/`)
- `referenced` — bytes live on disk elsewhere, we only hold a pointer
- `url_only` — no local file, just the source URL

---

## 1. Getting artifacts in

**Drop folder.** Put files into `C:\AI\Platform\MediaVault\intake\drop\`
or the screenshot folder. Then run:

    python C:\AI\Platform\MediaVault\core\ingest_engine.py scan

Each new file becomes an inbox queue item.

**URL paste.** In the Inbox, click **+ Add URL**, paste, save. The record
lands as `url_only` unless you change the storage mode. (Note: in v0.5
this control is on the to-do list — for now use the API or the FB bridge.)

**Capture JSON (bulk).** For large external captures:

    python ingest_engine.py scan --capture-json path\to\capture.json

**FB Candidates bridge.** In `fb_candidates.html`, open an accepted
candidate. The **→ Send to MediaVault Inbox** button (top right, gold)
creates a queue item in the Inbox and marks the candidate graduated.

**Browser extension capture.** When `ingest_source = 'extension-capture'`,
attention rule R4 reminds you to scope the artifact (add a `scope` pill
like `hunter_root` or `personal`).

---

## 2. Working the Inbox (v0.5 layout)

Each queue item shows up in the Inbox pane with:

- **Left:** the viewer — image preview or URL preview, plus the AI bar
  with **Enrich with AI** button.
- **Right (top):** the action bar — **Scrap / Save to Vault / Release** —
  always visible.
- **Right (middle):** the **Pill wall** — the primary tagging UI. Pills
  are grouped into collapsible sections by category:
    People · Bands · Places · Content kind · Topic · Scope · Rarity ·
    Uncategorized.
  An **+ add pill** input sits below the pill wall.
- **Right (bottom):** **Descriptions ▾** — collapsed by default. Expand
  to edit short / long / extracted text / notes / source URL / platform /
  dates / storage mode / media type.

### Pill states (inbox, session-only)

Every pill has one of three states for the artifact you're reviewing:

| State | Visual |
|---|---|
| `on` | Solid gold |
| `suggested` | Solid gold with dashed inner border (AI proposed, waiting for a glance) |
| `off` | Outline / absent |

Clicking a pill flips it: `on` → `off`; `suggested` → `on` (first click
confirms) → `off` (second click drops it); `off` → `on`.

The state only exists during the review session — it's not saved to the
database. When you click **Save**, anything still in `on` or `suggested`
is written to the artifact's tag array (the middle state is auto-confirmed
on save). No provenance (AI vs. manual) is kept; a tag on an artifact is
just a tag on an artifact.

### Adding a new pill

Type a slug into the **+ add pill** input. Matching pills appear in a
dropdown; press Enter on a match to apply it.

If you type something that's not in the vocabulary, pressing Enter creates
the tag in the vocabulary immediately and applies it as `on`. There's no
separate review step — Vocab Admin is where you rename, merge, or delete
tags later, but the tag is live the moment you save. Since slug uniqueness
is global, typing an existing slug under a new category just surfaces the
existing tag; there's never ambiguity about which `foo` you meant.

The slugifier accepts a single `namespace:` prefix, e.g.
`author:carsie_blanton` or `song:atomic_7`.

### Author convention

In v0.5, author is a pill, not a column. Use `author:<slug>`, e.g.
`author:carsie_blanton`. Old `author_name` values from v0.4 enrichment data
are auto-synthesized into pills with state `suggested` so you can review
them.

### Attention rules (R1-R5)

When something looks missing, the relevant control or section header glows
red:

- R1 — social-platform post (FB / IG / TikTok / Reverbnation) but no
  post date.
- R2 — top-level photo or video but no `content_kind` pill on (e.g.
  `live_show`, `studio_photo`).
- R3 — description mentions a Title-Case bigram (looks like a name) but
  no `people` or `bands` pill on.
- R4 — extension capture but no `scope` pill on (which project does this
  belong to?).
- R5 — pills are on but `media_type` is empty.

Warnings are **soft**. You can save anyway. The glow just nudges you.

### Actions

- **Scrap** — removes the queue row. Original file is untouched.
- **Save to Vault** — creates an artifact record with `status='vault'`,
  applies your pills (on + suggested → written to `artifacts.tags`),
  generates a thumbnail. No session state is persisted.
- **Release** — same as Save, then immediately flips to
  `status='released'`. The queue row is removed.

---

## 3. Browsing the Vault

Open the **MEDIAVAULT** pane.

### Filter bar

- **Search** — full-text over description, extracted text, source URL, notes
- **Date range** — capture or post date
- **Status** — default is `vault + released`
- **Storage mode**
- **Pill pills** — tri-state per pill:
  - click once: **MUST** (included)
  - click twice: **MUST NOT** (excluded)
  - click a third time: **off**
- **Show children** — toggle to reveal child artifacts (defaults off)
- **Sort** dropdown
- **Grid / Table** toggle

### Reading the grid

Each card shows the thumbnail, short description, and badges:

- ★ released
- 📁 vaulted
- ↗ referenced
- 🔗 url_only

Click a card to open the detail panel.

### Detail panel

All fields are edit-in-place. Buttons:

- **Release** / **Unrelease** — toggle between `vault` and `released`
- **Archive** / **Unarchive** — flip `status` to `archived` or back to
  `vault` / `released`. Archived rows are hidden from default views;
  un-archiving brings them back. `released_at` / `released_by` are
  preserved across an archive cycle, so an archived row remembers
  whether it had been released.
- **Attach to parent** (new in v0.5) — opens a searchable modal of
  candidate parents. Self and descendants are excluded automatically.
- **Detach** — appears only if the artifact has a parent set.
- **Edit pills** — applies the pill picker to the artifact.

(The author edit field was removed in v0.5 — change author by editing the
artifact's `author:<slug>` pill.)

---

## 4. Vocab Admin (v0.5)

Open via the gear icon top-right.

Table columns: slug, display name, **category**, **excl.** (★ if
exclusive), usage count, actions.

Filter row: **ALL / UNUSED**. (No proposed/accepted split — one-stage
vocabulary.)

Per-pill controls:

- **Rename** — change the slug (rewrites every artifact) or display name.
  If the new slug collides with an existing tag, the UI offers a merge.
- **Reject** — three modes:
  - **Remove** — delete and strip from every artifact.
  - **Replace** — delete and substitute another pill into every artifact.
  - **Deprecate** — keep but hide from picker; existing artifacts retain
    the pill.
- **Edit** — update display name, **category**, **is_exclusive**, or
  description.
- **Delete** — only for pills with `usage_count = 0`.

Top-bar tools (new in v0.5):

- **⇔ Merge** — pick a source pill and a target pill. Every artifact
  carrying source gets target instead; source is deleted. Use this for
  cleanup after operator typos or duplicate concepts (e.g. `liveshow`
  into `live_show`).
- **⌫ Bulk Delete** — checklist of every pill with `usage_count = 0`.
  All / None quick-toggles. Confirm to delete the selected ones.

After a Vocab Admin action, usage counts are recomputed.

---

## 5. Command-line helpers

From `core/`:

    python ingest_engine.py scan        # pull items from drop/screenshot folders into the queue
    python ingest_engine.py process     # generate thumbnails, write EXIF on saved items
    python ingest_engine.py status      # summary: counts by status and storage_mode

---

## 6. Common flows

**"I just captured 50 screenshots."**
scan → Inbox → for each, review the pill wall (the AI's `suggested`
pills are gold/dashed — leave them to accept, or click twice to remove)
→ Save to Vault (or Release for obvious keepers). Anything still
`suggested` at save time is auto-confirmed. Any new pills you typed are
applied immediately; Vocab Admin is where you clean up typos or merges
later.

**"I want to find every released Hunter Root item from 2013."**
MEDIAVAULT pane → pill `hunter_root` = MUST, pill `year_2013` = MUST →
Status = released only → grid.

**"I accepted a post in FB Candidates and want to vault it too."**
Open the candidate → Send to MediaVault Inbox → switch to Inbox → review
the new queue item → confirm pills → Save.

**"The operator typo'd `hunter-rot` instead of `hunter_root` on five items."**
Vocab Admin → ⇔ Merge → source: `hunter-rot`, target: `hunter_root` →
preview shows the affected count → confirm → done.

**"This screenshot is actually a child of MV-20260417-005."**
MEDIAVAULT pane → click the screenshot → click **Attach to parent** →
search "20260417-005" → click the candidate → done. The detail panel now
shows the parent and the parent's detail panel shows this as a child.

**"My pill vocabulary is full of one-off pills I never used."**
Vocab Admin → filter UNUSED → ⌫ Bulk Delete → All → confirm.

**"I want to tuck this old artifact away without scrapping it."**
Vault detail → **Archive**. Sets `status='archived'`. The row
disappears from default views; toggle **Show archived** on the filter
bar to find it again, then **Unarchive** to bring it back.
