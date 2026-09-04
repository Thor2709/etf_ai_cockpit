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
partial coverage and durable warnings. The durable manifest stores a complete
snapshot bundle: parser identity, canonical CIK/instrument identity, retained
object paths and SHA-256 values, source URL, timezone-aware acquisition time,
provider, document type, media, HTTP status, records, warnings, filing/history
maps, coverage status, and a bundle digest. Changed history or filing bytes
therefore create a new generation while retaining the old content-addressed
object; restart revalidates every retained object and replays the parser before
reporting verified evidence. Fabricated metadata, stale pointers, and objects
outside the immutable object layout are rejected without replacement.

Official `RawDocument` provenance is admitted only when its path, checksum,
timezone-aware timestamp, provider, exact SEC URL, document type, media type,
and integer HTTP status are consistent with a process-bound capability minted
by the SEC provider and its immutable payload. Caller-created metadata,
sidecars, or manifests cannot construct or rehydrate that capability and are
downgraded to `sec_local_import` manual evidence; matching fields alone never
establish official authority. ZIP members may derive authority only from an
admitted bulk capability. Filing URLs are bound to the
selected company CIK, accession directory, and primary document; a third-party
accession prefix is permitted. Local inputs are marked `sec_local_import` and
remain manual-review evidence, with HTML retained as `text/html` (other
unsupported local filing formats use an explicit binary media type). ZIP selection validates
the central directory before allocation, then bounds each selected member to
256 MiB and the selected aggregate to 512 MiB; the archive itself is bounded to
8 GiB. Detached history files receive their own capture timestamp and
per-input availability bound; they never inherit the parent snapshot time.
Missing or malformed `filings.files` coverage, history or filing bytes, and
parser row warnings remain
`partial`, never `complete`. Cancellation or publication failure propagates
through the caller's publication scope and does not replace the prior import
manifest. Every result keeps `execution_allowed=false` and this component never
creates canonical financial facts or starts scoring/execution.
