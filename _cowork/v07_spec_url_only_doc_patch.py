"""One-shot patch for SPEC.md §3 — add a sentence noting that
/api/artifact-register treats local_asset_path as conditionally required
based on storage_mode. Idempotent."""
from __future__ import annotations
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "SPEC.md"

OLD = (
    "Storage mode is explicit on the record, selectable in the inbox editor, "
    "and a filter facet in the vault. A single parent URL artifact may be "
    "`url_only` while its child extract (a downloaded image, a text transcript) "
    "is `vaulted` — they are independent records linked by `parent_artifact_id`.\n"
)

NEW = (
    "Storage mode is explicit on the record, selectable in the inbox editor, "
    "and a filter facet in the vault. A single parent URL artifact may be "
    "`url_only` while its child extract (a downloaded image, a text transcript) "
    "is `vaulted` — they are independent records linked by `parent_artifact_id`.\n"
    "\n"
    "**API contract for `local_asset_path`** (`POST /api/artifact-register`). "
    "The path field is conditionally required by `storage_mode`: required when "
    "`storage_mode` is `vaulted` or `referenced`; optional (may be null or "
    "omitted) when `storage_mode` is `url_only`. When a path is provided in "
    "the `url_only` case it is still validated normally — the file must exist "
    "and must live under one of the allowed asset roots (`C:\\AI`). Operators "
    "may legitimately reference an existing snapshot from a `url_only` "
    "artifact, and the safety check stands.\n"
)


def main() -> int:
    data = TARGET.read_bytes()
    orig = len(data)
    print(f"reading: {TARGET}  ({orig} bytes)")

    old_b = OLD.encode("utf-8")
    new_b = NEW.encode("utf-8")

    if new_b in data:
        print("  already patched, no changes")
        return 0
    if old_b not in data:
        # Try CRLF variant.
        old_crlf = old_b.replace(b"\n", b"\r\n")
        new_crlf = new_b.replace(b"\n", b"\r\n")
        if old_crlf in data:
            data = data.replace(old_crlf, new_crlf, 1)
        else:
            raise SystemExit("OLD anchor not found, refusing to patch")
    else:
        data = data.replace(old_b, new_b, 1)

    new_size = len(data)
    print(f"  size after: {new_size} bytes (delta {new_size - orig:+d})")
    os.remove(TARGET)
    TARGET.write_bytes(data)
    print(f"  wrote: {TARGET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
