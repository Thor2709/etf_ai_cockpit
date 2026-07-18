# Portfolio rebalancing review

ISSUE-0114 adds a deterministic, local-only rebalance review to the existing
portfolio sandbox. It converts a current holdings snapshot and candidate target
weights into visible advisory alternatives; it does not create orders or grant
broker authority.

The domain planner in `portfolio/rebalancing.py` makes integer or fractional
lot policy, minimum trade value, cash and settlement buffers, restrictions,
cost assumptions and optional tax metadata explicit. It compares full, partial,
deferred and no-trade alternatives and reports post-change cash and a simple
tracking-drift proxy.

Tax values are informational only. Without explicit tax lots and a labelled
jurisdiction the report shows tax as unavailable. The `/portfolio` page calls
the planner through the application facade and renders the assumptions,
warnings, alternatives and proposed changes with `execution_allowed=false`.

Broker APIs, order transmission, live fills, tax advice and the full accounting
or cost-model foundations remain outside this initial slice.
