# Pair-trading and cointegration: research-only scope (ISSUE-0061)

Status: bounded research specification. This document does not add a pair-trading
algorithm, score, signal, portfolio decision, paper-trading path, or execution
authority.

The cockpit's supported product is long-only stock and ETF research. Pair trading
normally needs a long leg and a short leg, so `pair_trading` stays
`research_only` with `authority=none`, `score_authority=false`,
`paper_authority=false`, and `execution_authority=none`. The `shorting` strategy
remains rejected by the canonical strategy scope. A pair-research result must
therefore never be interpreted as a recommendation or an order instruction.

## Required research protocol

Any future experiment must record a versioned, point-in-time universe and pair
selection snapshot. The candidate universe, listing/share class, currency,
corporate-action-adjusted observations, and all filters must be as-of the
research timestamp. Pair selection may not use later prices, later membership,
survivorship-filtered constituents, or a later regime label.

For each selected pair, the research record must include:

- **Cointegration and stationarity:** specify the model form, deterministic terms,
  estimation window, unit-root/cointegration test, lag rule, critical values,
  p-values and confidence interpretation. Test the residual spread rather than
  treating a high price correlation as cointegration. Report the spread's
  mean-reversion estimate and half-life only as descriptive evidence.
- **Break and regime controls:** test stability across rolling windows and
  predeclared market, volatility and liquidity regimes. A failed stability test,
  structural break, stationarity break, drifting hedge ratio, non-stationary residual or stale data
  must produce an explicit rejection/abstention state; it must not be silently
  carried forward.
- **Borrow and shorting evidence:** record whether the short leg is borrowable,
  the as-of timestamp, locate/recall constraints, borrow availability, borrow
  rate/fee, financing and any hard-to-borrow assumptions. Missing borrow evidence
  is a blocker, not a zero cost. In this product the presence of borrow evidence
  does not grant shorting authority.
- **Execution costs:** model both legs' spread, commissions/fees, market impact,
  latency, slippage, financing and borrow costs. State whether costs are gross or
  net, use point-in-time assumptions, and stress them. A gross spread without a
  net-of-cost result is not evidence of an implementable relationship.
- **Multiple testing:** predeclare the universe, pair-selection rule, windows,
  thresholds and stopping rule. Count all attempted, failed and discarded pairs
  and parameter variants. Apply a family-level multiplicity correction or other
  declared false-discovery control, and retain an untouched time-ordered
  evaluation period. Choosing the most stable-looking pair after inspecting all
  outcomes is selection leakage.

## System Map and rejection boundary

The System Map presents this topic under **Research-only strategy boundaries**
with the `pair_trading` scope row. It must show `research_only`, authority
`none`, `score_authority=false`, `paper_authority=false`, and
`execution_authority=none`, together with the stationarity, borrow, cost,
regime-break and multiple-testing requirements.

The following transitions are rejected by policy and tests:

1. pair research becoming a default score component or changing a current action;
2. pair research producing a trade signal, portfolio rebalance, paper position,
   order preview or broker call;
3. a short leg being treated as supported merely because a borrow quote exists;
4. a pair selected with future membership/prices or a broken/stale spread being
   treated as valid; and
5. a reported gross edge being promoted without explicit costs and multiplicity
   evidence.

No implementation is implied here. If a later, separately approved research
program is created, it must add its own data contract, audit record, validation
evidence and authority review without changing the default long-only lane.
