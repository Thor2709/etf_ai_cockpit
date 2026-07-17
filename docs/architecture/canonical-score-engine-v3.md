# Canonical score engine v3

The v3 score engine is the single calculation graph for score, signal, audit,
backtest and advisory review surfaces. It is deliberately local-first and
does not create broker or execution authority.

## Contract

Each component records its raw metric, score role, peer group, source identity
and authority, freshness, uncertainty, conflict status and explanation. A
component with missing data, blocked freshness, a source conflict or an
invalid source is excluded from its weighted group. The resulting coverage
and evidence-confidence values fall accordingly; missing data is never
silently treated as a neutral score.

The three policy groups are kept separate:

- attractiveness: evidence of instrument appeal;
- expected return: baseline and optional model forecasts;
- risk/implementation: risk, liquidity and allocation implementation quality.

Every group reports a score on a 0-10 scale, while the contribution rows use
the same normalised calculation graph and reconcile to the group output. The
legacy composite is retained only as an explicitly named migration field for
old action and export consumers.

## Versioning and provenance

`configs/score_engine_v3.yaml` is the policy source for ETF and STOCK rows.
Its LF-normalised SHA-256 is the formula checksum, so a checkout has the same
formula identity on Windows and Unix. Each score also carries a deterministic
source-vintage hash. Where a bitemporal source hash is available it is retained
on the component; compatibility adapters use a deterministic source and
decision-time fingerprint until every upstream source is bitemporal.

`data/derived/score_formula_registry.json` records both policies, the formula
version and a content-addressed registry signature. It is marked immutable
after a score run and is copied into audit packets. The audit packet checksum
manifests provide the durable run-level integrity boundary.

## Consumer path

Signal generation attaches `CanonicalScore` to `SignalResult`; scoreboards,
instrument detail, exports, portfolio review/proposal compatibility rows and
backtest signal logs consume that same object. Explanations are taken from
the component rows rather than reconstructed by each UI or report. Risk gates
and non-executable authority boundaries remain downstream controls; v3 does
not add broker automation.
