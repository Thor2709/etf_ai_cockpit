# Local screener boundary

ISSUE-0020's initial usable slice screens only evidence already present in the
local application snapshot. The application layer composes configured
instruments, canonical fundamentals and signal metadata into a deterministic
table. Query evaluation is pure: it does not refresh providers, run models,
change scores or create broker instructions.

Filters are typed as exact categorical matches or inclusive numeric bounds.
Missing filtered fields fail closed; missing sort fields are reported and left
unsorted. Numeric sort fields place missing and non-numeric evidence last.
Factor percentiles are calculated only across locally available values.

Saved screens contain the query and reproducibility lineage, not copied market
evidence. Revisions are immutable numbered JSON records under `data/screens`,
written atomically and checked for record and query tampering when loaded. CSV
exports under `exports/` include the query checksum, as-of date, universe
revision, formula version and `execution_allowed=false`; text cells that could
be interpreted as spreadsheet formulae are neutralised.

The `/screener` page is a thin presentation adapter over these application
contracts. Sector adapters, provider refresh, peer-universe construction,
portfolio optimisation, backtest certification and broker execution remain
outside this slice. Their unavailable states are explicit rather than inferred.
