# MediaVault v0.5 package — README

Five files. Use them in this order.

## What's in the zip

| File | Role |
|---|---|
| `README.md` | This file. Orientation. |
| `MEDIAVAULT_V05_DESIGN.md` | The thinking. Reasoning for every v0.5 decision, grounded in the audit. |
| `_cowork_prep_v05.py` | Pre-flight script. Acquires build lock, backs up DB, writes snapshot and readiness report, prints kickoff message. |
| `COWORK_BRIEF_v05.md` | Cowork's execution document. Seven phases. Line-number-exact. |
| `deploy_v05_package.py` | This extractor. |

And separately, not in the zip because it lives on your machine already:

- `_cowork/mv_v05_audit_20260419_170757.md` — the audit you ran. Cowork reads
  this as part of Phase 0.

## Execution sequence

1. **Deploy.** Download `files.zip` and `deploy_v05_package.py` to
   `C:\Users\macun\Downloads\`. Run:
   ```
   python "C:\Users\macun\Downloads\deploy_v05_package.py"
   ```
   The four package files land at `C:\AI\Platform\MediaVault\`. Existing files
   at the destination are backed up with a `.pre_v05_<timestamp>` suffix.

2. **Review the design.** Open `MEDIAVAULT_V05_DESIGN.md`. Three sections
   matter most:
   - **§2 Pill states.** The five-state inbox model vs. the tri-state vault
     filter. Same data, different display jobs.
   - **§3 Schema changes.** What drops (`author_name`, `tags_permission`,
     two dead permission columns), what gets renamed (`group_name` →
     `category`), what's added (`is_exclusive`).
   - **§9 The specific cleanup lists.** 14 merges, 38 deletions across
     seven themed groups (dead weight, year pills, visual details, song
     titles, genres, generic, workflow provenance), 5 vocabulary creates,
     and 7-category assignments. This is your review gate. The operator
     has already signed off through two rounds of iteration; flag anything
     that still looks wrong before running prep.

3. **Run prep.** When the design looks right:
   ```
   python "C:\AI\Platform\MediaVault\_cowork_prep_v05.py"
   ```
   Prep does these things:
   - Verifies environment (Python, files present, D: drive, DB shape).
   - Acquires `C:\AI\BUILD_LOCK.txt` in cowork's name. Refuses if someone
     else holds it.
   - Backs up `core/mediavault.sqlite` to `.bak_pre_v05_<stamp>`.
   - Writes `_cowork/pre_v05_snapshot_<stamp>.json` — the baseline
     cowork verifies against after the refactor.
   - Inventories the five quarantine targets.
   - Writes `_cowork/READINESS_REPORT_v05_<stamp>.md`.
   - Writes and prints `_cowork/KICKOFF_v05_<stamp>.md` — the kickoff message
     you paste into cowork.

   If prep reports any `✗` errors, resolve them and re-run. Warnings (`△`)
   are non-fatal; review them and proceed.

4. **Launch cowork.** At session start, grant cowork filesystem access to
   `C:\AI\` and `D:\AI_OK_TO_DELETE\`. Paste the kickoff message as cowork's
   first message.

5. **Walk away.** Cowork runs Phases 0–7. When finished:
   - `C:\AI\BUILD_LOCK.txt` reads `UNLOCKED`.
   - `_cowork/PHASE_SUMMARY_v05.md` has the per-phase report.
   - The v0.4 reference files are quarantined (or flagged if delete
     permission was declined, per v0.4 precedent).

## What v0.5 changes

Summary for fast orientation; the design doc has the full reasoning.

- **Inbox reworked around pills.** Five pill states visualize AI confidence
  and suggestions. Top action bar (Scrap / Save / Save & Release) always
  visible. ID hidden. Descriptions collapsed below pills. Parent-artifact
  linking moved to the vault.
- **Vault: attach-to-parent** via a searchable modal (never type an ID).
- **Vocab Admin: merge + bulk-delete** primary verbs. Conservative cleanup
  runs automatically in Phase 2.
- **Schema: drop `author_name`, `tags_permission`, two dead permission
  columns. Rename `tags.group_name` → `tags.category`. Add `is_exclusive`.**
- **Enrichment prompt rewritten** around "would I search for this someday"
  and emits per-pill confidence tiers.
- **Two bugs fixed:** save-and-release clears the queue row (no data
  cleanup needed — audit §8a confirmed zero stuck rows). `imgserver_extensions.py`
  rewritten against v0.4+ schema so `/api/artifact-register` works again.
- **Two dead routes wired to UI:** `/api/intake-upload` and `/api/intake-url`
  get a drop-file / paste-URL empty-state in the inbox. Previously only
  reachable via the Chrome extension or CLI.

## What v0.5 does NOT change

- IDs. Legacy `MV-HR-*` IDs stay (62 rows). New IDs stay `MV-YYYYMMDD-NNN`.
- `ext/hr_manager_renderer.js` — external, do not modify.
- `fb_candidates.html` — untouched.
- Port, DB filename, sql.js read pattern, aesthetic.
- `ingest_engine.py` CLI surface.
- The 80 artifacts. Every row survives. No data loss.

## Troubleshooting

- **Prep fails with "build lock not UNLOCKED."** Someone else (probably an
  earlier cowork session) holds it. Read `C:\AI\BUILD_LOCK.txt`; if it's
  stale, manually `Set-Content C:\AI\BUILD_LOCK.txt -Value "UNLOCKED"` and
  re-run prep.
- **Prep passes but cowork refuses to start.** Usually a missing filesystem
  grant. Grant `C:\AI\` and `D:\AI_OK_TO_DELETE\` at session start.
- **Cowork stops mid-refactor.** Check `_cowork/PHASE_SUMMARY_v05.md` —
  it updates after each phase. If cowork hit one of the brief's three stop
  conditions, it'll say which.
- **Something looks wrong post-ship.** The pre-v0.5 DB is at
  `core/mediavault.sqlite.bak_pre_v05_<stamp>`. Copy it back over
  `core/mediavault.sqlite` to roll back. The v0.5 frontend will still serve,
  but it'll complain about missing columns until you also revert `imgserver.py`
  from the quarantine copy (if one was made).
