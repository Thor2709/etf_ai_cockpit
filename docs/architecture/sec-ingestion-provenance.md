# SEC ingestion provenance boundary

`AppState.fetch_sec_companyfacts` passes the provider's complete `RawDocument`
to `import_sec_companyfacts`. The supplied document's path, source URL,
retrieval timestamp, checksum, provider, document type, media type and HTTP
status are validated and passed through to the statement writer for both a
fresh `200` response and a cache revalidation `304` response. The current
inventory contract persists the path, source URL, retrieval timestamp as
`ingested_at`, checksum, document type, document identity and existing source
authority/fact metadata; provider and HTTP status are not new inventory
columns.

The import seam keeps existing `Path` callers compatible. A Path-only import
continues to create the historical local URL/timestamp source record and its
existing `sec_edgar`-based source-authority behavior. This boundary does not
add manual-import authority protection. A supplied provider document must
instead be a valid SEC companyfacts document whose path resolves to the parsed
file, whose lowercase SHA-256 matches the bytes and parser result, whose source
URL matches the requested CIK, and whose retrieval time is timezone-aware. Any
mismatch is rejected before the atomic facts and inventory publication,
leaving prior evidence unchanged.

This boundary does not add network behavior, provider write authority, or
execution authority. SEC acquisition remains explicit and
`execution_allowed=false` remains unchanged.
