"""
imgserver_extensions.py
=======================
Handler functions that extend imgserver.py without rewriting it.

  1. handle_artifact_register(handler) - POST /api/artifact-register
       Creates an artifacts row pointing at any on-disk path. Bypasses
       the image-only ingest pipeline. Used for HTML page saves, audio,
       JSON, and any other pre-curated artifact.

  2. handle_asset_raw(handler) - GET /asset-raw?path=<absolute>
       Serves an arbitrary local file with a best-effort Content-Type.
       The /image-raw route already does this for images; this is its
       generalized twin.

  3. handle_deep_dive_vocabulary(handler) - GET /api/deep-dive-vocabulary
       Reads a vocabulary CSV from the museum repo at the hardcoded
       absolute path and returns the parsed structure (groups + per-tag
       rows). Originally added in Phase 4 of the Deep Dive feature as
       the picker source for an MV-side curation tab. The curation tab
       was removed in Phase v5-5 (deep tags now flow museum -> MV via
       the museum's `tools/sync-deep-tags-to-mv.mjs` export); this
       endpoint is retained per Phase v5-5 Q-1 as the suggestion source
       for MV's standard pill wall in a future session. The endpoint
       name and URL preserve git-history continuity; both may be
       renamed when the new role lands.

INTEGRATION (in imgserver.py):

  Add at top, with other imports:
      from imgserver_extensions import (
          handle_artifact_register,
          handle_asset_raw,
          handle_deep_dive_vocabulary,
      )

  Add in do_POST before the 404 fallthrough:
      if p.path == "/api/artifact-register":
          return handle_artifact_register(self)

  Add in do_GET before the 404 fallthrough:
      if p.path == "/asset-raw":
          return handle_asset_raw(self)
      if p.path == "/api/deep-dive-vocabulary":
          return handle_deep_dive_vocabulary(self)

Safety properties:
- handle_asset_raw refuses to serve any path that isn't under C:\\AI\\ - this
  prevents a malicious UI injection from dumping arbitrary filesystem contents.
- handle_artifact_register validates enum values against the artifacts schema
  before inserting, so bad data can't poison the DB.

v0.5 NOTES (design sec.8):
- DOMAIN_ENUM and the per-domain prefix mapping are deleted. The artifacts
  table never had a 'domain' column on disk; the v0.4 migration dropped it.
- All `tags_*` per-category columns are gone. Tags are a single JSON array
  in `artifacts.tags`. Callers send them as `tags: ["slug", ...]` (or as a
  pre-encoded JSON string).
- ID format is MV-YYYYMMDD-NNN; the id_sequence table key is `date_str`.
- author_name, tags_permission, permission_contact, permission_evidence_path
  columns are dropped. Callers that used to send `author_name` should send
  an `author:<slug>` pill in the `tags` array instead.
"""

from __future__ import annotations
import csv
import json
import mimetypes
import os
import re
import sqlite3
from pathlib import Path
from urllib.parse import urlparse, parse_qs

# Same path imgserver.py uses. Kept in sync by convention.
BASE = Path(r"C:\AI\Platform\MediaVault")
DB_PATH = BASE / "core" / "mediavault.sqlite"

# Allowed filesystem roots for /asset-raw. Absolute, normalized.
# Anything outside this tree is refused 403 regardless of what the UI asks for.
ASSET_ROOTS = [
    Path(r"C:\AI").resolve(),
]

# Enum whitelists mirroring the artifacts table CHECK constraints.
# Kept here so we can validate before INSERT rather than letting SQLite
# throw an opaque IntegrityError back to the client.
SOURCE_PLATFORM    = {"instagram", "youtube", "facebook", "bandcamp",
                      "press", "local", "other", "reverbnation"}
MEDIA_TYPE         = {"photo", "video", "audio", "link", "text", "mixed", "other"}
LINK_STATUS        = {"live", "dead", "local-only"}
POST_DATE_CONF     = {"extracted", "manual", "estimated", "unknown"}
INGEST_SOURCE      = {"screenshot-pipeline", "local-drop", "url-entry",
                      "csv-import", "extension-capture"}
STORAGE_MODE       = {"vaulted", "referenced", "url_only"}
STATUS_ENUM        = {"vault", "released", "archived", "deleted"}

# v0.5 slug grammar: lowercase, [a-z0-9_], optional single "namespace:" prefix.
_SLUG_RE = re.compile(r"^(?:[a-z0-9_]+:)?[a-z0-9_]+$")


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _json_response(handler, status, payload):
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _path_is_inside(child: Path, roots: list[Path]) -> bool:
    """True iff child resolves to a path beneath one of the allowed roots."""
    try:
        resolved = child.resolve()
    except Exception:
        return False
    for r in roots:
        try:
            resolved.relative_to(r)
            return True
        except ValueError:
            continue
    return False


def _slugify(value):
    """v0.5 slug: lowercase, optional namespace:, [a-z0-9_]."""
    if value is None:
        return None
    s = str(value).strip().lower()
    if not s:
        return None
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
    return full if _SLUG_RE.match(full) else None


def _coerce_tags(value) -> list[str]:
    """Accept list, JSON string, or None. Return a deduped, sorted slug list."""
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
        s = _slugify(v)
        if s:
            out.add(s)
    return sorted(out)


def _next_artifact_id(conn: sqlite3.Connection) -> str:
    """v0.5: MV-YYYYMMDD-NNN via id_sequence(date_str PK, last_seq)."""
    from datetime import date
    ds = date.today().strftime("%Y%m%d")
    conn.execute(
        "INSERT INTO id_sequence(date_str, last_seq) VALUES(?, 1) "
        "ON CONFLICT(date_str) DO UPDATE SET last_seq = last_seq + 1",
        [ds],
    )
    seq = conn.execute(
        "SELECT last_seq FROM id_sequence WHERE date_str=?", [ds]
    ).fetchone()[0]
    return f"MV-{ds}-{str(seq).zfill(3)}"


def _infer_media_type(path: Path) -> str:
    """Guess media_type from file extension when caller didn't specify."""
    ext = path.suffix.lower()
    if ext in {".jpg", ".jpeg", ".png", ".gif", ".webp",
               ".heic", ".heif", ".bmp", ".tiff", ".tif"}:
        return "photo"
    if ext in {".mp4", ".mov", ".avi", ".mkv"}:
        return "video"
    if ext in {".mp3", ".wav", ".flac", ".m4a", ".ogg"}:
        return "audio"
    if ext in {".html", ".htm", ".pdf"}:
        return "link"
    if ext in {".txt", ".md", ".json"}:
        return "text"
    return "other"


# ------------------------------------------------------------------
# POST /api/artifact-register
# ------------------------------------------------------------------

def handle_artifact_register(handler) -> None:
    """
    Body JSON fields:
      OPTIONAL (passed through if present, else sensible default):
        id                 artifact ID (auto-assigned if missing)
        ingest_source      default 'url-entry'
        source_url         canonical URL this asset represents
        source_platform    one of SOURCE_PLATFORM
        media_type         one of MEDIA_TYPE; inferred from extension when
                           a local file is provided. REQUIRED in the body
                           when local_asset_path is omitted (no file to
                           infer from).
        storage_mode       one of STORAGE_MODE; default 'vaulted' (file on disk)
        status             one of STATUS_ENUM; default 'vault'
        link_status        one of LINK_STATUS; default 'local-only' since the
                           file lives on disk
        local_asset_path   absolute path to the file on disk. REQUIRED when
                           storage_mode is 'vaulted' or 'referenced'.
                           OPTIONAL when storage_mode == 'url_only' (the
                           catalog record is the preservation artifact and
                           there are no local bytes). When provided in the
                           url_only case it is still validated normally:
                           the path must exist and must live under one of
                           ASSET_ROOTS. Operators may legitimately reference
                           an existing snapshot from a url_only artifact,
                           and the safety check stands.
        parent_artifact_id ID of parent artifact (self-FK)
        post_date          YYYY-MM-DD
        post_date_confidence  one of POST_DATE_CONF; default 'unknown'
        capture_date       YYYY-MM-DD; default = today
        description_short
        description_long
        extracted_text
        tags               JSON array of slugs (author:* pills go here too)
        thumbnail_path
        confidence_flags
        notes
    """
    try:
        length = int(handler.headers.get("Content-Length", 0))
        body = json.loads(handler.rfile.read(length)) if length else {}
    except Exception as e:
        return _json_response(handler, 400, {"ok": False, "error": f"bad json: {e}"})

    # --- Enum-validated optionals (reject bad values instead of silently null).
    # Validated up front so storage_mode is known when we decide whether
    # local_asset_path is required.
    def validated(key, enum, default=None):
        v = body.get(key, default)
        if v is None:
            return None
        if v not in enum:
            raise ValueError(f"{key}={v!r} not in {sorted(enum)}")
        return v

    try:
        ingest_source        = validated("ingest_source",      INGEST_SOURCE,  "url-entry")
        source_platform      = validated("source_platform",    SOURCE_PLATFORM)
        link_status          = validated("link_status",        LINK_STATUS,    "local-only")
        post_date_confidence = validated("post_date_confidence", POST_DATE_CONF, "unknown")
        storage_mode         = validated("storage_mode",       STORAGE_MODE,   "vaulted")
        status               = validated("status",             STATUS_ENUM,    "vault")
    except ValueError as e:
        return _json_response(handler, 400, {"ok": False, "error": str(e)})

    # --- local_asset_path: required for vaulted/referenced; optional for
    # url_only (the catalog record is the preservation artifact, no local
    # bytes). When provided the path is validated regardless of
    # storage_mode - operators may legitimately reference an existing
    # snapshot from a url_only artifact, and the safety check stands.
    local_path_raw = body.get("local_asset_path")
    local_path = None
    if local_path_raw:
        local_path = Path(local_path_raw)
        if not local_path.exists() or not local_path.is_file():
            return _json_response(handler, 400,
                {"ok": False, "error": f"file not found: {local_path_raw}"})
        if not _path_is_inside(local_path, ASSET_ROOTS):
            return _json_response(handler, 403,
                {"ok": False, "error": "local_asset_path outside allowed roots"})
    elif storage_mode != "url_only":
        return _json_response(handler, 400,
            {"ok": False, "error":
             f"local_asset_path is required when storage_mode={storage_mode!r}"})

    # --- media_type: inferred from the path when caller didn't specify;
    # required in the body when there is no local file to infer from.
    try:
        media_type = body.get("media_type")
        if not media_type:
            if local_path is not None:
                media_type = _infer_media_type(local_path)
            else:
                raise ValueError(
                    "media_type is required when local_asset_path is omitted")
        if media_type not in MEDIA_TYPE:
            raise ValueError(f"media_type={media_type!r} not in {sorted(MEDIA_TYPE)}")
    except ValueError as e:
        return _json_response(handler, 400, {"ok": False, "error": str(e)})

    tags = _coerce_tags(body.get("tags"))

    # --- DB insert --------------------------------------------------------
    from datetime import date, datetime
    today = date.today().isoformat()
    now_iso = datetime.now().isoformat(timespec="seconds")

    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            artifact_id = body.get("id") or _next_artifact_id(conn)

            # v0.6 Item 8d #11 fix: refuse to clobber an existing artifact.
            # Old code used INSERT OR REPLACE here, which silently destroyed
            # every column not present in the (sparse) extension payload -
            # tags, descriptions, media_type, thumbnail_path, post_date, etc.
            # all got nulled out the moment a caller passed an id that already
            # existed. Register is for *new* rows; mutations belong on
            # /api/artifact-update.
            existing_artifact = conn.execute(
                "SELECT 1 FROM artifacts WHERE id=?", [artifact_id]
            ).fetchone()
            if existing_artifact:
                return _json_response(handler, 409, {
                    "ok": False,
                    "error": (f"artifact {artifact_id} already exists; "
                              "use /api/artifact-update to modify it"),
                    "id": artifact_id,
                })

            # Auto-create any novel slug as proposed so the operator notices it
            # in Vocab Admin. Mirrors imgserver.py's handle_artifact_save.
            existing = {r[0] for r in conn.execute("SELECT slug FROM tags").fetchall()}
            for s in tags:
                if s not in existing:
                    conn.execute(
                        "INSERT INTO tags(slug, display_name, description, "
                        "category, is_proposed, is_exclusive, usage_count) "
                        "VALUES(?,?,?,?,?,?,0)",
                        [s, s.replace("_", " ").title(), None, None, 1, 0],
                    )

            conn.execute(
                """INSERT INTO artifacts(
                    id, source_url, source_platform, ingest_source, ingest_date,
                    storage_mode, local_asset_path, thumbnail_path, link_status,
                    parent_artifact_id, media_type,
                    post_date, post_date_confidence, capture_date,
                    status,
                    description_short, description_long, extracted_text,
                    tags,
                    confidence_flags, notes,
                    created_at, updated_at
                ) VALUES(?,?,?,?,?, ?,?,?,?, ?,?, ?,?,?, ?, ?,?,?, ?, ?,?, ?,?)""",
                [
                    artifact_id,
                    body.get("source_url"),
                    source_platform,
                    ingest_source,
                    today,
                    storage_mode,
                    str(local_path.resolve()) if local_path is not None else None,
                    body.get("thumbnail_path"),
                    link_status,
                    body.get("parent_artifact_id"),
                    media_type,
                    body.get("post_date"),
                    post_date_confidence,
                    body.get("capture_date") or today,
                    status,
                    body.get("description_short"),
                    body.get("description_long"),
                    body.get("extracted_text"),
                    json.dumps(tags),
                    body.get("confidence_flags"),
                    body.get("notes"),
                    now_iso,
                    now_iso,
                ],
            )
            # Bump usage_count for each tag we attached.
            for s in tags:
                conn.execute(
                    "UPDATE tags SET usage_count = usage_count + 1 WHERE slug=?",
                    [s],
                )
            conn.commit()
            return _json_response(handler, 200, {"ok": True, "id": artifact_id, "tags": tags})
        finally:
            conn.close()
    except Exception as e:
        return _json_response(handler, 500, {"ok": False, "error": str(e)})


# ------------------------------------------------------------------
# GET /asset-raw?path=<absolute>
# ------------------------------------------------------------------

def handle_asset_raw(handler) -> None:
    """Serve any file on disk under the allowed roots, with a best-effort
    Content-Type. Range requests are supported so <audio> scrubbing works."""
    query = parse_qs(urlparse(handler.path).query)
    raw = query.get("path", [""])[0]
    if not raw:
        handler.send_error(400, "path required")
        return

    p = Path(raw)
    if not p.exists() or not p.is_file():
        handler.send_error(404, "not found")
        return
    if not _path_is_inside(p, ASSET_ROOTS):
        handler.send_error(403, "path outside allowed roots")
        return

    ctype, _ = mimetypes.guess_type(p.name)
    if not ctype:
        ctype = "application/octet-stream"

    size = p.stat().st_size
    range_header = handler.headers.get("Range", "")
    start, end = 0, size - 1
    status = 200

    if range_header.startswith("bytes="):
        # Minimal single-range support: "bytes=START-" or "bytes=START-END"
        try:
            spec = range_header[len("bytes="):]
            s, _, e = spec.partition("-")
            if s:
                start = int(s)
            if e:
                end = int(e)
            if start > end or end >= size:
                handler.send_error(416, "range not satisfiable")
                return
            status = 206
        except ValueError:
            handler.send_error(400, "bad Range header")
            return

    length = end - start + 1
    handler.send_response(status)
    handler.send_header("Content-Type", ctype)
    handler.send_header("Content-Length", str(length))
    handler.send_header("Accept-Ranges", "bytes")
    if status == 206:
        handler.send_header("Content-Range", f"bytes {start}-{end}/{size}")
    handler.end_headers()

    with open(p, "rb") as f:
        if start:
            f.seek(start)
        remaining = length
        chunk = 64 * 1024
        while remaining > 0:
            buf = f.read(min(chunk, remaining))
            if not buf:
                break
            handler.wfile.write(buf)
            remaining -= len(buf)


# ------------------------------------------------------------------
# Deep Dive vocabulary endpoint.
# Originally added in Phase 4 as the picker source for an MV-side Deep
# Dive curation tab. The curation tab and its save handler were removed
# in Phase v5-5 (deep tags now flow museum -> MV via the museum-side
# export, not MV -> museum); this endpoint is retained per Phase v5-5
# Q-1 so a future session can wire it up as the suggestion source for
# MV's standard pill wall. The endpoint name and URL preserve
# git-history continuity and may be renamed when the new role lands.
# ------------------------------------------------------------------

# Hardcoded absolute path to the museum-side CSV. Per Q-C-locked-as-(a):
# MV is local-only, the museum repo lives at a known path on the operator's
# machine, and threading this through configuration adds no value. If the
# operator ever moves the museum repo this handler emits a clear error
# pointing at the missing path.
VOCABULARY_CSV_PATH = Path(
    r"C:\AI\Projects\weird-baby-museum\docs\deep-dive-vocabulary.csv"
)


def _read_deep_dive_vocabulary_csv() -> tuple[list[str], list[dict]]:
    """Parse the museum-side vocabulary CSV.

    Returns (groups_in_first_seen_order, rows). Each row is
    {tag, group, notes}. Empty/whitespace rows are skipped. Rows missing
    either `tag` or `group` are skipped (CSV is operator-edited and may
    contain blanks).

    Raises FileNotFoundError if the CSV isn't at the expected path.
    """
    if not VOCABULARY_CSV_PATH.exists():
        raise FileNotFoundError(str(VOCABULARY_CSV_PATH))
    groups_seen: list[str] = []
    rows: list[dict] = []
    with VOCABULARY_CSV_PATH.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            tag = (raw.get("tag") or "").strip()
            group = (raw.get("group") or "").strip()
            note = (raw.get("notes") or "").strip()
            if not tag or not group:
                continue
            if group not in groups_seen:
                groups_seen.append(group)
            rows.append({"tag": tag, "group": group, "notes": note})
    return groups_seen, rows


def handle_deep_dive_vocabulary(handler) -> None:
    """GET /api/deep-dive-vocabulary

    Reads the Deep Dive vocabulary CSV from the museum repo (hardcoded
    absolute path) and returns the parsed structure to the MV frontend.

    Response (200):
        {
          "ok": true,
          "source": "<absolute path to the CSV>",
          "groups": ["mood", "theme", "motif", "texture"],
          "tags":   [{"tag": "snarky", "group": "mood", "notes": ""}, ...]
        }

    Response (404 - CSV missing):
        {
          "ok": false,
          "error": "Could not read vocabulary CSV at <path>. Is the museum "
                   "repo at the expected location?"
        }
    """
    try:
        try:
            groups, rows = _read_deep_dive_vocabulary_csv()
        except FileNotFoundError:
            return _json_response(handler, 404, {
                "ok": False,
                "error": (
                    f"Could not read vocabulary CSV at "
                    f"{VOCABULARY_CSV_PATH}. Is the museum repo at the "
                    f"expected location?"
                ),
            })
        return _json_response(handler, 200, {
            "ok": True,
            "source": str(VOCABULARY_CSV_PATH),
            "groups": groups,
            "tags": rows,
        })
    except Exception as e:
        return _json_response(handler, 500,
            {"ok": False, "error": f"vocab read failed: {e}"})
