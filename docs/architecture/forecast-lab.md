# Forecast Lab initial slice

The Forecast Lab (`/forecasts`) is a local, read-only evidence workspace for
`ISSUE-0027`. It reads existing forecast artefacts and adjusted-close prices;
it does not train models, download weights, alter score authority or submit
orders.

The first slice exposes:

- run and model summaries, including unavailable and pending rows;
- matured-outcome metrics (MAE, MASE, directional accuracy and interval
  coverage);
- deterministic expanding walk-forward date splits for evaluation;
- prior-residual conformal interval diagnostics once the minimum number of
  matured observations exists;
- a simple distribution-shift drift signal and explicit resource metadata
  availability.

Rows after the selected as-of date are excluded. Actual outcomes are used only
for retrospective evaluation after the forecast date, and input prices must
be adjusted-close prices. TimesFM and Toto remain optional, shadow-only
challengers. `execution_allowed=false` and `promotion_state=shadow_only` are
fixed boundaries in this slice.

Training-centre persistence, immutable experiment/model registries, feature and
target contracts, full nested/purged validation, multiple-testing control,
production drift governance and champion promotion belong to later issues.
