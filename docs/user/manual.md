# ETF AI Evidence Cockpit — User Manual

**Version:** 1.0 (2026-09-04)
**Execution boundary:** `execution_allowed=false` (research and education only; no live trading or broker order execution).

## 1. What the cockpit does

The cockpit is a local-first workstation for ETF research, portfolio risk
assessment, model validation, and evidence-bounded review. It keeps source
lineage, observation dates, freshness, conflicts, assumptions, and unavailable
states visible. It does not upload data, silently invent values, or transmit
orders.

The in-app `/help` route is the authoritative user-facing explanation surface.
It contains searchable page-level guidance and the registry-backed glossary.
Each registered route is mapped to at least one guidance topic, including its
intended use and authority boundary.

## 2. Start and navigate

1. Open `/onboarding` to inspect local paths, sample data, and benchmark defaults.
2. Use `/signals`, `/screener`, `/comparison`, `/universe`, `/etf`, and
   `/instrument` to discover and inspect instruments.
3. Use `/portfolio`, `/portfolio-optimiser`, `/risk`, and `/stress-lab` for
   portfolio context and stress evidence.
4. Use `/data-models`, `/forecasts`, `/training-centre`, `/feature-catalogue`,
   and `/macro` for model and factor context.
5. Use `/backtests`, `/operations`, and `/forward-evidence` for simulations and
   paper evidence. These are not live execution paths.
6. Use `/evidence`, `/filings`, `/etf-disclosures`, `/news-context`, and
   `/providers` to inspect provenance and source status.
7. Use `/diagnostics`, `/errors`, `/import-export`, `/settings`, and
   `/release-readiness` for local health and recovery.
8. Use `/chatgpt`, `/decision-journal`, `/roadmap`, and `/help` for audit,
   human records, programme context, and explanations.

## 3. Scores and score components

Scores are normalised to a 0–10 scale. The displayed bands mean:

| Score | Meaning |
| --- | --- |
| 8-10 | Strong positive evidence |
| 6-7.9 | Positive or watchlist evidence |
| 4-5.9 | Mixed or hold evidence |
| 0-3.9 | Weak or negative evidence |
| N/A | Unavailable or inapplicable; not a zero |

The final score is a descriptive aggregation of eligible components; it is not
a forecast or instruction. Components are interpreted as follows:

- **Momentum:** recent multi-month price strength.
- **Trend:** medium- and long-horizon moving-average direction.
- **Relative strength:** comparison with the configured peer set.
- **Risk:** volatility and drawdown evidence.
- **Liquidity/cost:** whether spread, slippage, and commission could overwhelm
  the observed edge.
- **ETF exposure:** concentration and diversification from available holdings.
- **Stock value:** valuation evidence from available fundamentals.
- **Stock quality:** available quality evidence.
- **Analyst revision:** estimate/revision context, always low-authority.
- **Evidence confidence:** completeness, freshness, and integrity of the input
  evidence.
- **Expected return, attractiveness, risk/implementation, and portfolio fit:**
  separate derived context fields, not permissions.
- **Calibration and backtest trust:** model-validity evidence, not execution
  authority.

## 4. Authority levels, labels, and gates

Authority describes permitted use of evidence, never permission to trade.

- **Source/component authority:** high, medium, low, or unknown describes the
  reliability/provenance of an input. Official regulator or issuer evidence can
  be stronger than vendor, model, news, or manual context, subject to
  point-in-time, freshness, completeness, and conflict checks.
- **Research states:** `research_candidate`, `watchlist`, `hold_review`,
  `avoid`, `needs_evidence`, `manual_review`, and `not_scoreable` describe
  instrument review state. None is an order.
- **Portfolio-review states:** `not_applicable`, `maintain_review`,
  `increase_exposure_review`, `reduce_exposure_review`,
  `exit_thesis_review`, and `constraints_blocked` describe human portfolio
  context. None is an automated allocation.
- **Gate severities:** `blocker` stops the next transition;
  `authority_warning` is visible caution that may require manual review; and
  `notice` is non-blocking information. Warnings and notices never grant
  authority.
- **Capability authorities:** `context_only`, `evidence_only`,
  `research_state`, `portfolio_review`, `user_record`, and `none` describe an
  artifact's permitted scope. Lifecycle stages such as `research`,
  `shadow_proposal`, `paper`, `broker_read_only`, `draft_order`,
  `capped_automatic`, and `disabled` are vocabulary for governance review,
  not enabled features.

The effective execution authority remains `none`; the application invariant is
`execution_allowed=false`.

## 5. N/A, unavailable, and manual review

`N/A` means a value is unavailable or inapplicable: for example, a required
disclosure is missing, a source is stale or conflicted, or the observation
window is too short. `Unavailable`, `needs_evidence`, `manual_review`, and
`not_scoreable` are explicit fail-closed states. Zero is an observed numeric
value. Missing data is never silently zero-filled, imputed, or treated as a
passing score.

## 6. Methodology glossary

The `/help` glossary is loaded from `configs/glossary.yaml` and includes these
terms:

- **Alpha:** return relative to a selected benchmark over a stated period.
- **Beta:** sensitivity of returns to a benchmark.
- **Drawdown:** decline from a prior peak in a value series.
- **PBO:** probability of backtest overfitting.
- **Deflated Sharpe (DSR):** Sharpe evidence adjusted for multiple testing and
  non-normality.
- **MASE:** mean absolute scaled error for forecast evaluation.
- **Calibration:** agreement between predicted probabilities and observed
  outcomes.
- **Slippage:** difference between an assumed decision price and an observed
  fill proxy.
- **Edge-to-cost:** estimated gross edge divided by estimated friction.

These metrics provide context and quality checks. They do not override gates,
grant authority, or create an order.

## 7. Data, models, and audit evidence

Data and model adapters remain local-first and disabled-safe. Optional model
packages such as TimesFM or Toto do not change deterministic baseline behavior
when unavailable. Promotion requires walk-forward validation,
purging/embargo leakage controls, calibration evidence, and PBO review.

Backtests model assumptions such as transaction costs, liquidity, and slippage;
they do not guarantee fills. Audit exports retain source lineage and legal
notices. Consult `/help` for route-specific details and
[`documentation-strategy.md`](documentation-strategy.md) for the documentation
maintenance policy.
