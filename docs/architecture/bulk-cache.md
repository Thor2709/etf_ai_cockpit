# Bulk cache and safe promotion

`src/etf_cockpit/data/bulk_cache.py` keeps raw bulk sources immutable and
content-addressed under `data/raw/bulk_cache/`. A source can be resumed from a
retained `.part` file, but the object is not published until its size and
optional SHA-256 digest match the request. Repeated bytes reuse the existing
object; a changed digest creates a new manifest version and an invalidation
event for downstream consumers.

Network transport is opt-in: the default HTTP reader requires HTTPS and an
explicit host allow-list. Local files and test fixtures use the same publish
path without network calls. ZIP and TAR extraction rejects traversal, links,
member-count/expanded-size overflows and excessive compression ratios.

Parsers write validated bytes to a staged generation first. Only an explicit
`promote_generation` call atomically moves that generation into the published
directory. `scripts/check_bulk_cache.py` emits deterministic Markdown and JSON
health evidence and never fetches a provider.
