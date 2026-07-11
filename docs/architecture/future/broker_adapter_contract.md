# Future-only / no-authority

This is a future design record only. It describes review questions for a
possible adapter; it is not a broker integration, does not contain credentials
or endpoints, and provides no runnable order example.

## Boundary of a future adapter

A separately authorised adapter could translate a human-approved, versioned
intent into a provider-specific request. The adapter would be isolated from
signals, models, UI state and credentials. It would accept only an immutable
intent identifier, an approved account scope, an instrument identifier and a
bounded quantity representation. It would return an auditable provider
reference and a normalised status without changing the source proposal.

The interface would reject missing approval, stale evidence, unknown
instruments, policy breaches, duplicate intent identifiers and any request
outside the declared account scope. It would never infer approval from a
forecast, commentary, UI action or model output.

## Review obligations (future)

The adapter would need independent security review, secret-isolation tests,
rate and timeout controls, idempotency and replay tests, a failure-state
recovery plan and a complete audit manifest. Provider-specific details would
remain in a separately governed package. The current package intentionally has
no adapter, credential store or authority hand-off.
