"""
v0.6 punchlist — Item 1 regression test.

Exercises /api/tag-create (and /api/tag-update for symmetry) via
imgserver's actual handler functions, against a temp-copy of the live
DB. Asserts the punchlist's two stated cases plus a few edge shapes.

Why a copy of the live DB? The sandbox can't always create SQLite
journal files inside the source repo path. Copy to /tmp first.

Run:
    python _cowork/v06_tag_create_test.py
Exit codes:
    0 — all green
    1 — one or more assertions failed
"""
from __future__ import annotations

import io
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import traceback

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
SRC_DB = os.path.join(ROOT, "core", "mediavault.sqlite")

sys.path.insert(0, os.path.join(ROOT, "core"))
sys.path.insert(0, os.path.join(ROOT, "_cowork"))


def _copy_db() -> str:
    tmpdir = tempfile.mkdtemp(prefix="mv06_tagcreate_")
    dst = os.path.join(tmpdir, "mediavault.sqlite")
    shutil.copy2(SRC_DB, dst)
    return dst


def _ensure_migrated(db_path: str) -> None:
    """Ensure the temp copy has the v0.6 composite-unique schema. Invokes
    v06_phase3_migration against the copy if not."""
    import importlib
    c = sqlite3.connect(db_path)
    has = c.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='index' AND name='idx_tags_slug_category'"
    ).fetchone()
    c.close()
    if has:
        return
    mig = importlib.import_module("v06_phase3_migration")
    mig.DB = db_path
    # Migration writes its backup to <ROOT>/core/ — make sure that exists in
    # the temp tree so _backup() doesn't FileNotFound.
    mig.ROOT = os.path.dirname(db_path)
    os.makedirs(os.path.join(mig.ROOT, "core"), exist_ok=True)
    rc = mig.main()
    if rc != 0:
        raise RuntimeError(f"migration failed on temp db (rc={rc})")


class FakeHandler:
    """Minimal stand-in for BaseHTTPRequestHandler used by send_*/read_body."""

    def __init__(self, body: dict):
        self._body = json.dumps(body).encode("utf-8")
        self.headers = {"Content-Length": str(len(self._body))}
        self.rfile = io.BytesIO(self._body)
        self.wfile = io.BytesIO()


def _install_capture(imgserver):
    """Patch send_json/send_error to capture; return the capture list."""
    captured: list[tuple[str, int, object]] = []

    def cap_send_json(_h, status, payload):
        captured.append(("json", status, payload))

    def cap_send_error(_h, status, msg):
        captured.append(("err", status, msg))

    imgserver.send_json = cap_send_json
    imgserver.send_error = cap_send_error
    return captured


def main() -> int:
    db = _copy_db()
    print(f"using temp db: {db}")
    _ensure_migrated(db)
    print("  (schema migrated / already v0.6)")

    import imgserver  # noqa: E402

    imgserver.DB_PATH = db

    def _db_conn():
        c = sqlite3.connect(db)
        c.row_factory = sqlite3.Row
        return c

    imgserver.db_conn = _db_conn
    captured = _install_capture(imgserver)

    failures: list[str] = []

    def expect(cond: bool, label: str):
        marker = "PASS" if cond else "FAIL"
        print(f"  [{marker}] {label}")
        if not cond:
            failures.append(label)

    def call(handler, body):
        captured.clear()
        handler(FakeHandler(body))
        assert captured, "handler returned without sending a response"
        return captured[-1]

    print("\n--- /api/tag-create ---")

    # Case A: Tag Manager NEW TAG dialog payload (slug + display + category +
    # is_exclusive + description + is_proposed=0).
    res = call(
        imgserver.handle_tag_create,
        {
            "slug": "v06_test_tm",
            "display_name": "v06 Test TM",
            "category": "topic",
            "is_exclusive": 0,
            "description": "via Tag Manager",
            "is_proposed": 0,
        },
    )
    expect(res[1] == 200, f"Tag Manager NEW TAG returns 200 (got {res})")
    expect(res[2].get("ok") is True, "response.ok == True")
    row = sqlite3.connect(db).execute(
        "SELECT category, display_name, is_proposed FROM tags WHERE slug=?",
        ("v06_test_tm",),
    ).fetchone()
    expect(row is not None and row[0] == "topic" and row[1] == "v06 Test TM"
           and row[2] == 0,
           f"DB row reflects category='topic', is_proposed=0 (got {row})")

    # Case B: inbox "+ add pill" payload (slug + display + is_proposed=1, no
    # category). Per the v0.6 contract this is allowed and lands as
    # category=NULL ("uncategorized"). Item 6 will fix the inbox surface to
    # always supply a category, after which this contract still holds for
    # internal/legacy callers.
    res = call(
        imgserver.handle_tag_create,
        {
            "slug": "v06_test_inbox",
            "display_name": "v06 Test Inbox",
            "is_proposed": 1,
        },
    )
    expect(res[1] == 200, f"inbox + add pill returns 200 (got {res})")
    row = sqlite3.connect(db).execute(
        "SELECT category, is_proposed FROM tags WHERE slug=?",
        ("v06_test_inbox",),
    ).fetchone()
    expect(row is not None and row[0] is None and row[1] == 1,
           f"DB row reflects category=NULL, is_proposed=1 (got {row})")

    # Case C: legacy group_name body key still accepted as alias.
    res = call(
        imgserver.handle_tag_create,
        {
            "slug": "v06_test_legacy",
            "display_name": "v06 Test Legacy",
            "group_name": "topic",
        },
    )
    expect(res[1] == 200, f"legacy group_name alias returns 200 (got {res})")
    row = sqlite3.connect(db).execute(
        "SELECT category FROM tags WHERE slug=?",
        ("v06_test_legacy",),
    ).fetchone()
    expect(row is not None and row[0] == "topic",
           f"legacy alias landed as category='topic' (got {row})")

    # Case D: bad category type → 400.
    res = call(
        imgserver.handle_tag_create,
        {"slug": "v06_test_badcat", "category": ["topic"]},
    )
    expect(res[1] == 400, f"non-string category returns 400 (got {res})")

    # Case E: empty-string category collapses to NULL.
    res = call(
        imgserver.handle_tag_create,
        {"slug": "v06_test_emptycat", "display_name": "Empty Cat",
         "category": "   "},
    )
    expect(res[1] == 200, f"whitespace category returns 200 (got {res})")
    row = sqlite3.connect(db).execute(
        "SELECT category FROM tags WHERE slug=?",
        ("v06_test_emptycat",),
    ).fetchone()
    expect(row is not None and row[0] is None,
           f"whitespace category collapsed to NULL (got {row})")

    # Case F: re-creating an existing slug → 409.
    res = call(
        imgserver.handle_tag_create,
        {"slug": "v06_test_tm", "display_name": "dup", "category": "topic"},
    )
    expect(res[1] == 409, f"duplicate slug returns 409 (got {res})")

    # Case G (v0.6 item 3): same slug in a DIFFERENT category → 200.
    # Demonstrates the composite-uniqueness contract.
    res = call(
        imgserver.handle_tag_create,
        {"slug": "v06_test_tm", "display_name": "cross-cat",
         "category": "scope"},
    )
    expect(res[1] == 200,
           f"same slug in different category returns 200 (got {res})")
    n = sqlite3.connect(db).execute(
        "SELECT COUNT(*) FROM tags WHERE slug=?", ("v06_test_tm",),
    ).fetchone()[0]
    expect(n == 2, f"two rows now share slug v06_test_tm (got n={n})")

    # Case H: two (slug, NULL) rows are still forbidden.
    res = call(
        imgserver.handle_tag_create,
        {"slug": "v06_test_inbox", "display_name": "dup-null"},
    )
    expect(res[1] == 409, f"duplicate slug in NULL category returns 409 (got {res})")

    print("\n--- /api/tag-update ---")
    # Partial update: change category on the inbox-created tag.
    res = call(
        imgserver.handle_tag_update,
        {"slug": "v06_test_inbox", "category": "topic"},
    )
    expect(res[1] == 200, f"partial update returns 200 (got {res})")
    row = sqlite3.connect(db).execute(
        "SELECT category FROM tags WHERE slug=?",
        ("v06_test_inbox",),
    ).fetchone()
    expect(row is not None and row[0] == "topic",
           f"category UPDATE landed (got {row})")

    # Legacy alias on update path still routes to category column.
    # NB: after Case G above, there's already a (v06_test_tm, scope) row, so
    # changing v06_test_inbox's category to 'scope' would collide. Use a
    # distinct category instead.
    res = call(
        imgserver.handle_tag_update,
        {"slug": "v06_test_inbox", "group_name": "style"},
    )
    expect(res[1] == 200, f"legacy alias on tag-update returns 200 (got {res})")
    row = sqlite3.connect(db).execute(
        "SELECT category FROM tags WHERE slug=?",
        ("v06_test_inbox",),
    ).fetchone()
    expect(row is not None and row[0] == "style",
           f"legacy update alias landed as category='style' (got {row})")

    # Case I (v0.6 item 3): renaming to a slug that already exists in the
    # SAME category returns an enriched 409 with merge_offered=True.
    # Setup: create one row in 'scope' and try to rename v06_test_inbox
    # (currently 'style') to that slug while also setting category='scope'.
    call(imgserver.handle_tag_create,
         {"slug": "v06_test_mergetarget", "display_name": "Merge Target",
          "category": "scope"})
    res = call(
        imgserver.handle_tag_update,
        {"slug": "v06_test_inbox", "new_slug": "v06_test_mergetarget",
         "category": "scope"},
    )
    expect(res[1] == 409,
           f"same-category rename collision returns 409 (got {res})")
    payload = res[2] if isinstance(res[2], dict) else {}
    expect(payload.get("merge_offered") is True,
           f"409 payload.merge_offered == True (got {payload})")
    expect(payload.get("target_slug") == "v06_test_mergetarget",
           f"payload.target_slug correct (got {payload.get('target_slug')!r})")
    expect(payload.get("target_category") == "scope",
           f"payload.target_category correct "
           f"(got {payload.get('target_category')!r})")

    # Case J (v0.6 item 3): rename collision where target is in a
    # DIFFERENT category is allowed (creates a second row with that slug).
    # 'scope' slot is taken by Merge Target; rename v06_test_inbox to that
    # slug but keep category='style' (current value).
    res = call(
        imgserver.handle_tag_update,
        {"slug": "v06_test_inbox", "new_slug": "v06_test_mergetarget"},
    )
    expect(res[1] == 200,
           f"cross-category rename is allowed (got {res})")
    n = sqlite3.connect(db).execute(
        "SELECT COUNT(*) FROM tags WHERE slug=?",
        ("v06_test_mergetarget",),
    ).fetchone()[0]
    expect(n == 2,
           f"v06_test_mergetarget now in two categories (got n={n})")

    print()
    if failures:
        print(f"FAILED: {len(failures)} assertion(s)")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("ALL GREEN")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(2)
