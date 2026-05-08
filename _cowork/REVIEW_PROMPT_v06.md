# MediaVault — Full Codebase Review

**Session type:** Code review. Read-only. No implementation.
**Scope:** The entire MediaVault codebase at `C:\AI\Platform\MediaVault\`.
**Exclusion:** The Chrome extension (`wb_capture_ext`) is out of scope for this session.

---

## Your Role

You are a code reviewer. You are NOT implementing anything. You are NOT proposing patches. You are reading the codebase end-to-end and producing a single findings document.

Mike's concern: the codebase has grown fast across many sessions with multiple agents. He suspects tangles — duplicated logic, schema drift, handlers that evolved out of sync with their callers, dead code from earlier versions. He wants a fresh expert read of the whole thing, not just recent changes.

---

## Before You Start

1. Check `C:\AI\BUILD_LOCK.txt`. If locked, stop and tell Mike. If unlocked, leave it alone — this session is read-only and does not need the lock.
2. Read in this order, for orientation:
   - `C:\AI\VISION.md` — what Weird.Baby is, why MediaVault exists within it.
   - `C:\AI\Platform\MediaVault\_cowork\PHASE_SUMMARY_v05.md` — what v0.5 shipped.
   - `C:\AI\Platform\MediaVault\_cowork\PHASE_SUMMARY_v06.md` — what v0.6 shipped (if present).
   - `C:\AI\Platform\MediaVault\_cowork\PUNCHLIST_v06.md` — the v0.6 intent spec.
   - Any design review document Mike has filled in recently in `_cowork\` — treat as intent signal, not ground truth.
3. Then enumerate the codebase:
   ```powershell
   Get-ChildItem C:\AI\Platform\MediaVault\ -Recurse -File |
     Where-Object { $_.FullName -notmatch '\\(node_modules|\.git|__pycache__|\.venv)\\' } |
     Select-Object FullName, Length
   ```
4. Read every Python file, every HTML template, every JS file (excluding the Chrome extension). Read the schema. Read the migration scripts if any exist.

Never skim. If a file is long, read it completely. If you find yourself summarizing without having read, stop and read.

---

## The Three Passes

These are reading lenses, not separate reports. You will read the codebase once, holding all three in mind, and organize findings by which pass surfaced them.

### Pass 1 — Architecture coherence

Does the codebase make sense as a whole?

- Does each file have one clear responsibility, or have some files accreted multiple roles over time?
- Are `core/imgserver.py` and `core/imgserver_extensions.py` separated on a real architectural boundary, or is the split arbitrary?
- Does `register_artifacts.py` overlap with the ingest engine's responsibilities? If so, where and how?
- Are there patterns that appear in one module and should appear in others but don't?
- Are there patterns that appear in multiple modules inconsistently?
- Where is the code organized around a concept that no longer matches the current mental model? (e.g., code structured around "posts" when the current model is "artifacts")

### Pass 2 — Data layer integrity

The `group_name` vs `category` bug (fixed in v0.6) means at some point the schema and a handler drifted and nothing caught it. That is a symptom, not a one-time accident. How much more drift is present?

- For every table in the schema: list its columns. For each column, find every handler that writes it and every handler that reads it. Flag columns written but never read, or read but never written.
- For every handler that touches the DB: list the columns it writes and reads. Flag any column name that doesn't exist in the target table.
- Are there tables that were load-bearing in an earlier version and now just accumulate rows nobody queries?
- Are there places where the same conceptual operation (create a tag, link an artifact to a tag, update usage counts) is implemented more than once with diverging logic?
- Are migrations being done by hand, and if so, what's the risk of future drift?
- Is `usage_count` computed correctly everywhere it's maintained, or are there paths that update a tag without touching the count?

### Pass 3 — Surface consistency

MediaVault has multiple surfaces that operate on the same data: the Inbox, the Tag Manager, the Artifact renderer (`hr_manager_renderer.js`), and the capture → ingest pipeline. Do they agree?

- When the Inbox creates a tag vs when the Tag Manager creates a tag — is it the same code path, or two implementations that happen to agree most of the time? Where do they diverge?
- When the Inbox assigns a tag to an artifact vs when bulk operations do the same — same path? Diverging validation?
- Does the renderer handle every artifact kind the ingest pipeline can produce? Any kinds the pipeline can produce that the renderer breaks on?
- Are there fields the capture extension sends that the backend ignores? Fields the backend expects but no surface populates?
- Any place where the UI displays a piece of state that the backend doesn't actually maintain, or vice versa?

---

## Output

One document at:
`C:\AI\Platform\MediaVault\_cowork\REVIEW_v06.md`

Structure:

```
# MediaVault Full Codebase Review

## Summary
(3-5 sentences. Overall health. Not a rating — a characterization.
"The data layer is largely consistent but has two drift points.
The UI-to-backend contract has diverged in three places. Ingest is clean.")

## Findings

### Architecture
- Finding title
  - File: `path/to/file.py:142`
  - What's there
  - Why it's a finding (observation, not judgment)
  - Related findings, if any

(repeat)

### Data layer
(same format)

### Surface consistency
(same format)

## Intent ambiguities
(If the design review document or PUNCHLIST_v06 flagged places where
intent was unclear from code — reproduce those here with what the code
reveals about plausible interpretations. Do not pick one.)

## Things that look deliberate and correct
(Short section. Places where the code does something non-obvious that,
on reading, is clearly intentional and well-reasoned. This prevents
future review sessions from "fixing" things that aren't broken.)
```

---

## Rules

- **No patches. No diffs. No "fixed versions."** Findings only.
- **No severity ranking, no scoring, no priority.** Mike will triage.
- **Cite file and line for every finding.** "The tag system has inconsistencies" is useless. "`imgserver.py:847` writes `category` but `imgserver_extensions.py:223` writes `category_name`" is actionable.
- **Observations, not judgments.** "This function is called from two places with different assumptions about X" — not "this function is badly designed."
- **If you find yourself writing a finding without having read the relevant file, stop and read it.** Memory is not evidence.
- **Read the whole codebase.** Not "the important parts." The whole thing. Dead files reveal history; obvious-looking files sometimes hide the sharpest findings.
- **When done, do nothing else.** Do not start implementing. Do not propose a v0.7 punchlist. Do not touch the build lock. Output the review document and stop.
