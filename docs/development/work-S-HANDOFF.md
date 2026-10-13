ROOT CAUSE: Fund-only evidence was required for every configured instrument; absent evidence forced non-fund confidence to zero.
SCOPE RULE: structure_cap_scope(config) exempts enabled stock/equity_certificate entries; cap 1.0 with not_applicable provenance and existing version fields. All other/missing types retain fund behavior.
CONSUMERS CHANGED: Structural loader, signal service, snapshot builder, backtest engine, derived cache validator, yfinance analysis script.
CONSUMERS PENDING: BacktestService must pass its config to _cached_structure_columns_match; its file is outside the packet write set.
TESTS: All 8 new regressions pass; 2 existing yfinance/cache compatibility regressions pass.
TESTS: Required suite collected 171 cases; 6 failures on its first run: one subsequently fixed test fixture, four expected golden comparisons, one newly exposed explanation rounding mismatch.
GOLDENS REGENERATED: see GOLDENS line.
OWNER-COPY RESULT: run_signals.py exited 0; 81 instruments; actions hold=81; 57 nonzero confidence.
OWNER-COPY RESULT: blocked_by forecast_confidence_below_threshold=23, insufficient_history=4, forecast_uncertainty_unavailable=1.
OWNER-COPY RESULT: Configured types stock=31, equity_certificate=28, etf=21, certificate=1; all 59 non-funds have cap 1.0; all 81 signals keep execution_allowed=false.
RESOLVED (Opus): backtest_service passes config=self.config to the cache check; explanation confidence uses the published rounding.
GOLDENS: snapshot + backtest regenerated; only non-fund structure cap 0->1, confidence and reason text changed; no action labels changed.
