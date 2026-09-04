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

The acceptance-time column is optional for older SEC columnar history files.
When it is absent, rows are retained with unavailable acceptance/availability
and a `missing_acceptance_timestamp` warning. The top-level issuer CIK binds
recent rows; advertised CIK-bound history filenames bind historical files. Any
issuer CIK explicitly present in a supplied history or row must also match the
requested canonical issuer. Mismatched or mixed explicit identity data is
warned and excluded rather than being stamped with the requested CIK. Accession
prefixes are not treated as issuer identity because legitimate Section 16
filings use a reporting owner's CIK. SEC display names likewise remain
descriptive rather than identity authority because legal-name variants can
differ from the canonical instrument name.

SEC `filings.files` advertisements are treated as explicit boundaries. A
historical columnar file is read only when the caller supplies a path under its
exact advertised CIK-bound filename. Unadvertised or unsafe names fail closed;
advertised files that are absent, malformed, have invalid/skipped rows, or do
not contain their well-typed declared `filingCount` produce an explicit
incomplete-coverage warning. The parser never fetches history or performs
network access, and it does not infer amendment supersession.
