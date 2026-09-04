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
Cache-only selection is explicit and reports unavailable when no validated
artifact exists. No provider probe, background action, upload, broker write,
or live execution is enabled; `execution_allowed` remains false at downstream
boundaries.

The SEC access references are the official [EDGAR API documentation](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
and [EDGAR data access guidance](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data).
This component is an acquisition stage only and does not claim whole-issue
completion, parser integration, UI integration, or network-download workflow
completion.
