# SEC companyfacts bulk import boundary

`import_sec_companyfacts_bulk` consumes an explicitly supplied local SEC
`companyfacts.zip`. It selects only exact `CIK{10-digit-cik}.json` members
requested by `CanonicalIdentity`, parses each member with the existing
companyfacts parser, and publishes facts and inventory through the canonical
statement writer. There is no network access, broker action, background work,
or change to `execution_allowed` (the result is always false).

Archive and member lineage is retained in the isolated
`sec_companyfacts_bulk` cache. The archive is content-addressed; selected
members are streamed to hash-checked files below the full archive hash.
Member names, duplicate entries, traversal/absolute names, links, encryption,
sizes, compression ratios, compressed archive bytes, selected-member bytes
(256 MiB each; 512 MiB selected aggregate), and path/link boundaries are
validated before parsing. The parent acquisition container validator checks
EOCD/ZIP64 declarations and actual bounded central-directory spans before
`ZipFile` can allocate its member table. Unselected members are never extracted and their
uncompressed sizes are not treated as an extraction claim.
Requested CIKs are processed independently, so missing, malformed, or failed
members are disclosed per CIK and do not erase previously published evidence.

Each successful CIK is checkpointed only after its facts and inventory writes
complete. A resume revalidates current request authority/provenance, member
bytes/checksum, resolved destinations, parser name/version, identity, and
complete expected persisted fact records and inventory identity/count/source
IDs/authority/time/path/checksum/type. Stale, corrupt, or changed evidence is
reimported. Checkpoint read-modify-write is guarded and merges the complete
current checkpoint, retaining unrelated CIKs and concurrent updates.
The two persisted stores are read together under the canonical writer guards;
inventory matching includes the provider-specific document identity. Individual
facts and inventory writers, paired evidence publication, and the trust-refresh
inventory append hold the same persistent destination sidecars across their
complete read/merge/write operation. Multi-store acquisition deduplicates
resolved paths and uses a stable case-insensitive order; guards are released
on all exits, including cancellation. Under those sidecars, the existing
atomic-group recovery API resolves pending transactions before any store read
or merge. Its native guards release before publication; no recovery protocol
is added. Checkpoint reads release the non-reentrant statement guards before
invoking a writer.
Persisted acquisition time must match the checkpoint time;
local resumes do not substitute the new invocation's clock. Inventory execution
authority must be explicitly false. Fact authority selections are revalidated
using the canonical writer's existing selection functions over the retained
store, including later filings that legitimately supersede imported facts.

Before storing the archive, the importer checks the unresolved cache namespace
and the cache's exact staging, content-object, manifest and invalidation paths
for pre-existing symlinks/reparse points. This is a local filesystem boundary,
not protection against a privileged actor replacing paths during an import.

Checkpoint entries retain warning records and coverage (`complete` or
`partial`) alongside archive/member hashes and paths. A successful
facts/inventory publication whose checkpoint write fails is reported as
published-but-pending, not as a failed publication. Parser warnings are
returned and replayed on resume; warning-bearing imports are partial coverage.

Public `RawDocument` provenance is a caller-authored description, never proof
of official acquisition. Valid descriptions are checked for consistency but
cannot upgrade authority or supply the retained acquisition time. Imports
remain explicitly local (`file://` member URL, aware local capture timestamp,
`sec_local_import` source IDs and `manual_review` facts/inventory). Resume
retains the original proved local capture timestamp. Invalid descriptions
fail closed. A provider-fused official companyfacts import remains a later
integration gap; sidecars and checkpoint metadata cannot construct that proof.

Cancellation raises the existing `WorkflowTransitionError` at cache, member,
statement publication, and checkpoint boundaries; it cannot authorize a
later durable stage. Other parse or publication failures remain explicit
per-CIK failures, and checkpoints are not written for them. This component
does not establish network-download resumption, application/UI integration,
or whole-issue completion.
