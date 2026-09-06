# SEC companyfacts workflow boundary

The existing per-CIK `AppState.fetch_sec_companyfacts` entrypoint is
local-first: it first inspects a previously validated SEC nightly companyfacts
bulk artifact through the provider session retained by an explicit refresh,
without constructing a new provider or requiring a user agent. A cold AppState
cannot rehydrate acquisition proof from disk and reports that cache unavailable.
When the cache is missing or invalid, it reports the reason and uses the historical
per-CIK JSON path only when the caller supplied a valid SEC user agent. A
genuinely absent identity binding permits this JSON/manual-first-run fallback;
known malformed, conflicted or ambiguous registry evidence blocks both routes
before cache access or provider construction, even without a supplied ID.

Cache reads use that retained provider's `fetch_companyfacts_bulk(cache_only=True)`
boundary. The provider must belong to the selected cache root. Explicit refresh
retains its provider before acquisition, allowing interrupted same-session
retries to resume; a changed cache root or contact identity creates a new
session. No sidecar or metadata reconstructs acquisition proof. Existing
root/reparse, metadata, hash, ZIP and session-ledger checks remain enforced.

`AppState.import_sec_companyfacts_bulk` is the explicit local ZIP entrypoint.
It accepts one selected `CanonicalIdentity` (or a unique persisted CIK mapping),
imports only that CIK member, and publishes through the existing atomic
statement facts/inventory writer. Local ZIP provenance is marked
`sec_local_import`/`manual_review`; it is never silently promoted to official
authority. `AppState.fetch_sec_companyfacts_bulk` is the explicit network
refresh entrypoint and requires a configured name and contact email.

Relevant persisted identity rows are validated in both directions before
archive access or provider construction. Conflicting CIKs for an instrument,
ambiguous instruments for a CIK, null/empty identities, malformed relevant
CIKs and non-canonical supplied instrument strings are rejected. A genuinely
absent binding still permits an explicit local manual-review identity or the
per-CIK JSON fallback with its unresolved/manual-review identity. Bulk network
refresh requires a unique persisted binding.

Acquisition documents retain the actual provider HTTP status and timestamp,
including resumed 206 and revalidated 304. Passing those documents through the
public local importer does not grant official authority: canonical bulk facts
and inventory remain `sec_local_import`/`manual_review` with their local capture
time, also for caller-authored RawDocument inputs. Explicit refresh and
same-session cache selection instead call `SecEdgarProvider.import_companyfacts_bulk`,
which verifies its exact in-memory generation inside the private importer seam.
Those canonical facts and inventory retain official authority and the acquired
URL/time, including original time through 304 revalidation. AppState never
upgrades a fetched document through the public local importer. The newer
immutable single-JSON capture and provenance path is preserved.

Bulk cache misses do not trigger large downloads automatically. All durable
imports and explicit refreshes accept the caller publication guard, preserve
partial parser warnings and checkpoint failures as visible statuses, and keep
`execution_allowed=false`. The JSON picker/UI remains a separate JSON-only
path; this workflow does not claim UI integration or whole-issue completion.

Cache success reports its original acquisition timestamp, age and unverified
freshness; there is no invented expiry policy or automatic bulk refresh.
Result messages retain completion/coverage and checkpoint details, display a
bounded sample of warning codes plus omitted counts, and are capped at2,048
characters. Complete structured warnings remain in the existing import result
and, where publication succeeded, its checkpoint. Controlled error causes are
redacted and bounded; real HTTP429 errors retain their quota/rate-limit meaning.
An acquisition failure distinguishes unchanged canonical stores from raw
cache/partials that may have been retained. Once statement import has started,
an unexpected error does not claim that all state is unchanged.
