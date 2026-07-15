# UPDATEV2-0016 source gate

ETF holdings normalisation is implemented in `src/etf_cockpit/data/fund_holdings.py`, with completeness, freshness, confidence and invalid-weight states consumed by the Risk and ETF Disclosures pages. Weight validation blocks current exposure use when the sum is outside the approved bounds; partial top-holdings remain explicitly partial. Holdings are evidence-only and do not change model authority or enable execution. `execution_allowed` remains `false`.
