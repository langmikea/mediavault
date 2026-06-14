# COVERAGE PROOF — MediaVault Taxonomy v1

**What this proves:** every one of the 47 live `unsorted:*` values is mapped exactly once to a v1
destination, with 0 missing and 0 duplicates, plus the destination namespace tally.

**How it was generated:** an actual run of `tools/coverage_check.py` against the live database
`core/mediavault.sqlite` (read-only). The script parses `docs/taxonomy/NORMALIZATION_MAP.md` and diffs
it against the DB. The output below is pasted verbatim.

**Command:**

```
python3 tools/coverage_check.py core/mediavault.sqlite
```

**Verbatim output (exit code 0):**

```
MediaVault taxonomy v1 — coverage check
================================================
DB path           : core/mediavault.sqlite
Map path          : docs/taxonomy/NORMALIZATION_MAP.md
Live unsorted:*    : 47
Mapped values      : 47
Mapped exactly once: yes
Missing (unmapped) : 0
Phantom (not in DB): 0
------------------------------------------------
Namespace tally (destinations):
  attributes   36
  event        8
  lineup       2
  type         1
------------------------------------------------
RESULT: PASS  (47 values, all mapped exactly once, 0 missing, 0 dupes)
```

**Equivalent run via `$MEDIAVAULT_DB` (identical PASS, exit code 0):**

```
MEDIAVAULT_DB=core/mediavault.sqlite python3 tools/coverage_check.py
```

## Summary

| Check | Result |
|---|---|
| Live `unsorted:*` values | 47 |
| Mapped values | 47 |
| Mapped exactly once | yes |
| Missing (unmapped) | 0 |
| Phantom (mapped but not in DB) | 0 |
| Namespace tally | `event` 8, `lineup` 2, `type` 1, `attributes` 36 |
| **Result** | **PASS** |

Re-run any time with `python3 tools/coverage_check.py core/mediavault.sqlite` (or set `MEDIAVAULT_DB`).
