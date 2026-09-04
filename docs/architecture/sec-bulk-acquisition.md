# SEC nightly bulk acquisition boundary

`SecEdgarProvider.fetch_companyfacts_bulk()` and
`fetch_submissions_bulk()` are explicit caller-invoked acquisitions of the
official SEC nightly archives:

- `https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip`
- `https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip`

The SEC documents public EDGAR API access and a declared organisation/contact
user agent; it does not promise byte-range support. This adapter therefore
streams bounded chunks, validates the ZIP central directory without extracting
the filer universe, and retains only immutable successful bytes plus bounded
metadata. A failed, truncated, malformed, quota-limited, or cancelled fetch
does not replace the last good artifact.

Partial bytes are retained in a confined SEC namespace for a later explicit
retry. A retry sends `Range` and `If-Range` only when a strong stable ETag and
an exact stored offset are available. A `206` must repeat that ETag and provide
an exact `Content-Range`; mismatches fail closed without splicing. A `200`
response safely restarts from byte zero, including when a server ignores or
does not support ranges. Resumed artifacts preserve honest HTTP 206 provenance;
the current canonical local ZIP importer accepts only validated HTTP 200
provenance, so resumed-document admission remains a later integration step.

Successful `RawDocument` values retain the exact URL, aware acquisition time,
full SHA-256, provider `sec_edgar`, dataset document type, `application/zip`
media type, and actual HTTP status. A `304` revalidation reuses the prior
artifact hash and acquisition timestamp rather than inventing a new time.
Cache-only selection is explicit, reads immutable objects without waiting on a
live download, and reports unavailable when no strictly validated artifact
exists. Partial state is generation-bound (dataset, exact URL, size, strong
validator, byte count, and prefix hash), so a changed or tampered prefix cannot
be spliced into a later response. Network reads happen outside publication
authorization; each durable chunk/checkpoint and final promotion is guarded,
fsynced, and cancellation-aware. No provider probe, background action, upload,
broker write, or live execution is enabled; `execution_allowed` remains false
at downstream boundaries.

The bounded policy currently permits at most 2 GiB of archive bytes, 1,000,000
members, and a 256 MiB central directory. The member ceiling has headroom over
the 780,000+ submissions-member shape reported in this [SEC EDGAR issue
comment](https://github.com/sec-edgar/sec-edgar/issues/257#issuecomment-1004777593);
current nightly live sizes are not asserted. EOCD/ZIP64 metadata is checked
before allocating the bounded member table. Validation covers structure, names,
encryption, links, sizes, and compression ratios; member CRCs are not claimed
until a downstream consumer reads the selected member.

The SEC access references are the official [EDGAR API documentation](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
and [EDGAR data access guidance](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data).
This component is an acquisition stage only and does not claim whole-issue
completion, parser integration, UI integration, or network-download workflow
completion.
