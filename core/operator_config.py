"""Operator-tunable policy settings.

Edit these once; the engine picks them up on next run. Future C-bucket
policy items (C5 auto-release, etc.) extend this module.

Convention: ALL_CAPS module-level constants. Each setting includes a
comment naming the audit-brief item it implements, the default rationale,
and the cost/effect of flipping the value.
"""


# ─────────────────────────────────────────────────────────────────────────────
# C3 — HEIC transcoding policy (audit brief §5.2 C3, locked 2026-05-23)
# ─────────────────────────────────────────────────────────────────────────────
# When True, the ingest engine produces a JPEG primary at
# `catalogs/_assets/<artifact_id>.jpg` for every HEIC/HEIF artifact at
# process() time (after the operator approves the queue row and the
# artifact gets its MV-id). The HEIC original is preserved untouched.
#
# Default: False (operator-locked 2026-05-23 Option A — "conservative;
# matches current workflow"). The 19 iOS personal HEICs in intake/drop/
# are unlikely to be museum-bound; transcoding all of them by default
# would waste disk. Flip to True when actively publishing HEIC artifacts.
#
# Cost when True: ~equivalent to HEIC size per artifact (HEIC + JPEG
# stored side-by-side). For a 4 MB iPhone HEIC → ~2 MB JPEG primary,
# total disk ≈ 6 MB per artifact.
#
# Cost when False (current): museum can't render HEIC directly; operator
# must hand-convert HEIC → JPEG via Pillow/Photos.app/etc. before
# publishing. The brief notes Phase B's "operator pre-cropped and
# re-saved as PNG/JPEG before MV ingest" as the historical workflow.
TRANSCODE_HEIC_AT_INGEST = False

# JPEG output quality for HEIC→JPEG transcoding. Locked at 85 to match
# the thumbnail spec per SPEC.md §7. Don't drift without operator approval.
HEIC_JPEG_QUALITY = 85
