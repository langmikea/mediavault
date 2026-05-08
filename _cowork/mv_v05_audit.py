"""
MediaVault v0.5 audit — ground-truth probe before design.

Run this on Windows with pwsh:
    python "C:\\AI\\Platform\\MediaVault\\_cowork\\mv_v05_audit.py"

Writes:
    C:\\AI\\Platform\\MediaVault\\_cowork\\mv_v05_audit_<timestamp>.md

The audit is read-only. No writes to the DB, no file moves, no quarantines.
Paste the full .md output back to Claude; no design content will be produced
until that output is in hand.

What this is and is not:

This is a factual inventory of v0.4's real state after ~2 days of use. It is
NOT a sanity check of whether v0.4 works. Claude needs raw numbers, exact
column lists, vocabulary content, and specific line references before it
can responsibly design v0.5 around the pill-as-view model correction.

Sections:
    1.  Environment + lock state
    2.  File inventory and sizes
    3.  Full schema of every table in core/mediavault.sqlite
    4.  Row counts by table, status, storage_mode, released
    5.  Every vestigial/legacy column still on artifacts, with population counts
    6.  Vocabulary: all 106 tags, with group, is_proposed, usage_count
    7.  Vocabulary pollution scan: fuzzy-match merge candidates, zero-use,
        one-use, visual-detail shaped slugs
    8.  Queue inspection: statuses, artifact_id population, stuck rows
        (queue_id where status='pending' but artifact_id is set — this is
        the released-in-inbox bug made visible)
    9.  Parent/child structure: how many sidecars, how many linked
    10. Sample enrichment_json payloads (3 real rows) for field-name recon
    11. Sample artifact rows covering each status and storage_mode
    12. Author_name: populated rows + distinct values
    13. imgserver_extensions.py structural dump: which routes it handles,
        which columns it reads/writes
    14. mediavault.html line references for the fields the brief will edit:
        ID field, action buttons, parent input, description fields,
        tag picker location
    15. imgserver.py behavior on save-and-release: find the handler and
        dump the SQL it executes
    16. Which backend routes the frontend actually calls
"""

import os
import re
import json
import sqlite3
import datetime as dt
from pathlib import Path
from collections import Counter, defaultdict

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

ROOT          = Path(r"C:\AI\Platform\MediaVault")
DB_PATH       = ROOT / "core" / "mediavault.sqlite"
IMGSERVER     = ROOT / "core" / "imgserver.py"
EXT_PY        = ROOT / "core" / "imgserver_extensions.py"
HTML          = ROOT / "mediavault.html"
FB_HTML       = ROOT / "fb_candidates.html"
BUILD_LOCK    = Path(r"C:\AI\BUILD_LOCK.txt")

OUT_DIR       = ROOT / "_cowork"
STAMP         = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
OUT_FILE      = OUT_DIR / f"mv_v05_audit_{STAMP}.md"

# --------------------------------------------------------------------------
# Output buffer
# --------------------------------------------------------------------------

_lines = []

def w(s=""):
    _lines.append(str(s))

def h1(s):
    w(f"\n# {s}\n")

def h2(s):
    w(f"\n## {s}\n")

def h3(s):
    w(f"\n### {s}\n")

def code(body, lang=""):
    w(f"```{lang}")
    w(body.rstrip() if isinstance(body, str) else "\n".join(body))
    w("```")

def kv(k, v):
    w(f"- **{k}:** {v}")

def fail(label, err):
    w(f"- **{label}:** ERROR `{err}`")

# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def safe_text(path: Path, limit_bytes: int = None) -> str:
    try:
        b = path.read_bytes()
        if limit_bytes:
            b = b[:limit_bytes]
        return b.decode("utf-8", errors="replace")
    except Exception as e:
        return f"<read failed: {e}>"

def connect_ro():
    # URI read-only mode so the audit cannot write.
    uri = f"file:{DB_PATH}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn

def fuzzy_slug_buckets(slugs):
    """
    Group slugs that look like near-duplicates of each other.
    Intentionally conservative: buckets share a normalized stem.
    Pure flag for Mike to eyeball — no automated merge.
    """
    def stem(s):
        s = s.lower()
        s = re.sub(r"[^a-z0-9]+", "", s)  # strip _ - punct
        # Collapse trailing plurals / apostrophe-s.
        if s.endswith("s") and len(s) > 3:
            s = s[:-1]
        return s
    buckets = defaultdict(list)
    for slug in slugs:
        buckets[stem(slug)].append(slug)
    return {k: v for k, v in buckets.items() if len(v) > 1}

def looks_like_visual_detail(slug):
    """
    Slugs that look like physical descriptors rather than facts worth
    searching for later. Pattern-based; not a judgment call.
    Mike confirms or overrides; the audit just flags.
    """
    markers = [
        "shirt", "hat", "beard", "hair", "jacket", "glasses", "pants",
        "dress", "suit", "tie", "sunglasses", "tattoo", "smile", "pose",
        "sitting", "standing", "holding", "looking", "wearing",
        "blue", "red", "green", "black", "white", "yellow", "brown",
        "striped", "checkered", "patterned", "solid",
    ]
    s = slug.lower()
    return any(m in s for m in markers)

# --------------------------------------------------------------------------
# Section 1 — Environment + lock
# --------------------------------------------------------------------------

def section_env():
    h1("MediaVault v0.5 audit")
    kv("Generated", dt.datetime.now().isoformat(timespec="seconds"))
    kv("DB path", DB_PATH)
    kv("DB exists", DB_PATH.exists())
    if DB_PATH.exists():
        kv("DB size (bytes)", DB_PATH.stat().st_size)
        kv("DB mtime", dt.datetime.fromtimestamp(DB_PATH.stat().st_mtime).isoformat(timespec="seconds"))

    h2("1. Build lock")
    if BUILD_LOCK.exists():
        code(safe_text(BUILD_LOCK), "txt")
    else:
        kv("BUILD_LOCK.txt", "missing")

# --------------------------------------------------------------------------
# Section 2 — File inventory
# --------------------------------------------------------------------------

def section_files():
    h2("2. File inventory (top-level + core/)")

    def row(p: Path):
        if p.exists():
            return f"- `{p.name}` — {p.stat().st_size:,} bytes, mtime {dt.datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec='seconds')}"
        return f"- `{p.name}` — MISSING"

    h3("Key files")
    for p in [HTML, FB_HTML, IMGSERVER, EXT_PY, ROOT/"core"/"ingest_engine.py", ROOT/"SPEC.md",
              ROOT/"STATE.md", ROOT/"PROJECT.md", ROOT/"WORKFLOW.md",
              ROOT/"MEDIAVAULT_V04_DESIGN.md"]:
        w(row(p))

    h3("Preserved v0.2 reference files")
    for p in [ROOT/"hr_manager.html.old_v02", ROOT/"core"/"imgserver.py.old_v02"]:
        w(row(p))

    h3("core/ directory listing")
    core = ROOT/"core"
    if core.is_dir():
        for p in sorted(core.iterdir()):
            try:
                size = p.stat().st_size
                w(f"- `{p.name}` — {size:,} bytes")
            except Exception as e:
                w(f"- `{p.name}` — ERROR {e}")

# --------------------------------------------------------------------------
# Section 3 — Full schema
# --------------------------------------------------------------------------

def section_schema(conn):
    h2("3. Full schema (as it exists on disk)")
    rows = conn.execute(
        "SELECT type, name, sql FROM sqlite_master "
        "WHERE type IN ('table','index','view','trigger') AND name NOT LIKE 'sqlite_%' "
        "ORDER BY type, name"
    ).fetchall()
    for r in rows:
        h3(f"{r['type']}: {r['name']}")
        if r["sql"]:
            code(r["sql"], "sql")
        else:
            w("_(no SQL recorded — likely auto-created)_")

    h3("artifacts column list, in order")
    cols = conn.execute("PRAGMA table_info(artifacts)").fetchall()
    if cols:
        w("| # | name | type | notnull | default | pk |")
        w("|---|------|------|---------|---------|----|")
        for c in cols:
            w(f"| {c['cid']} | `{c['name']}` | {c['type']} | {c['notnull']} | {c['dflt_value']} | {c['pk']} |")

    h3("tags (vocabulary) column list, in order")
    cols = conn.execute("PRAGMA table_info(tags)").fetchall()
    if cols:
        w("| # | name | type | notnull | default | pk |")
        w("|---|------|------|---------|---------|----|")
        for c in cols:
            w(f"| {c['cid']} | `{c['name']}` | {c['type']} | {c['notnull']} | {c['dflt_value']} | {c['pk']} |")

# --------------------------------------------------------------------------
# Section 4 — Row counts
# --------------------------------------------------------------------------

def section_counts(conn):
    h2("4. Row counts")

    h3("Totals by table")
    for t in ("artifacts", "tags", "id_sequence", "ingest_queue"):
        try:
            n = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            kv(t, n)
        except Exception as e:
            fail(t, e)

    h3("artifacts by status")
    for r in conn.execute("SELECT status, COUNT(*) c FROM artifacts GROUP BY status ORDER BY c DESC"):
        kv(r["status"] or "(null)", r["c"])

    h3("artifacts by storage_mode")
    for r in conn.execute("SELECT storage_mode, COUNT(*) c FROM artifacts GROUP BY storage_mode ORDER BY c DESC"):
        kv(r["storage_mode"] or "(null)", r["c"])

    h3("artifacts by (status, storage_mode) cross")
    w("| status | storage_mode | count |")
    w("|---|---|---|")
    for r in conn.execute(
        "SELECT status, storage_mode, COUNT(*) c FROM artifacts "
        "GROUP BY status, storage_mode ORDER BY c DESC"
    ):
        w(f"| {r['status']} | {r['storage_mode']} | {r['c']} |")

    h3("artifacts with parent_artifact_id set (children)")
    try:
        n = conn.execute(
            "SELECT COUNT(*) FROM artifacts WHERE parent_artifact_id IS NOT NULL"
        ).fetchone()[0]
        kv("children with a parent link", n)
    except Exception as e:
        fail("parent count", e)

    h3("artifacts with released_at set")
    try:
        n = conn.execute(
            "SELECT COUNT(*) FROM artifacts WHERE released_at IS NOT NULL"
        ).fetchone()[0]
        kv("released_at populated", n)
    except Exception as e:
        fail("released_at count", e)

    h3("ingest_queue by status")
    try:
        for r in conn.execute("SELECT status, COUNT(*) c FROM ingest_queue GROUP BY status ORDER BY c DESC"):
            kv(r["status"] or "(null)", r["c"])
    except Exception as e:
        fail("queue status count", e)

# --------------------------------------------------------------------------
# Section 5 — Vestigial columns
# --------------------------------------------------------------------------

def section_vestigial(conn):
    h2("5. Vestigial / legacy columns on artifacts")
    w(
        "Counts how many rows have a non-null value in each column the v0.4 "
        "SPEC labels vestigial. Used to decide what to drop in v0.5."
    )

    cols_on_disk = {r["name"] for r in conn.execute("PRAGMA table_info(artifacts)")}

    # Probe every vestigial column the SPEC and the v0.4 design mentioned.
    # Also probe what Mike asked about: `tags_preservation`. Both possible
    # survivors get counted, whichever exists.
    probes = [
        "link_status",
        "tags_permission",
        "tags_preservation",
        "permission_contact",
        "permission_evidence_path",
        "author_name",
        "confidence_flags",
        "media_type",
        "capture_date",
        "post_date_confidence",
    ]
    w("| column | exists on disk | non-null rows | distinct values (sample up to 8) |")
    w("|---|---|---|---|")
    for col in probes:
        if col in cols_on_disk:
            try:
                n = conn.execute(f"SELECT COUNT(*) FROM artifacts WHERE {col} IS NOT NULL").fetchone()[0]
                vals = [r[0] for r in conn.execute(
                    f"SELECT DISTINCT {col} FROM artifacts WHERE {col} IS NOT NULL LIMIT 8"
                )]
                sample = ", ".join(f"`{v}`" for v in vals) if vals else "—"
                w(f"| `{col}` | yes | {n} | {sample} |")
            except Exception as e:
                w(f"| `{col}` | yes | ERROR | {e} |")
        else:
            w(f"| `{col}` | **no** | — | — |")

# --------------------------------------------------------------------------
# Section 6 — Full vocabulary
# --------------------------------------------------------------------------

def section_vocab(conn):
    h2("6. Vocabulary dump — every tag in the `tags` table")

    try:
        rows = conn.execute(
            "SELECT slug, display_name, group_name, is_proposed, usage_count, description "
            "FROM tags ORDER BY usage_count DESC, slug ASC"
        ).fetchall()
    except Exception as e:
        fail("tags dump", e); return

    kv("vocabulary total", len(rows))
    kv("proposed (is_proposed=1)", sum(1 for r in rows if r["is_proposed"]))
    kv("accepted (is_proposed=0)", sum(1 for r in rows if not r["is_proposed"]))
    kv("with group_name", sum(1 for r in rows if r["group_name"]))
    kv("without group_name", sum(1 for r in rows if not r["group_name"]))

    h3("Every tag, sorted by usage desc")
    w("| slug | display_name | group_name | proposed | uses | desc |")
    w("|---|---|---|---|---|---|")
    for r in rows:
        desc = (r["description"] or "").replace("|", "\\|")
        desc = (desc[:40] + "…") if len(desc) > 40 else desc
        w(f"| `{r['slug']}` | {r['display_name']} | {r['group_name'] or '—'} | {r['is_proposed']} | {r['usage_count']} | {desc} |")

# --------------------------------------------------------------------------
# Section 7 — Vocab pollution scan
# --------------------------------------------------------------------------

def section_pollution(conn):
    h2("7. Vocabulary pollution scan")
    w(
        "Flags for Mike to eyeball during v0.5 cleanup. No automated merge; "
        "the conservative cleanup script only acts on items Mike explicitly approves."
    )

    try:
        rows = conn.execute(
            "SELECT slug, display_name, usage_count FROM tags ORDER BY slug"
        ).fetchall()
    except Exception as e:
        fail("pollution scan", e); return

    slugs = [r["slug"] for r in rows]
    uses  = {r["slug"]: r["usage_count"] for r in rows}
    disp  = {r["slug"]: r["display_name"] for r in rows}

    h3("7a. Near-duplicate buckets (same stem)")
    buckets = fuzzy_slug_buckets(slugs)
    if not buckets:
        w("_(none)_")
    else:
        for stem_, group in sorted(buckets.items()):
            group = sorted(group, key=lambda s: -uses.get(s, 0))
            lines = [f"  - `{s}` → {disp[s]} ({uses[s]} uses)" for s in group]
            w(f"- stem `{stem_}`:")
            for l in lines: w(l)

    h3("7b. Zero-usage tags (candidates for bulk delete)")
    zero = [s for s in slugs if uses[s] == 0]
    kv("zero-use count", len(zero))
    if zero:
        code("\n".join(zero))

    h3("7c. Single-use tags (curator eyeball — often descriptive one-offs)")
    one = [s for s in slugs if uses[s] == 1]
    kv("single-use count", len(one))
    if one:
        code("\n".join(one))

    h3("7d. Slugs that look like visual details (pattern match)")
    w("_Match against a hand-written list of physical-descriptor keywords. Not exhaustive._")
    vis = [s for s in slugs if looks_like_visual_detail(s)]
    if not vis:
        w("_(none by keyword match)_")
    else:
        for s in vis:
            w(f"- `{s}` → {disp[s]} ({uses[s]} uses)")

    h3("7e. Slugs with spaces/capitals/weird chars (slug rule violations)")
    weird = [s for s in slugs if not re.fullmatch(r"[a-z0-9_:\-]+", s)]
    if not weird:
        w("_(none — all slugs look well-formed)_")
    else:
        for s in weird:
            w(f"- `{s}` (display: {disp[s]})")

# --------------------------------------------------------------------------
# Section 8 — Queue inspection (the released-in-inbox bug)
# --------------------------------------------------------------------------

def section_queue(conn):
    h2("8. ingest_queue deep inspection")

    try:
        rows = conn.execute(
            "SELECT queue_id, ingest_source, status, artifact_id, "
            "       raw_path, source_url, queued_at, updated_at, "
            "       CASE WHEN enrichment_json IS NULL THEN 0 ELSE length(enrichment_json) END AS enr_len, "
            "       error_message "
            "FROM ingest_queue ORDER BY queue_id"
        ).fetchall()
    except Exception as e:
        fail("queue dump", e); return

    kv("queue rows total", len(rows))

    h3("8a. Status × artifact_id matrix (detects released-in-inbox bug)")
    w("If any `status='pending'` row has `artifact_id IS NOT NULL`, that row has already been saved to vault "
      "but the queue entry wasn't cleared. That's the bug.")
    w("")
    mat = defaultdict(int)
    for r in rows:
        mat[(r["status"], r["artifact_id"] is not None)] += 1
    w("| status | has artifact_id | count |")
    w("|---|---|---|")
    for (st, has_aid), n in sorted(mat.items()):
        w(f"| {st} | {'yes' if has_aid else 'no'} | {n} |")

    h3("8b. Specific stuck rows (status='pending' AND artifact_id IS NOT NULL)")
    stuck = [r for r in rows if r["status"] == "pending" and r["artifact_id"]]
    if not stuck:
        w("_(none — bug has not produced leftover data, or has been cleaned)_")
    else:
        for r in stuck:
            kv(f"queue #{r['queue_id']}", f"artifact_id={r['artifact_id']} source={r['ingest_source']} raw={r['raw_path']} url={r['source_url']}")

    h3("8c. Full queue roster (one-line per row)")
    w("| q# | status | ingest_source | artifact_id | raw_path | source_url | enr_len | error |")
    w("|---|---|---|---|---|---|---|---|")
    for r in rows:
        raw = (r["raw_path"] or "")
        if len(raw) > 40: raw = "…" + raw[-40:]
        url = (r["source_url"] or "")
        if len(url) > 40: url = url[:40] + "…"
        err = (r["error_message"] or "").replace("\n"," ")
        if len(err) > 40: err = err[:40] + "…"
        w(f"| {r['queue_id']} | {r['status']} | {r['ingest_source']} | {r['artifact_id'] or '—'} | `{raw}` | `{url}` | {r['enr_len']} | {err} |")

# --------------------------------------------------------------------------
# Section 9 — Parent/child structure
# --------------------------------------------------------------------------

def section_parents(conn):
    h2("9. Parent/child structure")

    try:
        total = conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0]
        kids  = conn.execute("SELECT COUNT(*) FROM artifacts WHERE parent_artifact_id IS NOT NULL").fetchone()[0]
        kv("total artifacts", total)
        kv("with parent_artifact_id", kids)
        kv("top-level (parent NULL)", total - kids)
    except Exception as e:
        fail("parent counts", e); return

    h3("9a. Artifacts that look like sidecars by filename but have no parent link")
    # Heuristic: local_asset_path ending in metadata.json / .txt / .srt / .json,
    # or a row whose tags include anything resembling "metadata" / "sidecar".
    try:
        suspects = conn.execute("""
            SELECT id, local_asset_path, media_type, tags, parent_artifact_id
            FROM artifacts
            WHERE parent_artifact_id IS NULL
              AND (
                local_asset_path LIKE '%metadata.json'
                OR local_asset_path LIKE '%.json'
                OR local_asset_path LIKE '%.txt'
                OR local_asset_path LIKE '%.srt'
                OR media_type IN ('text','text-only','metadata_json','metadata','extracted_text')
              )
            ORDER BY id
        """).fetchall()
    except Exception as e:
        fail("sidecar probe", e); return

    kv("unlinked sidecar candidates", len(suspects))
    if suspects:
        for r in suspects[:25]:
            kv(f"`{r['id']}`", f"asset=`{r['local_asset_path']}` media_type=`{r['media_type']}` tags={r['tags']}")
        if len(suspects) > 25:
            w(f"_…and {len(suspects)-25} more_")

# --------------------------------------------------------------------------
# Section 10 — enrichment_json shape
# --------------------------------------------------------------------------

def section_enrichment(conn):
    h2("10. enrichment_json shape — 3 sample blobs")
    w("We need the exact key names currently being written so v0.5's confidence-tier "
      "emission doesn't collide with existing fields.")

    try:
        rows = conn.execute(
            "SELECT queue_id, status, enrichment_json FROM ingest_queue "
            "WHERE enrichment_json IS NOT NULL ORDER BY queue_id DESC LIMIT 3"
        ).fetchall()
    except Exception as e:
        fail("enrichment sample", e); return

    for r in rows:
        h3(f"queue #{r['queue_id']} (status={r['status']})")
        try:
            parsed = json.loads(r["enrichment_json"])
            code(json.dumps(parsed, indent=2, default=str), "json")
        except Exception as e:
            w(f"_(not valid JSON: {e})_")
            code(r["enrichment_json"][:2000])

    h3("Key-name inventory across all queue rows")
    try:
        all_rows = conn.execute(
            "SELECT enrichment_json FROM ingest_queue WHERE enrichment_json IS NOT NULL"
        ).fetchall()
    except Exception as e:
        fail("key inventory", e); return

    keys = Counter()
    for r in all_rows:
        try:
            obj = json.loads(r["enrichment_json"])
            if isinstance(obj, dict):
                keys.update(obj.keys())
        except Exception:
            pass
    if keys:
        w("| key | rows using it |")
        w("|---|---|")
        for k, n in keys.most_common():
            w(f"| `{k}` | {n} |")

# --------------------------------------------------------------------------
# Section 11 — Sample artifact rows
# --------------------------------------------------------------------------

def section_samples(conn):
    h2("11. Sample artifact rows — one per (status, storage_mode) if possible")

    try:
        combos = conn.execute(
            "SELECT DISTINCT status, storage_mode FROM artifacts"
        ).fetchall()
    except Exception as e:
        fail("sample combos", e); return

    for c in combos:
        try:
            r = conn.execute(
                "SELECT * FROM artifacts WHERE status = ? AND storage_mode = ? LIMIT 1",
                (c["status"], c["storage_mode"])
            ).fetchone()
        except Exception as e:
            fail(f"sample {c['status']}/{c['storage_mode']}", e); continue
        if not r: continue
        h3(f"{c['status']} / {c['storage_mode']} — sample id {r['id']}")
        for k in r.keys():
            val = r[k]
            if isinstance(val, str) and len(val) > 240:
                val = val[:240] + "…"
            w(f"  - `{k}`: {val}")

# --------------------------------------------------------------------------
# Section 12 — author_name inventory
# --------------------------------------------------------------------------

def section_author(conn):
    h2("12. `author_name` column — inventory before dropping")

    cols_on_disk = {r["name"] for r in conn.execute("PRAGMA table_info(artifacts)")}
    if "author_name" not in cols_on_disk:
        w("_(column not present on disk — nothing to migrate)_")
        return

    try:
        n_pop = conn.execute(
            "SELECT COUNT(*) FROM artifacts WHERE author_name IS NOT NULL AND TRIM(author_name) != ''"
        ).fetchone()[0]
        kv("rows with author_name populated", n_pop)

        vals = conn.execute("""
            SELECT author_name, COUNT(*) c
            FROM artifacts
            WHERE author_name IS NOT NULL AND TRIM(author_name) != ''
            GROUP BY author_name ORDER BY c DESC
        """).fetchall()
        if vals:
            h3("Distinct author_name values")
            for v in vals:
                kv(f"`{v['author_name']}`", v["c"])
    except Exception as e:
        fail("author inventory", e)

# --------------------------------------------------------------------------
# Section 13 — imgserver_extensions.py dump
# --------------------------------------------------------------------------

def section_extensions():
    h2("13. `imgserver_extensions.py` structural dump")
    if not EXT_PY.exists():
        w("_(file missing — nothing to report)_"); return

    txt = safe_text(EXT_PY)
    kv("size (chars)", len(txt))

    h3("Defined functions / methods (def lines)")
    for m in re.finditer(r"^(\s*)def\s+([A-Za-z_][A-Za-z_0-9]*)\s*\(.*", txt, re.M):
        indent = "nested" if m.group(1) else "top"
        w(f"- `{m.group(2)}` ({indent})")

    h3("Route / path strings referenced")
    for m in re.finditer(r"['\"](/[A-Za-z0-9_\-/]+)['\"]", txt):
        w(f"- `{m.group(1)}`")

    h3("Probable schema references (v0.2 column names)")
    for col in ("domain", "tags_year_era", "tags_content_type", "tags_subject",
                "tags_topic", "tags_rarity", "tags_preservation", "tags_permission",
                "tags_keywords", "tags_song_reference", "tags_domain_scoped",
                "tinyurl"):
        n = len(re.findall(rf"\b{re.escape(col)}\b", txt))
        if n:
            kv(f"mentions of `{col}`", n)

    h3("Full source (for the brief to reference)")
    code(txt, "python")

# --------------------------------------------------------------------------
# Section 14 — mediavault.html line references
# --------------------------------------------------------------------------

def section_html_refs():
    h2("14. `mediavault.html` line references for the v0.5 brief")
    if not HTML.exists():
        w("_(file missing)_"); return

    lines = safe_text(HTML).splitlines()

    targets = [
        ("ID field",                    r'id=\"fId\"'),
        ("Short description field",     r'id=\"fShortDesc\"'),
        ("Long description field",      r'id=\"fLongDesc\"'),
        ("Extracted text field",        r'id=\"fExtractedText\"'),
        ("Author field",                r'id=\"fAuthor\"'),
        ("Notes field",                 r'id=\"fNotes\"'),
        ("Tag picker container",        r'id=\"tagPicker\"'),
        ("Applied pills container",     r'id=\"appliedPills\"'),
        ("Parent artifact input",       r'id=\"fParentId\"'),
        ("Inbox action bar container",  r'id=\"inboxActions\"'),
        ("Scrap button onclick",        r'onclick=\"inboxScrap\('),
        ("Save button onclick",         r'onclick=\"inboxSave\(false\)'),
        ("Release button onclick",      r'onclick=\"inboxSave\(true\)'),
        ("Inbox save function",         r'async function inboxSave\('),
        ("Inbox scrap function",        r'async function inboxScrap\('),
        ("Vault tri-state cycle fn",    r'function cycleVaultTag\('),
        ("FILTER_TAG_STATE global",     r'let FILTER_TAG_STATE'),
        ("Tag chip click handler",      r'function toggleTagChip\('),
        ("renderTagBrowse fn",          r'function renderTagBrowse\('),
        ("renderAppliedPills fn",       r'function renderAppliedPills\('),
        ("Detail panel render fn",      r'function renderDetail\('),
        ("addAppliedTag fn (group excl)", r'function addAppliedTag\('),
    ]

    w("| target | first line match |")
    w("|---|---|")
    for label, pat in targets:
        first = None
        rx = re.compile(pat)
        for i, line in enumerate(lines, 1):
            if rx.search(line):
                first = i; break
        w(f"| {label} | {first if first else '**NOT FOUND**'} |")

    h3("14a. Inbox right-panel section headers in order (top-to-bottom)")
    rx = re.compile(r'<div class=\"sectionHead\">([^<]+)</div>')
    for i, line in enumerate(lines, 1):
        m = rx.search(line)
        if m:
            w(f"- L{i}: `{m.group(1).strip()}`")

# --------------------------------------------------------------------------
# Section 15 — imgserver.py save-and-release behavior
# --------------------------------------------------------------------------

def section_imgserver_save():
    h2("15. `imgserver.py` — save-and-release behavior (queue-row cleanup check)")
    if not IMGSERVER.exists():
        w("_(file missing)_"); return

    txt = safe_text(IMGSERVER)

    h3("Route table (`/api/...` string literals)")
    routes = sorted(set(re.findall(r"['\"](/api/[A-Za-z0-9_\-]+)['\"]", txt)))
    for r in routes:
        w(f"- `{r}`")

    h3("Likely save-and-release handler (function containing artifact-save logic)")
    # Find `/api/artifact-save` dispatch and dump surrounding code.
    m = re.search(r"(/api/artifact-save)", txt)
    if not m:
        w("_(no `/api/artifact-save` route found — unexpected; check manually)_")
    else:
        # Widen to a reasonable window around the hit.
        start = max(0, txt.rfind("\n", 0, max(0, m.start() - 2000)))
        end   = min(len(txt), m.end() + 3000)
        snippet = txt[start:end]
        code(snippet, "python")

    h3("All references to `ingest_queue` (SELECT/UPDATE/DELETE/INSERT)")
    for m in re.finditer(r"(SELECT|UPDATE|DELETE\s+FROM|INSERT\s+INTO)[^;\"']*ingest_queue[^;\"']*", txt, re.I):
        w(f"- `{m.group(0).strip()[:180]}`")

    h3("`release_immediately` usage sites")
    for i, line in enumerate(txt.splitlines(), 1):
        if "release_immediately" in line:
            w(f"- L{i}: `{line.strip()[:200]}`")

# --------------------------------------------------------------------------
# Section 16 — Frontend → backend route cross-reference
# --------------------------------------------------------------------------

def section_route_xref():
    h2("16. Frontend → backend route cross-reference")
    if not HTML.exists() or not IMGSERVER.exists():
        w("_(one of the files missing)_"); return

    html_txt = safe_text(HTML)
    py_txt   = safe_text(IMGSERVER)

    called   = sorted(set(re.findall(r"['\"`](/api/[A-Za-z0-9_\-]+)['\"`]", html_txt)))
    served   = sorted(set(re.findall(r"['\"`](/api/[A-Za-z0-9_\-]+)['\"`]", py_txt)))

    h3("Called by mediavault.html")
    for r in called:
        marker = "✓" if r in served else "❌ NOT SERVED"
        w(f"- `{r}` — {marker}")

    h3("Served by imgserver.py but never called by the frontend")
    dead = [r for r in served if r not in called]
    if not dead:
        w("_(none — every server route is called)_")
    else:
        for r in dead:
            w(f"- `{r}`")

# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    section_env()
    section_files()

    if not DB_PATH.exists():
        h2("DB MISSING — remaining sections skipped")
        OUT_FILE.write_text("\n".join(_lines), encoding="utf-8")
        print(f"Audit wrote: {OUT_FILE}")
        return

    conn = connect_ro()
    try:
        section_schema(conn)
        section_counts(conn)
        section_vestigial(conn)
        section_vocab(conn)
        section_pollution(conn)
        section_queue(conn)
        section_parents(conn)
        section_enrichment(conn)
        section_samples(conn)
        section_author(conn)
    finally:
        conn.close()

    section_extensions()
    section_html_refs()
    section_imgserver_save()
    section_route_xref()

    OUT_FILE.write_text("\n".join(_lines), encoding="utf-8")
    print(f"Audit wrote: {OUT_FILE}")
    print(f"Size: {OUT_FILE.stat().st_size:,} bytes")

if __name__ == "__main__":
    main()
