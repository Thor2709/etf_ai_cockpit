# SEC submissions parser boundary

`parse_submissions` is a deterministic, read-only parser for the SEC
submissions JSON contract. It binds the top-level CIK to the supplied
`CanonicalIdentity` before emitting any records, validates every parallel
column length, and retains each valid row—including amendments and repeated or
conflicting accessions—as an independent `SubmissionRecord`.

Each record carries its canonical instrument/CIK, accession, form, filing and
report dates, primary document, amendment flag, source SHA-256, deterministic
source ID, and the complete raw row. `accepted_at` and `available_at` are
populated only when `acceptanceDateTime` parses as a timezone-aware timestamp;
missing or invalid values remain `None` with an explicit warning. Filing and
report dates are never used as availability timestamps.

SEC `filings.files` advertisements are treated as explicit boundaries. A
historical columnar file is read only when the caller supplies a path under its
exact advertised CIK-bound filename. Unadvertised or unsafe names fail closed;
advertised files that are absent, malformed, have invalid/skipped rows, or do
not contain their well-typed declared `filingCount` produce an explicit
incomplete-coverage warning. The parser never fetches history or performs
network access, and it does not infer amendment supersession.
