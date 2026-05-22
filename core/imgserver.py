"""
imgserver.py — MediaVault v0.4
================================

Single-file localhost HTTP server backing the MediaVault UI.

- Port 51822 on 127.0.0.1 only.
- Serves mediavault.html as the SPA root.
- 30 routes total (see ROUTES list at the bottom of this file for the
  authoritative listing).
- Talks to core/mediavault.sqlite (v0.4 schema: flat tags JSON array,
  status / storage_mode columns, tags vocabulary table).
- Imports two helpers from core/imgserver_extensions.py
  (handle_artifact_register, handle_asset_raw). That module is a
  peer of this one and is editable; per Criterion 3 (2026-05-18) any
  earlier "do not modify" guidance about it is superseded by the
  v2.1-target spec.

SINGLE-WRITER RULE (spec §4.5 / §4.5.1):
    ``artifacts.tags`` MUST be written ONLY through
    ``write_artifact_tags(conn, artifact_id, new_tags)`` in
    ``core/artifact_tags.py``. Do NOT add a second SQL path that
    UPDATEs or INSERTs ``artifacts.tags`` anywhere in MV. The grep
    check at ``tools/check_single_tag_writer.py`` enforces this and
    will fail the build if a second writer reappears.

Run:
    python core/imgserver.py
"""

from __future__ import annotations

import collections
import json
import mimetypes
import os
import re
import shutil
import sqlite3
import sys
import threading
import urllib.error
import urllib.request
import webbrowser
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

# Helper module — extension handlers live alongside imgserver.py and are
# imported here rather than inlined. handle_artifact_register and
# handle_asset_raw are unchanged from v0.2; handle_deep_dive_vocabulary
# was added in Phase 4 of the museum's Deep Dive feature and retained in
# Phase v5-5 cleanup (per Q-1: the endpoint will be repurposed in a
# future session as a suggestion source for MV's standard pill wall).
from imgserver_extensions import (  # noqa: E402
    handle_artifact_register,
    handle_asset_raw,
    handle_deep_dive_vocabulary,
)

# §4.5 single coordinated writer for artifacts.tags. EVERY tag-write
# in this file routes through write_artifact_tags; do not add another.
from artifact_tags import (  # noqa: E402
    write_artifact_tags,
    validate_artifact_tags,
    TagValidationError,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PORT = 51822
HOST = "127.0.0.1"

BASE = Path(__file__).resolve().parent.parent
CORE = BASE / "core"
DB_PATH = CORE / "mediavault.sqlite"
MEDIAVAULT_HTML = BASE / "mediavault.html"
FB_CANDIDATES_HTML = BASE / "fb_candidates.html"
FB_CANDIDATES_JSON = CORE / "fb_candidates.json"
RENDERER_JS = BASE / "ext" / "hr_manager_renderer.js"
THUMB_DIR = BASE / "thumbnails" / "inbox"
INTAKE_DIR = BASE / "intake" / "inbox"
VAULTED_ROOT = BASE / "catalogs" / "vaulted"

ALLOWED_IMG_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp",
                    ".heic", ".heif", ".bmp", ".tiff", ".tif"}
MIME_TYPES = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp",
    ".tiff": "image/tiff", ".tif": "image/tiff",
    ".heic": "image/heic", ".heif": "image/heif",
}
THUMB_MAX = 600  # pixels (max edge)

# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def db_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Thumbnails
# ---------------------------------------------------------------------------

def make_thumbnail(src_path: Path) -> bytes:
    """Render a JPEG thumbnail (max edge THUMB_MAX) for an image file.

    Uses Pillow if available; if HEIC, requires pillow-heif.
    Returns raw JPEG bytes.
    """
    try:
        from PIL import Image  # type: ignore
    except ImportError:
        raise RuntimeError("Pillow not installed (pip install Pillow)")
    if src_path.suffix.lower() in {".heic", ".heif"}:
        try:
            from pillow_heif import register_heif_opener  # type: ignore
            register_heif_opener()
        except ImportError:
            raise RuntimeError("pillow-heif not installed (pip install pillow-heif)")
    img = Image.open(src_path)
    img.thumbnail((THUMB_MAX, THUMB_MAX))
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    buf = BytesIO()
    img.save(buf, "JPEG", quality=85)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Slug / tag helpers (mirror migrate_to_v04.py)
# ---------------------------------------------------------------------------

# v0.5: allow one optional "namespace:" prefix (e.g. author:hunter_root).
# Everything else is [a-z0-9_] as before.
SLUG_RE = re.compile(r"^(?:[a-z0-9_]+:)?[a-z0-9_]+$")


def slugify(value) -> str | None:
    if value is None:
        return None
    s = str(value).strip().lower()
    if not s:
        return None
    # v0.5: preserve a single "namespace:" prefix if the caller sent one
    # (e.g. "author:Hunter Root" → "author:hunter_root").
    prefix = ""
    if ":" in s:
        head, _, tail = s.partition(":")
        head = re.sub(r"[^a-z0-9_]", "", head.replace("-", "_").replace(" ", "_"))
        head = re.sub(r"_+", "_", head).strip("_")
        if head:
            prefix = head + ":"
            s = tail
    s = re.sub(r"[-/\\\s]+", "_", s)
    s = re.sub(r"[^a-z0-9_]", "", s)
    s = re.sub(r"_+", "_", s).strip("_")
    if not s or len(prefix) + len(s) > 64:
        return None
    full = prefix + s
    if not SLUG_RE.match(full):
        return None
    return full


def display_name_for(slug: str) -> str:
    if re.fullmatch(r"\d{4}", slug):
        return slug
    return slug.replace("_", " ").title()


# ---------------------------------------------------------------------------
# Vocabulary registry helpers (Phase 2.1 of source-of-truth refactor)
# ---------------------------------------------------------------------------
# §5.4 of DATA_ARCHITECTURE_SPEC_v2.1-target.md: namespace / tier /
# display_name metadata lives in the `vocabulary` registry table — *not* in
# the legacy `tags.category` / `display_name` columns. Read-side callers
# (autocomplete, tag-list endpoint, enrich-prompt vocab pull) source
# namespace metadata via the helpers below. The demoted `tags` table is
# read only for slug + usage_count (the columns that survive the §5.2
# schema operation that Phase 2.5 will run later).

def namespace_of(slug: str | None) -> str | None:
    """Return the namespace prefix of a slug, or None if it has no prefix.

    The slug grammar (`slugify`) permits one optional `namespace:` prefix.
    For `album:arkansas` this returns `'album'`; for the legacy bare slug
    `arkansas` this returns `None`.
    """
    if not slug or ":" not in slug:
        return None
    ns, _sep, _local = slug.partition(":")
    return ns or None


def load_vocabulary_meta(conn) -> dict[str, dict]:
    """Load the §5.4 `vocabulary` registry, keyed by namespace.

    Returns a mapping of namespace → {display_name, tier, sort_order,
    retired_at}. Used by the read-side call sites to attach namespace
    metadata to per-slug rows without depending on the registry-era
    columns of the demoted `tags` table.
    """
    rows = conn.execute(
        "SELECT namespace, display_name, tier, sort_order, retired_at "
        "FROM vocabulary"
    ).fetchall()
    return {r["namespace"]: dict(r) for r in rows}


def vocab_row_for_slug(slug: str, usage_count: int,
                      ns_meta: dict[str, dict]) -> dict:
    """Build a vocab-row dict for a slug using vocabulary-registry metadata.

    Returns the same shape the v0.5 `/api/tags` endpoint produced — so
    existing UI / prompt callers continue to work — but with namespace
    metadata sourced from the §5.4 `vocabulary` registry instead of the
    `tags` table itself. The legacy `tags.description`, `tags.category`,
    `tags.is_exclusive`, and `tags.is_proposed` columns are **no longer
    in the schema** — Phase 2.5 of the source-of-truth refactor dropped
    them on 2026-05-20 (see CHANGELOG v0.5.3 / SPEC.md §6.5). The fields
    below are synthesized here so v0.5 UI/prompt callers keep working.

    Fields produced: `slug`, `display_name`, `category`, `is_exclusive`,
    `is_proposed`, `usage_count`, `description`. `category` carries the
    namespace prefix of the slug (the new model's closest analogue to the
    legacy `tags.category` column). Bare slugs (no namespace prefix)
    carry `category=None`. `is_proposed` is always 0 (workflow retired
    per Decision Brief §9.3 Q2). `is_exclusive` is always 0 (the legacy
    per-tag exclusivity flag has no home in the new model).
    `description` is always None (no longer tracked per-tag).
    """
    ns = namespace_of(slug)
    meta = ns_meta.get(ns) if ns else None
    ns_display = (meta or {}).get("display_name") if meta else None
    if ns and ns_display:
        local = slug.split(":", 1)[1]
        display_name = f"{ns_display}: {display_name_for(local)}"
    else:
        display_name = display_name_for(slug)
    return {
        "slug": slug,
        "display_name": display_name,
        "category": ns,
        "is_exclusive": 0,
        "is_proposed": 0,
        "usage_count": usage_count or 0,
        "description": None,
    }


def validate_tags_json(value) -> list[str]:
    """Coerce input to a list of valid slugs (deduped, sorted)."""
    if value is None:
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except Exception:
            return []
    if not isinstance(value, (list, tuple)):
        return []
    out = set()
    for v in value:
        s = slugify(v)
        if s:
            out.add(s)
    return sorted(out)


def upsert_tag(conn: sqlite3.Connection, slug: str,
               display_name: str | None = None,
               category: str | None = None,
               is_proposed: int = 0,
               is_exclusive: int = 0) -> None:
    """Insert a tag-cache row if missing.

    The `tags` table is the per-value usage-count cache (post-§5.2
    demotion in Phase 2.2 of the source-of-truth refactor, schema
    finalized by Phase 2.5 on 2026-05-20). Live columns: `slug` (PRIMARY
    KEY), `display_name`, `usage_count`, `created_at`. This function
    writes `slug`, `usage_count` (defaulted to 0), `created_at` (now);
    `display_name` is currently left NULL, matching the post-2.5 cache
    convention (the human label is supplied per-namespace by the §5.4
    `vocabulary` registry, not per-tag).

    The `display_name` / `category` / `is_proposed` / `is_exclusive`
    parameters are retained in the signature for backward compatibility
    with v0.5 callers (every existing call site passes them by keyword).
    The latter three name columns that **no longer exist** in the live
    schema — Phase 2.5 dropped them — so they are accepted-and-discarded
    here. See CHANGELOG v0.5.3 / SPEC.md §6.5.
    """
    # Accept-and-discard the v0.5 metadata parameters (see docstring).
    # `category`, `is_proposed`, `is_exclusive` reference columns that
    # were dropped from the `tags` table by Phase 2.5.
    del display_name, category, is_proposed, is_exclusive
    row = conn.execute("SELECT slug FROM tags WHERE slug=?", (slug,)).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO tags(slug, usage_count, created_at) "
            "VALUES (?, 0, datetime('now'))",
            (slug,),
        )


def adjust_tag_usage(conn: sqlite3.Connection, added: list[str], removed: list[str]) -> None:
    for s in added:
        conn.execute("UPDATE tags SET usage_count=usage_count+1 WHERE slug=?", (s,))
    for s in removed:
        conn.execute("UPDATE tags SET usage_count=MAX(0,usage_count-1) WHERE slug=?", (s,))


# ---------------------------------------------------------------------------
# Path security: /image-raw and /asset-raw must not escape known roots.
# ---------------------------------------------------------------------------

ALLOWED_ASSET_ROOTS = [Path(r"C:\AI"), BASE]


def path_is_inside(child: Path, roots) -> bool:
    try:
        cr = child.resolve()
    except Exception:
        cr = child
    for r in roots:
        try:
            rr = r.resolve()
        except Exception:
            rr = r
        try:
            cr.relative_to(rr)
            return True
        except ValueError:
            continue
    return False


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------

def send_json(handler: BaseHTTPRequestHandler, status: int, payload) -> None:
    body = json.dumps(payload, default=str).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.end_headers()
    handler.wfile.write(body)


def send_error(handler: BaseHTTPRequestHandler, status: int, msg: str) -> None:
    send_json(handler, status, {"ok": False, "error": msg})


def send_bytes(handler: BaseHTTPRequestHandler, status: int, content_type: str,
               data: bytes, cache: bool = False) -> None:
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(data)))
    if not cache:
        handler.send_header("Cache-Control", "no-store")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.end_headers()
    handler.wfile.write(data)


def read_body(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length", 0) or 0)
    if not length:
        return {}
    raw = handler.rfile.read(length)
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Static file handlers (root, db, image-raw, ext renderer, fb)
# ---------------------------------------------------------------------------

def handle_root(h: BaseHTTPRequestHandler) -> None:
    if not MEDIAVAULT_HTML.exists():
        return send_error(h, 404, "mediavault.html missing")
    data = MEDIAVAULT_HTML.read_bytes()
    send_bytes(h, 200, "text/html; charset=utf-8", data)


def handle_ping(h: BaseHTTPRequestHandler) -> None:
    send_json(h, 200, {"ok": True, "ts": now_iso(), "version": "0.4"})


def handle_db(h: BaseHTTPRequestHandler) -> None:
    if not DB_PATH.exists():
        return send_error(h, 404, "DB missing")
    data = DB_PATH.read_bytes()
    send_bytes(h, 200, "application/octet-stream", data)


def handle_image_raw(h: BaseHTTPRequestHandler) -> None:
    qs = parse_qs(urlparse(h.path).query)
    p = qs.get("path", [None])[0]
    if not p:
        return send_error(h, 400, "missing path")
    fp = Path(unquote(p))
    if not path_is_inside(fp, ALLOWED_ASSET_ROOTS):
        return send_error(h, 403, "path outside allowed roots")
    if not fp.exists() or not fp.is_file():
        return send_error(h, 404, "file not found")
    ext = fp.suffix.lower()
    ct = MIME_TYPES.get(ext, "application/octet-stream")
    if ext in {".heic", ".heif"}:
        # Render heic to a JPEG thumb so browsers can display it.
        try:
            data = make_thumbnail(fp)
            return send_bytes(h, 200, "image/jpeg", data, cache=True)
        except Exception as e:
            return send_error(h, 500, f"thumb failed: {e}")
    send_bytes(h, 200, ct, fp.read_bytes(), cache=True)


def handle_renderer_js(h: BaseHTTPRequestHandler) -> None:
    if not RENDERER_JS.exists():
        return send_error(h, 404, "renderer missing")
    send_bytes(h, 200, "application/javascript; charset=utf-8", RENDERER_JS.read_bytes())


def handle_fb_html(h: BaseHTTPRequestHandler) -> None:
    if not FB_CANDIDATES_HTML.exists():
        return send_error(h, 404, "fb_candidates.html missing")
    send_bytes(h, 200, "text/html; charset=utf-8", FB_CANDIDATES_HTML.read_bytes())


# ---------------------------------------------------------------------------
# Queue & tags read endpoints
# ---------------------------------------------------------------------------

def handle_queue_list(h: BaseHTTPRequestHandler) -> None:
    qs = parse_qs(urlparse(h.path).query)
    status = qs.get("status", [None])[0]
    conn = db_conn()
    try:
        if status:
            rows = conn.execute(
                "SELECT * FROM ingest_queue WHERE status=? ORDER BY queue_id DESC",
                (status,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM ingest_queue ORDER BY queue_id DESC LIMIT 500"
            ).fetchall()
        send_json(h, 200, {"ok": True, "rows": [dict(r) for r in rows]})
    finally:
        conn.close()


def handle_tags_list(h: BaseHTTPRequestHandler) -> None:
    # Phase 2.1 (source-of-truth refactor): namespace metadata is sourced
    # from the §5.4 `vocabulary` registry, not the registry-era columns of
    # the demoted `tags` table. The cache is the slug-list source and
    # provides `usage_count`; everything else is derived from `vocabulary`
    # via `vocab_row_for_slug`.
    qs = parse_qs(urlparse(h.path).query)
    proposed_only = qs.get("proposed_only", ["0"])[0] == "1"
    # `category` is honoured as a namespace filter; the legacy "group"
    # query-param alias is retained for the rolling restart.
    namespace = qs.get("category", [None])[0] or qs.get("group", [None])[0]
    min_usage = int(qs.get("min_usage", ["0"])[0] or "0")
    # The is_proposed workflow is retired (Decision Brief §9.3 Q2).
    # `proposed_only=1` now returns an empty rowset so older clients fail
    # visibly rather than silently receiving the full vocabulary.
    if proposed_only:
        return send_json(h, 200, {"ok": True, "rows": []})
    conn = db_conn()
    try:
        rows = conn.execute(
            "SELECT slug, usage_count FROM tags "
            "WHERE usage_count >= ? "
            "ORDER BY usage_count DESC, slug",
            [min_usage],
        ).fetchall()
        ns_meta = load_vocabulary_meta(conn)
        result = [vocab_row_for_slug(r["slug"], r["usage_count"], ns_meta)
                  for r in rows]
        if namespace:
            result = [r for r in result if r["category"] == namespace]
        send_json(h, 200, {"ok": True, "rows": result})
    finally:
        conn.close()


def handle_fb_candidates_get(h: BaseHTTPRequestHandler) -> None:
    if not FB_CANDIDATES_JSON.exists():
        return send_json(h, 200, {"ok": True, "candidates": []})
    try:
        data = json.loads(FB_CANDIDATES_JSON.read_text(encoding="utf-8"))
    except Exception as e:
        return send_error(h, 500, f"parse error: {e}")
    send_json(h, 200, {"ok": True, "candidates": data})


# ---------------------------------------------------------------------------
# Intake endpoints
# ---------------------------------------------------------------------------

def handle_intake_upload(h: BaseHTTPRequestHandler) -> None:
    """Accept multipart/form-data file upload, drop into intake/inbox/, queue."""
    ctype = h.headers.get("Content-Type", "")
    if "multipart/form-data" not in ctype:
        return send_error(h, 400, "expected multipart/form-data")
    import cgi
    INTAKE_DIR.mkdir(parents=True, exist_ok=True)
    fs = cgi.FieldStorage(
        fp=h.rfile,
        headers=h.headers,
        environ={"REQUEST_METHOD": "POST", "CONTENT_TYPE": ctype},
    )
    if "file" not in fs:
        return send_error(h, 400, "no file part")
    item = fs["file"]
    fname = os.path.basename(item.filename or "upload.bin")
    dst = INTAKE_DIR / fname
    if dst.exists():
        stem, suf = dst.stem, dst.suffix
        i = 1
        while (INTAKE_DIR / f"{stem}_{i}{suf}").exists():
            i += 1
        dst = INTAKE_DIR / f"{stem}_{i}{suf}"
    dst.write_bytes(item.file.read())
    conn = db_conn()
    try:
        cur = conn.execute(
            "INSERT INTO ingest_queue(ingest_source, raw_path, queued_at, status, updated_at) "
            "VALUES(?,?,?,?,?)",
            ("intake-upload", str(dst), now_iso(), "pending", now_iso()),
        )
        conn.commit()
        send_json(h, 200, {"ok": True, "queue_id": cur.lastrowid, "raw_path": str(dst)})
    finally:
        conn.close()


def handle_intake_url(h: BaseHTTPRequestHandler) -> None:
    body = read_body(h)
    src_url = body.get("source_url")
    if not src_url:
        return send_error(h, 400, "source_url required")
    enrichment = {
        "source_platform": body.get("source_platform"),
        "tags_proposed": body.get("tags") or [],
        "description_short": body.get("description_short"),
    }
    conn = db_conn()
    try:
        cur = conn.execute(
            "INSERT INTO ingest_queue(ingest_source, source_url, queued_at, status, "
            " enrichment_json, updated_at) VALUES(?,?,?,?,?,?)",
            ("url-entry", src_url, now_iso(), "pending",
             json.dumps(enrichment), now_iso()),
        )
        conn.commit()
        send_json(h, 200, {"ok": True, "queue_id": cur.lastrowid})
    finally:
        conn.close()


def handle_intake_from_fb_candidate(h: BaseHTTPRequestHandler) -> None:
    body = read_body(h)
    cand_id = body.get("fb_candidate_id")
    if cand_id is None:
        return send_error(h, 400, "fb_candidate_id required")
    if not FB_CANDIDATES_JSON.exists():
        return send_error(h, 404, "fb_candidates.json missing")
    try:
        candidates = json.loads(FB_CANDIDATES_JSON.read_text(encoding="utf-8"))
    except Exception as e:
        return send_error(h, 500, f"parse error: {e}")
    cand = None
    if isinstance(candidates, list):
        for c in candidates:
            if str(c.get("id")) == str(cand_id):
                cand = c
                break
    if cand is None:
        return send_error(h, 404, "candidate not found")

    # v0.5: emit pill_states shape. Author → author:<slug> pill
    # (on_uncertain — operator should confirm). Candidate tags also land in
    # pill_states so the enrichment re-read picks them up as pills, not as
    # the retired tags_proposed flat array.
    pill_states: dict[str, str] = {}
    for raw in (cand.get("tags") or []):
        s = slugify(raw)
        if s:
            pill_states[s] = "on_uncertain"
    author = cand.get("author")
    if author:
        a_slug = slugify(f"author:{author}")
        if a_slug:
            pill_states[a_slug] = "on_uncertain"
    enrichment = {
        "source_platform": "facebook",
        "description_long": cand.get("fact") or cand.get("text"),
        "pill_states": pill_states,
    }
    raw_path = cand.get("local_image_path")
    conn = db_conn()
    try:
        cur = conn.execute(
            "INSERT INTO ingest_queue(ingest_source, source_url, raw_path, "
            " queued_at, status, enrichment_json, updated_at) VALUES(?,?,?,?,?,?,?)",
            ("fb_candidate", cand.get("post_url") or cand.get("url"),
             raw_path, now_iso(), "pending", json.dumps(enrichment), now_iso()),
        )
        new_qid = cur.lastrowid
        conn.commit()
    finally:
        conn.close()

    # Mark candidate as graduated
    cand["graduated"] = True
    FB_CANDIDATES_JSON.write_text(json.dumps(candidates, indent=2), encoding="utf-8")
    send_json(h, 200, {"ok": True, "queue_id": new_qid})


# ---------------------------------------------------------------------------
# Queue mutate endpoints
# ---------------------------------------------------------------------------

def handle_queue_update(h: BaseHTTPRequestHandler) -> None:
    body = read_body(h)
    qid = body.get("queue_id")
    if qid is None:
        return send_error(h, 400, "queue_id required")
    sets = []
    args: list = []
    for k in ("status", "enrichment_json", "error_message", "raw_path", "source_url"):
        if k in body:
            v = body[k]
            if k == "enrichment_json" and not isinstance(v, str):
                v = json.dumps(v)
            sets.append(f"{k}=?")
            args.append(v)
    if not sets:
        return send_error(h, 400, "nothing to update")
    sets.append("updated_at=?")
    args.append(now_iso())
    args.append(qid)
    conn = db_conn()
    try:
        conn.execute(f"UPDATE ingest_queue SET {','.join(sets)} WHERE queue_id=?", args)
        conn.commit()
        send_json(h, 200, {"ok": True})
    finally:
        conn.close()


def handle_queue_delete(h: BaseHTTPRequestHandler) -> None:
    body = read_body(h)
    qid = body.get("queue_id")
    if qid is None:
        return send_error(h, 400, "queue_id required")
    conn = db_conn()
    try:
        conn.execute("DELETE FROM ingest_queue WHERE queue_id=?", (qid,))
        conn.commit()
        send_json(h, 200, {"ok": True})
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Enrichment (vision + text)
# ---------------------------------------------------------------------------

def _build_enrich_prompt_v05(row, ej, vocab_rows) -> str:
    """Design §6 verbatim: 'would I search for this someday' + pill_states.

    vocab_rows: iterable of (slug, display_name, category) rows.
    """
    vocab_lines = "\n".join(
        f"    {r['slug']}  ({r['category'] or 'uncategorized'})  — {r['display_name']}"
        for r in vocab_rows
    )
    # Backward-compat source for existing_tags: pill_states keys first,
    # else v0.4 tags_known ∪ tags_proposed.
    existing = []
    ps = ej.get("pill_states")
    if isinstance(ps, dict):
        existing = sorted(ps.keys())
    else:
        existing = sorted(set((ej.get("tags_known") or [])
                              + (ej.get("tags_proposed") or [])
                              + (ej.get("tags") or [])))
    return f"""You are cataloging an artifact for Mike's personal creative archive
(\"MediaVault\"). Your job is to propose pills — short tags that help Mike
re-find this artifact later when he's browsing by topic, not by ID.

A pill earns its place by answering YES to:

    Would Mike plausibly want to locate this artifact again by this fact?

PASS: named people (Hunter Root, Carsie Blanton); bands; venues (Musikfest,
    Bearsville Theater); cities; content types (live_show, tour_announcement,
    song_page, poster); years; album/song titles.

FAIL: visual details (striped_shirt, long_hair, brick_wall, red_bandana);
    generic descriptors that are better left to description_long
    (acoustic_performance when there's already live_show); adjectives
    (beautiful, bright); anonymous subjects (\"Joe and some other guy\" — skip
    him; \"Cheech and Chong\" — keep them).

Categories (use to place pills; see below for the question each answers):
    bands, people, places, content_kind, topic, scope, rarity.

What each category is for:
    bands        — which band is this? (Hunter Root, Medusa's Disco)
    people       — which named individual? (author:* pills live here)
    places       — what physical place? (lancaster_pa)
    content_kind — what kind of artifact? (live_show, poster, tour_announcement,
                   music_video, fan_art, memorabilia)
    topic        — what is this about? (songwriting, lyme_disease)
    scope        — which of Mike's worlds can claim this? (personal, family, fan)
    rarity       — how rare? exclusive; one of common/notable/rare/unique.

Do NOT propose:
    - year pills (post_date is a separate field below)
    - song titles (find-via-search, not pills)
    - genre pills (out of scope for this archive)
    - preservation pills (retired concept)

Evidence provided:
    Source URL:         {row['source_url'] or 'none'}
    Source platform:    {ej.get('source_platform') or 'unknown'}
    Capture date:       {ej.get('capture_date') or 'unknown'}
    Existing pills:     {', '.join(existing) or 'none'}
    Existing desc:      {ej.get('description_short') or 'none'}
    Extracted text:     {ej.get('extracted_text') or 'none'}
    Images (if any):    {1 if row['raw_path'] else 0} attached

Existing vocabulary (slugs + category + display name you may reuse):
{vocab_lines}

Return ONE JSON object:

    {{
      "description_short": "one sentence",
      "description_long": "2-4 sentences with detail",
      "post_date": "YYYY-MM-DD or null",
      "post_date_confidence": "extracted|manual|estimated|unknown",
      "media_type": "photo|video|audio|link|text|mixed|other",

      "pill_states": {{
        "<slug>": "on_confident" | "on_uncertain" | "off_suspected" | "off_maybe"
      }},

      "warnings": ["missing_category:<name>"],
      "notes": "anything unusual"
    }}

Rules:
- `on_confident`: the evidence directly supports this pill (the image
  shows the band, the URL is the artist's page, etc.).
- `on_uncertain`: the evidence suggests this pill but you want Mike to
  eyeball it.
- `off_suspected`: this pill probably applies based on context, but the
  evidence isn't in-frame enough to commit. Show it so Mike can click it.
- `off_maybe`: weaker hint. Show it only if it's a useful prompt.
- Do NOT propose visual-detail pills. If you notice a striped shirt, put
  it in `description_long`, not in pills.
- Prefer vocabulary slugs. If a novel slug is clearly needed, put it in
  `pill_states` anyway — the system auto-creates it as proposed."""


def _upgrade_v04_enrichment_to_pill_states(ej: dict) -> dict:
    """
    Backward-compat: if enrichment_json is a v0.4 blob with tags_known /
    tags_proposed flat arrays (no pill_states), lift every tag to
    pill_states with state='on_uncertain' so the operator confirms.
    Idempotent; existing pill_states wins.
    """
    if not isinstance(ej, dict):
        return ej
    if isinstance(ej.get("pill_states"), dict):
        return ej
    known = ej.get("tags_known") or []
    proposed = ej.get("tags_proposed") or []
    all_tags = sorted({slugify(t) for t in (known + proposed) if t})
    if not all_tags:
        return ej
    ej["pill_states"] = {t: "on_uncertain" for t in all_tags if t}
    return ej


def handle_enrich(h: BaseHTTPRequestHandler) -> None:
    """
    POST /api/enrich {queue_id}

    Loads the queue row, builds the v0.5 pill-states prompt (design §6),
    stores any new slugs as proposed tags, and writes enrichment_json back
    in pill_states shape. v0.4 shape is transparently upgraded on read.

    NOTE: The actual model invocation requires an Anthropic API key. If the
    key isn't configured we still echo back the prompt so the operator can
    run enrichment manually (e.g. paste into a Claude session).
    """
    body = read_body(h)
    qid = body.get("queue_id")
    if qid is None:
        return send_error(h, 400, "queue_id required")
    conn = db_conn()
    try:
        row = conn.execute(
            "SELECT * FROM ingest_queue WHERE queue_id=?", (qid,)
        ).fetchone()
        if not row:
            return send_error(h, 404, "queue row not found")

        try:
            ej = json.loads(row["enrichment_json"] or "{}")
        except Exception:
            ej = {}
        ej = _upgrade_v04_enrichment_to_pill_states(ej)

        # Phase 2.1: namespace metadata comes from the §5.4 vocabulary
        # registry; the demoted `tags` table is the slug-list source for
        # `slug` + `usage_count` only. The legacy filters on
        # `is_proposed=0` and `category != 'deprecated'` are gone —
        # is_proposed is retired (Decision Brief §9.3 Q2) and the
        # `deprecated` category was a column-value flag whose role is
        # served by the `retired_at` field on the vocabulary registry
        # (already filtered out at namespace level when meta is absent).
        raw_rows = conn.execute(
            "SELECT slug, usage_count FROM tags "
            "ORDER BY usage_count DESC, slug "
            "LIMIT 300"
        ).fetchall()
        ns_meta = load_vocabulary_meta(conn)
        vocab_rows = [vocab_row_for_slug(r["slug"], r["usage_count"], ns_meta)
                      for r in raw_rows]
        prompt = _build_enrich_prompt_v05(row, ej, vocab_rows)

        # If no API key, just return the prompt (caller can invoke offline).
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            return send_json(h, 200, {
                "ok": True,
                "queue_id": qid,
                "prompt": prompt,
                "note": "ANTHROPIC_API_KEY not set; returning prompt only.",
            })

        # Network path (intentionally minimal — full vision requires multipart).
        try:
            req = urllib.request.Request(
                "https://api.anthropic.com/v1/messages",
                data=json.dumps({
                    "model": "claude-3-5-sonnet-20241022",
                    "max_tokens": 1500,
                    "messages": [{"role": "user", "content": prompt}],
                }).encode("utf-8"),
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
            )
            resp = urllib.request.urlopen(req, timeout=60).read()
            out = json.loads(resp.decode("utf-8"))
            text = out.get("content", [{}])[0].get("text", "")
        except urllib.error.HTTPError as e:
            return send_error(h, 502, f"anthropic api: {e}")
        except Exception as e:
            return send_error(h, 502, f"anthropic call failed: {e}")

        try:
            enrichment = json.loads(text)
        except Exception:
            enrichment = {"raw_text": text}

        # Accept either v0.5 (pill_states) or v0.4 (tags_proposed) shape from
        # the model. Upgrade v0.4 → v0.5 in-flight.
        enrichment = _upgrade_v04_enrichment_to_pill_states(enrichment)

        # Auto-create any novel slugs referenced in pill_states as proposed.
        ps = enrichment.get("pill_states") or {}
        if isinstance(ps, dict):
            for raw in ps.keys():
                s = slugify(raw)
                if s:
                    upsert_tag(conn, s)

        conn.execute(
            "UPDATE ingest_queue SET enrichment_json=?, status='enriched', updated_at=? "
            "WHERE queue_id=?",
            (json.dumps(enrichment), now_iso(), qid),
        )
        conn.commit()
        send_json(h, 200, {"ok": True, "queue_id": qid, "enrichment": enrichment})
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Artifact endpoints
# ---------------------------------------------------------------------------

def handle_next_id(h: BaseHTTPRequestHandler) -> None:
    ds = date.today().strftime("%Y%m%d")
    conn = db_conn()
    try:
        conn.execute(
            "INSERT INTO id_sequence(date_str, last_seq) VALUES(?,1) "
            "ON CONFLICT(date_str) DO UPDATE SET last_seq=last_seq+1",
            (ds,),
        )
        seq = conn.execute(
            "SELECT last_seq FROM id_sequence WHERE date_str=?", (ds,)
        ).fetchone()[0]
        conn.commit()
        new_id = f"MV-{ds}-{str(seq).zfill(3)}"
        send_json(h, 200, {"ok": True, "id": new_id})
    finally:
        conn.close()


ARTIFACT_FIELDS = (
    "source_url", "source_platform", "ingest_source", "ingest_date",
    "storage_mode", "local_asset_path", "thumbnail_path", "link_status",
    "parent_artifact_id", "media_type",
    "post_date", "post_date_confidence", "capture_date",
    "status", "released_at", "released_by",
    "description_short", "description_long", "extracted_text",
    "confidence_flags", "notes",
)


def _vault_in_file(raw_path: str, artifact_id: str) -> str:
    """Copy raw_path into catalogs/vaulted/YYYY/MM/<id>.<ext>; return new abs path."""
    src = Path(raw_path)
    today = date.today()
    dst_dir = VAULTED_ROOT / f"{today.year:04d}" / f"{today.month:02d}"
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / f"{artifact_id}{src.suffix.lower()}"
    if not dst.exists():
        shutil.copy2(src, dst)
    return str(dst)


def handle_artifact_save(h: BaseHTTPRequestHandler) -> None:
    """Promote a queue row into a new artifact."""
    body = read_body(h)
    qid = body.get("queue_id")
    aid = body.get("id")
    fields = body.get("fields") or {}
    raw_path = body.get("raw_path")
    release_now = bool(body.get("release_immediately"))
    if not aid:
        return send_error(h, 400, "id required")
    # v0.6 Item 8d follow-up: distinguish "caller sent no tags key" from
    # "caller sent tags=[]". Only the latter should clear existing tags;
    # the former should leave them alone. Same contract as the other
    # content fields in the UPDATE branch below.
    #
    # Crit 3 (§4.5): tag validation is now strict §3.1 (no bare slugs).
    # Pre-validation here gives us a clean canonical list to upsert
    # novel vocab rows with; write_artifact_tags re-validates as part
    # of the single-writer guarantee.
    tags_supplied = "tags" in fields
    if tags_supplied:
        try:
            tags = validate_artifact_tags(fields.get("tags"))
        except TagValidationError as e:
            return send_error(h, 400, str(e))
    else:
        tags = []

    storage_mode = fields.get("storage_mode") or "vaulted"
    local_path = fields.get("local_asset_path") or raw_path

    conn = db_conn()
    try:
        # If vaulting and the file isn't yet inside the vaulted root, copy it.
        if storage_mode == "vaulted" and local_path:
            try:
                lp = Path(local_path)
                vroot = VAULTED_ROOT.resolve()
                if not str(lp.resolve()).lower().startswith(str(vroot).lower()):
                    if lp.exists():
                        local_path = _vault_in_file(str(lp), aid)
            except Exception:
                pass  # fall through; user's path stays as-is

        # Tag upserts (proposed if not in vocab)
        existing = {r[0] for r in conn.execute("SELECT slug FROM tags").fetchall()}
        for s in tags:
            if s not in existing:
                upsert_tag(conn, s)

        status = "released" if release_now else (fields.get("status") or "vault")
        released_at = now_iso() if release_now else None
        released_by = "mike" if release_now else None
        ingest_date = fields.get("ingest_date") or date.today().isoformat()

        # v0.6 Item 8d #1 fix: previously this handler always INSERTed. That
        # crashed on demote-then-save (artifacts.id already exists because
        # /api/artifact-requeue only flips status='inbox'; the row persists)
        # and also would have crashed on any fresh save, since the INSERT
        # never bound created_at/updated_at (both NOT NULL, no DEFAULT).
        # SQLite evaluates NOT NULL before PK UNIQUE, which is why the error
        # surfaced as "NOT NULL constraint failed: artifacts.created_at"
        # rather than a PK collision.
        #
        # Correct behavior: if the artifact row already exists, UPDATE it
        # (preserving created_at and the original ingest_date). Otherwise
        # INSERT a fresh row, stamping created_at = updated_at = now.
        now = now_iso()
        existing = conn.execute(
            "SELECT 1 FROM artifacts WHERE id=?", (aid,)
        ).fetchone()

        # Fields the save flow owns regardless of caller input — storage/path
        # come from the server-side vaulting decision above, and status+release
        # bookkeeping is computed from release_now. These always get written.
        AUTHORITATIVE = {
            "storage_mode": storage_mode,
            "local_asset_path": local_path,
            "status": status,
            "released_at": released_at,
            "released_by": released_by,
        }

        if existing:
            # v0.6 Item 8d #1 follow-up: NEVER write a field the caller didn't
            # explicitly supply with a value. Older logic ran scalar.get(k) for
            # every ARTIFACT_FIELDS column, which silently NULLed descriptions,
            # media_type, post_date, thumbnail_path, etc. any time the frontend
            # sent a sparse `fields` dict (as happens on demote-then-save when
            # the inbox form hadn't been pre-populated with the existing row).
            # That wipe was catastrophic — it gutted MV-HR-20260405-003 in
            # testing. Rule: caller-supplied content fields need both
            # `k in fields` AND a non-None value before we touch them.
            # Tags follow the same rule: only touch tags if the caller
            # explicitly included a "tags" key in fields. Omitting tags
            # from the payload leaves the existing tag set alone.
            #
            # Crit 3 (§4.5): tags are NEVER part of this UPDATE's SET clause.
            # The single-writer rule routes every tag-write through
            # write_artifact_tags below, which runs in the same connection /
            # transaction as this UPDATE.
            sets: list = []
            args: list = []
            for k, v in AUTHORITATIVE.items():
                sets.append(f"{k}=?")
                args.append(v)
            for k in ARTIFACT_FIELDS:
                if k in AUTHORITATIVE:
                    continue  # already handled above
                if k not in fields:
                    continue  # caller didn't mention it — leave alone
                v = fields[k]
                if v is None:
                    continue  # explicit null from a blank form field — skip
                sets.append(f"{k}=?")
                args.append(v)
            sets.append("updated_at=?")
            args.append(now)
            args.append(aid)
            conn.execute(
                f"UPDATE artifacts SET {','.join(sets)} WHERE id=?",
                args,
            )
        else:
            # Fresh save from the inbox queue. Default ingest_date to today
            # if the caller didn't set one, and bind both timestamps.
            #
            # Crit 3 (§4.5): tags is intentionally absent from the column
            # list — the schema default ('[]') seeds the row and
            # write_artifact_tags below sets the real tag set. This keeps
            # the single-writer property: no INSERT INTO artifacts(...)
            # in this codebase mentions the tags column.
            scalar = dict(fields)
            scalar.update(AUTHORITATIVE)
            scalar.setdefault("ingest_date", ingest_date)
            cols = ["id", *ARTIFACT_FIELDS, "created_at", "updated_at"]
            vals: list = [aid,
                          *[scalar.get(k) for k in ARTIFACT_FIELDS],
                          now, now]
            placeholders = ",".join(["?"] * len(cols))
            conn.execute(
                f"INSERT INTO artifacts({','.join(cols)}) VALUES({placeholders})",
                vals,
            )
        # Crit 3 (§4.5): the ONE tag-write for this handler. Runs after
        # the INSERT or UPDATE above (the row now exists either way), in
        # the same connection. write_artifact_tags handles dedupe, the
        # added/removed diff against the row's current tags, and the
        # usage-count cache refresh. No adjust_tag_usage call is needed
        # — write_artifact_tags subsumes it.
        if tags_supplied:
            try:
                write_artifact_tags(conn, aid, tags)
            except TagValidationError as e:
                # Pre-validation above should have caught this, but the
                # single-writer is the authoritative gate — surface a 400
                # if it ever fires here.
                return send_error(h, 400, str(e))
        if qid is not None:
            # v0.5 bug fix: release-in-inbox must mark the queue row done, not
            # leave it in 'keep' (which made it look un-processed next session).
            queue_status = "approved" if release_now else "keep"
            conn.execute(
                "UPDATE ingest_queue SET artifact_id=?, status=?, updated_at=? "
                "WHERE queue_id=?",
                (aid, queue_status, now_iso(), qid),
            )
        conn.commit()
        send_json(h, 200, {"ok": True, "id": aid, "status": status})
    except sqlite3.IntegrityError as e:
        return send_error(h, 409, f"db integrity: {e}")
    finally:
        conn.close()


def handle_artifact_update(h: BaseHTTPRequestHandler) -> None:
    body = read_body(h)
    aid = body.get("id")
    fields = body.get("fields") or {}
    if not aid:
        return send_error(h, 400, "id required")
    conn = db_conn()
    try:
        row = conn.execute("SELECT tags FROM artifacts WHERE id=?", (aid,)).fetchone()
        if not row:
            return send_error(h, 404, "artifact not found")

        # Crit 3 (§4.5): tags are NEVER part of this UPDATE's SET clause.
        # They flow through write_artifact_tags below, in the same
        # connection / transaction. Pre-validate now so we can register
        # novel slugs as proposed before the write.
        new_tags = None
        if "tags" in fields:
            try:
                new_tags = validate_artifact_tags(fields["tags"])
            except TagValidationError as e:
                return send_error(h, 400, str(e))
            existing = {r[0] for r in conn.execute("SELECT slug FROM tags").fetchall()}
            for s in new_tags:
                if s not in existing:
                    upsert_tag(conn, s)

        sets = []
        args: list = []
        for k in ARTIFACT_FIELDS:
            if k in fields and k != "tags":
                sets.append(f"{k}=?")
                args.append(fields[k])

        if not sets and new_tags is None:
            return send_error(h, 400, "nothing to update")

        if sets:
            sets.append("updated_at=?")
            args.append(now_iso())
            args.append(aid)
            conn.execute(f"UPDATE artifacts SET {','.join(sets)} WHERE id=?", args)

        added: list = []
        removed: list = []
        if new_tags is not None:
            try:
                result = write_artifact_tags(conn, aid, new_tags)
            except TagValidationError as e:
                return send_error(h, 400, str(e))
            added = result["added"]
            removed = result["removed"]

        conn.commit()
        send_json(h, 200, {"ok": True, "added": added, "removed": removed})
    finally:
        conn.close()


def _set_status(h: BaseHTTPRequestHandler, new_status: str,
                set_release: bool = False, clear_release: bool = False) -> None:
    body = read_body(h)
    aid = body.get("id")
    if not aid:
        return send_error(h, 400, "id required")
    conn = db_conn()
    try:
        sets = ["status=?", "updated_at=?"]
        args: list = [new_status, now_iso()]
        if set_release:
            sets += ["released_at=?", "released_by=?"]
            args += [now_iso(), "mike"]
        if clear_release:
            sets += ["released_at=?", "released_by=?"]
            args += [None, None]
        args.append(aid)
        conn.execute(f"UPDATE artifacts SET {','.join(sets)} WHERE id=?", args)
        conn.commit()
        send_json(h, 200, {"ok": True, "id": aid, "status": new_status})
    finally:
        conn.close()


def handle_artifact_release(h):    _set_status(h, "released", set_release=True)
def handle_artifact_unrelease(h):  _set_status(h, "vault",   clear_release=True)
def handle_artifact_archive(h):    _set_status(h, "archived")


def handle_artifact_delete(h: BaseHTTPRequestHandler) -> None:
    body = read_body(h)
    aid = body.get("id")
    if not aid:
        return send_error(h, 400, "id required")
    conn = db_conn()
    try:
        # Decrement usage_count for this artifact's tags
        row = conn.execute("SELECT tags FROM artifacts WHERE id=?", (aid,)).fetchone()
        if not row:
            return send_error(h, 404, "artifact not found")
        try:
            tags = json.loads(row["tags"] or "[]")
        except Exception:
            tags = []
        adjust_tag_usage(conn, [], tags)
        conn.execute("DELETE FROM artifacts WHERE id=?", (aid,))
        conn.commit()
        send_json(h, 200, {"ok": True, "id": aid})
    finally:
        conn.close()


def handle_artifact_requeue(h: BaseHTTPRequestHandler) -> None:
    body = read_body(h)
    aid = body.get("id")
    if not aid:
        return send_error(h, 400, "id required")
    conn = db_conn()
    try:
        row = conn.execute("SELECT * FROM artifacts WHERE id=?", (aid,)).fetchone()
        if not row:
            return send_error(h, 404, "artifact not found")
        cur = conn.execute(
            "INSERT INTO ingest_queue(ingest_source, raw_path, source_url, queued_at, "
            " status, artifact_id, updated_at) VALUES(?,?,?,?,?,?,?)",
            ("requeue", row["local_asset_path"], row["source_url"], now_iso(),
             "pending", aid, now_iso()),
        )
        conn.execute(
            "UPDATE artifacts SET status='inbox', updated_at=? WHERE id=?",
            (now_iso(), aid),
        )
        conn.commit()
        send_json(h, 200, {"ok": True, "queue_id": cur.lastrowid})
    finally:
        conn.close()


def handle_thumbgen(h: BaseHTTPRequestHandler) -> None:
    body = read_body(h)
    aid = body.get("id")
    src = body.get("path")
    if not src:
        return send_error(h, 400, "path required")
    sp = Path(src)
    if not sp.exists():
        return send_error(h, 404, "source not found")
    THUMB_DIR.mkdir(parents=True, exist_ok=True)
    out = THUMB_DIR / f"{aid or sp.stem}.jpg"
    try:
        out.write_bytes(make_thumbnail(sp))
    except Exception as e:
        return send_error(h, 500, f"thumb gen failed: {e}")
    if aid:
        conn = db_conn()
        try:
            conn.execute(
                "UPDATE artifacts SET thumbnail_path=?, updated_at=? WHERE id=?",
                (str(out), now_iso(), aid),
            )
            conn.commit()
        finally:
            conn.close()
    send_json(h, 200, {"ok": True, "thumbnail_path": str(out)})


# ---------------------------------------------------------------------------
# Tag management endpoints
# ---------------------------------------------------------------------------

def handle_tag_create(h: BaseHTTPRequestHandler) -> None:
    """
    Create a tag-cache row.

    Phase 2.3 of the source-of-truth refactor: namespace metadata lives
    in the §5.4 `vocabulary` registry -- never in the `tags` cache. The
    handler writes only the columns that survive the §5.2 schema
    demotion (slug, usage_count, created_at).

      Required: slug. The slug self-describes its namespace via the
        `namespace:value` prefix (e.g. `album:arkansas`); slugify()
        enforces the grammar.
      Optional: display_name, description, category, group_name (alias),
        is_proposed, is_exclusive. All accepted-and-discarded for
        backward compatibility with the v0.6 UI's edit modal. The
        latter four (`description`, `category`, `is_proposed`,
        `is_exclusive`) name columns that **no longer exist** in the
        live schema -- Phase 2.5 dropped them on 2026-05-20 (CHANGELOG
        v0.5.3 / SPEC.md §6.5).

    Per-slug uniqueness is enforced by the `slug` PRIMARY KEY -- the
    v0.6-era composite `(slug, category)` uniqueness retired with the
    `category` column in Phase 2.5.
    """
    body = read_body(h)
    slug = slugify(body.get("slug"))
    if not slug:
        return send_error(h, 400, "invalid slug")
    conn = db_conn()
    try:
        existing = conn.execute(
            "SELECT slug FROM tags WHERE slug=?", (slug,)
        ).fetchone()
        if existing:
            return send_error(h, 409, f"tag {slug!r} already exists")
        upsert_tag(conn, slug)
        conn.commit()
        send_json(h, 200, {
            "ok": True,
            "slug": slug,
            "category": namespace_of(slug),  # for backward-compat with v0.6 UI
        })
    finally:
        conn.close()


def handle_tag_update(h: BaseHTTPRequestHandler) -> None:
    """
    Update a tag-cache row.

    Phase 2.3 of the source-of-truth refactor: only the rename path
    (slug -> new_slug) has a visible effect. The cache holds only
    slug + usage_count + created_at, so body fields `display_name` /
    `description` / `category` / `is_exclusive` / `group_name` are
    accepted-and-ignored for backward compat with the v0.6 UI edit
    modal. Namespace metadata lives in the §5.4 `vocabulary` registry.
    """
    body = read_body(h)
    slug = body.get("slug")
    if not slug:
        return send_error(h, 400, "slug required")
    new_slug = body.get("new_slug")
    if new_slug:
        new_slug = slugify(new_slug)
        if not new_slug:
            return send_error(h, 400, "invalid new_slug")
    conn = db_conn()
    try:
        row = conn.execute(
            "SELECT slug, usage_count FROM tags WHERE slug=?", (slug,)
        ).fetchone()
        if not row:
            return send_error(h, 404, "tag not found")
        if new_slug and new_slug != slug:
            # Collision check is now single-slug PK; the v0.6 composite
            # (slug, category) handshake collapses since category is no
            # longer in the cache.
            existing = conn.execute(
                "SELECT slug, usage_count FROM tags WHERE slug=?",
                (new_slug,),
            ).fetchone()
            if existing:
                return send_json(h, 409, {
                    "ok": False,
                    "error": "merge_required",
                    "merge_offered": True,
                    "target_slug": existing["slug"],
                    # `target_category` is preserved as a key for the
                    # v0.6 UI's merge offer; populated from the slug's
                    # namespace prefix (§5.4 vocabulary registry shape).
                    "target_category": namespace_of(existing["slug"]),
                    "target_usage": existing["usage_count"] or 0,
                    "target_display_name": display_name_for(existing["slug"]),
                })
            # Crit 3 (§4.5): the rename's sweep over artifacts goes
            # through the single coordinated writer. We seed the new
            # cache row with usage_count=0; write_artifact_tags
            # increments it per artifact as the sweep replaces the old
            # slug with the new one, so the final cache value matches
            # reality without any manual carry-over.
            upsert_tag(conn, new_slug)
            rows = conn.execute(
                "SELECT id, tags FROM artifacts "
                "WHERE EXISTS (SELECT 1 FROM json_each(artifacts.tags) WHERE value=?)",
                (slug,),
            ).fetchall()
            for ar in rows:
                try:
                    arr = json.loads(ar["tags"])
                except Exception:
                    continue
                new_arr = [new_slug if x == slug else x for x in arr]
                try:
                    write_artifact_tags(conn, ar["id"], new_arr)
                except TagValidationError as e:
                    # An existing artifact carries a malformed tag --
                    # abort the rename so the operator can address the
                    # data before the sweep runs.
                    conn.rollback()
                    return send_error(h, 400,
                        f"artifact {ar['id']} carries invalid tag: {e}")
            conn.execute("DELETE FROM tags WHERE slug=?", (slug,))
            slug = new_slug
        # No-op path: registry-era body fields are ignored (see docstring).
        conn.commit()
        send_json(h, 200, {"ok": True, "slug": slug})
    finally:
        conn.close()


# Removed Phase 2.3 (source-of-truth refactor §4.4.C): handle_tag_accept
# is gone. The is_proposed workflow is retired (Decision Brief §9.3 Q2);
# v0.6 already removed the UI ACCEPT button (mediavault.html v0.6 Item 8d
# follow-up C4). The /api/tag-accept route registration and the dead
# `tagAccept()` JS helper are removed in the same commit.


def handle_tag_reject(h: BaseHTTPRequestHandler) -> None:
    """
    Reject a tag.

      'remove'    -- strip tag from every artifact, delete cache row.
      'replace'   -- swap to replacement_slug across artifacts, delete
                     the original cache row.

    Phase 2.3 of the source-of-truth refactor: the 'deprecate' mode is
    retired. There is no `category='deprecated'` state to enter (the
    `category` column is dropped by §5.2 in Phase 2.5); the legacy
    deprecation semantics were "leave artifacts, hide tag from
    autocomplete" -- that role is served by `retired_at` on the §5.4
    `vocabulary` registry at the namespace level. The cache row's
    sole role is usage counting.
    """
    body = read_body(h)
    slug = body.get("slug")
    mode = body.get("mode")
    repl = body.get("replacement_slug")
    if not slug or mode not in ("remove", "replace"):
        return send_error(h, 400,
            "slug and valid mode required (remove|replace)")
    if mode == "replace" and not repl:
        return send_error(h, 400, "replacement_slug required for replace mode")
    if repl:
        repl = slugify(repl)
        if not repl:
            return send_error(h, 400, "invalid replacement_slug")
    conn = db_conn()
    try:
        # Crit 3 (§4.5): the remove/replace sweep over artifacts goes
        # through the single coordinated writer. write_artifact_tags
        # handles the per-artifact diff and the usage_count cache
        # delta automatically.
        if mode == "replace":
            # ensure replacement exists in the cache BEFORE the sweep,
            # so write_artifact_tags' usage_count UPDATE lands on a
            # real row.
            if not conn.execute("SELECT slug FROM tags WHERE slug=?", (repl,)).fetchone():
                upsert_tag(conn, repl)

        rows = conn.execute(
            "SELECT id, tags FROM artifacts "
            "WHERE EXISTS (SELECT 1 FROM json_each(artifacts.tags) WHERE value=?)",
            (slug,),
        ).fetchall()
        affected = 0
        for ar in rows:
            try:
                arr = json.loads(ar["tags"])
            except Exception:
                continue
            if mode == "remove":
                new = [x for x in arr if x != slug]
            else:
                new = [repl if x == slug else x for x in arr]
            try:
                write_artifact_tags(conn, ar["id"], new)
            except TagValidationError as e:
                conn.rollback()
                return send_error(h, 400,
                    f"artifact {ar['id']} carries invalid tag: {e}")
            affected += 1

        conn.execute("DELETE FROM tags WHERE slug=?", (slug,))
        conn.commit()
        send_json(h, 200, {"ok": True, "slug": slug, "mode": mode, "affected": affected})
    finally:
        conn.close()


def handle_tag_delete(h: BaseHTTPRequestHandler) -> None:
    body = read_body(h)
    slug = body.get("slug")
    if not slug:
        return send_error(h, 400, "slug required")
    conn = db_conn()
    try:
        row = conn.execute("SELECT usage_count FROM tags WHERE slug=?", (slug,)).fetchone()
        if not row:
            return send_error(h, 404, "tag not found")
        if row[0] != 0:
            return send_error(h, 409, f"tag in use ({row[0]} artifacts)")
        conn.execute("DELETE FROM tags WHERE slug=?", (slug,))
        conn.commit()
        send_json(h, 200, {"ok": True, "slug": slug})
    finally:
        conn.close()


def handle_tag_merge(h: BaseHTTPRequestHandler) -> None:
    """
    POST /api/tag-merge {sources: [slug, ...], target: slug}

    For each artifact carrying any source slug, replace the source with the
    target (deduped, sorted). Then delete the source vocab rows. Usage counts
    are recomputed from artifacts.tags afterwards. Single transaction.
    """
    body = read_body(h)
    sources = body.get("sources") or []
    target = slugify(body.get("target") or "")
    if not isinstance(sources, list) or not sources or not target:
        return send_error(h, 400, "sources (list) and target (slug) required")
    sources = [slugify(s) for s in sources if s]
    sources = [s for s in sources if s and s != target]
    if not sources:
        return send_error(h, 400, "no valid source slugs after sanitisation")

    conn = db_conn()
    try:
        # Ensure target exists (auto-create if absent, no category assumed).
        if not conn.execute("SELECT slug FROM tags WHERE slug=?", (target,)).fetchone():
            upsert_tag(conn, target)

        # Crit 3 (§4.5): the merge sweep over artifacts goes through
        # the single coordinated writer. write_artifact_tags handles
        # the per-artifact diff and the per-slug usage_count delta;
        # the final full-table recompute below remains as
        # defense-in-depth (§3.2 backstop-style).
        affected = 0
        for src in sources:
            rows = conn.execute(
                "SELECT id, tags FROM artifacts "
                "WHERE EXISTS (SELECT 1 FROM json_each(artifacts.tags) WHERE value=?)",
                (src,),
            ).fetchall()
            for ar in rows:
                try:
                    arr = json.loads(ar["tags"] or "[]")
                except Exception:
                    arr = []
                new_arr = [target if x == src else x for x in arr]
                try:
                    write_artifact_tags(conn, ar["id"], new_arr)
                except TagValidationError as e:
                    conn.rollback()
                    return send_error(h, 400,
                        f"artifact {ar['id']} carries invalid tag: {e}")
                affected += 1
            conn.execute("DELETE FROM tags WHERE slug=?", (src,))

        # Recompute usage counts from scratch for sanity. The single
        # writer keeps the cache correct row-by-row; this full recompute
        # is the §3.2 backstop, not the authority.
        conn.execute(
            "UPDATE tags SET usage_count = ("
            "  SELECT COUNT(*) FROM artifacts a, json_each(a.tags) j "
            "  WHERE j.value = tags.slug)"
        )
        conn.commit()
        send_json(h, 200, {
            "ok": True, "merged": sources, "into": target,
            "artifacts_touched": affected,
        })
    finally:
        conn.close()


def handle_tag_bulk_delete(h: BaseHTTPRequestHandler) -> None:
    """
    POST /api/tag-bulk-delete {slugs: [slug, ...]}

    Strip every listed slug from every artifact carrying it, then delete the
    vocab rows. Usage counts are recomputed from artifacts.tags. Single
    transaction. Returns per-slug touch counts.
    """
    body = read_body(h)
    slugs = body.get("slugs") or []
    if not isinstance(slugs, list) or not slugs:
        return send_error(h, 400, "slugs (list) required")
    slugs = [slugify(s) for s in slugs if s]
    slugs = [s for s in slugs if s]
    if not slugs:
        return send_error(h, 400, "no valid slugs after sanitisation")

    conn = db_conn()
    try:
        # Crit 3 (§4.5): the bulk-delete sweep over artifacts goes
        # through the single coordinated writer. write_artifact_tags
        # handles the per-artifact diff and the usage_count delta;
        # the final full-table recompute remains as defense-in-depth.
        per_slug = {}
        for slug in slugs:
            rows = conn.execute(
                "SELECT id, tags FROM artifacts "
                "WHERE EXISTS (SELECT 1 FROM json_each(artifacts.tags) WHERE value=?)",
                (slug,),
            ).fetchall()
            for ar in rows:
                try:
                    arr = json.loads(ar["tags"] or "[]")
                except Exception:
                    arr = []
                new = [x for x in arr if x != slug]
                try:
                    write_artifact_tags(conn, ar["id"], new)
                except TagValidationError as e:
                    conn.rollback()
                    return send_error(h, 400,
                        f"artifact {ar['id']} carries invalid tag: {e}")
            per_slug[slug] = len(rows)
            conn.execute("DELETE FROM tags WHERE slug=?", (slug,))

        conn.execute(
            "UPDATE tags SET usage_count = ("
            "  SELECT COUNT(*) FROM artifacts a, json_each(a.tags) j "
            "  WHERE j.value = tags.slug)"
        )
        conn.commit()
        send_json(h, 200, {"ok": True, "deleted": per_slug})
    finally:
        conn.close()


def handle_fb_candidate_save(h: BaseHTTPRequestHandler) -> None:
    body = read_body(h)
    candidates = body.get("candidates")
    if candidates is None:
        return send_error(h, 400, "candidates required")
    FB_CANDIDATES_JSON.write_text(json.dumps(candidates, indent=2), encoding="utf-8")
    send_json(h, 200, {"ok": True, "count": len(candidates) if isinstance(candidates, list) else 0})


# ---------------------------------------------------------------------------
# Route table
# ---------------------------------------------------------------------------

GET_ROUTES = {
    "/":                       handle_root,
    "/ping":                   handle_ping,
    "/db":                     handle_db,
    "/fb":                     handle_fb_html,
    "/api/queue":              handle_queue_list,
    "/api/tags":               handle_tags_list,
    "/api/fb-candidates":      handle_fb_candidates_get,
    "/api/deep-dive-vocabulary": handle_deep_dive_vocabulary,  # from imgserver_extensions (retained per Phase v5-5 Q-1; will be repurposed)
    "/ext/hr_manager_renderer.js": handle_renderer_js,
}

POST_ROUTES = {
    "/api/intake-upload":            handle_intake_upload,
    "/api/intake-url":               handle_intake_url,
    "/api/intake-from-fb-candidate": handle_intake_from_fb_candidate,
    "/api/queue-update":             handle_queue_update,
    "/api/queue-delete":             handle_queue_delete,
    "/api/enrich":                   handle_enrich,
    "/api/next-id":                  handle_next_id,
    "/api/artifact-save":            handle_artifact_save,
    "/api/artifact-update":          handle_artifact_update,
    "/api/artifact-release":         handle_artifact_release,
    "/api/artifact-unrelease":       handle_artifact_unrelease,
    "/api/artifact-archive":         handle_artifact_archive,
    "/api/artifact-delete":          handle_artifact_delete,
    "/api/artifact-requeue":         handle_artifact_requeue,
    "/api/artifact-register":        handle_artifact_register,   # from imgserver_extensions
    "/api/thumbgen":                 handle_thumbgen,
    "/api/tag-create":               handle_tag_create,
    "/api/tag-update":               handle_tag_update,
    "/api/tag-reject":               handle_tag_reject,
    "/api/tag-delete":               handle_tag_delete,
    "/api/tag-merge":                handle_tag_merge,
    "/api/tag-bulk-delete":          handle_tag_bulk_delete,
    "/api/fb-candidate-save":        handle_fb_candidate_save,
}

# Prefix-matched routes (path starts with these — extension via query string).
GET_PREFIX_ROUTES = [
    ("/image-raw", handle_image_raw),
    ("/asset-raw", handle_asset_raw),
]

# ROUTES totals (kept verifiable by code, not just comments):
ROUTE_COUNT = (len(GET_ROUTES) + len(POST_ROUTES) + len(GET_PREFIX_ROUTES))


# ---------------------------------------------------------------------------
# Handler class
# ---------------------------------------------------------------------------

class H(BaseHTTPRequestHandler):
    server_version = "MediaVault/0.5"

    def log_message(self, fmt, *args):  # noqa: D401
        # Quieter access log, prefixed for grep.
        sys.stdout.write("[mv] " + (fmt % args) + "\n")

    # CORS preflight (used by the optional capture extension)
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.end_headers()

    def _dispatch(self, table, prefix_table=None):
        path = urlparse(self.path).path
        fn = table.get(path)
        if fn is not None:
            try:
                fn(self)
            except Exception as e:
                send_error(self, 500, f"handler error: {e}")
            return
        if prefix_table:
            for prefix, fn in prefix_table:
                if path == prefix or path.startswith(prefix + "?") or path.startswith(prefix + "/"):
                    try:
                        fn(self)
                    except Exception as e:
                        send_error(self, 500, f"handler error: {e}")
                    return
        send_error(self, 404, f"no route: {path}")

    def do_GET(self):
        self._dispatch(GET_ROUTES, GET_PREFIX_ROUTES)

    def do_POST(self):
        self._dispatch(POST_ROUTES)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(open_browser: bool = True) -> None:
    print(f"MediaVault imgserver v0.5")
    print(f"  DB:    {DB_PATH}")
    print(f"  HTML:  {MEDIAVAULT_HTML}")
    print(f"  Port:  {PORT} on {HOST}")
    print(f"  Routes: {ROUTE_COUNT}")
    print()
    print("GET routes:")
    for p in sorted(GET_ROUTES):
        print(f"  GET  {p}")
    for p, _ in GET_PREFIX_ROUTES:
        print(f"  GET  {p}* (prefix)")
    print("POST routes:")
    for p in sorted(POST_ROUTES):
        print(f"  POST {p}")
    print()

    server = ThreadingHTTPServer((HOST, PORT), H)
    if open_browser:
        try:
            webbrowser.open(f"http://{HOST}:{PORT}/")
        except Exception:
            pass
    print(f"Serving http://{HOST}:{PORT}/  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()


if __name__ == "__main__":
    main(open_browser=("--no-browser" not in sys.argv))
