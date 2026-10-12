# #809 ETF decision safe-point handoff

## Implemented

- Canonical tracking difference is annualized arithmetic active return: `252 * mean(fund return - benchmark return)`. Tracking error remains `sqrt(252) * sample_std(active return)`.
- ETF decision composition requires `ETF_EXPOSURE_PEERS` support by default. Callers may explicitly opt into fallback with `strict_exposure_peers=False`.
- Synthetic tests exercise canonical TD/TE, strict peer failure, #707 look-through producer consumption, and missing look-through fail-closed behavior.

## Defaults and limitations

- The annualization period is 252 business-daily observations per year; tracking-error standard deviation uses `ddof=1`, matching the existing canonical implementation.
- Missing peer or look-through evidence remains unavailable. Execution stays disabled.
- The current look-through producer supplies valuation/quality and categorical factor exposure; this decision graph consumes valuation/quality evidence. Broader factor scoring remains limited by #707 producer coverage and the configured DA-001 metrics.
- This is a synthetic machinery safe point. Real-data acceptance, #811 rank validation, and owner promotion remain outside this handoff.

## Documentation follow-up

The existing decision-architecture overview still describes compounded TD and should be synchronized before treating that overview as current.
