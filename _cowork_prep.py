"""
_cowork_prep.py — MediaVault v0.4 Refactor, Session Prep

Run ONCE before launching cowork. Idempotent, safe to re-run.

What it does:
  1. Acquires the global build lock in cowork's name.
  2. Verifies the environment (Python, DB, paths, imgserver state).
  3. Backs up the canonical DB with a timestamped name.
  4. Quarantines known-dead files to D:\\AI_OK_TO_DELETE\\.
  5. Captures a pre-refactor snapshot for cowork's reference, including:
       - Full DB row counts and schema
       - Sidecar detection with parent-candidate matches
       - Missing asset file detection
       - Tag frequency tabulation (for migration sanity checks)
  6. Writes two files cowork reads at launch:
       - _cowork/READINESS_REPORT.md
       - _cowork/pre_refactor_snapshot.json
  7. Prints a launch checklist with the exact kickoff message.

What it does NOT do:
  - Schema migration (cowork's Phase 1)
  - imgserver.py or mediavault.html rewrite (cowork's Phases 2-3)
  - Any code generation (cowork's job)

Run:
    python "C:\\AI\\Platform\\MediaVault\\_cowork_prep.py"

Exit code: 0 if ready, 1 if blocking failure.
"""

import os
import sys
import shutil
import sqlite3
import json
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------
ROOT         = Path(r"C:\AI\Platform\MediaVault")
CORE_DB      = ROOT / "core" / "mediavault.sqlite"
EMPTY_STUB_1 = ROOT / "mediavault.sqlite"
EMPTY_STUB_2 = ROOT / "mediavault.db"
BUILD_LOCK   = Path(r"C:\AI\BUILD_LOCK.txt")
QUARANTINE_ROOT = Path(r"D:\AI_OK_TO_DELETE")
COWORK_DIR   = ROOT / "_cowork"

TS_COMPACT  = datetime.now().strftime("%Y%m%d_%H%M%S")
TS_DATE     = datetime.now().strftime("%Y%m%d")
TS_READABLE = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# ---------------------------------------------------------------------
# Files to quarantine (from design doc §8)
# Three small utilities (scrap_all.py, core/analyze_captures.py,
# core/dump_paths.py) are KEPT per Mike's v0.4 call. Note dump_paths.py
# is actually on the quarantine list in design doc §8 - it's just a
# debug script. Keep scrap_all and analyze_captures, quarantine the rest.
# ---------------------------------------------------------------------
QUARANTINE_PATTERNS = [
    # Empty stub DBs at root
    "mediavault.sqlite",
    "mediavault.db",
    # .bak files
    "STATE.md.bak",
    "hr_manager.html.bak_*",
    "core/imgserver.py.bak*",
    "core/ingest_engine.py.bak*",
    "core/mediavault.sqlite.bak_*",
    "core/mediavault_backup_*",
    "capture-extension/*.bak*",
    "ui/mediavault_browser.html.bak",
    "ui/mediavault_inbox.html.bak*",
    "ui/recapture_navigator.html",
    # Root one-shot patch scripts
    "fix_ai_final.py",
    "fix_ai_func.py",
    "fix_ai_func2.py",
    "fix_ai_preprocess.py",
    "fix_queue.py",
    "patch_ai.py",
    "check_enriched.py",
    "check_item.py",
    "check_queue.py",
    "check_queue2.py",
    # Core one-shot patch scripts
    "core/patch_capture.py",
    "core/patch_comments.py",
    "core/patch_comments2.py",
    "core/patch_comments3.py",
    "core/patch_image.py",
    "core/patch_scan.py",
    "core/patch_scan2.py",
    "core/fix3.py",
    "core/check3.py",
    "core/dump_paths.py",
    "core/migrate_ingest_source.py",
]

# Entire folders to quarantine
QUARANTINE_FOLDERS = [
    "capture-extension",
]

# Explicitly KEPT (per Mike's v0.4 decisions — these are useful utilities):
#   scrap_all.py                  — queue bulk-skip, useful operational tool
#   core/analyze_captures.py      — debug query for extension captures

# ---------------------------------------------------------------------
# Report collection
# ---------------------------------------------------------------------
report = []
checks = []

def w(s=""):
    print(s)
    report.append(s)

def check(name, status, detail=""):
    checks.append((name, status, detail))
    icon = {"PASS": "✓", "WARN": "⚠", "FAIL": "✗"}[status]
    w(f"  {icon} [{status}] {name}" + (f" — {detail}" if detail else ""))

def has_fails():
    return any(c[1] == "FAIL" for c in checks)


# ---------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------
def step_environment():
    w("## Step 1 — Environment checks")
    w("")

    pyv = sys.version.split()[0]
    if sys.version_info >= (3, 10):
        check("Python version", "PASS", pyv)
    else:
        check("Python version", "FAIL", f"{pyv} (need 3.10+)")

    if ROOT.is_dir():
        check("Project root", "PASS", str(ROOT))
    else:
        check("Project root", "FAIL", f"{ROOT} missing")
        return False

    if CORE_DB.is_file() and CORE_DB.stat().st_size > 1000:
        check("Canonical DB", "PASS", f"{CORE_DB.stat().st_size:,} bytes")
    else:
        check("Canonical DB", "FAIL", "core\\mediavault.sqlite missing or empty")
        return False

    if Path("D:\\").exists():
        check("D: drive", "PASS")
    else:
        check("D: drive", "WARN", "quarantine step will use fallback")

    try:
        t = ROOT / f".perm_test_{TS_COMPACT}"
        t.write_text("ok")
        t.unlink()
        check("Write access to project root", "PASS")
    except Exception as e:
        check("Write access to project root", "FAIL", str(e))
        return False

    try:
        if BUILD_LOCK.exists():
            current = BUILD_LOCK.read_text().strip()
            check("Build lock file", "PASS", f"state: {current[:40]!r}")
        else:
            BUILD_LOCK.write_text("UNLOCKED")
            check("Build lock file", "PASS", "created as UNLOCKED")
    except Exception as e:
        check("Build lock file", "FAIL", str(e))
        return False

    try:
        import urllib.request
        try:
            urllib.request.urlopen("http://127.0.0.1:51822/ping", timeout=1)
            check("imgserver on :51822", "WARN",
                  "RUNNING — stop it before cowork starts schema migration")
        except Exception:
            check("imgserver on :51822", "PASS", "not running (clean state)")
    except Exception:
        check("imgserver on :51822", "WARN", "could not probe")

    return True


def step_build_lock():
    w("")
    w("## Step 2 — Acquire build lock")
    w("")
    current = BUILD_LOCK.read_text().strip()
    if current.upper().startswith("LOCKED") and "cowork" not in current.lower():
        w(f"  Lock currently held: {current!r}")
        w(f"  Refusing to overwrite. Resolve and re-run.")
        check("Build lock acquisition", "FAIL", "held by another session")
        return False

    new_lock = (
        "LOCKED\n"
        "Session: MediaVault v0.4 refactor (cowork)\n"
        f"Taken: {TS_READABLE}\n"
        "By: cowork (prepped by web Claude)\n"
    )
    BUILD_LOCK.write_text(new_lock)
    check("Build lock acquisition", "PASS", "LOCKED for cowork")
    return True


def step_db_backup():
    w("")
    w("## Step 3 — Database backup")
    w("")
    backup_name = f"mediavault.sqlite.bak_v04prep_{TS_COMPACT}"
    backup_path = CORE_DB.parent / backup_name
    try:
        shutil.copy2(CORE_DB, backup_path)
        check("DB backup", "PASS",
              f"{backup_name} ({backup_path.stat().st_size:,} bytes)")
        return str(backup_path)
    except Exception as e:
        check("DB backup", "FAIL", str(e))
        return None


def step_quarantine():
    w("")
    w("## Step 4 — Quarantine dead files")
    w("")

    qdir = QUARANTINE_ROOT / f"MediaVault_v04_refactor_{TS_DATE}"
    try:
        qdir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        check("Quarantine folder creation", "FAIL", str(e))
        return qdir, 0

    moved = 0
    skipped = 0

    for pattern in QUARANTINE_PATTERNS:
        matches = list(ROOT.glob(pattern))
        for src in matches:
            if not src.is_file():
                continue
            rel = src.relative_to(ROOT)
            dest = qdir / rel
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                if dest.exists():
                    dest = dest.with_suffix(dest.suffix + f".{TS_COMPACT}")
                shutil.move(str(src), str(dest))
                moved += 1
            except Exception as e:
                w(f"    skip {rel}: {e}")
                skipped += 1

    for folder_name in QUARANTINE_FOLDERS:
        src = ROOT / folder_name
        if not src.is_dir():
            continue
        dest = qdir / folder_name
        try:
            if dest.exists():
                dest = dest.with_name(dest.name + f"_{TS_COMPACT}")
            shutil.move(str(src), str(dest))
            moved += 1
            w(f"    folder moved: {folder_name}/")
        except Exception as e:
            w(f"    skip folder {folder_name}/: {e}")
            skipped += 1

    # debug_scripts: quarantine contents except README.md
    debug_dir = ROOT / "debug_scripts"
    if debug_dir.is_dir():
        debug_dest = qdir / "debug_scripts"
        debug_dest.mkdir(parents=True, exist_ok=True)
        for f in debug_dir.iterdir():
            if not f.is_file():
                continue
            if f.name.lower() == "readme.md":
                continue
            try:
                shutil.move(str(f), str(debug_dest / f.name))
                moved += 1
            except Exception:
                skipped += 1

    detail = f"{moved} items → {qdir}"
    if skipped:
        detail += f" ({skipped} skipped)"
    check("Quarantine sweep", "PASS", detail)
    return qdir, moved


def step_snapshot(backup_path):
    w("")
    w("## Step 5 — Pre-refactor snapshot")
    w("")
    COWORK_DIR.mkdir(parents=True, exist_ok=True)
    snap = {
        "captured_at": TS_READABLE,
        "schema_target_version": "0.4",
        "db_path": str(CORE_DB),
        "db_size_bytes": CORE_DB.stat().st_size,
        "backup_path": backup_path,
    }

    try:
        c = sqlite3.connect(CORE_DB)
        c.row_factory = sqlite3.Row

        tables = [r[0] for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )]
        snap["tables"] = {}
        for t in tables:
            try:
                n = c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                snap["tables"][t] = n
            except Exception as e:
                snap["tables"][t] = f"ERROR: {e}"
        check("Table inventory", "PASS",
              ", ".join(f"{k}={v}" for k, v in snap["tables"].items()))

        # Existing columns on artifacts (for migration to reference)
        snap["artifact_columns_before"] = [
            r[1] for r in c.execute("PRAGMA table_info(artifacts)").fetchall()
        ]

        # Distinct-value tabulations for each tag column
        # (these become the starter tag vocabulary)
        tag_columns = [
            "tags_year_era", "tags_content_type", "tags_song_reference",
            "tags_release_stage", "tags_subject", "tags_topic", "tags_rarity",
            "tags_preservation", "tags_permission", "tags_keywords",
        ]
        snap["tag_column_values"] = {}
        for col in tag_columns:
            try:
                rows = c.execute(
                    f"SELECT {col}, COUNT(*) FROM artifacts "
                    f"WHERE {col} IS NOT NULL AND {col} != '' "
                    f"GROUP BY {col} ORDER BY 2 DESC"
                ).fetchall()
                snap["tag_column_values"][col] = [(v, n) for v, n in rows]
            except Exception as e:
                snap["tag_column_values"][col] = f"ERROR: {e}"
        total_distinct = sum(
            len(v) for v in snap["tag_column_values"].values()
            if isinstance(v, list)
        )
        check("Tag column tabulation", "PASS",
              f"{total_distinct} distinct values across {len(tag_columns)} columns")

        # Artifact domain/platform/ingest_source breakdowns
        snap["artifacts_by_domain"] = dict(
            c.execute("SELECT domain, COUNT(*) FROM artifacts GROUP BY domain")
        )
        snap["artifacts_by_platform"] = dict(
            c.execute("SELECT source_platform, COUNT(*) FROM artifacts "
                      "GROUP BY source_platform")
        )
        snap["artifacts_by_ingest_source"] = dict(
            c.execute("SELECT ingest_source, COUNT(*) FROM artifacts "
                      "GROUP BY ingest_source")
        )

        # Queue breakdown
        snap["queue_by_status"] = dict(
            c.execute("SELECT status, COUNT(*) FROM ingest_queue "
                      "GROUP BY status")
        )

        # Sidecar detection (cowork's migration will link these to parents)
        sidecars = c.execute("""
            SELECT id, source_url, local_asset_path, description_short,
                   media_type_in_post, tags_content_type
            FROM artifacts
            WHERE (local_asset_path LIKE '%.json')
               OR (tags_content_type LIKE '%metadata_json%')
               OR (tags_content_type LIKE '%sidecar%')
            ORDER BY id
        """).fetchall()
        snap["sidecar_rows"] = [dict(r) for r in sidecars]
        check("Sidecar rows identified", "PASS",
              f"{len(sidecars)} rows to be linked to parents")

        # For each sidecar, find parent candidates (same source_url, non-.json)
        parent_matches = []
        for s in sidecars:
            if not s["source_url"]:
                parent_matches.append({
                    "sidecar_id": s["id"],
                    "sidecar_short": s["description_short"],
                    "parent_candidates": [],
                    "reason_no_parent": "no source_url"
                })
                continue
            parents = c.execute("""
                SELECT id, local_asset_path, media_type_in_post
                FROM artifacts
                WHERE source_url = ?
                  AND id != ?
                  AND (local_asset_path IS NULL
                       OR local_asset_path NOT LIKE '%.json')
            """, (s["source_url"], s["id"])).fetchall()
            parent_matches.append({
                "sidecar_id": s["id"],
                "sidecar_short": s["description_short"],
                "parent_candidates": [dict(p) for p in parents],
            })
        snap["sidecar_parent_matches"] = parent_matches
        matched = sum(1 for m in parent_matches if m.get("parent_candidates"))
        check("Sidecar parent matching", "PASS",
              f"{matched}/{len(parent_matches)} sidecars have parent candidates")

        # Missing asset files
        with_asset = c.execute(
            "SELECT id, local_asset_path FROM artifacts "
            "WHERE local_asset_path IS NOT NULL AND local_asset_path != ''"
        ).fetchall()
        missing = []
        for r in with_asset:
            p = r["local_asset_path"]
            if p and not Path(p).exists():
                missing.append({"id": r["id"], "missing_path": p})
        snap["missing_asset_files"] = missing
        check("Missing asset files", "PASS",
              f"{len(missing)} of {len(with_asset)} artifacts reference missing files")

        # Storage-mode preview (what migration will assign)
        catalogs_prefix = str(ROOT / "catalogs").lower()
        vaulted_count = 0
        referenced_count = 0
        url_only_count = 0
        for r in c.execute("SELECT source_url, local_asset_path FROM artifacts"):
            lap = (r[1] or "").lower()
            if not lap:
                if r[0]:
                    url_only_count += 1
                else:
                    referenced_count += 1  # orphan case, will be referenced
            elif lap.startswith(catalogs_prefix):
                vaulted_count += 1
            else:
                referenced_count += 1
        snap["storage_mode_preview"] = {
            "vaulted": vaulted_count,
            "referenced": referenced_count,
            "url_only": url_only_count,
        }
        check("Storage-mode assignment preview", "PASS",
              f"vaulted={vaulted_count}, referenced={referenced_count}, "
              f"url_only={url_only_count}")

        c.close()
    except Exception as e:
        check("DB introspection", "FAIL", str(e))
        return None

    out_path = COWORK_DIR / "pre_refactor_snapshot.json"
    out_path.write_text(json.dumps(snap, indent=2, default=str),
                        encoding="utf-8")
    w(f"  Snapshot saved: {out_path}")
    return out_path


def finalize():
    w("")
    w("---")
    w("## Summary")
    w("")
    n_pass = sum(1 for c in checks if c[1] == "PASS")
    n_warn = sum(1 for c in checks if c[1] == "WARN")
    n_fail = sum(1 for c in checks if c[1] == "FAIL")
    w(f"  {n_pass} PASS · {n_warn} WARN · {n_fail} FAIL")
    w("")

    if n_fail:
        w("  🛑 BLOCKING FAILURES — fix before launching cowork:")
        for name, _, detail in [c for c in checks if c[1] == "FAIL"]:
            w(f"     - {name}: {detail}")
    else:
        if n_warn:
            w("  ⚠ Warnings (non-blocking):")
            for name, _, detail in [c for c in checks if c[1] == "WARN"]:
                w(f"     - {name}: {detail}")
            w("")
        w("  ✅ READY FOR COWORK.")
        w("")

    w("---")
    w("## Cowork launch checklist")
    w("")
    w("  1. Launch cowork on your desktop.")
    w("")
    w("  2. Grant cowork filesystem access to:")
    w("       C:\\AI\\  (recursive read/write)")
    w("       D:\\AI_OK_TO_DELETE\\  (recursive read/write)")
    w("")
    w("  3. Paste as cowork's first message:")
    w("")
    w("     ---- begin cowork kickoff ----")
    w("     Read, in order:")
    w(f"       C:\\AI\\Platform\\MediaVault\\COWORK_BRIEF.md")
    w(f"       C:\\AI\\Platform\\MediaVault\\MEDIAVAULT_V04_DESIGN.md")
    w(f"       C:\\AI\\Platform\\MediaVault\\_cowork\\READINESS_REPORT.md")
    w(f"       C:\\AI\\Platform\\MediaVault\\_cowork\\pre_refactor_snapshot.json")
    w("")
    w("     You have full authority to execute every phase in COWORK_BRIEF.md")
    w("     without asking permission. Build lock is LOCKED in your name.")
    w("     DB is backed up. Dead files are already quarantined.")
    w("     Execute phases 1 through 6 in order. Only stop for the three")
    w("     flagged conditions in §10 of COWORK_BRIEF.md.")
    w("")
    w("     When done, update STATE.md, set BUILD_LOCK.txt to UNLOCKED,")
    w("     and report what shipped.")
    w("     ---- end cowork kickoff ----")
    w("")
    w("  4. Walk away.")
    w("")

    try:
        COWORK_DIR.mkdir(parents=True, exist_ok=True)
        rp = COWORK_DIR / "READINESS_REPORT.md"
        rp.write_text("\n".join(report), encoding="utf-8")
        print(f"\nReport written: {rp}")
    except Exception as e:
        print(f"\nCOULD NOT WRITE REPORT: {e}")

    sys.exit(0 if not has_fails() else 1)


def main():
    w(f"# MediaVault v0.4 Cowork Prep — {TS_READABLE}")
    w("")
    if not step_environment():
        return finalize()
    if not step_build_lock():
        return finalize()
    backup_path = step_db_backup()
    if not backup_path:
        return finalize()
    step_quarantine()
    step_snapshot(backup_path)
    finalize()


if __name__ == "__main__":
    main()
