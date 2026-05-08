"""
Regression test for the v0.7 fix:
  api: allow local_asset_path null when storage_mode is url_only

Runs the actual handle_artifact_register handler against an isolated copy
of the live SQLite DB and asserts three behaviors:

  1. storage_mode='url_only' + local_asset_path=None   ->  200, NULL stored.
  2. storage_mode='url_only' + local_asset_path=<real> ->  200, path stored.
  3. storage_mode='vaulted'  + local_asset_path=None   ->  4xx, validation rejects.

Plus a bonus case 4: storage_mode='url_only' + bogus path -> still 4xx
(path validation stands when a path is provided, regardless of storage_mode).

Pattern mirrors _cowork/v06_tag_create_test.py: temp-copy the live DB,
patch the module's DB_PATH, build a FakeHandler, capture send_response
output. No HTTP server is started.

ASSET_ROOTS quirk: production code hard-codes Path(r"C:\\AI") as the only
allowed root. On a Linux test runner that path resolves to nonsense, so
under-roots checks never pass for any real file. The harness overrides
ASSET_ROOTS at test time to the MediaVault tree (which contains the
fixture file the test points at). Production code is unchanged.

Run:
    python -m pytest tests/test_artifact_register_url_only.py -v
or:
    python tests/test_artifact_register_url_only.py
Exit codes:
    0 - all green
    1 - one or more assertions failed
"""
from __future__ import annotations

import io
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
SRC_DB = os.path.join(ROOT, "core", "mediavault.sqlite")

sys.path.insert(0, os.path.join(ROOT, "core"))


def _copy_db() -> str:
    tmpdir = tempfile.mkdtemp(prefix="mv07_register_url_only_")
    dst = os.path.join(tmpdir, "mediavault.sqlite")
    shutil.copy2(SRC_DB, dst)
    return dst


def _patch_asset_roots(ext) -> None:
    """Override ASSET_ROOTS to the MediaVault tree so a real fixture file
    inside the repo passes the under-roots check on any platform."""
    ext.ASSET_ROOTS = [Path(ROOT).resolve()]


class FakeHandler:
    """Minimal stand-in for BaseHTTPRequestHandler - captures status/body."""

    def __init__(self, body_dict: dict):
        body = json.dumps(body_dict).encode("utf-8")
        self.headers = {"Content-Length": str(len(body))}
        self.rfile = io.BytesIO(body)
        self.wfile = io.BytesIO()
        self._status = None
        self._sent_headers: list = []

    def send_response(self, status):
        self._status = status

    def send_header(self, k, v):
        self._sent_headers.append((k, v))

    def end_headers(self):
        pass

    @property
    def response_body(self) -> dict:
        raw = self.wfile.getvalue()
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))


def _call(handler_fn, body):
    fh = FakeHandler(body)
    handler_fn(fh)
    return fh._status, fh.response_body


def _real_test_file_under_ai() -> str:
    """A file we know exists inside the MediaVault tree. The handler's own
    source is guaranteed to be there. Returns an absolute path."""
    return os.path.join(ROOT, "core", "imgserver_extensions.py")


def _row(db: str, art_id: str):
    c = sqlite3.connect(db)
    c.row_factory = sqlite3.Row
    try:
        return c.execute(
            "SELECT id, storage_mode, local_asset_path, media_type "
            "FROM artifacts WHERE id=?", (art_id,)
        ).fetchone()
    finally:
        c.close()


def _setup_module_db():
    """Copy the live DB, patch DB_PATH and ASSET_ROOTS on the handler module.
    Returns (temp-db-path, module)."""
    db = _copy_db()
    import imgserver_extensions as ext
    ext.DB_PATH = db
    _patch_asset_roots(ext)
    return db, ext


# ---------------------------------------------------------------
# Script-mode runner (mirrors _cowork/v06_tag_create_test.py).
# ---------------------------------------------------------------
def main() -> int:
    db, ext = _setup_module_db()
    print(f"using temp db: {db}")

    failures = []

    def expect(cond, label):
        marker = "PASS" if cond else "FAIL"
        print(f"  [{marker}] {label}")
        if not cond:
            failures.append(label)

    # Case 1: url_only + null path -> 200, NULL stored.
    print("\n--- Case 1: url_only + null path ---")
    status, body = _call(ext.handle_artifact_register, {
        "id": "MV-TEST-URLONLY-NULL",
        "storage_mode": "url_only",
        "media_type": "link",
        "source_url": "https://example.com/post/1",
        "tags": ["platform:youtube", "scope:hunter_root"],
    })
    expect(status == 200, f"returns 200 (got {status} body={body})")
    expect(body.get("ok") is True, "response.ok == True")
    r = _row(db, "MV-TEST-URLONLY-NULL")
    expect(r is not None, "artifact row inserted")
    if r is not None:
        expect(r["storage_mode"] == "url_only",
               f"storage_mode='url_only' (got {r['storage_mode']!r})")
        expect(r["local_asset_path"] is None,
               f"local_asset_path IS NULL (got {r['local_asset_path']!r})")
        expect(r["media_type"] == "link",
               f"media_type='link' (got {r['media_type']!r})")

    # Case 2: url_only + real path -> 200, stored.
    print("\n--- Case 2: url_only + real path ---")
    real_path = _real_test_file_under_ai()
    expect(os.path.isfile(real_path), f"fixture file exists: {real_path}")
    status, body = _call(ext.handle_artifact_register, {
        "id": "MV-TEST-URLONLY-PATH",
        "storage_mode": "url_only",
        "media_type": "text",
        "local_asset_path": real_path,
        "source_url": "https://example.com/post/2",
        "tags": ["platform:youtube"],
    })
    expect(status == 200, f"returns 200 (got {status} body={body})")
    r = _row(db, "MV-TEST-URLONLY-PATH")
    expect(r is not None, "artifact row inserted")
    if r is not None:
        expect(r["storage_mode"] == "url_only", "storage_mode='url_only' preserved")
        expect(r["local_asset_path"] is not None,
               "local_asset_path stored (not NULL)")
        try:
            same = os.path.samefile(r["local_asset_path"], real_path)
        except FileNotFoundError:
            same = False
        expect(same, f"stored path resolves to fixture (got {r['local_asset_path']!r})")

    # Case 3: vaulted + null path -> 4xx.
    print("\n--- Case 3: vaulted + null path -> reject ---")
    status, body = _call(ext.handle_artifact_register, {
        "id": "MV-TEST-VAULTED-NULL",
        "storage_mode": "vaulted",
        "media_type": "photo",
        "source_url": "https://example.com/post/3",
    })
    expect(400 <= (status or 0) < 500, f"returns 4xx (got {status})")
    expect(body.get("ok") is False, "response.ok == False")
    expect("local_asset_path" in str(body),
           f"error mentions local_asset_path (got {body!r})")
    r = _row(db, "MV-TEST-VAULTED-NULL")
    expect(r is None, "no artifact row inserted on rejection")

    # Case 4: url_only + bogus path -> still 4xx (path validation stands).
    print("\n--- Case 4: url_only + bogus path -> still reject ---")
    bogus = os.path.join(ROOT, "does", "not", "exist", "nope.txt")
    status, body = _call(ext.handle_artifact_register, {
        "id": "MV-TEST-URLONLY-BOGUS",
        "storage_mode": "url_only",
        "media_type": "link",
        "local_asset_path": bogus,
    })
    expect(400 <= (status or 0) < 500, f"returns 4xx (got {status})")
    r = _row(db, "MV-TEST-URLONLY-BOGUS")
    expect(r is None, "no artifact row inserted on bogus-path rejection")

    print()
    if failures:
        print(f"FAILED ({len(failures)}):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("all green")
    return 0


# ---------------------------------------------------------------
# pytest entry points (one per case).
# ---------------------------------------------------------------
def test_url_only_with_null_path_succeeds():
    db, ext = _setup_module_db()
    status, body = _call(ext.handle_artifact_register, {
        "id": "MV-PYTEST-URLONLY-NULL",
        "storage_mode": "url_only",
        "media_type": "link",
        "source_url": "https://example.com/a",
    })
    assert status == 200, body
    r = _row(db, "MV-PYTEST-URLONLY-NULL")
    assert r is not None
    assert r["storage_mode"] == "url_only"
    assert r["local_asset_path"] is None


def test_url_only_with_real_path_succeeds():
    db, ext = _setup_module_db()
    real = _real_test_file_under_ai()
    status, body = _call(ext.handle_artifact_register, {
        "id": "MV-PYTEST-URLONLY-PATH",
        "storage_mode": "url_only",
        "media_type": "text",
        "local_asset_path": real,
    })
    assert status == 200, body
    r = _row(db, "MV-PYTEST-URLONLY-PATH")
    assert r is not None
    assert r["local_asset_path"] is not None
    assert os.path.samefile(r["local_asset_path"], real)


def test_vaulted_with_null_path_rejects():
    db, ext = _setup_module_db()
    status, body = _call(ext.handle_artifact_register, {
        "id": "MV-PYTEST-VAULTED-NULL",
        "storage_mode": "vaulted",
        "media_type": "photo",
    })
    assert 400 <= status < 500, body
    assert body.get("ok") is False
    assert "local_asset_path" in str(body)
    assert _row(db, "MV-PYTEST-VAULTED-NULL") is None


def test_url_only_with_bogus_path_rejects():
    db, ext = _setup_module_db()
    bogus = os.path.join(ROOT, "does", "not", "exist", "nope.txt")
    status, body = _call(ext.handle_artifact_register, {
        "id": "MV-PYTEST-URLONLY-BOGUS",
        "storage_mode": "url_only",
        "media_type": "link",
        "local_asset_path": bogus,
    })
    assert 400 <= status < 500, body
    assert _row(db, "MV-PYTEST-URLONLY-BOGUS") is None


if __name__ == "__main__":
    sys.exit(main())
