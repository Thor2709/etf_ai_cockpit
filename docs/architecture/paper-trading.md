# Local paper trading

ISSUE-0031 provides a local-only paper account for recording the result of
manually accepted proposal decisions. It is a simulation and evidence store;
it is not a broker adapter and every view and event carries
`execution_allowed=false`.

## Ledger contract

The account is stored as an append-only JSONL event chain under
`data/operations/paper/ledger.jsonl`. Each event contains a schema version,
sequence, prior-event hash and event hash. Reads replay the complete chain
from the opening event, so a malformed row, checksum failure, conflicting
proposal decision or invalid corporate action fails closed as a blocked
reconciliation rather than producing a partial account.

The local file lock serialises critical sections across application instances.
Fill identifiers and corporate-action identifiers are idempotency keys. A
retry can therefore be safely replayed, while a changed acceptance term or a
contradictory rejection is rejected.

The ledger records long-only orders, partial fills, cancellations, fees and
FX, realised and unrealised PnL, open positions, win rate, payoff ratio,
benchmark return, and drawdown. Marks must be adjusted-close observations and
persist source authority and checksum. Corporate actions persist the same
provenance and adjust split quantities, cost basis, marks and dividends.

## Application and UI boundary

`LocalApplicationApi` exposes typed account, proposal, order, fill,
cancellation, adjusted-close mark and corporate-action actions. The
Operations Centre presents those actions with readable failure states. No
action creates a broker order, accesses credentials, uploads data or enables
live execution. Instrument Detail reads ledger fills through the application
UI facade, preserving the presentation boundary.

The later broker, automatic execution, cloud synchronisation and complete
experiment framework remain out of scope for this slice.
