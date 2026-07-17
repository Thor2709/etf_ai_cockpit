# Transparent factor risk

`portfolio.factor_risk` provides a local-first, evidence-only factor model for
stocks, ETFs and portfolios. It consumes adjusted-price histories, current
allocation metadata, optional latest descriptors and optional issuer holdings.
It does not fetch paid factor data and does not create execution authority.

The versioned model (`factor_risk.v1`) exposes:

- market, size, value, momentum, quality, investment and low-volatility
  descriptors, with robust median/MAD winsorisation and standardisation;
- explicit industry, country and currency one-hot exposures from allocation
  metadata or weighted look-through holdings;
- iteratively reweighted cross-sectional return estimates with standard errors;
- PSD-repaired factor covariance, specific risk, equal-weight market-beta
  baseline and split-sample stability diagnostics;
- factor-return validation against a caller-supplied public series without
  treating that series as a proprietary or authoritative replacement;
- coverage, rank constraints, unavailable descriptors and look-through
  reconciliation as visible report fields.

The Risk workspace displays the model status, selected/excluded factors,
historical factor-return rows, portfolio factor/specific variance shares and
local CSV exports. Missing descriptors remain unavailable rather than being
silently imputed. Every report sets `execution_allowed=false`.
