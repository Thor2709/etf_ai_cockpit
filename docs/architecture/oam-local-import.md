# Local structured OAM imports

The national OAM adapters expose `OAMAdapter.discover_local` for a user-owned
JSON, CSV or XML export. This path is deliberately independent of the remote
endpoint: it does not consult `enabled`, call a transport, resolve links, or
perform network I/O. The selected regular file is bounded, copied to a
content-addressed snapshot, and only then parsed.

Rows imported this way are recorded with `source_authority=local_user_import`,
`manual_review=true`, `coverage_status=manual_review`, and
`execution_allowed=false`. An ISIN match is still labelled
`matched_isin_manual_review`; parsing bytes does not promote a local file to
official evidence. The immutable raw snapshot is retained before parsing;
discovery rows and coverage are published only after the complete structured
export and all declared links pass validation. Unsupported, malformed, HTML,
untrusted-link, changed-during-read, and oversized inputs return a controlled
rejection and do not replace the discovery registry.

`write_oam_discovery_registry` is an upsert keyed by content-addressed
`source_id`. A new jurisdiction therefore preserves existing evidence from
other jurisdictions, while re-importing the same source replaces only its own
rows. The complete registry read-modify-write is serialized with a persistent
sidecar guard so concurrent jurisdiction imports cannot silently erase one
another. Coverage and warnings remain explicit and are never used to enable
scoring, broker access, or execution.


Local source IDs include the complete structured row and snapshot hash, so
missing identifiers cannot collapse distinct issuers or documents. Companies
House rows also distinguish the effective company number. Exact duplicate rows
within the same content remain deduplicated.

Under the registry guard, reimporting an identical local row retains its earliest
stored observed `available_at`, including concurrent imports published out of
order. `retrieved_at` describes the selected import snapshot; caller-declared
historical availability remains only `claimed_available_at` and never supplies
the observed availability. Different snapshot content remains distinct evidence.

Local JSON record lists reject non-object members instead of silently dropping
malformed rows. All declared source, document and metadata links are validated
before query filtering, including links on unmatched rows. Companies House
local queries never supply missing source company numbers: company-number
constraints require an explicit matching row value, and issuer constraints
filter the source issuer name. ISIN constraints return no matches because this
adapter does not establish ISIN identity. Remote discovery behavior is unchanged.
