"""
v0.6 Item 4 — author tag cleanup.

Against the running imgserver at http://127.0.0.1:51822:

  1. DELETE FROM ALL these two tags (strip from every artifact, delete row):
        author:elmthree_productions   (expected: 2 artifacts)
        author:hunterrootofficial     (expected: 1 artifact)

  2. Strip trailing " (author)" from every remaining tag's display_name.
     The category column already marks a tag as belonging to `people`; the
     parenthetical is redundant (per punchlist §4).

Idempotent — re-runnable with no side effects once clean.

Run:
    python C:\\AI\\Platform\\MediaVault\\_cowork\\v06_item4_cleanup.py
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:51822"
DELETE_FROM_ALL = ["author:elmthree_productions", "author:hunterrootofficial"]
SUFFIX = " (author)"


def _get(path):
    with urllib.request.urlopen(BASE + path, timeout=10) as r:
        return r.status, json.loads(r.read().decode("utf-8", errors="replace"))


def _post(path, body):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        BASE + path, data=data,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            text = r.read().decode("utf-8", errors="replace")
            try:
                return r.status, json.loads(text)
            except json.JSONDecodeError:
                return r.status, text
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", errors="replace")
        try:
            return e.code, json.loads(text)
        except json.JSONDecodeError:
            return e.code, text


def _tags_list(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("rows"), list):
        return payload["rows"]
    return []


def main() -> int:
    print(f"target: {BASE}")
    code, _ = _get("/ping")
    if code != 200:
        print(f"  /ping {code}: server not reachable", file=sys.stderr)
        return 2

    code, resp = _get("/api/tags")
    rows = _tags_list(resp)
    by_slug = {t["slug"]: t for t in rows}
    print(f"  loaded {len(rows)} tags")

    # --- 1. DELETE FROM ALL targets --------------------------------------
    print("\n--- DELETE FROM ALL ---")
    present = [s for s in DELETE_FROM_ALL if s in by_slug]
    if not present:
        print("  (neither target slug is present — already deleted)")
    else:
        for slug in present:
            t = by_slug[slug]
            print(f"  {slug}  ({t.get('usage_count', 0)} artifact(s))")
        code, ret = _post("/api/tag-bulk-delete", {"slugs": present})
        if code != 200:
            print(f"  FAILED: {code} {ret}")
            return 1
        per = (ret.get("deleted") or {}) if isinstance(ret, dict) else {}
        for slug, n in per.items():
            print(f"    {slug}: stripped from {n} artifact(s), tag row deleted")

    # --- 2. Strip ' (author)' suffix from remaining display_names --------
    print("\n--- strip ' (author)' suffix from display names ---")
    code, resp = _get("/api/tags")
    rows = _tags_list(resp)
    changed = 0
    for t in rows:
        slug = t.get("slug")
        disp = (t.get("display_name") or "").rstrip()
        if not disp.endswith(SUFFIX):
            continue
        new = disp[: -len(SUFFIX)].rstrip()
        if not new:
            print(f"  SKIP {slug}: stripping would leave display blank")
            continue
        code, ret = _post(
            "/api/tag-update", {"slug": slug, "display_name": new}
        )
        if code != 200:
            print(f"  FAILED {slug}: {code} {ret}")
            return 1
        print(f"  {slug:45s}  {disp!r}  ->  {new!r}")
        changed += 1
    if changed == 0:
        print("  (no display names needed editing — already clean)")

    # --- 3. Verify -------------------------------------------------------
    print("\n--- verify ---")
    code, resp = _get("/api/tags")
    rows = _tags_list(resp)
    leftover_suffix = [
        t for t in rows
        if (t.get("display_name") or "").rstrip().endswith(SUFFIX)
    ]
    leftover_targets = [t for t in rows if t["slug"] in DELETE_FROM_ALL]
    print(f"  rows with ' (author)' suffix: {len(leftover_suffix)} (want 0)")
    print(f"  unwanted target slugs still present: {len(leftover_targets)} (want 0)")

    hr = next((t for t in rows if t["slug"] == "author:hunter_root"), None)
    if hr:
        print(f"  author:hunter_root: display_name={hr.get('display_name')!r}, "
              f"usage={hr.get('usage_count', 0)}")
    else:
        print("  author:hunter_root: NOT FOUND (expected present)")

    if leftover_suffix or leftover_targets or not hr:
        print("\nFAILED — see above")
        return 1
    print("\nALL GREEN — author tags are clean.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
