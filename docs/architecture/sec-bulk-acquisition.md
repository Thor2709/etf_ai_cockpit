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
an exact `Content-Range`; mismatches fail closed without splicing. A valid
shorter range remains a resumable prefix: publication requires the complete
resource length, even when the prefix itself happens to be a valid ZIP.
Supported interrupted reads use the configured bounded retry allowance and
retain only exception bytes within the declared response span. A `200`
response safely restarts from byte zero, including when a server ignores or
does not support ranges. Resumed artifacts preserve honest HTTP 206 provenance.
The local submissions importer admits official 206 and 304 provenance only
inside the concrete provider's fused acquisition-to-import call. A bounded,
provider-owned in-memory session ledger binds the status-bearing document to
the retained immutable artifact; public paths, RawDocument values, sidecars,
and manifests never recreate that proof and are downgraded or rejected as
local/manual evidence. There is no generic capability-upgrade API.

Successful in-memory `RawDocument` values retain the exact URL, aware acquisition time,
full SHA-256, provider `sec_edgar`, dataset document type, `application/zip`
media type, and actual HTTP status. A `304` revalidation reuses the prior
artifact hash and acquisition timestamp rather than inventing a new time.
Both ordinary responses and HTTP-error304 responses retain their effective
URL for the same exact-endpoint check; redirected responses are not admitted.
Cache-only selection is explicit, reads immutable objects without waiting on a
live download, and reports unavailable when no strictly validated artifact
exists or when the same-session ledger proof is absent; sidecars alone cannot
authorize an offline replay. When the ledger is cold, validators and Range are
omitted. An unexpected 304 receives one unconditional full request; another
304, 206, or error fails closed. Same-session revalidation retains the proved
original acquisition time and HTTP 200/206 identity with a separate in-memory
304 lineage, so repeated revalidation and cache-only replay retain the original
proof. Session verification hashes artifacts in bounded 1 MiB reads. Partial
state is generation-bound (dataset, exact URL, size, strong
validator, byte count, and prefix hash), so a changed or tampered prefix cannot
be spliced into a later response. Each successfully published checkpoint binds
its exact byte count, total size, validator and prefix hash in process; writable
sidecars cannot redefine that state on explicit retries or automatic retries. Network reads happen outside publication
authorization; each durable chunk/checkpoint and final promotion is guarded,
fsynced, and cancellation-aware. No provider probe, background action, upload,
broker write, or live execution is enabled; `execution_allowed` remains false
at downstream boundaries.

The explicit per-dataset local resource policy is:

| Dataset | Archive bytes | Members | Central-directory bytes |
| --- | ---: | ---: | ---: |
| Companyfacts | 8 GiB | 50,000 | 32 MiB |
| Submissions | 8 GiB | 1,000,000 | 256 MiB |

Companyfacts uses the existing canonical local importer's 8 GiB archive ceiling;
submissions has separate directory/member headroom. These are bounded product
resource policies, not measurements or guarantees about today's archives.
Declared over-limit downloads fail before streaming; local cache/imports stay
available. The submissions member ceiling has headroom over
the 780,000+ submissions-member shape reported in this [SEC EDGAR issue
comment](https://github.com/sec-edgar/sec-edgar/issues/257#issuecomment-1004777593);
current nightly live sizes are not asserted. Complete and partial sidecar reads
are capped at 64 KiB before JSON parsing, with malformed/deeply nested data failing
closed; oversized partials are rejected before hashing.

EOCD selection uses the APPNOTE-bounded comment window and explicit EOCD,
ZIP64 locator, and ZIP64 record structures; it does not depend on private
`zipfile` helpers. The selected adjacent records and actual central-directory
record count/byte spans are checked with fixed-size reads before `ZipFile` may
allocate its bounded member table. The compatibility regressions cover
ordinary EOCD, ZIP64 without sentinels, inconsistent declarations, and
preallocation limits across supported Python runtimes.
Validation covers structure, names,
encryption, links, sizes, and compression ratios; member CRCs are not claimed
until a downstream consumer reads the selected member.

The SEC access references are the official [EDGAR API documentation](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
and [EDGAR data access guidance](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data).
This component is an acquisition stage only and does not claim whole-issue
completion, parser integration, UI integration, or network-download workflow
completion.
