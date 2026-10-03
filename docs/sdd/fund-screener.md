# Ordinary-fund screener

The fund screener builds advisory total, sector, country, and country-by-sector top-N views from sealed slice-A analysis records, slice-B peer cohorts, and slice-C return distributions and recommendation projections. It does not calculate or revise those source results, and every output has `execution_allowed=False`.

Call `build_fund_screener` with a sequence of `FundScreenerInput` values. Each value joins one `FundPeerFund`, its `FundReturnDistribution`, its `FundRecommendationProjection`, and its `FundPeerCohort`. The analysis record, distribution, and recommendation projection must identify the same share class and decision time. A missing peer cohort remains explicit and prevents the fund from receiving a rank.

By default, the view ranks one slot per `economic_strategy_id`. It applies the slice-B representative rule: earliest known inception, then share-class ID; when inception evidence is incomplete, it applies the existing share-class-ID fallback. Other classes remain attached through their recommendation projections. `allow_multiple_classes` opts into separate class slots.

The country bucket uses the resolved `legal_domicile` field. Sector uses resolved `sector`. Missing, low-confidence, future-dated, or ambiguous classification excludes a fund from the affected view and records a reason; total ranking can remain available. No country or sector is inferred from another classification field.

Eligible calibrated distributions rank before research-only distributions. The score combines within-tier midrank percentiles for total return, the available forecast quantiles and calibrated probabilities, fee (lower is better), and the slice-B peer percentile. Each of these four components has a configurable weight. Unavailable or blocked analysis, unavailable distributions, missing fees, missing peer ranks, or missing score inputs are excluded with funnel reasons.

The strict `screener` section in `configs/fund_analysis_v1.yaml` sets `top_n`, `allow_multiple_classes`, `bootstrap_samples`, `ranking_seed`, and the four `score_weights`. Defaults are top 10, one economic slot, 500 peer bootstrap samples, seed 157, and equal component weights. Peer-rank stability uses the fixed-income bootstrap helper with the configured sample count and seed.
