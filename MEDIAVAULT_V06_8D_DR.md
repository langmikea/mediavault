# MediaVault v0.6 — Session 8d Design Review

**Status:** draft for Mike's decisions
**Scope:** four design questions that surfaced during 8d polish rounds. None can be patched cleanly without a decision first.
**How to use:** read each section, pick an option (or propose your own), fill in the "Decision" line. I implement from there.

---

## 1. Pill lifecycle

### Context

Today a pill has 5 states (`on_confident`, `on_uncertain`, `off_suspected`, `off_maybe`, `unset`). Clicking cycles through states locally. Nothing persists to the server until the user hits **SAVE TO VAULT** (inbox) or — for vault — it's actually unclear; I haven't found a save trigger on vault pill clicks.

The accumulated view filters `TAG_LIST` where state is `on_*`. The per-category sort puts `on_*` first, so a state change moves the pill. On reload, the server returns committed state, so any uncommitted clicks vanish.

### Problem you hit

You clicked an applied pill in the vault accumulated view. It disappeared (confusing — looked like removal). You reloaded. It came back (confusing — looked like the click didn't work). Between those two moments, the pill's position in the subgroup changed.

Three symptoms, one missing concept: **when does a click become real?**

### Decisions

**Q1.1 — When does a pill click commit to the server?**

- **A. Immediately on click** — no pending state, no ghost. Click = save. Reload reflects truth. Simplest model.
- **B. On navigate away from the artifact** — click stages a pending change (ghost visual), navigating to another artifact or closing the detail flushes. Reload before navigating loses the change.
- **C. On explicit save only** — today's inbox model. Vault would need a save button.
- **D. Auto-debounced** — click stages, a 2s timer after the last click flushes. Compromise between A and B.

**My recommendation: A for vault, C for inbox.** Vault artifacts are already curated; pill toggles there are small edits that should feel direct. Inbox is a staging area where batch editing before commit makes sense.

**Decision:** ______

**Q1.2 — Do we keep the 5 pill states or simplify?**

The 5-state model is rich but almost nobody uses `off_suspected` / `off_maybe` in practice (based on what I see in the DB; confirm with your own usage).

- **A. Keep all 5** — current behavior.
- **B. Collapse to 3**: `on_confident`, `on_uncertain`, `off` (unset).
- **C. Collapse to 2**: `on`, `off`.

**My recommendation: B.** `off_suspected` and `off_maybe` were useful when AI proposed and you were triaging; now that author-pill AI proposal is gone, the negative-side states add complexity without use. Uncertain still matters as a "flag for later review" bucket.

**Decision:** ______

**Q1.3 — Sort key within a category (what determines pill order)?**

- **A. Usage count desc, then alphabetical** — common pills first.
- **B. Alphabetical only** — predictable.
- **C. State rank first, then usage** — today's behavior (causes position jumps).

**My recommendation: A, and stable regardless of state.** Pills don't move when toggled.

**Decision:** ______

**Q1.4 — "Ghost" visual (only relevant if Q1.1 picks B, C, or D)**

- **A. Reduced opacity (60%)**
- **B. Dashed border**
- **C. Strikethrough text**
- **D. Different color (muted gold)**

**My recommendation: A + B.** Opacity alone is subtle; the dash signals "staged" unambiguously.

**Decision:** ______

---

## 2. Storage semantics

### Context

Three modes exist today:

| Mode | What's stored locally | Survives source deletion? |
| --- | --- | --- |
| `vaulted` | Raw file copied to `catalogs/vaulted/YYYY/MM/<id>.<ext>` | Yes |
| `referenced` | External local file, not copied | Only if you don't move the file |
| `url_only` | Nothing. URL + metadata only | No |

### Problem you hit

The FB video `MV-HR-20260405-004.jpg` has `storage_mode = vaulted` but its `local_asset_path` points at a `.jpg` thumbnail, not the video. If Hunter Root takes the post down, the video is gone. "Vaulted" is lying.

This isn't a bug in one artifact — it's the general ingest behavior for video-type captures.

### Decisions

**Q2.1 — What does "vaulted" mean for video content?**

- **A. Run yt-dlp at ingest** → actually download the video → true `vaulted`. Needs yt-dlp installed, disk space, network dependency at capture time, possible ToS concerns.
- **B. New mode `vaulted_thumb_only`** → thumbnail captured, video is still `url_only`-equivalent for the actual media. UI shows a "video not locally stored" badge. No download.
- **C. User choice at ingest** → an option "also save video?" when you capture a video post.
- **D. Status quo + UI honesty** → keep `vaulted`, but display "thumbnail only, video lives at source" in the detail panel for any vaulted video whose `local_asset_path` doesn't match the `media_type`.

**My recommendation: B.** A is operationally heaviest; D preserves the lie in the data layer. B is honest data + no new dependencies. C is A with a checkbox.

**Decision:** ______

**Q2.2 — What's the real risk profile?**

Knowing the answer changes Q2.1's priority:
- Which platforms do you capture from where posts routinely vanish? (FB, Instagram, TikTok are the usual suspects.)
- How bad is it, for you, if a video disappears? (Catastrophic? Mildly annoying? Fine because you archived elsewhere?)

Not a multiple choice — a paragraph of context would let me weight A vs B correctly.

**Decision / context:** ______

**Q2.3 — Existing vaulted-but-thumb-only artifacts**

However we fix Q2.1, there are already video artifacts in the DB with `storage_mode=vaulted` + thumbnail-only local path. Those need a migration:

- **A. Mark them all `vaulted_thumb_only`** (if B wins) during a migration script.
- **B. Leave alone** — only new ingests follow the new rule.
- **C. Run yt-dlp retroactively** (if A wins) to actually vault the videos that are still accessible.

**My recommendation: A or C depending on Q2.1.**

**Decision:** ______

---

## 3. Detail-panel contract

### Context

Inbox and vault both have a right-side detail panel with the pill wall + form fields. They drifted over versions:

- Inbox had `pillAddWrap` input (now removed in this round — good).
- Section ordering differs slightly.
- Vault uses an auto-refresh-on-click model for some fields (I think — needs confirmation).
- Your C7 from the last round: `MEDIA TYPE` is under `STORAGE` which feels wrong.

### Decisions

**Q3.1 — Should inbox and vault detail panels share the same contract?**

- **A. Identical structure, with inbox having extra top bar (SCRAP/SAVE/RELEASE)**.
- **B. Different on purpose** — inbox is "staging/editing", vault is "review/adjust". Keep them different.

**My recommendation: A.** Reduces code surface. Most differences today are historical accidents, not design intent.

**Decision:** ______

**Q3.2 — Section grouping (proposal)**

Current sections: `DESCRIPTIONS`, `SOURCE`, `DATES`, `STORAGE` (contains storage_mode + media_type).

Proposal:

```
IDENTITY      : media_type, post_date, capture_date, post_date_confidence
SOURCE        : source_url, source_platform
DESCRIPTIONS  : short, long, extracted text, notes
STORAGE       : storage_mode, local_asset_path (read-only), thumbnail_path (read-only)
```

`media_type` moves to IDENTITY where it belongs; `STORAGE` becomes about bytes on disk, not metadata.

**Decision: accept / modify / reject:** ______

**Q3.3 — Resizable panel**

- **A. Fixed 420px (today).**
- **B. Drag handle, width persisted in localStorage, min 320, max 800.**
- **C. Two snap widths — narrow (320) and wide (560) — toggled by a button.**

**My recommendation: B.** Mechanically easy, and users know how to use drag handles.

**Decision:** ______

---

## 4. Inbox lifecycle

### Context

Queue items flow: `pending` → (enrich / edit / save) → artifact row + `saved` queue status. Or `skip` (scrapped). Or `requeue` (demoted from vault back to inbox).

Today, field edits are pure local until SAVE TO VAULT. Navigating to another queue item loses pending edits silently. RELEASE vs SAVE TO VAULT difference: I actually don't know what RELEASE does differently — I'd need to check the handler.

### Decisions

**Q4.1 — What does RELEASE mean vs SAVE TO VAULT?**

Genuine question from me. If you can explain in one sentence, I'll document it. If you can't, that's a sign it should be simplified or removed.

**Answer:** ______

**Q4.2 — Navigating away with unsaved edits**

- **A. Silently discard** (today).
- **B. Warn with a dialog** — "You have unsaved changes in this item. Save / discard / cancel?"
- **C. Auto-save on navigate** — no warning.

**My recommendation: B.** A loses work; C is surprising.

**Decision:** ______

**Q4.3 — Empty queue state**

You saw the side panel not clearing when the queue emptied. That's now fixed inline. Separate Q: should the right panel be hidden entirely when there's no selected item, or kept visible but empty?

- **A. Hidden (collapse width to 0).**
- **B. Visible but empty (current, after today's fix).**
- **C. Show a "nothing selected" placeholder with tips.**

**My recommendation: C.** Empty panels feel broken; placeholders feel intentional.

**Decision:** ______

---

## Out of scope for this DR (noted, not decided)

- **`D:\AI_OK_TO_DELETE\mv_launch.ps1` relocation** — operational hygiene, not design. Move it to `C:\AI\Platform\MediaVault\mv_launch.ps1` when convenient.
- **Pending Python edits needing server restart** — `imgserver.py` (tags preservation + category required) and `ingest_engine.py` (no author pills). Restart on your schedule.

---

## What happens after you decide

I read the filled-in doc, estimate the work per section, and propose an ordering (likely: Q1 → Q3 → Q4 → Q2 since Q2 has the longest tail). Each section becomes a session with focused scope, not a patch-whack-a-mole round.
