# MediaVault Punchlist — v0.6

**Source:** Mike review session, 2026-04-19 (10 clips covering Inbox + Tag Manager)
**Previous:** `PHASE_SUMMARY_v05.md`
**Status:** Ready for cowork session. Execute in the order below.

---

## Execution Order

1. **[BLOCKER] Backend schema bug** — `group_name` vs `category` mismatch. Unblocks #2 and #6.
2. **Tag Manager: sort + sticky header + clickable columns.** Prerequisite for using the page comfortably during the rest of the cleanup.
3. **Tag Manager: slug-per-category uniqueness + rename/merge logic.** Unblocks author tag cleanup.
4. **Tag data cleanup: author tags.** Remove `(author)` suffix; delete two unwanted author tags.
5. **Top nav + BULK DELETE rework.**
6. **Create Pill dialog fixes** — category pulldown in inbox add-pill; checkbox alignment.
7. **Inbox visual polish** — outline buttons, relocate to top bar, pills panel simplification.

Items 1–4 are functional blockers. Items 5–7 are quality-of-life and can bundle into a single visual pass.

---

## 1. [BLOCKER] Backend schema bug

**Error seen:**
```
Create failed: /api/tag-create 500: {"ok": false, "error": "handler error: table tags has no column named group_name"}
```

**Root cause confirmed:**
```
PRAGMA table_info(tags) →
  slug, display_name, description, category, is_exclusive, is_proposed, usage_count, created_at
```
No `group_name` column exists. The handler is writing `group_name` where it should write `category`.

**Fix:**
- Grep `core/imgserver.py` and `core/imgserver_extensions.py` for `group_name`.
- Replace every write-side reference with `category`.
- Check read-side too — any `row['group_name']` or `row.group_name` needs to become `category`.
- After fix, test both surfaces that hit this:
  - Inbox "+ add pill" field (Clip 4 reproduction case).
  - Tag Manager → + NEW TAG dialog (Clip 9 reproduction case).

**Tests to add:**
- `POST /api/tag-create` with `{slug, display_name, category}` → 200 + row in DB.
- `POST /api/tag-create` with no category → either defaults to uncategorized or returns 400 (pick one and enforce).

---

## 2. Tag Manager — sort, sticky header, clickable columns

**Default sort:** Category ASC, then Display Name ASC.
(Currently appears to be usage DESC, which is disorienting when managing tags by category.)

**Clickable column headers:** Slug, Display Name, Category, Status, Usage.
- First click: sort ASC on that column.
- Second click on same column: sort DESC.
- Third click: return to default sort.
- Show ▲ / ▼ indicator on the active sort column; no indicator on inactive columns.

**Sticky header row:** Currently the header row scrolls with the data (see Clip 6 — "audio" row visible half-tucked under the "Slug" header). Fix:
- `position: sticky; top: 0;` on the header row.
- Header must have a solid background so data rows don't bleed through.
- Confirm no z-index conflicts with the action bar above it.

---

## 3. Tag Manager — slug uniqueness per category + rename/merge

**Current behavior (wrong):** Renaming `author:hunter_root` → `hunter_root` returns 409 `new_slug already exists` because `hunter_root` exists in `bands`. But they're in different categories — this should be allowed.

**Fix A — DB constraint:**
- Slug uniqueness is currently global (slug is the PRIMARY KEY).
- Change to composite uniqueness: `UNIQUE(slug, category)`.
- Migration: confirm no existing cross-category slug collisions before altering. If there are, resolve them first.

**Fix B — `/api/tag-update` handler:**
- On rename, check for collision *within the same category only*.
- If collision found in same category → offer merge (see Fix C).
- If collision found in different category → allow the rename (per Fix A).
- If no collision → rename propagates normally.

**Fix C — Merge-on-duplicate flow:**
When a rename target collides in the same category, show a confirmation dialog:
> *"A tag with slug `hunter_root` already exists in category `people`. Merge into it? All 13 artifacts using `author:hunter_root` will be retagged to `hunter_root`, and `author:hunter_root` will be deleted."*

Buttons: `CANCEL` / `MERGE`.

On merge:
- Reassign all artifacts from source tag to target tag.
- Delete source tag.
- Recompute `usage_count` on target.

**New action — DELETE FROM ALL:**
Per-row action (or selection-based — see item 5). Unassigns the tag from every artifact, then deletes the tag row.
Confirmation: *"This tag is on N artifacts. Remove from all artifacts and delete the tag?"*
Buttons: `CANCEL` / `DELETE`.

**Audit EDIT behavior:**
Mike is concerned EDIT may be branching/duplicating pills. Before touching the UI, grep the handler and confirm: EDIT should open the existing row's properties in a modal (same shape as Create Pill), and Save should UPDATE the same row. If it's creating a new row, that's the bug — fix the handler first. EDIT must never spawn a duplicate.

---

## 4. Tag data cleanup — author tags

**Remove `(author)` suffix from display names:**
The category column already communicates that a tag is in the `people` category. The `(author)` suffix is redundant.

Update display names:
- `author:hunter_root` → display name `Hunter Root` (was `Hunter Root (author)`).
- `author:nick_root` or whatever slug — display name `Nick Root` (was `Nick Root` already per Clip 5, but verify no suffix anywhere).

**Delete two author tags entirely (DELETE FROM ALL):**
- `author:elmthree_productions` (2 artifacts) — remove from all, then delete tag.
- `author:hunterrootofficial` (1 artifact) — remove from all, then delete tag.

**Keep:**
- `author:hunter_root` (13 artifacts, rename display to `Hunter Root`).
- Nick Root tag (1 artifact, already clean).

**Note:** If slug-per-category (item 3) lands first, we can also rename `author:hunter_root` → `hunter_root` in category `people`, which would collide with `hunter_root` (the band/person) in `bands` — but per the new constraint that's fine. Defer this decision until item 3 is in. For now just fix the display names.

---

## 5. Top nav + BULK DELETE rework

**Top nav:**
- **KEEP:** `MEDIAVAULT` logo (left, yellow). `INBOX` / `MEDIAVAULT` tab switcher.
- **DELETE:** `← BACK TO VAULT` button on Tag Manager (the tab switcher handles this).
- **DELETE:** Gear icon (top right).
- **Status dot (green, top right):** If it indicates server-connected state, keep but shrink. If it's decorative, remove.

**BULK DELETE rework:**
Current implementation is unused-only, which isn't useful. Replace with real selection-based delete.

**Primary pattern — checkbox column:**
- Add a leftmost checkbox column to the tag table.
- Header has a "select all visible" checkbox.
- When ≥1 row is selected, a `DELETE SELECTED (N)` button appears where `BULK DELETE` is now.
- Click → confirmation dialog listing the tags (or count + sample if many) → confirms → unassigns from all artifacts, deletes tags.

**Secondary pattern — per-row delete:**
- Add a small × in the Actions column alongside `RENAME` / `EDIT`.
- Same confirmation dialog scaled to one tag.

Implement both. They compose — a user can delete one row with × or several with checkboxes.

---

## 6. Create Pill dialog fixes

**Clip 4 (inbox "+ add pill" field):**
Currently a bare text input at the bottom of the pills panel. Typing a slug and submitting fires `/api/tag-create` with no category → schema error (fixed in item 1) AND no user control over which category the new tag joins.

Replace the bare input with an inline expansion or small modal containing:
- Slug (text)
- Display name (text, auto-filled from slug via title case, editable)
- Category (dropdown — same list as Tag Manager Create Pill dialog)
- Submit

Do NOT let any tag be created without an explicit category choice.

**Clip 8 (Create Pill dialog in Tag Manager):**
- Checkbox placement: both checkboxes (`EXCLUSIVE WITHIN CATEGORY`, `MARK AS PROPOSED`) currently float above their labels. Fix to: `[checkbox] Label text` on a single row, checkbox vertically centered with the label baseline.
- Tighten vertical rhythm — the gap between the checkbox and the description block below it is visually uneven with the rest of the form.

---

## 7. Inbox visual polish

**Clip 1 — Action button styling:**
Convert `SCRAP` / `SAVE TO VAULT` / `RELEASE` to outline style:
- Transparent fill.
- Colored border + colored text (red / amber / green respectively).
- On hover: subtle fill or border brighten.

Reason: filled yellow/green currently reads as state ("this is the current status"), not action. Outline reads as button.

**Clip 2 — Relocate action buttons:**
Move the three action buttons from the right column into the top bar, right side, where the gear was (gear being removed in item 5).
- Left side of top bar: `← PREV` / filename selector / `NEXT →` / "1 of 25" (navigation cluster).
- Right side of top bar: `SCRAP` / `SAVE TO VAULT` / `RELEASE` (decision cluster).

This puts the artifact decision buttons at the visual anchor of the page rather than floating in the right column, and frees the right column for pill work + descriptions.

**Clip 3 — Pills panel simplification:**
- Remove the `PILLS` header.
- Default every category (PEOPLE, BANDS, PLACES, CONTENT_KIND, TOPIC, SCOPE, RARITY) to **expanded** on page load.
- Keep the ▸/▾ toggle for manual collapse.
- Left-justify category titles (no more centered).
- Keep the `0/N` count on the right.

---

## 8d. Vault round-4 — bug fix + panel rearrangement (NEXT SESSION)

**Context:** Items 8, 8b, 8c landed three rounds of iterative Vault feedback. Mike tested 8c, found one data bug and three UI issues, then called a wrap. Pick this up fresh.

**1. [P0 BUG] `/api/artifact-save` 409 on NOT NULL `artifacts.created_at`**

Reproduced by: demote a vault item to inbox, edit it in the inbox form, click SAVE TO VAULT. Server returns:
```
{"ok": false, "error": "db integrity: NOT NULL constraint failed: artifacts.created_at"}
```
Hypothesis: the save path in `core/imgserver.py::handle_artifact_save` is taking the INSERT branch for an already-existing artifact id (the demote preserved the id) and the INSERT statement doesn't populate `created_at`. The UPDATE branch probably should fire.

Investigation plan:
- Read `handle_artifact_save` fully. Find the branch that decides INSERT vs UPDATE.
- Check `artifact_requeue` — does it clear or preserve the id on the artifact row when demoting?
- Check schema for `artifacts.created_at` default — if there's no DEFAULT, every INSERT must explicitly pass it.
- Fix: either UPDATE on id-exists, or always bind `created_at=COALESCE(existing, now())` in the INSERT.
- Smoke test: demote → edit → resave → verify new row is consistent, old queue row cleared.

**2. [C2] Vault side panel always visible (frame persists)**

Current: `#vaultDetail` toggles `display:none` / `.open` based on whether an artifact is selected. Grip and panel appear together when you click a row.

Target: panel frame is **always rendered** at its resting width. When nothing is selected, show a minimal placeholder ("Select an artifact"). No pop-in/pop-out.

Touch points:
- `#vaultDetail` CSS: drop the `display:none` / `.open { display:block }` pair; use `display:block` permanently.
- `#vaultDetailGrip` CSS: same — grip is always visible.
- `selectArtifact(id)` / `closeDetail()`: no longer toggles visibility, only the content.
- `renderDetail(id)`: keep. Add a `renderDetailEmpty()` for the no-selection state.

**3. [C3] Move action cluster from side panel into top bar**

Current: SCRAP / DEMOTE / RELEASE-toggle / ARCHIVE live as a sticky row at the top of `#vaultDetail`.

Target: these four buttons live in the top bar `.tabActions[data-for="vault"]` cluster, immediately after the existing `search` + `GRID` + `TABLE` + count group. When no artifact is selected, the four buttons are hidden (or disabled with an "—" state).

Touch points:
- HTML: add a `<span id="vaultArtifactActions">` inside the vault tabActions; render its contents from `renderDetail` / a sibling helper tied to `CURRENT_ARTIFACT_ID`.
- Remove the `.dActionsTop` block from the side-panel template.
- Reuse the existing `btnScrap` / `btnDemote` / `btnRelease{.on}` / `btnArchive` CSS — just rehomed.
- Hook the show/hide into `selectArtifact` and `closeDetail`.

**4. [C4] Rethink tag-click-to-remove in the side panel**

Mike's verdict on the click-to-pending-remove implementation: "Wrong. Just wrong." No detail yet. Ask him at the start of next session which interaction he actually wants — options to offer:
- hover shows an `×` on each pill, click × removes (matches the inbox applied-pills pattern)
- right-click / long-press menu (Remove tag / Rename / etc.)
- shift-click to mark, batch remove on an explicit "Apply" button
- single click with immediate commit + toast with "undo" (no pending state)

Revert the current click-to-pending-remove code while waiting on the answer — current behavior likely misfires any time he means to read a tag.

**5. [C4 related] Verify pill wall is still visible in the inbox form**

Mike's screenshot of the scrolled-down inbox form captured no pill wall. Likely just scroll position (pills are above the form), but worth confirming: with `<details id="descDetails">` now `open` by default, does the form push the pill wall out of the viewport in a way that's confusing? If so, consider pinning the pill wall to the top of the right column (sticky) or moving it below the form.

**6. Follow-up sanity pass after all the above**

- Demote → edit → save → verify.
- Panel always visible across artifact selection and tab switches.
- Action cluster in top bar reacts to selection state.
- Inbox still shows only active queue rows (`pending` + `enriched`) — regression check on the 8c filter.
- `node --check` extracted inline JS.

---

## Open questions for Mike

None blocking — all decisions captured above. Flag if any of these need a revisit:

- Button placement in top bar (item 7, Clip 2): decision cluster on **right** side — confirm.
- Status dot (item 5): decorative or functional? Decides keep/remove.
- Slug-per-category migration (item 3): any existing cross-category slug collisions to resolve before altering constraint?
- **Item 8d #4:** which tag-removal interaction does Mike actually want?
