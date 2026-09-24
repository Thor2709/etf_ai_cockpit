# SEC ingestion provenance boundary

The SEC companyfacts import accepts a provider `RawDocument` only as an
in-memory result of the concrete provider acquisition call. A public `Path`,
sidecar, or caller-constructed `RawDocument` cannot establish SEC authority;
those inputs are retained as local/manual evidence after the usual path,
checksum, URL, timestamp, document-type, media-type and HTTP-status checks.
The provider's opaque session generation is process-local and cannot be reconstructed from
durable cache metadata.

Provider acquisition and import are one fused boundary. A fresh `200`, an
exact same-session cache replay, or a same-session `304` may carry official
provenance in the returned in-memory result. On a ledger miss, validators and
`Range` are omitted; an unexpected cold `304` gets one unconditional full-`200`
retry and then fails closed. Cache mutation, eviction, malformed metadata and
ambiguous redirects never manufacture authority. Durable records remain
local/manual and preserve `execution_allowed=false`.

For a supplied fetched document, the importer captures a validated,
content-addressed sibling before parsing and publishes from that capture, so
source-file mutation after validation cannot make the facts/inventory pair
refer to different bytes. Existing provider generations are content-addressed
and retained as local/manual evidence. A `304` is admitted only with the
provider's exact same-session ledger proof; missing, malformed or
timezone-naive timestamps fail closed without fabricating an acquisition time
or replacing prior evidence.

This boundary does not add network behavior, provider write authority, or
execution authority. SEC acquisition remains explicit and
`execution_allowed=false` remains unchanged.
