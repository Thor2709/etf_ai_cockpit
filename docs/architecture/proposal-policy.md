# Proposal policy and authority boundary

ISSUE-0130 turns an immutable optimiser and portfolio snapshot into a local
review decision. The policy requires explicit optimiser output, portfolio and
data revisions plus every required freshness, confidence, event, liquidity,
cost, concentration and account-authority gate. A headline score or a manual
UI quantity cannot satisfy those inputs.

Each decision records deterministic input and complete-decision checksums,
proposal policy version,
authority-matrix checksum, gate-policy version/checksum, gate table, rationale,
quantity delta, `as_of`, expiry and the alternatives
`no_trade`, `defer`, `reduce` and `manual_review`. Replaying identical inputs
reproduces the same decision ID; changing an immutable input creates a new
decision.

The effective authority stage is the lowest of strategy, model and account
stages. Only `shadow_proposal` and `paper` can produce a proposal-ready review;
research, disabled and future draft/live stages remain blocked or manual
review. Every result has `execution_allowed=false`. Persistence is local JSON
evidence under `data/operations/proposals/`; records are append-only,
content-addressed and rejected on checksum, authority-policy or gate-policy
mismatch. It is not an order ledger or paper broker.

Full paper broker/ledger and forward evidence remain ISSUE-0129 scope;
accounting and cost foundations remain ISSUE-0127/0128 scope; broker
reconciliation and live execution remain disabled later issues.
