# #809 ETF decision safe-point handoff

## Implemented

- Tracking difference is unchanged: compounded fund total return minus index total return over the period (existing `etf_economics` contract). Tracking error remains `sqrt(252) * sample_std(active return)`.
- Strict mode drops out-of-group peers (and all peers when the target has no group) before support counting and ranking, for both vehicle and exposure paths.
- ETF decision composition requires `ETF_EXPOSURE_PEERS` support by default. Callers may explicitly opt into fallback with `strict_exposure_peers=False`.
- Synthetic tests exercise canonical TD/TE, strict peer failure, #707 look-through producer consumption, and missing look-through fail-closed behavior.

## Defaults and limitations

- Tracking-error annualization is 252 business-daily observations per year; its standard deviation uses `ddof=1`, matching the existing canonical implementation.
- Missing peer or look-through evidence remains unavailable. Execution stays disabled.
- The current look-through producer supplies valuation/quality and categorical factor exposure; this decision graph consumes valuation/quality evidence. Broader factor scoring remains limited by #707 producer coverage and the configured DA-001 metrics.
- This is a synthetic machinery safe point. Real-data acceptance, #811 rank validation, and owner promotion remain outside this handoff.
