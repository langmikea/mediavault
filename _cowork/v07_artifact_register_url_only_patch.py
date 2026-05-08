"""
One-shot patch script for the v0.7 punchlist item:
  api: allow local_asset_path null when storage_mode is url_only

Replaces a contiguous block in core/imgserver_extensions.py and the single
INSERT-VALUES line that writes local_asset_path. Idempotent: if the new
markers are already present, the script reports "no changes" and exits 0.

Run:
    python _cowork/v07_artifact_register_url_only_patch.py
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "core" / "imgserver_extensions.py"

OLD_DOCSTRING_BLOCK = (
    '      REQUIRED:\n'
    '        local_asset_path   absolute path to the file on disk\n'
    '\n'
    "      OPTIONAL (passed through if present, else sensible default):\n"
    "        id                 artifact ID (auto-assigned if missing)\n"
    "        ingest_source      default 'url-entry'\n"
    "        source_url         canonical URL this asset represents\n"
    "        source_platform    one of SOURCE_PLATFORM\n"
    "        media_type         one of MEDIA_TYPE; inferred from extension if missing\n"
    "        storage_mode       one of STORAGE_MODE; default 'vaulted' (file on disk)\n"
    "        status             one of STATUS_ENUM; default 'vault'\n"
    "        link_status        one of LINK_STATUS; default 'local-only' since the\n"
    "                           file lives on disk\n"
)

NEW_DOCSTRING_BLOCK = (
    "      OPTIONAL (passed through if present, else sensible default):\n"
    "        id                 artifact ID (auto-assigned if missing)\n"
    "        ingest_source      default 'url-entry'\n"
    "        source_url         canonical URL this asset represents\n"
    "        source_platform    one of SOURCE_PLATFORM\n"
    "        media_type         one of MEDIA_TYPE; inferred from extension when\n"
    "                           a local file is provided. REQUIRED in the body\n"
    "                           when local_asset_path is omitted (no file to\n"
    "                           infer from).\n"
    "        storage_mode       one of STORAGE_MODE; default 'vaulted' (file on disk)\n"
    "        status             one of STATUS_ENUM; default 'vault'\n"
    "        link_status        one of LINK_STATUS; default 'local-only' since the\n"
    "                           file lives on disk\n"
    "        local_asset_path   absolute path to the file on disk. REQUIRED when\n"
    "                           storage_mode is 'vaulted' or 'referenced'.\n"
    "                           OPTIONAL when storage_mode == 'url_only' (the\n"
    "                           catalog record is the preservation artifact and\n"
    "                           there are no local bytes). When provided in the\n"
    "                           url_only case it is still validated normally:\n"
    "                           the path must exist and must live under one of\n"
    "                           ASSET_ROOTS. Operators may legitimately reference\n"
    "                           an existing snapshot from a url_only artifact,\n"
    "                           and the safety check stands.\n"
)

OLD_VALIDATION_BLOCK = (
    "    # --- Required fields --------------------------------------------------\n"
    "    local_path_raw = body.get(\"local_asset_path\")\n"
    "    if not local_path_raw:\n"
    "        return _json_response(handler, 400,\n"
    "            {\"ok\": False, \"error\": \"local_asset_path is required\"})\n"
    "\n"
    "    local_path = Path(local_path_raw)\n"
    "    if not local_path.exists() or not local_path.is_file():\n"
    "        return _json_response(handler, 400,\n"
    "            {\"ok\": False, \"error\": f\"file not found: {local_path_raw}\"})\n"
    "    if not _path_is_inside(local_path, ASSET_ROOTS):\n"
    "        return _json_response(handler, 403,\n"
    "            {\"ok\": False, \"error\": \"local_asset_path outside allowed roots\"})\n"
    "\n"
    "    # --- Enum-validated optionals (reject bad values instead of silently null)\n"
    "    def validated(key, enum, default=None):\n"
    "        v = body.get(key, default)\n"
    "        if v is None:\n"
    "            return None\n"
    "        if v not in enum:\n"
    "            raise ValueError(f\"{key}={v!r} not in {sorted(enum)}\")\n"
    "        return v\n"
    "\n"
    "    try:\n"
    "        ingest_source        = validated(\"ingest_source\",      INGEST_SOURCE,  \"url-entry\")\n"
    "        source_platform      = validated(\"source_platform\",    SOURCE_PLATFORM)\n"
    "        media_type           = body.get(\"media_type\") or _infer_media_type(local_path)\n"
    "        if media_type not in MEDIA_TYPE:\n"
    "            raise ValueError(f\"media_type={media_type!r} not in {sorted(MEDIA_TYPE)}\")\n"
    "        link_status          = validated(\"link_status\",        LINK_STATUS,    \"local-only\")\n"
    "        post_date_confidence = validated(\"post_date_confidence\", POST_DATE_CONF, \"unknown\")\n"
    "        storage_mode         = validated(\"storage_mode\",       STORAGE_MODE,   \"vaulted\")\n"
    "        status               = validated(\"status\",             STATUS_ENUM,    \"vault\")\n"
    "    except ValueError as e:\n"
    "        return _json_response(handler, 400, {\"ok\": False, \"error\": str(e)})\n"
)

NEW_VALIDATION_BLOCK = (
    "    # --- Enum-validated optionals (reject bad values instead of silently null).\n"
    "    # Validated up front so storage_mode is known when we decide whether\n"
    "    # local_asset_path is required.\n"
    "    def validated(key, enum, default=None):\n"
    "        v = body.get(key, default)\n"
    "        if v is None:\n"
    "            return None\n"
    "        if v not in enum:\n"
    "            raise ValueError(f\"{key}={v!r} not in {sorted(enum)}\")\n"
    "        return v\n"
    "\n"
    "    try:\n"
    "        ingest_source        = validated(\"ingest_source\",      INGEST_SOURCE,  \"url-entry\")\n"
    "        source_platform      = validated(\"source_platform\",    SOURCE_PLATFORM)\n"
    "        link_status          = validated(\"link_status\",        LINK_STATUS,    \"local-only\")\n"
    "        post_date_confidence = validated(\"post_date_confidence\", POST_DATE_CONF, \"unknown\")\n"
    "        storage_mode         = validated(\"storage_mode\",       STORAGE_MODE,   \"vaulted\")\n"
    "        status               = validated(\"status\",             STATUS_ENUM,    \"vault\")\n"
    "    except ValueError as e:\n"
    "        return _json_response(handler, 400, {\"ok\": False, \"error\": str(e)})\n"
    "\n"
    "    # --- local_asset_path: required for vaulted/referenced; optional for\n"
    "    # url_only (the catalog record is the preservation artifact, no local\n"
    "    # bytes). When provided the path is validated regardless of\n"
    "    # storage_mode — operators may legitimately reference an existing\n"
    "    # snapshot from a url_only artifact, and the safety check stands.\n"
    "    local_path_raw = body.get(\"local_asset_path\")\n"
    "    local_path = None\n"
    "    if local_path_raw:\n"
    "        local_path = Path(local_path_raw)\n"
    "        if not local_path.exists() or not local_path.is_file():\n"
    "            return _json_response(handler, 400,\n"
    "                {\"ok\": False, \"error\": f\"file not found: {local_path_raw}\"})\n"
    "        if not _path_is_inside(local_path, ASSET_ROOTS):\n"
    "            return _json_response(handler, 403,\n"
    "                {\"ok\": False, \"error\": \"local_asset_path outside allowed roots\"})\n"
    "    elif storage_mode != \"url_only\":\n"
    "        return _json_response(handler, 400,\n"
    "            {\"ok\": False, \"error\":\n"
    "             f\"local_asset_path is required when storage_mode={storage_mode!r}\"})\n"
    "\n"
    "    # --- media_type: inferred from the path when caller didn't specify;\n"
    "    # required in the body when there is no local file to infer from.\n"
    "    try:\n"
    "        media_type = body.get(\"media_type\")\n"
    "        if not media_type:\n"
    "            if local_path is not None:\n"
    "                media_type = _infer_media_type(local_path)\n"
    "            else:\n"
    "                raise ValueError(\n"
    "                    \"media_type is required when local_asset_path is omitted\")\n"
    "        if media_type not in MEDIA_TYPE:\n"
    "            raise ValueError(f\"media_type={media_type!r} not in {sorted(MEDIA_TYPE)}\")\n"
    "    except ValueError as e:\n"
    "        return _json_response(handler, 400, {\"ok\": False, \"error\": str(e)})\n"
)

OLD_INSERT_LINE = "                    str(local_path.resolve()),\n"
NEW_INSERT_LINE = "                    str(local_path.resolve()) if local_path is not None else None,\n"


def _replace(data: bytes, old: str, new: str, label: str) -> bytes:
    old_b = old.encode("utf-8")
    new_b = new.encode("utf-8")
    if old_b in data:
        return data.replace(old_b, new_b, 1)
    # Try CRLF variant — FUSE preserves Windows line endings.
    old_crlf = old_b.replace(b"\n", b"\r\n")
    new_crlf = new_b.replace(b"\n", b"\r\n")
    if old_crlf in data:
        return data.replace(old_crlf, new_crlf, 1)
    # Already patched (new block present) — idempotent.
    if new_b in data or new_crlf in data:
        print(f"  [{label}] already patched, skipping")
        return data
    raise SystemExit(
        f"  [{label}] OLD block not found and NEW block not present — abort.")


def main() -> int:
    print(f"reading: {TARGET}")
    data = TARGET.read_bytes()
    orig_size = len(data)
    print(f"  size before: {orig_size} bytes")

    data = _replace(data, OLD_DOCSTRING_BLOCK, NEW_DOCSTRING_BLOCK, "docstring")
    data = _replace(data, OLD_VALIDATION_BLOCK, NEW_VALIDATION_BLOCK, "validation")
    data = _replace(data, OLD_INSERT_LINE, NEW_INSERT_LINE, "insert-line")

    new_size = len(data)
    print(f"  size after:  {new_size} bytes (delta {new_size - orig_size:+d})")

    # Atomic-ish swap: remove then write.
    os.remove(TARGET)
    TARGET.write_bytes(data)
    print(f"  wrote: {TARGET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
