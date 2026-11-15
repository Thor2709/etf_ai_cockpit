# INT-21 — ETF look-through fundamentals roll-up

**Status: proposal only; not a canonical GitHub issue.**

- Priority: `P2`; gate `G3`; lane `A`; estimated size `medium`
- Logical prerequisites: `INT-03, INT-04`; source-file serialization: `-`
- Readiness: `READY`
- Intended files: `analysis/look_through.py; data/holdings_registry.py`
- Baseline: `Thor2709/etf_ai_cockpit@1afe17c09fb53299f7c46459254d94ce8323acd1`
- Authority: canonical issue admission must be reviewed by project root and generated via the repository's guarded control process.

## Proposed technical issue

ETF look-through fundamentals roll-up
- Gate G3 | Priority P2 | Size medium | Depends on: INT-03, INT-04 | Features: F0024, F0079
- Targets: `analysis/look_through.py` (`:675`, `:788-826`, coverage floor `:20`), `data/holdings_registry.py` (`:34`, `:137`), `data/ishares_holdings.py`.
- Rules: holdings carry `as_of` and `known_at`; each constituent metric is the vintage known at the holdings `known_at`; constituents are joined by issuer identity; coverage = weight of constituents with an available metric / weight of all equity holdings (cash and derivatives excluded, stated in the output); holdings older than the configured age are `stale`; a held fund is not expanded and counts as uncovered (`nested_fund_not_expanded`).
- Steps: roll up EBIT margin, revenue growth, net debt / EBITDA, dividend and shareholder yield, gross profitability and the Piotroski distribution; activate inactive issuer adapters one at a time when their file format is confirmed.
- Acceptance: below the 0.80 coverage floor the roll-up is `unavailable`; a stale snapshot is flagged; a fund-of-funds reports the uncovered weight.

## Gate G4 - research, document and optional model extras
