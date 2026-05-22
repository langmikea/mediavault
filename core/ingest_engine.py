"""
ingest_engine.py — MediaVault Ingest Engine (v0.4)
C:/AI/Platform/MediaVault/core/ingest_engine.py

Usage:
  python ingest_engine.py scan      # scan drop zone and screenshots, queue new items
  python ingest_engine.py process   # post-approval: thumbnails, EXIF, file moves
  python ingest_engine.py status    # print queue summary

v0.4 changes from v0.2:
  - Domain concept removed. No DOMAIN_PREFIXES, no --domain flag, no domain column.
  - ID format is MV-YYYYMMDD-NNN (no prefix). id_sequence is (date_str, last_seq).
  - Tags are a single JSON array in artifacts.tags. No more tags_* columns.
  - Ingest queue no longer has a domain column.
  - Default storage_mode for vaulted items is 'vaulted' (the engine copies into the vault).

Dependencies:
  pip install Pillow pillow-heif            # image handling + HEIC support
  winget install exiftool                   # EXIF/XMP writing (PATH must include it)
  send2trash: pip install send2trash        # Recycle Bin moves

Self-bootstrapping: installs missing Python deps on first run.
"""

import os
import sys
import sqlite3
import shutil
import subprocess
import json
from datetime import datetime, date
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
# PATHS
# ─────────────────────────────────────────────────────────────────────────────
BASE          = Path(r"C:\AI\Platform\MediaVault")
DB_PATH       = BASE / "core" / "mediavault.sqlite"
VOCAB_PATH    = BASE / "core" / "tag_vocabulary.json"
DROP_DIR      = BASE / "intake" / "drop"
IMAGES_DIR    = BASE / "intake" / "images"
PROCESSED_DIR = BASE / "intake" / "processed"
THUMBS_ROOT   = BASE / "catalogs"
VAULTED_ROOT  = BASE / "catalogs" / "vaulted"
DOWNLOADS_DIR = Path(r"C:\Users\macun\Downloads")

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".heif",
                        ".mp4", ".mov", ".avi", ".mkv", ".bmp", ".tiff", ".tif",
                        # M4 (2026-05-22, audit brief §5.1 step 3): widen Path A
                        # to accept page-saves, documents, and text artifacts.
                        # _infer_media_type() (imgserver_extensions.py:215) maps
                        # these to link/text. No thumbnail generators exist for
                        # these extensions; generate_thumbnail() returns None and
                        # process() treats no-thumb as a valid state (audit §3.4).
                        # MP3/audio stays out of M4 scope - that is M2.
                        ".html", ".htm", ".pdf", ".txt", ".md", ".json"}

# ─────────────────────────────────────────────────────────────────────────────
# BOOTSTRAP DEPENDENCIES
# ─────────────────────────────────────────────────────────────────────────────
def bootstrap():
    required = {"Pillow": "PIL", "pillow_heif": "pillow_heif", "send2trash": "send2trash"}
    for pkg, mod in required.items():
        try:
            __import__(mod)
        except ImportError:
            print(f"Installing {pkg}...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", pkg, "--quiet"])

bootstrap()

from PIL import Image
try:
    import pillow_heif
    pillow_heif.register_heif_opener()
    HEIC_SUPPORT = True
except ImportError:
    HEIC_SUPPORT = False
    print("Warning: pillow-heif not available. HEIC files will be skipped for thumbnail generation.")

try:
    from send2trash import send2trash
    RECYCLE_AVAILABLE = True
except ImportError:
    RECYCLE_AVAILABLE = False
    print("Warning: send2trash not available. Files will be moved to intake/processed instead of Recycle Bin.")

# ─────────────────────────────────────────────────────────────────────────────
# DB
# ─────────────────────────────────────────────────────────────────────────────
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def next_id(conn):
    """Generate MV-YYYYMMDD-NNN using the v0.4 id_sequence table."""
    date_str = date.today().strftime("%Y%m%d")
    conn.execute("""
        INSERT INTO id_sequence (date_str, last_seq)
        VALUES (?, 1)
        ON CONFLICT(date_str) DO UPDATE SET last_seq = last_seq + 1
    """, (date_str,))
    conn.commit()
    row = conn.execute(
        "SELECT last_seq FROM id_sequence WHERE date_str=?",
        (date_str,)
    ).fetchone()
    seq = row[0]
    return f"MV-{date_str}-{seq:03d}"


def upsert_tag(conn, slug, display_name=None, category=None, is_proposed=0,
               is_exclusive=0):
    """Insert a tag-cache row if missing. Returns the slug on success.

    The `tags` table is the per-value usage-count cache (post-§5.2
    demotion in Phase 2.2 of the source-of-truth refactor, schema
    finalized by Phase 2.5 on 2026-05-20). Live columns: `slug` (PRIMARY
    KEY), `display_name`, `usage_count`, `created_at`. This function
    writes `slug`, `usage_count` (defaulted to 0), `created_at` (now);
    `display_name` is left NULL on the cache row — the human label is
    supplied per-namespace by the §5.4 `vocabulary` registry, not
    per-tag. The `ON CONFLICT(slug)` clause leans on the slug PRIMARY
    KEY added in Phase 2.5.

    The `display_name` / `category` / `is_proposed` / `is_exclusive`
    parameters are retained in the signature for backward compatibility
    with v0.5 callers. The latter three name columns that **no longer
    exist** in the live schema — Phase 2.5 dropped them — so they are
    accepted-and-discarded here. See CHANGELOG v0.5.3 / SPEC.md §6.5.
    """
    slug = slugify(slug)
    if not slug:
        return None
    # Accept-and-discard the v0.5 metadata parameters (see docstring).
    # `category`, `is_proposed`, `is_exclusive` reference columns that
    # were dropped from the `tags` table by Phase 2.5.
    del display_name, category, is_proposed, is_exclusive
    conn.execute(
        "INSERT INTO tags (slug, usage_count, created_at) "
        "VALUES (?, 0, datetime('now')) "
        "ON CONFLICT(slug) DO NOTHING",
        (slug,),
    )
    return slug


def slugify(value):
    """v0.5: preserve an optional single `namespace:` prefix (e.g. author:)."""
    import re
    s = str(value or "").strip().lower()
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
    return prefix + s


# ─────────────────────────────────────────────────────────────────────────────
# SCAN — queue new items
# ─────────────────────────────────────────────────────────────────────────────
def import_extension_captures():
    """Move mv-capture-*.json files (and paired .png screenshots) from Downloads
    into the drop zone for processing."""
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    moved = 0

    for json_file in DOWNLOADS_DIR.glob("mv-capture-*.json"):
        dest_json = DROP_DIR / json_file.name
        if dest_json.exists():
            continue

        png_file = DOWNLOADS_DIR / (json_file.stem + ".png")
        screenshot_path = None

        if png_file.exists():
            dest_png = IMAGES_DIR / png_file.name
            if dest_png.exists():
                dest_png = IMAGES_DIR / f"{png_file.stem}_{datetime.now().strftime('%f')}.png"
            try:
                shutil.move(str(png_file), str(dest_png))
                screenshot_path = str(dest_png)
                print(f"  Screenshot imported: {dest_png.name}")
            except Exception as e:
                print(f"  Screenshot move failed ({png_file.name}): {e}")
        else:
            print(f"  No screenshot found for: {json_file.name}")

        if screenshot_path:
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
                data["_screenshot_path"] = screenshot_path
                json_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
            except Exception as e:
                print(f"  Failed to patch JSON with screenshot path ({json_file.name}): {e}")
                screenshot_path = None

        shutil.move(str(json_file), str(dest_json))
        moved += 1
        print(f"  Imported capture: {json_file.name}" + (" + screenshot" if screenshot_path else " (no screenshot)"))

    return moved


def queue_capture_json(conn, path: Path):
    """Queue a capture JSON file from the extension. v0.4: no domain column."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        source_url = data.get("post_url") or data.get("url")
        if not source_url:
            print(f"  Skip (no URL): {path.name}")
            return False

        screenshot_path = data.get("_screenshot_path")
        if screenshot_path and not Path(screenshot_path).exists():
            print(f"  Warning: screenshot_path not found on disk: {screenshot_path}")
            screenshot_path = None

        # v0.6 Item 8d follow-up C2: previously emitted an author:<slug> pill
        # for every captured post. Mike rejected this — when the post author
        # is the same band that already has a band pill (e.g. "Hunter Root"
        # author of a Hunter Root band post), the author:hunter_root pill is
        # pure noise. Drop the auto-emit; if author tracking ever becomes
        # useful, it can be re-introduced as an explicit category, not a
        # namespaced freeform pill.
        pill_states = {}

        # M1 (2026-05-22, audit brief §5.1): seed media_type from the
        # screenshot path's extension. url_only captures (no screenshot)
        # default to 'link' since the artifact is fundamentally a URL
        # reference. Operator can override in the inbox dropdown.
        from imgserver_extensions import _infer_media_type
        if screenshot_path:
            seeded_media_type = _infer_media_type(Path(screenshot_path))
        else:
            seeded_media_type = "link"

        enrichment = {
            "media_type":        seeded_media_type,
            "description_short": (data.get("post_text") or data.get("title") or "")[:120],
            "description_long":  (data.get("post_text") or "")[:1000],
            "extracted_text":    data.get("post_text") or "",
            "source_url":        source_url,
            "source_platform":   data.get("platform"),
            "post_date":         data.get("post_date"),
            "link_status":       "live",
            "storage_mode":      "vaulted" if screenshot_path else "url_only",
            "pill_states":       pill_states,
            "_comments":         data.get("comments", []),
            "_screenshot_path":  screenshot_path,
        }

        ai = ai_preprocess(data)
        if ai.get("post_date") and not enrichment["post_date"]:
            enrichment["post_date"] = ai["post_date"]
            enrichment["post_date_confidence"] = ai.get("post_date_confidence", "estimated")

        conn.execute("""
            INSERT INTO ingest_queue
                (ingest_source, raw_path, source_url, queued_at, status, enrichment_json)
            VALUES (?, ?, ?, ?, ?, ?)
        """, ("extension-capture", screenshot_path, source_url,
              datetime.now().isoformat(), "enriched", json.dumps(enrichment)))
        conn.commit()

        if screenshot_path:
            print(f"  Queued with screenshot: {Path(screenshot_path).name}")
        else:
            print(f"  Queued (no screenshot — AI vision will be skipped at enrich time)")

        path.unlink()
        return True
    except Exception as e:
        print(f"  Error reading capture {path.name}: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# AI PRE-PROCESSING (text-only)
# ─────────────────────────────────────────────────────────────────────────────
def ai_preprocess(data: dict) -> dict:
    import urllib.request, urllib.error
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("  [ai_preprocess] No ANTHROPIC_API_KEY set - skipping.")
        return {}
    post_text  = (data.get("post_text") or "")[:1500]
    title      = data.get("title") or ""
    src_url    = data.get("url") or data.get("post_url") or ""
    platform   = data.get("platform") or "facebook"
    comments   = data.get("comments") or []
    from datetime import datetime as _dt
    capture_ts = data.get("captured_at") or _dt.now().strftime("%Y-%m-%d %H:%M")
    today_str  = _dt.now().strftime("%Y-%m-%d")
    lines = [
        "You are helping catalog a social-media post for a creative archive.",
        "Platform: " + platform,
        "Page URL: " + src_url,
        "Page title: " + title,
        "Post text: " + (post_text or "(none)"),
        "Today's date: " + today_str,
        "Capture timestamp: " + capture_ts,
        "Post comments (first 5): " + (" | ".join((c or "")[:120] for c in comments[:5]) or "(none)"),
        "",
        "Task:",
        "Extract or calculate the post date. Use relative times (12w, 3h, 2d) calculated from today.",
        "Return null only if no time signal exists.",
        "",
        "Return ONLY JSON, no prose, no markdown:",
        '{"post_date":"YYYY-MM-DD or null","post_date_confidence":"extracted|estimated|unknown"}',
    ]
    payload = json.dumps({
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 128,
        "messages": [{"role": "user", "content": "\n".join(lines)}]
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", data=payload,
        headers={"Content-Type": "application/json",
                 "anthropic-version": "2023-06-01",
                 "x-api-key": api_key},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            result = json.loads(resp.read())
        text = result["content"][0]["text"].strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"): text = text[4:]
        parsed = json.loads(text.strip())
        print(f"  [ai_preprocess] date={parsed.get('post_date')} conf={parsed.get('post_date_confidence')}")
        return parsed
    except urllib.error.HTTPError as e:
        print(f"  [ai_preprocess] API error {e.code}: {e.read().decode()[:300]}")
        return {}
    except Exception as e:
        print(f"  [ai_preprocess] Error: {e}")
        return {}


def extract_exif_date(path):
    """Backward-compat wrapper. Returns (date_str, confidence)."""
    result = extract_exif(path)
    return result.get("post_date"), result.get("post_date_confidence")

def _gps_to_decimal(vals, ref):
    try:
        d, m, s = float(vals[0]), float(vals[1]), float(vals[2])
        dec = d + m / 60 + s / 3600
        if ref in ("S", "W"):
            dec = -dec
        return round(dec, 6)
    except Exception:
        return None

def extract_exif(path):
    """Extract useful EXIF fields. In v0.4 any derived tag slugs are placed under
    'tags_proposed' for the enrichment reviewer to approve, rather than written
    into a per-category column."""
    out = {}
    proposed_tags = []
    try:
        ext = Path(path).suffix.lower()
        if ext in (".heic", ".heif"):
            import pillow_heif
            pillow_heif.register_heif_opener()
        from PIL import Image as _Img
        from PIL.ExifTags import TAGS, GPSTAGS
        img = _Img.open(path)
        exif_data = img._getexif() if hasattr(img, "_getexif") else None
        if not exif_data:
            exif_data = img.getexif() if hasattr(img, "getexif") else None
        if not exif_data:
            if proposed_tags:
                out["tags_proposed"] = proposed_tags
            return out
        tag_map = {TAGS.get(k, k): v for k, v in exif_data.items()}
        # Date
        raw_date = tag_map.get("DateTimeOriginal") or tag_map.get("DateTime")
        if raw_date:
            parts = str(raw_date).strip().split(" ")[0].split(":")
            if len(parts) == 3:
                date_str = f"{parts[0]}-{parts[1]}-{parts[2]}"
                out["post_date"] = date_str
                out["post_date_confidence"] = "extracted"
                proposed_tags.append(parts[0])  # year slug
        # Device
        make  = tag_map.get("Make", "").strip() if isinstance(tag_map.get("Make"), str) else ""
        model = tag_map.get("Model", "").strip() if isinstance(tag_map.get("Model"), str) else ""
        if make or model:
            out["capture_device"] = f"{make} {model}".strip()
        # Extended metadata
        def _xp(val):
            if isinstance(val, bytes):
                try: return val.decode("utf-16-le").rstrip("\x00").strip()
                except Exception: return ""
            return str(val).strip() if val else ""
        title     = _xp(tag_map.get("XPTitle"))     or tag_map.get("ImageDescription", "")
        subject   = _xp(tag_map.get("XPSubject"))
        keywords  = _xp(tag_map.get("XPKeywords"))
        comment   = _xp(tag_map.get("XPComment"))   or _xp(tag_map.get("UserComment", b""))
        author    = _xp(tag_map.get("XPAuthor"))    or tag_map.get("Artist", "")
        copyright = tag_map.get("Copyright", "")
        if title:     out["xp_title"]     = str(title).strip()
        if subject:   out["xp_subject"]   = subject
        if keywords:
            out["xp_keywords"]  = keywords
            for kw in str(keywords).replace(",", ";").split(";"):
                s = slugify(kw)
                if s and s not in proposed_tags:
                    proposed_tags.append(s)
        if comment:   out["xp_comment"]   = comment
        if author:    out["xp_author"]    = str(author).strip()
        if copyright: out["xp_copyright"] = str(copyright).strip()
        # GPS
        gps_ifd = exif_data.get_ifd(0x8825) if hasattr(exif_data, "get_ifd") else {}
        if not gps_ifd:
            raw_gps = tag_map.get("GPSInfo")
            if isinstance(raw_gps, dict):
                gps_ifd = raw_gps
        if gps_ifd:
            gps = {GPSTAGS.get(k, k): v for k, v in gps_ifd.items()}
            lat = _gps_to_decimal(gps.get("GPSLatitude", []), gps.get("GPSLatitudeRef", ""))
            lon = _gps_to_decimal(gps.get("GPSLongitude", []), gps.get("GPSLongitudeRef", ""))
            if lat is not None and lon is not None:
                out["gps_lat"] = lat
                out["gps_lon"] = lon
                try:
                    import urllib.request as _ur, json as _j
                    geo_url = f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json"
                    req = _ur.Request(geo_url, headers={"User-Agent": "MediaVault/1.0"})
                    with _ur.urlopen(req, timeout=5) as r:
                        geo = _j.loads(r.read())
                    addr = geo.get("address", {})
                    parts = [p for p in [
                        addr.get("venue") or addr.get("amenity"),
                        addr.get("city") or addr.get("town") or addr.get("village"),
                        addr.get("state")
                    ] if p]
                    if parts:
                        out["gps_location"] = ", ".join(parts)
                except Exception:
                    pass
    except Exception:
        pass
    if proposed_tags:
        out["tags_proposed"] = proposed_tags
    return out


def scan():
    conn  = get_conn()
    added = 0

    import_extension_captures()
    for f in DROP_DIR.glob("mv-capture-*.json"):
        if queue_capture_json(conn, f):
            added += 1

    if DROP_DIR.exists():
        for f in DROP_DIR.iterdir():
            if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS:
                if not already_queued(conn, str(f)):
                    queue_item(conn, str(f), "local-drop")
                    added += 1
                    print(f"  Queued (drop): {f.name}")
                    # Extract EXIF metadata and pre-populate enrichment_json
                    exif = extract_exif(str(f))
                    if exif:
                        existing_row = conn.execute(
                            "SELECT enrichment_json FROM ingest_queue WHERE raw_path=?", (str(f),)
                        ).fetchone()
                        existing = json.loads(existing_row["enrichment_json"] or "{}") if existing_row and existing_row["enrichment_json"] else {}
                        merged = dict(existing)
                        # M5 (2026-05-22, audit brief §5.1): EXIF merge —
                        # union tags_proposed with any list pre-seeded by
                        # queue_item (e.g. hr_filename.parse_hr_filename);
                        # overwrite other keys as before. Without the union,
                        # exif's tags_proposed (or its absence) would erase
                        # the filename-grammar suggestions.
                        for k, v in exif.items():
                            if k == "tags_proposed" and isinstance(v, list):
                                existing_list = merged.get("tags_proposed", []) or []
                                merged["tags_proposed"] = list(dict.fromkeys(existing_list + v))
                            else:
                                merged[k] = v
                        # Ensure drop-zone files default to vaulted (engine will own them)
                        merged.setdefault("storage_mode", "vaulted")
                        conn.execute(
                            "UPDATE ingest_queue SET enrichment_json=? WHERE raw_path=?",
                            (json.dumps(merged), str(f))
                        )
                        conn.commit()
                        print(f"    EXIF: date={exif.get('post_date')} tags_proposed={exif.get('tags_proposed')} gps={exif.get('gps_lat')},{exif.get('gps_lon')}")

    conn.close()
    print(f"\nScan complete. {added} new item(s) added to queue.")
    return added


def already_queued(conn, raw_path):
    row = conn.execute(
        "SELECT status FROM ingest_queue WHERE raw_path = ? ORDER BY queue_id DESC LIMIT 1",
        (raw_path,)
    ).fetchone()
    if row is not None and row["status"] in ("pending", "enriched", "keep", "approved"):
        return True
    from pathlib import Path as _Path
    fname = _Path(raw_path).name
    processed = BASE / "intake" / "processed" / fname
    images    = BASE / "intake" / "images"    / fname
    if processed.exists() or images.exists():
        return True
    rows = conn.execute(
        "SELECT status FROM ingest_queue WHERE raw_path LIKE ? ORDER BY queue_id DESC LIMIT 1",
        (f"%{fname}",)
    ).fetchone()
    if rows is not None and rows["status"] in ("pending", "enriched", "keep", "approved"):
        return True
    return False


def queue_item(conn, raw_path, ingest_source):
    """v0.4: no domain column.
       M1 (2026-05-22, audit brief §5.1): seed
       enrichment_json.media_type at queue time via _infer_media_type()
       so the inbox dropdown pre-fills with a confident default the
       operator can override but rarely needs to. Eliminates the Gate
       3.1 NULL-media_type artifact pattern on the happy path."""
    from imgserver_extensions import _infer_media_type
    from hr_filename import parse_hr_filename
    media_type = _infer_media_type(Path(raw_path))
    # M5 (2026-05-22, audit brief §5.1 step 3): seed tags_proposed
    # from HR filename grammar for actor__album__kind__title files.
    # Non-HR filenames return [] from the parser, leaving enrichment
    # unchanged. Anchored to the operator's historical HR-cluster
    # tagging (MV-HR-20260416-001 .. -014) — see core/hr_filename.py.
    enrichment = {"media_type": media_type}
    hr_tags = parse_hr_filename(Path(raw_path).name)
    if hr_tags:
        enrichment["tags_proposed"] = hr_tags
    enrichment_json = json.dumps(enrichment)
    conn.execute("""
        INSERT INTO ingest_queue
            (ingest_source, raw_path, queued_at, status, enrichment_json)
        VALUES (?, ?, ?, 'pending', ?)
    """, (ingest_source, raw_path, datetime.now().isoformat(), enrichment_json))
    conn.commit()


# ─────────────────────────────────────────────────────────────────────────────
# PROCESS — post-approval: thumbnails, EXIF, file moves
# ─────────────────────────────────────────────────────────────────────────────
def process():
    conn = get_conn()

    # v0.4 schema: artifacts has a single `tags` JSON column. Pair queue rows with
    # their artifacts via local_asset_path or matching ingest date.
    # v0.5: tags_permission column dropped; pair via artifacts.tags instead.
    rows = conn.execute("""
        SELECT iq.queue_id, iq.raw_path, iq.ingest_source,
               a.id as artifact_id, a.description_short,
               a.source_url, a.tags
        FROM ingest_queue iq
        JOIN artifacts a ON a.ingest_source = iq.ingest_source
            AND (a.local_asset_path = iq.raw_path OR a.ingest_date = date('now'))
        WHERE iq.status = 'approved'
          AND (a.thumbnail_path IS NULL OR a.thumbnail_path = '')
    """).fetchall()

    if not rows:
        rows = conn.execute("""
            SELECT queue_id, raw_path, ingest_source
            FROM ingest_queue WHERE status = 'approved' AND raw_path IS NOT NULL
        """).fetchall()
        rows = [dict(r) for r in rows]
        for r in rows:
            art = conn.execute(
                "SELECT id, description_short, source_url, tags "
                "FROM artifacts WHERE local_asset_path = ?", (r["raw_path"],)
            ).fetchone()
            if art:
                r["artifact_id"]       = art["id"]
                r["description_short"] = art["description_short"]
                r["source_url"]        = art["source_url"]
                r["tags"]              = art["tags"]
            else:
                r["artifact_id"] = None

    processed = skipped = 0

    for r in rows:
        r = dict(r)
        raw_path = r.get("raw_path")
        if not raw_path or not Path(raw_path).exists():
            print(f"  Skip (file not found): {raw_path}")
            skipped += 1
            continue
        artifact_id = r.get("artifact_id")
        if not artifact_id:
            print(f"  Skip (no artifact record): {raw_path}")
            skipped += 1
            continue

        raw_path   = Path(raw_path)
        thumb_path = generate_thumbnail(raw_path, artifact_id, r.get("enrichment_json"))

        if thumb_path:
            tag_slugs = _parse_tags_json(r.get("tags"))
            write_exif(thumb_path, artifact_id,
                       r.get("description_short", ""), r.get("source_url", ""),
                       tag_slugs)
            conn.execute("UPDATE artifacts SET thumbnail_path = ? WHERE id = ?", (str(thumb_path), artifact_id))
            conn.commit()
            print(f"  Thumbnail: {thumb_path.name}")

        move_original(conn, r["queue_id"], raw_path, r.get("ingest_source", ""))
        processed += 1

    skipped_items = conn.execute(
        "SELECT queue_id, raw_path FROM ingest_queue WHERE status = 'skip' AND raw_path IS NOT NULL"
    ).fetchall()
    recycled = 0
    for row in skipped_items:
        p = Path(row["raw_path"])
        if p.exists():
            recycle_file(p)
            recycled += 1
        conn.execute(
            "UPDATE ingest_queue SET status='failed', error_message='recycled' WHERE queue_id=?",
            (row["queue_id"],)
        )
    conn.commit()
    conn.close()
    print(f"\nProcess complete. {processed} artifact(s) processed, {skipped} skipped, {recycled} recycled.")


def _parse_tags_json(s):
    if not s:
        return []
    try:
        a = json.loads(s)
        return a if isinstance(a, list) else []
    except Exception:
        return []


# ─────────────────────────────────────────────────────────────────────────────
# THUMBNAIL GENERATION
# ─────────────────────────────────────────────────────────────────────────────
def generate_thumbnail(raw_path: Path, artifact_id: str, enrichment_json: str = None) -> Path | None:
    """v0.4: thumbnails live at catalogs/_thumbs/<artifact_id>.jpg (no per-domain folder)."""
    thumb_dir  = THUMBS_ROOT / "_thumbs"
    thumb_dir.mkdir(parents=True, exist_ok=True)
    thumb_path = thumb_dir / f"{artifact_id}.jpg"

    if enrichment_json:
        try:
            import base64
            ej      = json.loads(enrichment_json)
            crops   = ej.get("_crops", [])
            primary = next((c for c in crops if c.get("primary")), crops[0] if crops else None)
            if primary and primary.get("b64"):
                thumb_path.write_bytes(base64.b64decode(primary["b64"]))
                print(f"  Thumbnail from crop: {thumb_path.name}")
                return thumb_path
        except Exception as e:
            print(f"  Crop read error, falling back to full image: {e}")

    if raw_path.suffix.lower() in {".mp4", ".mov", ".avi", ".mkv"}:
        return generate_video_thumbnail(raw_path, thumb_path)

    try:
        img = Image.open(raw_path).convert("RGB")
        img.thumbnail((400, 400), Image.LANCZOS)
        img.save(thumb_path, "JPEG", quality=85)
        return thumb_path
    except Exception as e:
        print(f"  Thumbnail error ({raw_path.name}): {e}")
        return None


def generate_video_thumbnail(raw_path: Path, thumb_path: Path) -> Path | None:
    try:
        subprocess.run(["ffmpeg", "-i", str(raw_path), "-vframes", "1", "-q:v", "2", str(thumb_path), "-y"],
                       capture_output=True, timeout=30)
        if thumb_path.exists():
            return thumb_path
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    print(f"  ffmpeg not available for video thumbnail: {raw_path.name}")
    return None


# ─────────────────────────────────────────────────────────────────────────────
# EXIF / XMP WRITING
# ─────────────────────────────────────────────────────────────────────────────
def write_exif(thumb_path: Path, artifact_id: str, description: str,
               source_url: str, tag_slugs):
    """v0.4: tag_slugs is a list of slugs from the flat tags array."""
    try:
        if isinstance(tag_slugs, str):
            tag_slugs = _parse_tags_json(tag_slugs)
        keywords = ", ".join(filter(None, tag_slugs or []))
        args = ["exiftool",
                f"-ImageDescription={description or ''}",
                f"-XMP:Description={description or ''}",
                f"-XMP:Identifier={artifact_id}",
                f"-XMP:Source={source_url or ''}",
                f"-XMP:Subject={keywords}",
                "-overwrite_original", str(thumb_path)]
        result = subprocess.run(args, capture_output=True, text=True, timeout=15)
        if result.returncode != 0:
            print(f"  exiftool warning: {result.stderr.strip()}")
    except FileNotFoundError:
        print("  exiftool not found — skipping EXIF write. Install: winget install exiftool")
    except subprocess.TimeoutExpired:
        print("  exiftool timeout")


# ─────────────────────────────────────────────────────────────────────────────
# FILE MOVES
# ─────────────────────────────────────────────────────────────────────────────
def move_original(conn, queue_id: int, raw_path: Path, ingest_source: str):
    try:
        if ingest_source == "screenshot-pipeline":
            recycle_file(raw_path)
            print(f"  Recycled: {raw_path.name}")
        else:
            dest = PROCESSED_DIR / raw_path.name
            if dest.exists():
                dest = PROCESSED_DIR / f"{raw_path.stem}_{queue_id}{raw_path.suffix}"
            shutil.move(str(raw_path), str(dest))
            print(f"  Moved to processed: {raw_path.name}")
        conn.execute(
            "UPDATE ingest_queue SET status='failed', error_message='file-moved' WHERE queue_id=?",
            (queue_id,)
        )
        conn.commit()
    except Exception as e:
        print(f"  Move failed ({raw_path.name}): {e}")


def recycle_file(path: Path):
    if RECYCLE_AVAILABLE:
        send2trash(str(path))
    else:
        dest = PROCESSED_DIR / path.name
        if dest.exists():
            dest = PROCESSED_DIR / f"{path.stem}_recycled{path.suffix}"
        shutil.move(str(path), str(dest))
        print(f"  (send2trash unavailable — moved to processed instead)")


# ─────────────────────────────────────────────────────────────────────────────
# STATUS
# ─────────────────────────────────────────────────────────────────────────────
def status():
    conn = get_conn()
    print(f"\n{'='*50}")
    print("MediaVault — Ingest Queue Status")
    print(f"{'='*50}")

    rows = conn.execute(
        "SELECT status, COUNT(*) as n FROM ingest_queue GROUP BY status ORDER BY status"
    ).fetchall()
    if not rows:
        print("  Queue is empty.")
    else:
        for row in rows:
            print(f"  {row['status']:<16} {row['n']:>4}")

    total = conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0]
    print(f"\n  Total catalog records: {total}")
    # v0.4: break down by status (lifecycle) rather than domain
    for row in conn.execute(
        "SELECT status, COUNT(*) as n FROM artifacts GROUP BY status ORDER BY status"
    ).fetchall():
        print(f"    {row['status']:<16} {row['n']:>4} artifacts")
    # And by storage mode
    for row in conn.execute(
        "SELECT storage_mode, COUNT(*) as n FROM artifacts GROUP BY storage_mode ORDER BY storage_mode"
    ).fetchall():
        print(f"    storage={row['storage_mode']:<10} {row['n']:>4} artifacts")

    pending = conn.execute("""
        SELECT raw_path, ingest_source, queued_at
        FROM ingest_queue WHERE status = 'pending'
        ORDER BY queued_at LIMIT 10
    """).fetchall()
    if pending:
        print(f"\n  Pending items (first 10):")
        for p in pending:
            name = Path(p['raw_path']).name if p['raw_path'] else '—'
            print(f"    {name}  ({p['ingest_source']})")

    conn.close()
    print()


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def parse_json_arr(s):
    if not s:
        return []
    try:
        a = json.loads(s)
        return a if isinstance(a, list) else [a]
    except Exception:
        return [s]


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"

    if cmd == "scan":
        print("Scanning for new items...")
        added_count = scan()
        if added_count and added_count > 1:
            try:
                ans = input(f"\n{added_count} items added. Run triage? [y/N]: ").strip().lower()
                if ans == 'y':
                    print("Upload the new items to Claude and ask for triage analysis.")
            except EOFError:
                pass
    elif cmd == "process":
        print("Processing approved items...")
        process()
    elif cmd == "status":
        status()
    else:
        print(f"Unknown command: {cmd}")
        print("Usage: python ingest_engine.py scan|process|status")
        sys.exit(1)
