# ETF AI Cockpit user guide

The cockpit is a local research and evidence tool. It helps you inspect data,
compare instruments, review model evidence and record your own decisions. It
does not provide financial or tax advice. `execution_allowed=false`: this
release does not connect to a live brokerage account or transmit orders.

## Start with the evidence

Choose a workspace from navigation or the command palette. Start with the
instrument identity and data date, then check source, coverage, freshness and
warnings before reading a score. Import or refresh only data you are permitted
to use. The application keeps missing, stale, conflicted and unsupported data
visible; it does not invent observations or silently turn missing values into
zero.

Use the `Help & Glossary` panel on every page for a short explanation of that
workspace. The Help & Glossary page defines common metrics and authority
states. This guide covers the broader workflow and limitations.

## How to read scores

The canonical score engine keeps three 0–10 groups separate:

- **Attractiveness** summarises configured evidence about an instrument's
  appeal. Depending on the asset, components can include momentum, trend,
  relative strength, ETF exposure, stock value or stock quality.
- **Expected return** summarises the baseline and any available optional model
  forecast evidence for the configured horizon. It is distinct from a return
  forecast expressed in percent.
- **Risk/implementation** summarises risk, liquidity and cost, rebalance and
  concentration evidence. It does not mean that risk is absent.

The configured primary horizon is 1–3 months. The component table is the
explanation: it shows the measurement, role, source, peer context, freshness,
uncertainty and conflicts used for that group. The score policy is versioned;
check its formula version and the instrument's as-of date when comparing runs.
The groups are not one universal recommendation. A value from one group, asset
type, peer set or horizon is not automatically comparable with another.

When required inputs are missing, stale, conflicted or invalid, they are
excluded and coverage or evidence confidence falls. An absent ETF stock-value
component, for example, is not a stock-value score of zero. Read `N/A` as
unavailable or inapplicable, and read zero only as an observed numeric value.
If the page says `not scoreable`, the required evidence or policy is absent and
there is no authoritative score for that request. A risk gate, blocker or
manual-review state takes precedence over a positive score or model output.

Alpha and beta depend on their selected benchmark and period. Drawdown describes
the decline from a prior peak. PBO and the deflated Sharpe ratio are
overfitting and robustness diagnostics, not proof of future returns. MASE, MAE,
directional accuracy, calibration and interval coverage describe different
aspects of forecast error and uncertainty; compare them only with their stated
units, horizon, sample and baseline. Slippage and edge-to-cost use estimates or
fill proxies, so inspect the assumptions and source dates. The in-app glossary
contains concise definitions for these terms.

## Models and model cards

The deterministic baseline remains the core path. TimesFM, Toto and other
challengers are optional; missing packages or weights must remain unavailable
and must not change baseline behaviour. Forecast and training pages show the
task, run state, version and available evaluation evidence. Do not treat a
model as approved merely because it is installed or has a model card.

A full model card should identify the intended task and horizon, data and
features, version, validation method and results, uncertainty, limitations,
resource requirements and licence. The registered cards in `Forecast Lab` show
tasks, availability, licence, resource class and promotion state; optional
packages or weights that are unavailable are shown as `N/A`. `Data & Models`
shows loaded dataset provenance, while `Training Centre` shows local run and
approval evidence. If a card or field is absent, do not infer model approval or
capability. Future observations must not be used to judge a forecast before
its outcome horizon has matured. Model-generated commentary is advisory and
cannot override evidence gates or grant authority.

## ETF and sector-specific evidence

ETF views combine fund identity and available disclosure/holdings evidence
with adjusted prices, benchmark comparisons and liquidity or cost context.
Holdings are point-in-time evidence: check their date and coverage before using
look-through exposure. A partial or missing holdings file does not establish
that an exposure is absent.

ETF data adapters can provide only a subset of identity, price, disclosure and
holdings fields, depending on their implementation and source terms. Check the
adapter status and source details in Provider Status or the Data Catalogue.
Some optional adapters do not implement ETF metadata or holdings; those fields
remain unavailable instead of triggering an inferred value or silent refresh.

Stock research uses sector-aware routes where classification and source
evidence support them. Financial, real-asset, cyclical and innovation/healthcare
metrics can differ from industrial-company formulas. If classification is
uncertain, an adapter is unsupported or its required inputs are missing, the
page marks the result unavailable or inapplicable and shows the limitation.
Do not compare sector-specific metrics as though their formulas and peer groups
were identical. Adapter outputs remain evidence, not orders or execution
authority.

## Data sources and licences

Mandatory workflows use local user files or explicitly cached official
evidence. Optional providers and model packages are non-blocking. Provider
status, source identity, retrieval date, observation date and terms should be
visible before you rely on imported data. A capability or cache marked
unavailable does not silently trigger a remote request.

The local terms registry records cache, redistribution and audit-export
conditions. Restricted source documents remain local; an export may contain
their permitted metadata and provenance without the underlying text. Check the
source's terms before sharing an export. The registry currently requires
professional review for applicable terms and jurisdictions; it is a governance
record, not legal advice or permission to redistribute data.

## Authority, paper use and live capability

The authority labels describe guarded stages, not investment quality:

| Stage | What it means in this release |
| --- | --- |
| Research | Evidence and deterministic analysis for human review; enabled by default. |
| Shadow proposal | A frozen, non-executable proposal preview after research gates; disabled by default. |
| Paper | Local simulation and forward evidence; it is not a broker connection. |
| Broker read-only | Reserved for future read-only reconciliation; no credentials or broker access are present. |
| Draft order | A disabled contract reserved for a separately approved future capability. |
| Capped automatic | A disabled future stage requiring separate authority and release evidence. |
| Disabled | The capability is unavailable and cannot influence mandatory workflows. |

Local paper activity is a simulation. Review each proposal and paper state
manually; simulated fills, fees and prices are not actual brokerage outcomes.
Keep observation-only proposals separate from accepted paper activity. This
release has no live trading procedure: live accounts, credentials, order
submission and broker writes are disabled, and `execution_allowed=false`.

## Incidents and recovery

If a paper order state is unknown, contradictory or fails integrity checks,
stop further paper actions and preserve the ledger and incident records. Compare
the observed state with the local ledger and reconcile before retrying. Do not
speculatively retry an uncertain action, edit or truncate evidence, or clear a
freeze while a mismatch remains. Append a post-mortem after recovery. Follow
[`Incident runbooks`](../operations/INCIDENT_RUNBOOKS.md) for disconnect, order
break and integrity-failure steps.

For other errors, record the visible message and affected data date, then use
Diagnostics and Errors & Recovery to inspect the local state. Keep original
inputs and logs so a later review can distinguish a source problem from a
calculation or application failure.

## Reproducibility

For a result you may need to review later, retain the app version, instrument
identity, as-of date, source snapshot, score formula version, model/run version,
configuration and visible warnings. Use Import & Export to create the
appropriate local audit packet or table export, then retain its manifest and
checksums. Restricted source contents may be omitted from the packet while
permitted provenance remains.

Replaying a result requires the same input snapshot and policy versions.
Current provider availability, later source revisions, changed model weights
or different assumptions can produce a different result. Keep the original
packet unchanged; record a correction as a new review or run rather than
replacing old evidence.

## Documentation map

This guide and the in-app glossary are the user-facing explanations. The
canonical score methodology is documented in
[`Score engine v3`](../architecture/canonical-score-engine-v3.md); the local
paper ledger contract is in [`Paper trading`](../architecture/paper-trading.md).
The source/model terms registry and adapter contracts are governance and
developer references, not substitutes for the permissions attached to a data
source or model.
