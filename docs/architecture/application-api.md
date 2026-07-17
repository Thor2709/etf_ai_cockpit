# Local application API

This document is generated from `etf_cockpit.application.contracts` (`application_api.v1`). The first transport is local in-process; no HTTP listener or cloud service is enabled.

## Query resources

`QueryRequest.resource` supports `universe`, `instruments`, `scores`, `forecasts`, `portfolios`, `jobs`, `paper` and `operations`. Each query returns an immutable `PageView` with `total`, `offset`, `limit` and `next_offset`.

## Commands

`RefreshDataCommand`, `SubmitWorkflowCommand` and `CancelWorkflowCommand` require an idempotency key. Commands may include an expected revision; stale revisions return `conflict` and never run. Repeating the same key and payload returns `replayed` without running the handler again.

## Boundary rules

- Query adapters expose serialisable view models and never return pandas frames or domain objects.
- Pages use the in-process API; durable job state remains in the existing local scheduler.
- No command grants broker or execution authority; `execution_allowed` remains `false`.
- The JSON schema beside this document is the contract artefact for a second local frontend.
