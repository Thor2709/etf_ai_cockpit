# Durable local job scheduler

ISSUE-0077 adds a local-first scheduler for work that must survive a UI or
worker restart. `DurableJobScheduler` stores workflow records, typed job
specifications, dependency edges and an append-only hash-chained event stream
in `data/storage/cockpit.sqlite3`. SQLite WAL mode and the forward-only v4
storage migration keep the transactional state recoverable without a broker or
cloud service.

Each job records an input hash, bounded redacted inputs, resource declarations,
retry budget, lease owner and expiry, heartbeat, checkpoint, outputs, timing,
error fingerprint and terminal state. A worker claims only jobs whose
dependencies succeeded. Expired leases return to the queue within the retry
budget; exhausted jobs fail and all downstream queued jobs become blocked.

Submission uses a stable deduplication key. Repeated submissions return the
existing workflow, so a duplicate button press cannot create a second committed
output. Outputs are written to the durable record only on a successful terminal
transition; cancelled, failed and blocked jobs cannot publish output metadata.

`run_once` is intentionally a small worker seam. The application can place it
inside a bounded thread or process pool while checkpoints, heartbeats and
cancellation remain in the same store. The Jobs & Activity page exposes the
workflow graph, dependency state, retries, checkpoints, timing, recovery and
the event-chain result. The page's self-check demonstrates the complete
submission, claim and completion path without external services.

Event payloads are size-limited and pass through the existing redaction helper.
Each event includes the previous event hash and its own SHA-256 hash; malformed
or tampered history is visible as an invalid chain. The scheduler has no broker,
credential or order-transmission capability.
