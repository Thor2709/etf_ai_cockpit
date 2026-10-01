# Analysis depth scheduling

Profile depth runs reserve each job's full plan estimates for CPU, memory, and disk before the scheduler claims it. The durable scheduler checks those aggregate reservations atomically, so the plan's worker limit and caller's `max_jobs` request set upper bounds while available resources and scheduler concurrency determine how many jobs can run together. Low-resource runs use one worker and a shard size of one. Legacy bulk runs continue to execute one job at a time with scheduler default resources.

For each content-addressed stage cache key, publication replaces a corrupt entry, reuses a valid entry with the same output hash, and raises `AnalysisDepthError` when a valid entry has a different hash, which signals a determinism violation. Successful optional stages that return `None` publish and reuse a hashed omission through the same path, so concurrent omission and value results for one key are treated as a determinism violation.

The shared stage cache is guarded while entries are read and published. Concurrent results for the same content key must have the same content hash. Timing-store writes are serialized within the process so concurrent jobs do not overwrite one another's records.

Cancellation is checked at stage boundaries. The active stage is recorded with outcome `cancelled`, later stage runners do not run, and the scheduler keeps the job terminal in its cancelled state. Outputs from earlier completed stages remain cached. A later `start()` creates a new run over the same inputs and can reuse those outputs; cancelling a run does not make it claimable again. Crash and lease-expiry resume retain the scheduler's existing behavior.

When profiled stage execution raises an `AnalysisDepthError`, the exception carries timing records for every completed stage and the failing stage. The failing stage's records use outcome `failed`, including a cache determinism conflict discovered after its runner completed. Bulk jobs append these records once before the scheduler records the failure.

Mandatory results are expected to match across serial and concurrent execution and when low-resource sharding is used. A plan marked `blocked` fails before job submission with its compatibility reason.
