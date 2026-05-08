# Task — Investigate pill_states

**Status:** Investigation, not implementation yet.
**Context:** Finding from `REVIEW_v06.md` data layer section. Frontend sends `pill_states` on every artifact save. Backend silently drops it. Nothing errors, but data the UI appears to be persisting is not being persisted.
**Intent:** Before fixing, figure out what `pill_states` was *supposed* to do, whether it's still needed, and what the UI is currently doing with values that never round-trip.

---

## Why this one first

Three reasons this finding is the right starting point for post-review work:

1. **It exercises the whole stack.** Frontend → handler → schema → reload → UI display. Fixing or removing it requires touching every layer, which surfaces whether other data-layer findings are entangled with it.
2. **It's silently wrong.** No error is raised. You've been using MediaVault assuming the save button saves everything it shows; it doesn't save this. The scope of the data loss is unknown until investigated.
3. **It's an intent question before it's a technical question.** The answer isn't "patch the handler." The answer is: *is `pill_states` supposed to exist?* That's a decision you make before a single line gets changed.

---

## What the review found

Reproduced here so the task is self-contained. Verify against `REVIEW_v06.md` for exact file:line citations.

- Frontend sends a `pill_states` field in the POST body of the artifact save operation (inbox save flow).
- Backend handler for that endpoint does not read `pill_states` from the body.
- The `artifacts` table has no `pill_states` column.
- SPEC document references `pill_states` but the schema does not implement it.
- No error is raised; the field is accepted at the HTTP layer and discarded at the parse layer.

---

## Investigation — do this before deciding anything

### Step 1 — Reconstruct the intent

Read, in order:

1. The SPEC reference to `pill_states`. What does SPEC say it's for?
2. Every frontend file that constructs, reads, or displays `pill_states`. What values does it take? What does the UI do differently based on those values?
3. `PHASE_SUMMARY_v05.md` and `PHASE_SUMMARY_v06.md` — any mention of `pill_states` being added, deferred, or removed?
4. Search git history (if available) or file timestamps to see when `pill_states` first appeared in the frontend. Was it added alongside a matching backend change that later got reverted, or was it added frontend-only?

Write a short paragraph answering: *what was `pill_states` supposed to let you do, and from which direction — frontend or backend — did the feature come in?*

### Step 2 — Characterize the data loss

For the current session's behavior:

1. Reload the inbox. Pick an artifact. Note which pills are in which state in the UI.
2. Change one pill's state (whatever the UI lets you change — this is what you need to identify in step 1).
3. Save.
4. Reload. Does the pill come back in the state you left it in, or does it revert?

If the state reverts: the feature is visibly broken and you've been re-doing work without realizing it.
If the state persists: something else is providing the persistence (likely a related field that *does* round-trip), and `pill_states` is shadow-data that never mattered. This is the more likely case.

Either answer is useful. Document which.

### Step 3 — Map the field's reach

Grep the codebase for every occurrence of `pill_states` (and any case variants). For each hit, note:

- File and line.
- Is it being written, read, or just passed through?
- Does removing it break anything upstream?

This produces the full map of what a "remove `pill_states`" patch would actually touch, in case that's the decision.

### Step 4 — Check for entangled findings

Before fixing, cross-reference `REVIEW_v06.md`. Any other data-layer findings that touch pill state, pill create, or the inbox save path? The review flagged several pill-related divergences (inbox vs Tag Manager, category rules, CATEGORY_ORDER mismatch). If `pill_states` is entangled with any of those, the fix needs to consider them together — not because they all have to ship together, but because fixing one in isolation could make another worse.

List every related finding and whether it bears on the `pill_states` decision.

---

## The decision (after investigation, not before)

One of three outcomes. The investigation determines which.

**A. Ship it.** `pill_states` is a real feature, the frontend has been sending it, the backend needs to accept it. Add the column to `artifacts`, teach the save handler to read it, teach the load handler to return it, verify round-trip. Remove the SPEC/schema drift.

**B. Remove it.** `pill_states` is dead weight — either a deprecated concept or something that was never finished. Strip it from the frontend, strip the SPEC reference, add a note in a decision log explaining why.

**C. Defer it with a comment.** `pill_states` is a real future feature but not a v0.7 priority. Leave the frontend as-is but add a TODO comment that makes the current state obvious to the next reviewer, so this doesn't get re-discovered in six months as a fresh finding.

Default bias: **B** unless the investigation produces clear evidence for A. Deleted code is easier to re-add than silent-drift code is to debug.

---

## What to produce

A short document at:
`C:\AI\Platform\MediaVault\_cowork\PILL_STATES_INVESTIGATION.md`

Structure:

```
# pill_states — Investigation Findings

## What it was supposed to do
(One paragraph from Step 1.)

## What's actually happening
(Results of Step 2 — does the state revert or persist?)

## Where it lives in code
(Map from Step 3 — every file:line reference.)

## Entanglements
(From Step 4 — related findings that bear on the decision.)

## Recommended decision
(A, B, or C, with reasoning. Do not implement. Mike decides.)
```

Stop there. Do not fix anything. The point of this task is to turn a silent-drift finding into a decidable question, not to ship a patch.

---

## Rules for this session

- Read-only. Same as the review session.
- Do not touch `BUILD_LOCK.txt`.
- Do not modify any file outside `_cowork\`.
- If during investigation you discover another silent-drift finding that REVIEW_v06.md missed, add it to a "Related findings discovered during investigation" section at the end of the investigation doc. Do not chase it in this session.
- When done, stop. No patches, no punchlist, no v0.7 spec.
