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
with a reason code. Later sections (`bank_economics`, `events`, `valuation`,
and `scorecard`) are explicit `UNAVAILABLE` placeholders for subsequent SPBK
issues.
