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
with a reason code. `scorecard` remains an explicit `UNAVAILABLE` placeholder;
the owner valuation section is populated only when the claim is resolved.

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
`execution_allowed=false`. Merger increments are calculated from supplied
benefit, loss, tax, ramp, allocation, legacy-count and discount inputs; fixture
path labels are never interpreted as economics. Events with missing or invalid
`known_at` are excluded from a decision-time view.

## Owner valuation and implementation

SPBK-004 adds the pure `valuation` layer. Owner book and EPS retain the
period-end and weighted-average EC count conventions from the claim contract;
mixing denominators raises an error. Stable P/B, clean-surplus dividend and
residual-income routes, reverse-implied expectations, capital release and
buyback accretion are calculated only from explicit inputs. Scenario weights,
required returns, hurdle rates and exit costs are operator-supplied; absent
assumptions produce an unavailable scenario section rather than invented
probabilities. The suite entry point also exposes explicit recovery, four-state
marketability, capital-policy, IRR, decision-price, timestamp/currency/quantity
and implementation sections; omitted assumptions remain unavailable. Displayed depth is walked for a quantity-specific order. If
depth is absent the result stays `UNAVAILABLE` and identifies the labelled
`execution-cost-v1` estimate fallback. No valuation output enables execution.
