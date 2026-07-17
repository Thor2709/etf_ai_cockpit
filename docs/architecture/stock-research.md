# Stock research evidence

ISSUE-0092, ISSUE-0093 and ISSUE-0096 provide a local statement-derived Stock
Research workspace. Profitability, earnings quality, balance-sheet, solvency
and valuation outputs are transparent dictionaries carrying formulas, periods,
source IDs, coverage and confidence. Negative, missing and structurally
inapplicable values are separate states.

Valuation uses explicit scenario assumptions for relative measures, DCF,
reverse DCF and residual income. It exposes ranges and model disagreement
instead of a single fair-value claim. Special sectors are marked for adapters;
industrial distress evidence is contextual and is not a credit rating.

No remote provider, broker, order or action authority is introduced. All
outputs retain `execution_allowed=false`, and missing statement or market
inputs remain readable unavailable states in the `/stock-research` workspace.
