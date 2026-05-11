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
       Reads the Deep Dive vocabulary CSV from the museum repo at the
       hardcoded absolute path and returns the parsed structure (groups
       + per-tag rows). Added in Phase 4 of the Deep Dive feature; see
       `C:\\AI\\Projects\\weird-baby-museum\\docs\\deep-dive-review\\SPEC_DRAFT_v3.md`
       sec.5 Phase 4 for context.

  4. handle_artifact_deep_dive_save(handler) - POST /api/artifact-deep-dive-save
       Persists a Deep Dive curation onto an artifact: writes
       `deep:<group>:<tag>` entries into `artifacts.tags` and a
       `card_id:<value>` entry into `artifacts.notes`. The write format
       matches what `weird-baby-museum/tools/export-deep-tags.mjs`
       reads. Added in Phase 4.

INTEGRATION (in imgserver.py):

  Add at top, with other imports:
      from imgserver_extensions import (
          handle_artifact_register,
          handle_asset_raw,
          handle_deep_dive_vocabulary,
          handle_artifact_deep_dive_save,
      )

  Add in do_POST before the 404 fallthrough:
      if p.path == "/api/artifact-register":
          return handle_artifact_register(self)
      if p.path == "/api/artifact-deep-dive-save":
          return handle_artifact_deep_dive_save(self)

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
from datetime import datetime
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
# Deep Dive - Phase 4 of the museum's Deep Dive feature.
# See: C:\AI\Projects\weird-baby-museum\docs\deep-dive-review\SPEC_DRAFT_v3.md
#       sec.3.2 (operator curation data flow)
#       sec.5 Phase 4 (this implementation)
#       Q-1 (notes storage convention)
# The Phase 3 export script that consumes our writes is at:
#       C:\AI\Projects\weird-baby-museum\tools\export-deep-tags.mjs
# Its extractCardId() parses `notes` as a JSON array and pulls every
# element matching `card_id:<value>`; its tag parse uses the regex
# ^deep:([^:]+):(.+)$ over `tags[]`. We write exactly that shape.
# ------------------------------------------------------------------

# Hardcoded absolute path to the museum-side CSV. Per Q-C-locked-as-(a):
# MV is local-only, the museum repo lives at a known path on the operator's
# machine, and threading this through configuration adds no value. If the
# operator ever moves the museum repo this handler emits a clear error
# pointing at the missing path.
VOCABULARY_CSV_PATH = Path(
    r"C:\AI\Projects\weird-baby-museum\docs\deep-dive-vocabulary.csv"
)

# Pattern recognized by `weird-baby-museum/tools/export-deep-tags.mjs`.
# Matches the export script's regex literally so write-then-export round-trips.
_DEEP_TAG_RE = re.compile(r"^deep:([^:]+):(.+)$")

# Notes-array entry prefix used to attach an artifact to a museum card.
# Matches the export script's `extractCardId` parse (`s.startsWith("card_id:")`).
_CARD_ID_PREFIX = "card_id:"


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


def _parse_notes_array(raw):
    """Normalize the `artifacts.notes` text into a JSON-array-shaped list of
    strings. The Phase 3 export script (`tools/export-deep-tags.mjs`,
    function `extractCardId`) parses notes with `JSON.parse(notesText)` and
    expects an array. Any pre-existing free-form notes content is wrapped as
    a single-element array so it isn't lost on first Deep Dive save.

    Returns (list_of_strings, was_already_array_form).
    """
    if raw is None:
        return [], True
    if isinstance(raw, list):
        return [s for s in raw if isinstance(s, str)], True
    s = str(raw).strip()
    if not s:
        return [], True
    if s.startswith("["):
        try:
            parsed = json.loads(s)
        except Exception:
            parsed = None
        if isinstance(parsed, list):
            # Coerce non-string elements to strings so downstream
            # JSON.stringify in the export script sees the expected shape.
            return [x if isinstance(x, str) else json.dumps(x) for x in parsed], True
    # Plain-text notes (HR-* legacy rows store artist bios here). Wrap so
    # no operator-entered content is lost when Deep Dive first touches
    # the artifact. The export script will simply ignore the wrapped
    # element since it doesn't start with `card_id:`.
    return [str(raw)], False


def _validate_card_id(card_id) -> str:
    """Sanitize the operator-supplied card_id.

    Per SPEC_DRAFT_v3.md sec.2 (card-identity foundation), every museum card
    has an explicit id like `art-014`, `arc-007`, `exit-002`. We don't try
    to enforce the prefix here - the museum may grow new card kinds - but
    we strip whitespace, reject newlines/colons that would break the
    `card_id:<value>` parse, and enforce a reasonable length cap.

    Empty string is allowed and means "no card_id" (clear any existing).
    """
    if card_id is None:
        return ""
    s = str(card_id).strip()
    if not s:
        return ""
    # Newlines and colons would break the `card_id:<value>` token contract.
    if "\n" in s or "\r" in s or ":" in s:
        raise ValueError(
            f"card_id must not contain newline or colon characters; got {s!r}"
        )
    if len(s) > 128:
        raise ValueError(f"card_id too long ({len(s)} chars; max 128)")
    return s


def _normalize_deep_pair(pair):
    """Accept [group, tag] or {group, tag}; return (group, tag) or None.

    The slug-grammar rules in this codebase (`_slugify` above, and the
    JS slugifier in mediavault.html) are stricter than what the museum
    CSV permits - the CSV uses hyphens like `pink-hats` and lowercase
    group names like `mood`. We allow [a-z0-9_-] for both segments
    after lowercasing and trim, so the format matches the export script's
    `^deep:([^:]+):(.+)$` parse without forcing the museum CSV to use
    underscores.
    """
    if isinstance(pair, dict):
        group = pair.get("group")
        tag = pair.get("tag")
    elif isinstance(pair, (list, tuple)) and len(pair) == 2:
        group, tag = pair
    else:
        return None
    if not isinstance(group, str) or not isinstance(tag, str):
        return None
    g = group.strip().lower()
    t = tag.strip().lower()
    # Disallow colon (would break the deep:<g>:<t> token format) and any
    # whitespace / control characters. Hyphens permitted to match the
    # museum CSV's `pink-hats` style. The export script's regex
    # `^deep:([^:]+):(.+)$` is permissive on the tag segment, so we are too.
    if not g or not t or ":" in g or ":" in t:
        return None
    if re.search(r"\s", g) or re.search(r"\s", t):
        return None
    return g, t


def handle_artifact_deep_dive_save(handler) -> None:
    """POST /api/artifact-deep-dive-save

    Body JSON:
        id        (str)         REQUIRED - artifact ID to update.
        selected  (list)        list of [group, tag] pairs (or {group, tag}
                                 objects). This is the full set of Deep Dive
                                 tags the artifact should carry after this
                                 save. ANY existing `deep:*` tags not in this
                                 list are removed. Defaults to [].
        card_id   (str)         REQUIRED key (value may be empty to clear).
                                 The museum card id this curation attaches to
                                 (e.g., "art-014"). Stored in `notes` as a
                                 string element matching `card_id:<value>`.
        freeform  (list)        OPTIONAL list of [group, tag] pairs the
                                 operator typed in rather than picking from
                                 the vocabulary CSV. Each gets a vocabulary
                                 row in MV's `tags` table with
                                 is_proposed=1 (per SPEC_DRAFT_v3.md D3).
                                 Must be a subset of `selected`.

    Behavior:
        - Reads the existing artifact row (404 if missing).
        - Recomputes `artifacts.tags`:
              new = [t for t in old if not t.startswith("deep:")]
                    + [f"deep:{g}:{t}" for (g, t) in selected]
          deduped, sorted alphabetically for stable storage. Format
          matches the export script's `^deep:([^:]+):(.+)$` parse.
        - Recomputes `artifacts.notes` as a JSON-stringified array:
              base = parse_notes_array(old_notes)
              base = [s for s in base if not s.startswith("card_id:")]
              if card_id: base += [f"card_id:{card_id}"]
              new_notes = json.dumps(base)
          Preserves any non-card_id legacy notes content (wrapped as a
          single element if old notes were free-form rather than already
          a JSON array).
        - For each freeform [group, tag], inserts a vocabulary row with
          slug=`deep:<group>:<tag>`, is_proposed=1, display_name set to a
          human label. Idempotent (existing rows are left alone).
        - Bumps usage_count for newly-added deep:* tags, decrements for
          removed ones.
        - Sets updated_at = now.

    Response (200):
        {
          "ok": true,
          "id": "MV-...",
          "tags": [...final merged tag array...],
          "notes": [...final merged notes array...],
          "deep_added": ["deep:mood:snarky", ...],
          "deep_removed": [...],
          "card_id": "art-014",
          "freeform_inserted": ["deep:mood:made_up", ...]
        }
    """
    try:
        length = int(handler.headers.get("Content-Length", 0))
        body = json.loads(handler.rfile.read(length)) if length else {}
    except Exception as e:
        return _json_response(handler, 400, {"ok": False, "error": f"bad json: {e}"})

    artifact_id = body.get("id")
    if not artifact_id:
        return _json_response(handler, 400, {"ok": False, "error": "id required"})

    selected_raw = body.get("selected") or []
    freeform_raw = body.get("freeform") or []
    if not isinstance(selected_raw, list):
        return _json_response(handler, 400,
            {"ok": False, "error": "selected must be a list"})
    if not isinstance(freeform_raw, list):
        return _json_response(handler, 400,
            {"ok": False, "error": "freeform must be a list"})

    # Normalize selections - silently drop malformed entries since the UI
    # is the only caller and it's already on its best behavior. Dedup
    # while preserving first-seen order.
    selected_pairs = []
    seen_sel = set()
    for raw in selected_raw:
        pair = _normalize_deep_pair(raw)
        if pair is None or pair in seen_sel:
            continue
        seen_sel.add(pair)
        selected_pairs.append(pair)

    freeform_pairs = []
    seen_ff = set()
    for raw in freeform_raw:
        pair = _normalize_deep_pair(raw)
        if pair is None or pair in seen_ff:
            continue
        # freeform must be a subset of selected - otherwise nothing
        # attaches them to the artifact and the vocabulary insert is junk.
        if pair not in seen_sel:
            continue
        seen_ff.add(pair)
        freeform_pairs.append(pair)

    if "card_id" not in body:
        return _json_response(handler, 400,
            {"ok": False, "error": "card_id key required (empty string allowed to clear)"})
    try:
        card_id = _validate_card_id(body.get("card_id"))
    except ValueError as e:
        return _json_response(handler, 400, {"ok": False, "error": str(e)})

    now_iso = datetime.now().isoformat(timespec="seconds")

    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT tags, notes FROM artifacts WHERE id=?",
                [artifact_id],
            ).fetchone()
            if row is None:
                return _json_response(handler, 404,
                    {"ok": False, "error": f"artifact not found: {artifact_id}"})

            # --- Tags merge ---------------------------------------------
            try:
                old_tags = json.loads(row["tags"] or "[]")
                if not isinstance(old_tags, list):
                    old_tags = []
            except Exception:
                old_tags = []
            old_tags = [t for t in old_tags if isinstance(t, str)]

            non_deep = [t for t in old_tags if not t.startswith("deep:")]
            new_deep = [f"deep:{g}:{t}" for (g, t) in selected_pairs]
            merged_set = set(non_deep) | set(new_deep)
            merged_tags = sorted(merged_set)

            old_deep_set = {t for t in old_tags if _DEEP_TAG_RE.match(t)}
            new_deep_set = set(new_deep)
            deep_added = sorted(new_deep_set - old_deep_set)
            deep_removed = sorted(old_deep_set - new_deep_set)

            # --- Notes merge --------------------------------------------
            notes_arr, _was_array = _parse_notes_array(row["notes"])
            notes_arr = [s for s in notes_arr if not s.startswith(_CARD_ID_PREFIX)]
            if card_id:
                notes_arr.append(f"{_CARD_ID_PREFIX}{card_id}")
            # Stringify as a JSON array exactly as the Phase 3 export
            # script expects (`JSON.parse(notesText)` over a JSON array
            # of strings).
            new_notes_text = json.dumps(notes_arr)

            # --- Freeform vocabulary inserts (is_proposed=1 per D3) -----
            # The novel deep:<group>:<tag> slugs become MV vocabulary rows
            # with is_proposed=1 so they surface in the Vocab Admin tab.
            existing_slugs = {
                r[0] for r in conn.execute("SELECT slug FROM tags").fetchall()
            }
            freeform_inserted = []
            for (g, t) in freeform_pairs:
                slug = f"deep:{g}:{t}"
                if slug in existing_slugs:
                    continue
                # Display name uses the raw tag (preserving hyphens etc.)
                # rather than running it through MV's strict slugifier.
                display = f"deep:{g}:{t}".replace("_", " ").replace("-", " ")
                conn.execute(
                    "INSERT INTO tags(slug, display_name, description, "
                    "category, is_proposed, is_exclusive, usage_count) "
                    "VALUES(?,?,?,?,?,?,0)",
                    [slug, display, None, None, 1, 0],
                )
                freeform_inserted.append(slug)
                existing_slugs.add(slug)

            # Auto-create vocabulary rows for any selected deep:* tag that
            # isn't in the vocabulary yet, with is_proposed=0 - those are
            # picked from the CSV and shouldn't be flagged as proposed.
            # The CSV is the source of truth for "known" Deep Dive tags;
            # MV's vocabulary just gets a corresponding row for
            # usage_count tracking.
            for (g, t) in selected_pairs:
                slug = f"deep:{g}:{t}"
                if slug in existing_slugs:
                    continue
                # If it's not in freeform, it came from the CSV - insert
                # as confirmed (is_proposed=0). Use the same display rule.
                display = f"deep:{g}:{t}".replace("_", " ").replace("-", " ")
                conn.execute(
                    "INSERT INTO tags(slug, display_name, description, "
                    "category, is_proposed, is_exclusive, usage_count) "
                    "VALUES(?,?,?,?,?,?,0)",
                    [slug, display, None, None, 0, 0],
                )
                existing_slugs.add(slug)

            # --- Bump / decrement usage_count for changed deep:* tags ---
            for slug in deep_added:
                conn.execute(
                    "UPDATE tags SET usage_count = usage_count + 1 WHERE slug=?",
                    [slug],
                )
            for slug in deep_removed:
                conn.execute(
                    "UPDATE tags SET usage_count = MAX(0, usage_count - 1) "
                    "WHERE slug=?",
                    [slug],
                )

            # --- Write the row ------------------------------------------
            conn.execute(
                "UPDATE artifacts SET tags=?, notes=?, updated_at=? WHERE id=?",
                [json.dumps(merged_tags), new_notes_text, now_iso, artifact_id],
            )
            conn.commit()

            return _json_response(handler, 200, {
                "ok": True,
                "id": artifact_id,
                "tags": merged_tags,
                "notes": notes_arr,
                "deep_added": deep_added,
                "deep_removed": deep_removed,
                "card_id": card_id,
                "freeform_inserted": freeform_inserted,
            })
        finally:
            conn.close()
    except Exception as e:
        return _json_response(handler, 500, {"ok": False, "error": str(e)})
