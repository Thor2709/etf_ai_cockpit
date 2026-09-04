# SEC submissions and raw-filing import

`import_sec_submissions` is an explicit, local-only ingestion boundary. It
accepts one `CanonicalIdentity`, validates the CIK and optional persisted
bidirectional identity registry, and parses either a submissions JSON snapshot
with explicitly named history files or a ZIP containing the selected CIK
member. No network request or provider construction occurs in this service.

The parser's filing rows remain available as structured `SubmissionRecord`
values, including amendment accessions, availability timestamps, source hashes,
and unrecognised raw-row fields. Metadata is not treated as a filing document.
Actual filing bytes must be supplied explicitly by accession; each supplied
snapshot, history file, and filing is retained through the existing
content-addressed cache. Missing advertised history or filing bytes produce
partial coverage and durable warnings. Changed snapshots append a new manifest
generation while retaining prior raw generations; restart revalidates retained
object paths and hashes before reporting verified evidence.

Official `RawDocument` provenance is admitted only when its path, checksum,
timezone-aware timestamp, provider, exact SEC URL, document type, media type,
and HTTP status are consistent. Local inputs are marked `sec_local_import` and
remain manual-review evidence. Cancellation or publication failure propagates
through the caller's publication scope and does not replace the prior import
manifest. Every result keeps `execution_allowed=false` and this component never
creates canonical financial facts or starts scoring/execution.
