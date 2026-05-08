"""
v0.6 punchlist — Item 1 smoke test.

Hits a *running* imgserver at http://127.0.0.1:51822 and asserts both
pill-creation surfaces succeed end-to-end:

  - Inbox "+ add pill" shape:
        POST /api/tag-create {slug, display_name, is_proposed:1}
  - Tag Manager + NEW TAG dialog shape:
        POST /api/tag-create {slug, display_name, category, is_exclusive,
                              description, is_proposed}

Cleans up by DELETing both test slugs (uses /api/tag-delete; falls back
to a direct sqlite cleanup hint if the endpoint is missing).

Run *after* restarting imgserver:
    python _cowork/v06_smoke_tag_create.py
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:51822"
# slugify() strips leading underscores, so don't use them — match what the
# server will store.
TEST_SLUG_INBOX = "smoke_v06_inbox_pill"
TEST_SLUG_TM    = "smoke_v06_tm_pill"


def _tags_list(payload) -> list:
    """/api/tags returns {ok, rows: [...]}; old shape was a bare list."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("rows"), list):
        return payload["rows"]
    return []


def _post(path: str, body: dict) -> tuple[int, dict | str]:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        BASE + path, data=data,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            text = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, json.loads(text)
            except json.JSONDecodeError:
                return resp.status, text
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", errors="replace")
        try:
            return e.code, json.loads(text)
        except json.JSONDecodeError:
            return e.code, text


def _get(path: str) -> tuple[int, object]:
    try:
        with urllib.request.urlopen(BASE + path, timeout=8) as resp:
            text = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, json.loads(text)
            except json.JSONDecodeError:
                return resp.status, text
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")


def _cleanup(slug: str) -> None:
    try:
        _post("/api/tag-delete", {"slug": slug})
    except Exception:
        pass


def main() -> int:
    failures: list[str] = []

    def expect(cond: bool, label: str, detail: object = ""):
        marker = "PASS" if cond else "FAIL"
        line = f"  [{marker}] {label}"
        if detail:
            line += f"  {detail}"
        print(line)
        if not cond:
            failures.append(label)

    print(f"target: {BASE}")
    code, body = _get("/ping")
    expect(code == 200, "/ping reachable", f"(status {code})")
    if code != 200:
        print("  (server not reachable — abort)")
        return 2

    # Confirm baseline tags. /api/tags returns {ok, rows:[...]}.
    code, tags_resp = _get("/api/tags")
    tags = _tags_list(tags_resp)
    expect(code == 200 and isinstance(tags_resp, dict)
           and tags_resp.get("ok") is True and isinstance(tags_resp.get("rows"), list),
           "/api/tags returns {ok, rows:[...]}",
           f"(status {code}, rows={len(tags)})")
    baseline = {t["slug"] for t in tags}

    # Pre-cleanup in case a prior smoke left rows.
    if TEST_SLUG_INBOX in baseline:
        _cleanup(TEST_SLUG_INBOX)
    if TEST_SLUG_TM in baseline:
        _cleanup(TEST_SLUG_TM)

    print("\n--- inbox + add pill surface ---")
    code, resp = _post("/api/tag-create", {
        "slug": TEST_SLUG_INBOX,
        "display_name": "Smoke Inbox Pill",
        "is_proposed": 1,
    })
    expect(code == 200, "POST /api/tag-create (inbox shape) returns 200",
           f"resp={resp}")
    expect(isinstance(resp, dict) and resp.get("ok") is True,
           "response.ok == True")

    print("\n--- Tag Manager + NEW TAG surface ---")
    code, resp = _post("/api/tag-create", {
        "slug": TEST_SLUG_TM,
        "display_name": "Smoke TM Pill",
        "category": "topic",
        "is_exclusive": 0,
        "description": "smoke test row",
        "is_proposed": 0,
    })
    expect(code == 200, "POST /api/tag-create (Tag Manager shape) returns 200",
           f"resp={resp}")
    expect(isinstance(resp, dict) and resp.get("ok") is True,
           "response.ok == True")

    # Verify both rows present + categories correct.
    time.sleep(0.1)
    code, tags_resp = _get("/api/tags")
    tags = _tags_list(tags_resp)
    by_slug = {t["slug"]: t for t in tags}
    inbox_row = by_slug.get(TEST_SLUG_INBOX, {})
    tm_row    = by_slug.get(TEST_SLUG_TM, {})
    expect(bool(inbox_row), "inbox-shape row visible in /api/tags")
    expect(bool(tm_row),    "TM-shape row visible in /api/tags")
    expect(inbox_row.get("category") in (None, "", "uncategorized"),
           "inbox row category is NULL / blank (uncategorized)",
           f"category={inbox_row.get('category')!r}")
    expect(tm_row.get("category") == "topic",
           "TM row category == 'topic'",
           f"category={tm_row.get('category')!r}")
    expect(int(inbox_row.get("is_proposed", 0)) == 1,
           "inbox row is_proposed == 1")
    expect(int(tm_row.get("is_proposed", 0)) == 0,
           "TM row is_proposed == 0")

    # Duplicate-slug guard (same category).
    print("\n--- duplicate guard (same category) ---")
    code, resp = _post("/api/tag-create", {
        "slug": TEST_SLUG_TM, "display_name": "dup",
        "category": "topic",
    })
    expect(code == 409, "duplicate slug in same category returns 409",
           f"(status {code}, resp={resp})")

    # v0.6 item 3: same slug in a different category should now succeed.
    print("\n--- composite uniqueness (different category) ---")
    TEST_SLUG_TM_CROSS_CAT = "scope"
    code, resp = _post("/api/tag-create", {
        "slug": TEST_SLUG_TM, "display_name": "cross-cat smoke",
        "category": TEST_SLUG_TM_CROSS_CAT,
    })
    expect(code == 200, "same slug in different category returns 200",
           f"(status {code}, resp={resp})")
    # Verify both rows are present, then clean up the extra one.
    code, tags_resp = _get("/api/tags")
    tags = _tags_list(tags_resp)
    rows_same_slug = [t for t in tags if t["slug"] == TEST_SLUG_TM]
    expect(len(rows_same_slug) == 2,
           "two rows now share the slug",
           f"(count={len(rows_same_slug)})")

    # v0.6 item 3: when a rename targets a slug that already exists in the
    # SAME category, the server should return 409 with a merge_offered
    # payload so the UI can offer a merge. Use a decoy source so we're
    # testing the rename path (new_slug != slug).
    print("\n--- merge-offer rename (same-category collision) ---")
    DECOY = "smoke_v06_decoy_src"
    _cleanup(DECOY)
    code, resp = _post("/api/tag-create", {
        "slug": DECOY, "display_name": "decoy",
        "category": "topic",
    })
    expect(code == 200, "decoy create returns 200",
           f"(status {code}, resp={resp})")
    code, resp = _post("/api/tag-update", {
        "slug": DECOY,
        "new_slug": TEST_SLUG_TM,
        "category": TEST_SLUG_TM_CROSS_CAT,
    })
    expect(code == 409,
           "same-(slug,category) rename collision returns 409",
           f"(status {code}, resp={resp})")
    expect(isinstance(resp, dict) and resp.get("merge_offered") is True,
           "409 payload has merge_offered=True",
           f"resp={resp}")
    expect(isinstance(resp, dict) and resp.get("target_slug") == TEST_SLUG_TM,
           "409 payload target_slug matches",
           f"resp={resp}")

    # Cleanup.
    print("\n--- cleanup ---")
    _cleanup(DECOY)
    # Both rows of TEST_SLUG_TM need removing; tag-delete refuses if in use,
    # so use tag-bulk-delete which strips from artifacts too. These smoke
    # rows aren't on any artifacts, so bulk-delete is safe.
    _post("/api/tag-bulk-delete", {"slugs": [TEST_SLUG_TM, TEST_SLUG_INBOX]})
    code, tags_resp = _get("/api/tags")
    tags = _tags_list(tags_resp)
    by_slug = {t["slug"]: t for t in tags}
    expect(TEST_SLUG_INBOX not in by_slug, "inbox-shape row removed")
    expect(TEST_SLUG_TM    not in by_slug, "TM-shape row removed")

    print()
    if failures:
        print(f"FAILED: {len(failures)} assertion(s)")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("ALL GREEN — both pill-create surfaces work end-to-end.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
