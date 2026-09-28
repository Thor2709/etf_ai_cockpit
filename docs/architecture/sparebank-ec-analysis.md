# Native Sparebank EC analysis

The `sparebank-analysis-suite.v1` contract is the single entry point for a
Norwegian savings-bank equity certificate (EC). Its pure calculation layer
receives already-selected, point-in-time evidence; it does not read files or
perform pandas operations. The application adapter selects the persisted
`ec_facts.json` revision whose `known_at` is no later than the decision time.

Routing is fail-closed and requires all three independent facts: Norwegian
jurisdiction, savings-bank legal form, and an EC instrument/capital class.
Issuer names and the `analysis_tier` universe grouping are not routing
signals. Ordinary shares of a savings bank therefore remain on the ordinary
stock path.

`ECClaimState` retains effective and knowledge time, source/revision identity,
owner-side pools (`ec_capital`, `overkursfond`, `utjevningsfond`), self-owned
pools (`sparebankens_fond`, `gavefond`, `kompensasjonsfond`), reported and
reconstructed eierbrøk, separate registered/outstanding/treasury/period-end and
weighted-average EC counts, owner-attributable book and earnings, foundation
holdings, voting evidence, per-field provenance, coverage and claim status.
The reconstructed claim is `owner pools / (owner pools + self-owned pools)`;
accounting equity is never used as the denominator. Foundation ECs remain
outstanding and are not treasury or private-holder wealth.

Owner book per EC uses the period-end count. Owner EPS uses the weighted-average
count. Missing facts remain unavailable and lower coverage. If a routed claim
is not `resolved`, generic bank/stock valuation is explicitly inapplicable
with a reason code. `valuation` and `scorecard` remain explicit `UNAVAILABLE`
placeholders until their respective issues add them.

## Bank economics and structural events

SPBK-002 adds the pure `bank_economics` interpretation layer. It consumes the
financial-sector adapter's already projected metrics and keeps reported versus
normalised earnings, credit stock/flow, capital headroom, and funding evidence
separate. Missing evidence remains `UNAVAILABLE`; no regulatory ratio or
deposit beta is inferred. The normalisation bridge records each adjustment's
mechanism, evidence locator, persistence assumption, and tax treatment.

SPBK-003 adds the pure structural-event ledger. Conversion, primary and
secondary issues, rights, buybacks, mergers, and §10-19 deficit coverage retain
pre/post claim states and recipient cash flows. Merger value split, exchange
ratio, EC-class ownership, and eierbrøk remain four distinct fields. Agreement,
legal completion, technical integration, and economic maturity are independent
milestones; legal completion does not imply maturity. All outputs remain
`execution_allowed=false`.
