# Release certification and readiness

`ISSUE-0152` owns the finite completion-programme certification contract. The
initial implementation is intentionally evidence-only and fail-closed. It
does not infer release readiness from source-file presence, does not transmit
orders and does not make network calls.

Run the local report with:

```text
python scripts/check_release_certification.py --root . --report-dir artifacts/release_certification/issue-0152
```

The command always writes Markdown and JSON reports, includes duration and
failure details, and returns non-zero while mandatory evidence is blocked.
The `/release-readiness` page shows the same local report, legal-terms status,
registry checksum and accepted limitations.

The current report is blocked for evidence-based reasons: the canonical
programme still contains unresolved records, `ISSUE-0149` remains
`hardening_required` pending professional legal and repository-licence review,
the current candidate has no signed ISSUE-0152 release manifest, and the
pre-certification full-suite baseline has recorded limitations. These are
tracked blockers, not certification exemptions. Execution remains disabled.
