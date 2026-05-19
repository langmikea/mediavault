"""
tools/check_single_tag_writer.py
================================

§4.5.1(b) verification: the single coordinated writer rule for
``artifacts.tags`` (DATA_ARCHITECTURE_SPEC_v2.1-target.md §4.5 / §4.5.1).

Greps the MV codebase for any SQL that writes ``artifacts.tags`` outside
the one permitted location, ``core/artifact_tags.py``. The patterns are:

    UPDATE artifacts ... tags = ...
    INSERT INTO artifacts(... tags ...) VALUES (...)

Exit code:
    0  no violations — single-writer rule holds
    1  one or more violations — §4.5 broken; the build is NOT done

Usage:
    python tools/check_single_tag_writer.py            # scan MV root
    python tools/check_single_tag_writer.py --paths X  # scan custom paths

Add to CI / pre-commit to prevent regression.

Implementation note — TOKEN-AWARE for Python:
    The naive "grep multi-line regex over the whole file" approach
    false-positives on Python code that builds SQL dynamically with
    f-strings (e.g. UPDATE artifacts SET <dynamic columns> WHERE id=?
    where the inserted column list happens not to contain tags=?).
    Because Python has no SQL-statement terminator like ; to bound the
    regex, a lazy multi-line match would drift past the dynamic SQL
    into a later mention of tags.

    For .py files we therefore use tokenize to extract STRING tokens
    and run the patterns inside each literal independently. A
    violation must satisfy: the literal must contain both
    "UPDATE artifacts" (or "INSERT INTO artifacts(...)") AND a
    tag-write inside the same literal.

    For non-Python files (.sql, .mjs, .js, .html) we fall back to a
    looser whole-file regex, which is adequate for those formats.

Deliberate blind spots — written down so they aren't ambiguous:

  ``_cowork/`` — NOT a blanket exclusion. Operator one-shot scripts
      land here, and §4.5's spirit (every artifacts.tags write goes
      through write_artifact_tags) applies to them too. Five named
      historical scripts are allowlisted by exact path because they
      already ran against the current DB and pre-date this rule:
        - _cowork/v05_phase1_migration.py
        - _cowork/v05_phase2_vocab.py
        - _cowork/v08_phase_v5_6_seed_reverend.py
        - _cowork/v09_phase_v5_6_recanonicalize_reverend.py
        - _cowork/v11_cleanup_legacy_tag_patterns.py
      Any other .py file in _cowork/ that writes artifacts.tags will
      fail this check. Future migrations must route through
      write_artifact_tags() so validation + cache refresh stay
      consistent with runtime writes — the check now enforces that,
      not merely recommends it.

  ``debug_scripts/`` — currently README-only; the directory exists
      for ad-hoc operator scratch and contains no source code today.
      If executable .py files land here, revisit this exclusion.

  ``ext/``, ``ui/`` — frontend assets; no SQL.

  ``catalogs/``, ``thumbnails/``, ``intake/``, ``core/backups/`` —
      asset/data directories, no source code.

  ``core/artifact_tags.py`` and this script itself — the permitted
      writer and the check, by definition.
"""
from __future__ import annotations

import argparse
import io
import re
import sys
import tokenize
from pathlib import Path
from typing import Iterable


UPDATE_RE = re.compile(
    r"UPDATE\s+artifacts\b[^;]*?\btags\s*=",
    re.IGNORECASE | re.DOTALL,
)
INSERT_RE = re.compile(
    r"INSERT\s+(?:OR\s+\w+\s+)?INTO\s+artifacts\s*\([^)]*?\btags\b[^)]*?\)",
    re.IGNORECASE | re.DOTALL,
)


PERMITTED_RELATIVE = Path("core/artifact_tags.py")
SELF_RELATIVE = Path("tools/check_single_tag_writer.py")
# Historical _cowork/ migration scripts that write artifacts.tags directly.
# Each already ran against the live DB; the current state reflects them.
# Allowlisted by exact relative path so the §4.5.1(b) check passes against
# the live tree while still failing any NEW _cowork/ file that bypasses
# write_artifact_tags(). See "Deliberate blind spots" in the docstring.
COWORK_ALLOWLIST = frozenset({
    Path("_cowork/v05_phase1_migration.py"),
    Path("_cowork/v05_phase2_vocab.py"),
    Path("_cowork/v08_phase_v5_6_seed_reverend.py"),
    Path("_cowork/v09_phase_v5_6_recanonicalize_reverend.py"),
    Path("_cowork/v11_cleanup_legacy_tag_patterns.py"),
})

# See "Deliberate blind spots" in the module docstring for the rationale
# behind each entry. Note _cowork/ is NOT in this set — it is scanned
# like anywhere else; only the five files in COWORK_ALLOWLIST above are
# excused, by exact path.
SKIP_DIRS = {
    ".git",
    "core/backups",     # DB backups
    "core/__pycache__",
    "catalogs",         # vaulted asset bytes
    "thumbnails",       # rendered thumbnails
    "intake",           # raw inbox files
    "debug_scripts",    # ad-hoc operator scratch; see docstring
    "node_modules",
    ".venv",
    "venv",
    "ext",              # frontend JS, no SQL
    "ui",               # frontend assets, no SQL
}

SKIP_NAME_RE = re.compile(
    r"(?:\.bak(?:_|\.|$)|\.old(?:_|\.|$)|\.pre_|\.sqlite(?:$|\.))",
    re.IGNORECASE,
)

SCAN_EXTS = {".py", ".html", ".sql", ".mjs", ".js", ".ts"}


def is_excluded(path: Path, root: Path) -> bool:
    try:
        rel = path.relative_to(root)
    except ValueError:
        return True
    rel_str = str(rel).replace("\\", "/")
    if rel == PERMITTED_RELATIVE:
        return True
    if rel == SELF_RELATIVE:
        return True
    if rel in COWORK_ALLOWLIST:
        return True
    parts = rel_str.split("/")
    for skip in SKIP_DIRS:
        skip_parts = skip.split("/")
        if parts[: len(skip_parts)] == skip_parts:
            return True
    if SKIP_NAME_RE.search(path.name):
        return True
    return False


_TRIPLE_DQ = chr(34) * 3
_TRIPLE_SQ = chr(39) * 3


def _iter_python_strings(text: str) -> Iterable:
    """Yield (line_no, literal_body) for every STRING token in *text*.
    Falls back to a single whole-file window if tokenize chokes."""
    try:
        tokens = list(tokenize.tokenize(io.BytesIO(text.encode("utf-8")).readline))
    except (tokenize.TokenizeError, IndentationError, SyntaxError):
        yield (1, text)
        return
    for tok in tokens:
        if tok.type == tokenize.STRING:
            raw = tok.string
            i = 0
            while i < len(raw) and raw[i] in "rRbBuUfF":
                i += 1
            triple = raw[i:i + 3]
            if triple == _TRIPLE_DQ or triple == _TRIPLE_SQ:
                quote = triple
            else:
                quote = raw[i:i + 1]
            if not quote:
                continue
            body = raw[i + len(quote):]
            if body.endswith(quote):
                body = body[: -len(quote)]
            yield (tok.start[0], body)


def _line_no_for_offset(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def scan_python_file(path: Path):
    text = path.read_text(encoding="utf-8", errors="replace")
    hits = []
    for line_no, literal in _iter_python_strings(text):
        for name, regex in (("UPDATE", UPDATE_RE), ("INSERT", INSERT_RE)):
            m = regex.search(literal)
            if m:
                snippet = re.sub(r"\s+", " ", m.group(0)).strip()
                if len(snippet) > 160:
                    snippet = snippet[:157] + "..."
                hits.append((name, line_no, snippet))
    return hits


def scan_text_file(path: Path):
    text = path.read_text(encoding="utf-8", errors="replace")
    hits = []
    for name, regex in (("UPDATE", UPDATE_RE), ("INSERT", INSERT_RE)):
        for m in regex.finditer(text):
            line_no = _line_no_for_offset(text, m.start())
            snippet = re.sub(r"\s+", " ", m.group(0)).strip()
            if len(snippet) > 160:
                snippet = snippet[:157] + "..."
            hits.append((name, line_no, snippet))
    return hits


def scan_file(path: Path):
    try:
        if path.suffix.lower() == ".py":
            return scan_python_file(path)
        return scan_text_file(path)
    except Exception as e:
        print(f"warning: could not scan {path}: {e}", file=sys.stderr)
        return []


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument(
        "--root", type=Path,
        default=Path(__file__).resolve().parent.parent,
        help="Repo root to scan (default: this script's parent's parent).",
    )
    parser.add_argument(
        "--paths", nargs="*", type=Path, default=None,
        help="Optional explicit paths to scan instead of walking the root.",
    )
    parser.add_argument(
        "--quiet", "-q", action="store_true",
        help="Suppress per-file 'scanned' output; only report violations.",
    )
    args = parser.parse_args(argv)

    root: Path = args.root.resolve()
    if args.paths:
        candidates = []
        for p in args.paths:
            p = p.resolve()
            if p.is_dir():
                candidates.extend(p.rglob("*"))
            elif p.is_file():
                candidates.append(p)
    else:
        candidates = list(root.rglob("*"))

    files = [
        p for p in candidates
        if p.is_file()
        and p.suffix.lower() in SCAN_EXTS
        and not is_excluded(p, root)
    ]
    files.sort()

    violations = []
    for f in files:
        for name, line_no, snippet in scan_file(f):
            violations.append((f, name, line_no, snippet))

    if not args.quiet:
        print("§4.5.1(b) single-writer check")
        print(f"  root:                {root}")
        print(f"  permitted writer:    {PERMITTED_RELATIVE}")
        print(f"  files scanned:       {len(files)}")
        print(f"  violations found:    {len(violations)}")
        print()

    if violations:
        print("VIOLATIONS — second writer of artifacts.tags detected:")
        print()
        for path, kind, line_no, snippet in violations:
            try:
                rel = path.relative_to(root)
            except ValueError:
                rel = path
            print(f"  {rel}:{line_no}  [{kind}]  {snippet}")
        print()
        print("§4.5 forbids any tag-write outside core/artifact_tags.py.")
        print("Route every artifacts.tags write through")
        print("  write_artifact_tags(conn, artifact_id, new_tags)")
        return 1

    if not args.quiet:
        print("OK — single coordinated writer for artifacts.tags holds.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
