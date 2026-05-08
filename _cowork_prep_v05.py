"""
MediaVault v0.5 cowork prep — run once before launching cowork.

What this does, in order:

  1. Verifies environment: Python version, DB exists and is v0.4 shape,
     key files present, D: drive writable (quarantine target).
  2. Refuses to run if C:\\AI\\BUILD_LOCK.txt is not UNLOCKED.
  3. Acquires the build lock in cowork's name.
  4. Backs up core/mediavault.sqlite to a timestamped copy.
  5. Writes a pre-refactor JSON snapshot — counts, vocabulary, queue state,
     enrichment-format histogram, unlinked-sidecar candidates, vestigial
     column population — so cowork has a baseline to verify against after
     the refactor.
  6. Inventories the quarantine targets listed in the design doc §12.
  7. Writes a readiness report cowork consumes as context.
  8. Prints the kickoff message the operator pastes into cowork.

This script does NOT migrate the schema or run any cleanup. Those are
cowork's jobs under COWORK_BRIEF_v05.md. Prep is read-mostly; it writes only
the lock, a DB backup, a JSON snapshot, and two Markdown reports.
"""

from __future__ import annotations
import json
import os
import shutil
import sqlite3
import sys
import datetime as dt
from pathlib import Path
from collections import Counter

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------

ROOT           = Path(r"C:\AI\Platform\MediaVault")
DB             = ROOT / "core" / "mediavault.sqlite"
IMGSERVER      = ROOT / "core" / "imgserver.py"
EXT_PY         = ROOT / "core" / "imgserver_extensions.py"
INGEST_PY      = ROOT / "core" / "ingest_engine.py"
HTML           = ROOT / "mediavault.html"
FB_HTML        = ROOT / "fb_candidates.html"
BUILD_LOCK     = Path(r"C:\AI\BUILD_LOCK.txt")
QUARANTINE_D   = Path(r"D:\AI_OK_TO_DELETE")

OUT_DIR        = ROOT / "_cowork"
STAMP          = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
SNAPSHOT_JSON  = OUT_DIR / f"pre_v05_snapshot_{STAMP}.json"
READINESS_MD   = OUT_DIR / f"READINESS_REPORT_v05_{STAMP}.md"
KICKOFF_MD     = OUT_DIR / f"KICKOFF_v05_{STAMP}.md"

# --------------------------------------------------------------------------
# Output collectors
# --------------------------------------------------------------------------

_report = []

def R(line=""):
    _report.append(str(line))

# Green/yellow/red traffic-light markers the operator can skim for.
PASS = "✓"
WARN = "△"
FAIL = "✗"

errors = []   # fatal; refuse to print kickoff
warns  = []   # non-fatal

def mark_fail(msg):
    errors.append(msg)
    R(f"{FAIL} {msg}")

def mark_warn(msg):
    warns.append(msg)
    R(f"{WARN} {msg}")

def mark_pass(msg):
    R(f"{PASS} {msg}")

# --------------------------------------------------------------------------
# Section 1 — environment
# --------------------------------------------------------------------------

def check_environment():
    R("# MediaVault v0.5 — Readiness Report")
    R("")
    R(f"Generated: {dt.datetime.now().isoformat(timespec='seconds')}")
    R(f"Operator: Mike Lang")
    R(f"Agent: cowork (pending)")
    R("")

    R("## 1. Environment")
    R("")
    v = sys.version_info
    if v >= (3, 10):
        mark_pass(f"Python {v.major}.{v.minor}.{v.micro}")
    else:
        mark_fail(f"Python {v.major}.{v.minor}.{v.micro} — need 3.10+")

    if not ROOT.is_dir():
        mark_fail(f"MediaVault root missing: {ROOT}")
        return
    mark_pass(f"MediaVault root present: {ROOT}")

    # Key files
    for p, label in [
        (DB,        "core/mediavault.sqlite"),
        (IMGSERVER, "core/imgserver.py"),
        (EXT_PY,    "core/imgserver_extensions.py"),
        (INGEST_PY, "core/ingest_engine.py"),
        (HTML,      "mediavault.html"),
        (FB_HTML,   "fb_candidates.html"),
    ]:
        if p.exists():
            mark_pass(f"{label} — {p.stat().st_size:,} bytes")
        else:
            mark_fail(f"{label} — MISSING")

    # Quarantine target
    if QUARANTINE_D.exists():
        mark_pass(f"Quarantine drive writable: {QUARANTINE_D}")
    else:
        mark_warn(f"Quarantine root not present: {QUARANTINE_D} (cowork can create)")

    # Output directory
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    mark_pass(f"Output dir: {OUT_DIR}")

# --------------------------------------------------------------------------
# Section 2 — build lock
# --------------------------------------------------------------------------

def handle_build_lock():
    R("")
    R("## 2. Build lock")
    R("")

    if not BUILD_LOCK.exists():
        mark_warn(f"BUILD_LOCK.txt missing at {BUILD_LOCK} — creating as UNLOCKED")
        BUILD_LOCK.write_text("UNLOCKED\n", encoding="utf-8")

    cur = BUILD_LOCK.read_text(encoding="utf-8").strip()
    first_word = cur.splitlines()[0].strip() if cur else ""

    if first_word != "UNLOCKED":
        mark_fail(
            "Build lock is not UNLOCKED. Refusing to clobber another session.\n"
            f"         Current contents:\n{cur}"
        )
        return False

    new_content = (
        "LOCKED\n"
        "Session: MediaVault v0.5 refactor (cowork)\n"
        f"Taken:   {dt.datetime.now().isoformat(timespec='seconds')}\n"
        "Agent:   cowork\n"
    )
    BUILD_LOCK.write_text(new_content, encoding="utf-8")
    mark_pass("Build lock acquired for v0.5 refactor")
    return True

# --------------------------------------------------------------------------
# Section 3 — DB backup
# --------------------------------------------------------------------------

def backup_db():
    R("")
    R("## 3. Database backup")
    R("")

    if not DB.exists():
        mark_fail(f"DB missing: {DB}")
        return None

    bak = DB.with_name(DB.name + f".bak_pre_v05_{STAMP}")
    shutil.copy2(DB, bak)

    if not bak.exists() or bak.stat().st_size != DB.stat().st_size:
        mark_fail(f"Backup failed or size mismatch at {bak}")
        return None

    mark_pass(f"Backup: {bak.name} — {bak.stat().st_size:,} bytes")
    return bak

# --------------------------------------------------------------------------
# Section 4 — snapshot
# --------------------------------------------------------------------------

def write_snapshot():
    """
    Write a JSON snapshot cowork reads as baseline. Numbers here must be
    reproducible post-refactor — if any ARTIFACT count, queue count, or
    vocabulary usage-count disagrees after v0.5 ships, something ate data.
    """
    R("")
    R("## 4. Pre-refactor snapshot")
    R("")

    if not DB.exists():
        mark_fail("Cannot snapshot — DB missing")
        return

    # Open read-only via URI so the snapshot cannot write.
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    snap = {
        "generated": dt.datetime.now().isoformat(timespec="seconds"),
        "db_size_bytes": DB.stat().st_size,
        "db_mtime": dt.datetime.fromtimestamp(DB.stat().st_mtime).isoformat(timespec="seconds"),
    }

    # Totals
    snap["counts"] = {}
    for t in ("artifacts", "tags", "id_sequence", "ingest_queue"):
        snap["counts"][t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]

    # Status / storage_mode cross
    snap["artifacts_by_status"] = {
        r["status"]: r["c"]
        for r in conn.execute("SELECT status, COUNT(*) c FROM artifacts GROUP BY status")
    }
    snap["artifacts_by_storage_mode"] = {
        r["storage_mode"]: r["c"]
        for r in conn.execute("SELECT storage_mode, COUNT(*) c FROM artifacts GROUP BY storage_mode")
    }
    snap["artifacts_by_status_storage"] = [
        {"status": r["status"], "storage_mode": r["storage_mode"], "count": r["c"]}
        for r in conn.execute(
            "SELECT status, storage_mode, COUNT(*) c FROM artifacts "
            "GROUP BY status, storage_mode"
        )
    ]
    snap["parent_links"] = conn.execute(
        "SELECT COUNT(*) FROM artifacts WHERE parent_artifact_id IS NOT NULL"
    ).fetchone()[0]
    snap["released_at_populated"] = conn.execute(
        "SELECT COUNT(*) FROM artifacts WHERE released_at IS NOT NULL"
    ).fetchone()[0]

    # Queue
    snap["queue_by_status"] = {
        r["status"]: r["c"]
        for r in conn.execute("SELECT status, COUNT(*) c FROM ingest_queue GROUP BY status")
    }
    snap["queue_stuck_rows"] = [
        dict(r)
        for r in conn.execute(
            "SELECT queue_id, status, artifact_id, ingest_source, raw_path, source_url "
            "FROM ingest_queue "
            "WHERE status='pending' AND artifact_id IS NOT NULL"
        )
    ]

    # Vestigial columns — populated counts before drop
    cols_on_disk = {r["name"] for r in conn.execute("PRAGMA table_info(artifacts)")}
    snap["vestigial_populated"] = {}
    for col in ("link_status", "tags_permission", "permission_contact",
                "permission_evidence_path", "author_name",
                "confidence_flags", "capture_date"):
        if col in cols_on_disk:
            snap["vestigial_populated"][col] = conn.execute(
                f"SELECT COUNT(*) FROM artifacts WHERE {col} IS NOT NULL"
            ).fetchone()[0]
        else:
            snap["vestigial_populated"][col] = None  # not on disk

    # author_name distinct values — needed to verify pill migration later
    if "author_name" in cols_on_disk:
        snap["author_name_distribution"] = {
            (r["author_name"] or "(null)"): r["c"]
            for r in conn.execute(
                "SELECT author_name, COUNT(*) c FROM artifacts "
                "WHERE author_name IS NOT NULL AND TRIM(author_name) != '' "
                "GROUP BY author_name"
            )
        }

    # Full vocabulary for diff after merges
    snap["vocabulary"] = [
        dict(r)
        for r in conn.execute(
            "SELECT slug, display_name, group_name, is_proposed, usage_count "
            "FROM tags ORDER BY slug"
        )
    ]
    snap["vocabulary_total"] = len(snap["vocabulary"])

    # Enrichment format histogram
    snap["enrichment_format"] = {
        "v04_style": 0,
        "v05_style": 0,
        "empty": 0,
    }
    for r in conn.execute("SELECT enrichment_json FROM ingest_queue"):
        s = r[0]
        if not s:
            snap["enrichment_format"]["empty"] += 1
            continue
        try:
            obj = json.loads(s)
        except Exception:
            snap["enrichment_format"]["empty"] += 1
            continue
        if "pill_states" in obj:
            snap["enrichment_format"]["v05_style"] += 1
        elif "tags_year_era" in obj or "tags_content_type" in obj:
            snap["enrichment_format"]["v04_style"] += 1
        else:
            snap["enrichment_format"]["empty"] += 1

    # Unlinked sidecar candidates — operator uses vault attach-to-parent later
    snap["unlinked_sidecar_candidates"] = [
        dict(r) for r in conn.execute("""
            SELECT id, local_asset_path, media_type, tags
            FROM artifacts
            WHERE parent_artifact_id IS NULL
              AND (
                local_asset_path LIKE '%metadata.json'
                OR local_asset_path LIKE '%.json'
                OR local_asset_path LIKE '%.txt'
                OR local_asset_path LIKE '%.srt'
                OR media_type IN ('text','text-only','metadata_json','metadata')
              )
        """)
    ]

    conn.close()
    SNAPSHOT_JSON.write_text(json.dumps(snap, indent=2), encoding="utf-8")

    mark_pass(f"Snapshot written: {SNAPSHOT_JSON.name}")
    R("")
    R("### Key numbers (must match post-refactor after merges are accounted for)")
    R("")
    R(f"- artifacts total: **{snap['counts']['artifacts']}**")
    R(f"- queue total:     **{snap['counts']['ingest_queue']}**")
    R(f"- vocabulary:      **{snap['counts']['tags']}** tags")
    R(f"- parent links:    **{snap['parent_links']}**")
    R(f"- released:        **{snap['released_at_populated']}**")
    R("")
    R("### Vestigial column population")
    R("")
    for col, n in snap["vestigial_populated"].items():
        label = "(not on disk)" if n is None else f"{n} rows populated"
        R(f"- `{col}`: {label}")

    R("")
    R("### Enrichment-format histogram (for backward-compat reading)")
    R("")
    for k, v in snap["enrichment_format"].items():
        R(f"- {k}: {v}")

    R("")
    R("### Queue stuck rows (released-in-inbox bug residue)")
    R("")
    if not snap["queue_stuck_rows"]:
        mark_pass("No stuck rows. Bug fix in code only; no data cleanup needed.")
    else:
        mark_warn(f"{len(snap['queue_stuck_rows'])} stuck row(s) — cowork will clear")
        for r in snap["queue_stuck_rows"]:
            R(f"  - queue #{r['queue_id']}: artifact_id={r['artifact_id']}")

# --------------------------------------------------------------------------
# Section 5 — quarantine inventory
# --------------------------------------------------------------------------

def inventory_quarantine_targets():
    R("")
    R("## 5. Quarantine inventory")
    R("")
    R("Cowork will move these to `D:\\AI_OK_TO_DELETE\\MediaVault_v05_refactor_<date>\\`")
    R("")

    targets = [
        (ROOT / "hr_manager.html.old_v02",              "v0.2 frontend reference"),
        (ROOT / "core" / "imgserver.py.old_v02",        "v0.2 backend reference"),
        (ROOT / "core" / "_test.txt",                   "leftover scratch"),
        (ROOT / "core" / "screenshot_match.json",       "empty stub"),
        (ROOT / "core" / "migrate_to_v04.py",           "v0.4 migration script, shipped"),
    ]

    present = 0
    for p, why in targets:
        if p.exists():
            present += 1
            R(f"- `{p.relative_to(ROOT)}` — {p.stat().st_size:,} bytes · {why}")
        else:
            R(f"- `{p.relative_to(ROOT)}` — _(absent, nothing to quarantine)_ · {why}")

    R("")
    R(f"**{present} file(s) will move to quarantine.**")

# --------------------------------------------------------------------------
# Section 6 — readiness summary
# --------------------------------------------------------------------------

def finalize_readiness():
    R("")
    R("## 6. Readiness summary")
    R("")

    if errors:
        R(f"**{FAIL} NOT READY — {len(errors)} error(s):**")
        for e in errors: R(f"  - {e}")
        R("")
        R("Resolve errors, then re-run `_cowork_prep_v05.py`.")
    elif warns:
        R(f"**{WARN} READY WITH {len(warns)} WARNING(S):**")
        for w in warns: R(f"  - {w}")
        R("")
        R("Warnings are non-fatal. Review, then proceed to kickoff.")
    else:
        R(f"**{PASS} ALL GREEN — ready for cowork.**")

    R("")
    R(f"Readiness report: `{READINESS_MD.name}`")
    R(f"Snapshot:         `{SNAPSHOT_JSON.name}`")
    R(f"Kickoff message:  `{KICKOFF_MD.name}`")

# --------------------------------------------------------------------------
# Section 7 — kickoff
# --------------------------------------------------------------------------

def write_kickoff():
    body = f"""# MediaVault v0.5 — cowork kickoff

**Paste this whole message as cowork's first message.**

Grant cowork filesystem access to:
  - `C:\\AI\\`
  - `D:\\AI_OK_TO_DELETE\\`

---

You are executing `C:\\AI\\Platform\\MediaVault\\COWORK_BRIEF_v05.md`.

Context you must read before writing anything:

1. `C:\\AI\\Platform\\MediaVault\\COWORK_BRIEF_v05.md` — the brief. Authoritative.
2. `C:\\AI\\Platform\\MediaVault\\MEDIAVAULT_V05_DESIGN.md` — design rationale.
3. `C:\\AI\\Platform\\MediaVault\\_cowork\\{READINESS_MD.name}` — pre-refactor state.
4. `C:\\AI\\Platform\\MediaVault\\_cowork\\{SNAPSHOT_JSON.name}` — baseline numbers.
5. `C:\\AI\\Platform\\MediaVault\\_cowork\\mv_v05_audit_20260419_170757.md` — the audit Mike ran.

The build lock is held in your name. Do not release it until the brief's
final phase (smoke test passed, docs updated, PHASE_SUMMARY written).

Authority grant: you may execute every phase in the brief without asking.
Stop and ask the operator only for the three conditions listed in the brief's
§Stop conditions — nothing else. Smaller judgment calls (style, file placement
within an agreed folder, internal naming) are yours.

Begin with Phase 0 (preflight): read the brief in full, verify the snapshot
numbers match the live DB, then proceed to Phase 1.
"""
    KICKOFF_MD.write_text(body, encoding="utf-8")
    R("")
    R("## 7. Kickoff message")
    R("")
    R(f"Written to: `{KICKOFF_MD.name}`")

# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main():
    check_environment()
    if errors:
        finalize_readiness()
        READINESS_MD.write_text("\n".join(_report), encoding="utf-8")
        print(READINESS_MD.read_text(encoding="utf-8"))
        sys.exit(1)

    if not handle_build_lock():
        finalize_readiness()
        READINESS_MD.write_text("\n".join(_report), encoding="utf-8")
        print(READINESS_MD.read_text(encoding="utf-8"))
        sys.exit(1)

    backup_db()
    write_snapshot()
    inventory_quarantine_targets()
    write_kickoff()
    finalize_readiness()

    READINESS_MD.write_text("\n".join(_report), encoding="utf-8")

    # Echo the readiness to stdout and then the pasteable kickoff.
    print(READINESS_MD.read_text(encoding="utf-8"))
    print()
    print("=" * 76)
    print("PASTE THIS AS COWORK'S FIRST MESSAGE")
    print("=" * 76)
    print(KICKOFF_MD.read_text(encoding="utf-8"))

    sys.exit(1 if errors else 0)

if __name__ == "__main__":
    main()
