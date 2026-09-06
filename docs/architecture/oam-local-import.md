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
