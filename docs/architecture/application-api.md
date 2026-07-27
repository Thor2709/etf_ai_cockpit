# Local application API

This document is generated from `etf_cockpit.application.contracts` (`application_api.v1`). The first transport is local in-process; no HTTP listener or cloud service is enabled.

## Query resources

`QueryRequest.resource` supports `universe`, `instruments`, `scores`, `forecasts`, `portfolios`, `jobs`, `paper`, `proposals` and `operations`. Each query returns an immutable `PageView` with `total`, `offset`, `limit` and `next_offset`. Proposal review creation uses the typed `ProposalReviewRequest` through the same local boundary and returns gate evidence with execution disabled. Paper account opening and proposal actions use typed local contracts backed by the append-only paper ledger.

## Commands

`RefreshDataCommand`, `SubmitWorkflowCommand` and `CancelWorkflowCommand` require an idempotency key. Commands may include an expected revision; stale revisions return `conflict` and never run. Repeating the same key and payload returns `replayed` without running the handler again.

## Boundary rules

- Query adapters expose serialisable view models and never return pandas frames or domain objects.
- Pages use the in-process API; durable job state remains in the existing local scheduler.
- No command grants broker or execution authority; `execution_allowed` remains `false`.
- Paper fills use explicit execution quotes; account marks require adjusted-close evidence and remain local simulation only.
- The JSON schema beside this document is the contract artefact for a second local frontend.
## Fixed-income contractual terms

`LocalApplicationApi.get_fixed_income_terms` and
`application.ui_facade.load_fixed_income_terms_projection` expose the same
read-only `fixed-income-terms.v1` projection. The data layer alone validates
and generates supported contractual schedules; selectors and pages only render
terms, source/knowledge/retrieval lineage, overlay history, conflicts and
capability flags. Pricing, screening, proposals and execution remain false.
