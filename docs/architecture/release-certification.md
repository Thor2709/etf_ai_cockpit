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

The certification issue itself is excluded from the closure check, because it
can only become final after certification passes. Records with the `deferred`
status are accepted final states and appear as explicit lines in the accepted
limitations. The report stays blocked until a signed manifest matches the
current commit. Execution remains disabled.
