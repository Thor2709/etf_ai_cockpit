# Sparebank book gap analysis (SB2, October 2026)

One row per numbered equation, scorecard-relevant rule and table in the owner's book (Norwegian equity certificates, 7 chapters). `Locator` is the code that implements the item, or `missing`. `Score impact` says which scorecard input the item feeds. `unavailable` items fail closed with a reason; none is estimated.

Totals: implemented 79, partial 59, missing 120, background 123 of 381 rows. Manifest: [sparebank-book-manifest.md](sparebank-book-manifest.md).

## Calibration facts from the book

- The book prints no numeric weights or anchors (p. 64): the scorecard uses equal weights and documented judgement anchors, recorded in `configs/sparebank_scorecard_v1.yaml` with book pages and versioned (`formula_version`).
- Deposit-to-loan is a quantity measure, not franchise quality (p. 48): kept as the weakest funding input.
- P/B is not the thesis (eq. 5.23, p. 107): shown, not scored.
- Capital allocation is deliberately non-doctrinal (5.8.1, p. 114): shown, weight 0.
- Illustrative COE 10% and growth 3% (p. 16, p. 111) are used only as labelled defaults.


## Chapter 1 equations

| Ref | Page | Item | Status | Locator | Limitation or reason | Score impact |
|---|---|---|---|---|---|---|
| eq. 1.1 | 2 | Accounting identity A=L+E | background | missing | Accounting identity; no product calculation is needed. | none |
| eq. 1.2 | 2 | Capital and funding to income chain | background | missing | Narrative chain, no numeric content. | none |
| eq. 1.3 | 3 | Profit chain P = NII+F+O-C-CL-T | implemented | `src/etf_cockpit/analysis/bank_metric_facts.py::_financial_metric_facts` |  | Statement lines feed every ratio below |
| eq. 1.4 | 4 | NII = interest income - interest expense | implemented | `src/etf_cockpit/analysis/bank_metric_facts.py::_financial_metric_facts` |  | Net interest income line is read from the primary statement |
| eq. 1.5 | 4 | Fee income by product | missing | missing | Product-level fees sit in note text blocks, not structured ESEF facts. | None today; cost/income uses total fees |
| eq. 1.6 | 4 | Net interest margin and rate sensitivity | implemented | `src/etf_cockpit/analysis/sparebank/book_calcs.py::net_interest_margin` |  | net_interest_margin; nii_sensitivity is display only |
| eq. 1.7 | 4 | Net interest margin and rate sensitivity | implemented | `src/etf_cockpit/analysis/sparebank/book_calcs.py::net_interest_margin` |  | net_interest_margin; nii_sensitivity is display only |
| eq. 1.8 | 5 | Structural vs cyclical earnings, rate transmission, off-balance lending, lagged risk | background | missing | Conceptual statements without a calculation. | none |
| eq. 1.9 | 6 | Structural vs cyclical earnings, rate transmission, off-balance lending, lagged risk | background | missing | Conceptual statements without a calculation. | none |
| eq. 1.10 | 6 | Structural vs cyclical earnings, rate transmission, off-balance lending, lagged risk | background | missing | Conceptual statements without a calculation. | none |
| eq. 1.11 | 7 | Structural vs cyclical earnings, rate transmission, off-balance lending, lagged risk | background | missing | Conceptual statements without a calculation. | none |
| eq. 1.12 | 7 | ECL = PD x LGD x EAD | background | missing | Loan-level PD, LGD and EAD are not published; documented non-goal. | none |
| eq. 1.13 | 8 | Problem exposure worked example | background | missing | Worked example only. | none |
| eq. 1.14 | 9 | Risk-adjusted lending spread | implemented | `src/etf_cockpit/analysis/sparebank/book_calcs.py::risk_adjusted_lending_spread` |  | risk_adjusted_margin_pct (scored, axis lending_economics) |
| eq. 1.15 | 9 | CET1 ratio = CET1 capital / RWA | implemented | `src/etf_cockpit/data/pillar3_queue.py::PILLAR3_METRICS` |  | Confirmed Pillar 3 CET1 ratio (headroom input) |
| eq. 1.16 | 10 | Leverage ratio | implemented | `src/etf_cockpit/data/pillar3_queue.py::PILLAR3_METRICS` |  | Confirmed Pillar 3 leverage ratio (display only) |
| eq. 1.17 | 10 | CET1 headroom = actual - required | implemented | `src/etf_cockpit/analysis/sparebank/book_calcs.py::cet1_headroom` |  | cet1_headroom_pp (scored) once actual and requirement are confirmed |
| eq. 1.18 | 12 | Ownership fraction (eierbrok) | implemented | `src/etf_cockpit/analysis/sparebank/claim.py::reconstruct_eierbrok` |  | Gate: claim must resolve; scales EC earnings and book |
| eq. 1.19 | 12 | Ownership fraction (eierbrok) | implemented | `src/etf_cockpit/analysis/sparebank/claim.py::reconstruct_eierbrok` |  | Gate: claim must resolve; scales EC earnings and book |
| eq. 1.20 | 13 | Economic ownership vs voting vs free float | background | missing | Distinction only. | none |
| eq. 1.21 | 14 | EC-attributable book equity | implemented | `src/etf_cockpit/analysis/sparebank/valuation.py::owner_valuation` |  | owner_book_per_ec, owner P/B |
| eq. 1.22 | 14 | Average EC-attributable equity | partial | `src/etf_cockpit/analysis/sparebank/valuation.py::owner_valuation` | Closing owner pool used; opening pool is not extractable from filings, limitation stated | Slightly overstates ROE in growth years |
| eq. 1.23 | 14 | P/E from P/B and ROE | implemented | `src/etf_cockpit/analysis/sparebank/book_calcs.py::price_to_earnings_from_pb` |  | owner_pe shown (display only) |
| eq. 1.24 | 15 | Justified P/B = (ROE-g)/(COE-g); ROE=COE gives P/B=1 | implemented | `src/etf_cockpit/analysis/sparebank/book_calcs.py::justified_price_to_book` |  | justified P/B and value per EC (expectations_gap input) |
| eq. 1.25 | 15 | Justified P/B = (ROE-g)/(COE-g); ROE=COE gives P/B=1 | implemented | `src/etf_cockpit/analysis/sparebank/book_calcs.py::justified_price_to_book` |  | justified P/B and value per EC (expectations_gap input) |
| eq. 1.26 | 16 | Implied ROE from P/B | implemented | `src/etf_cockpit/analysis/sparebank/book_calcs.py::implied_roe` |  | Reverse valuation (expectations_gap_pp, scored) |
| eq. 1.27 | 17 | Merger value-created decomposition | missing | missing | Merger synergy, integration cost and overpayment need deal terms not present in filings. | none (no merger inputs) |
| eq. 1.28 | 18 | EPS and BVPS accretion breakeven | missing | missing | Merger terms are not captured; buyback accretion is covered under 5.46-5.49. | none |
| eq. 1.29 | 18 | EPS and BVPS accretion breakeven | missing | missing | Merger terms are not captured; buyback accretion is covered under 5.46-5.49. | none |
| eq. 1.30 | 19 | Annual recurring after-tax synergy | missing | missing | Merger synergies are announcements, not structured data. | none |

## Chapter 2 equations

| Ref | Page | Item | Status | Locator | Limitation or reason | Score impact |
|---|---|---|---|---|---|---|
| eq. 2.1 | 23 | Buying a claim on an ownerless bank | background | missing | Framing question. | none |
| eq. 2.2 | 24 | Ownerless capital, retention, corporate forms | background | missing | Conceptual structure. | none |
| eq. 2.3 | 24 | Ownerless capital, retention, corporate forms | background | missing | Conceptual structure. | none |
| eq. 2.4 | 24 | Ownerless capital, retention, corporate forms | background | missing | Conceptual structure. | none |
| eq. 2.5 | 27 | EC capital is not EC count x nominal value | implemented | `src/etf_cockpit/analysis/sparebank/claim.py::build_claim_state` |  | Gate: owner pool built from capital, share premium and equalisation reserve |
| eq. 2.6 | 27 | Ownership fraction reconstruction and example | implemented | `src/etf_cockpit/analysis/sparebank/claim.py::reconstruct_eierbrok` |  | Same function as 1.18-1.19 |
| eq. 2.7 | 29 | Ownership fraction reconstruction and example | implemented | `src/etf_cockpit/analysis/sparebank/claim.py::reconstruct_eierbrok` |  | Same function as 1.18-1.19 |
| eq. 2.8 | 30 | Issuance, conversion, foundations, sell-down mechanics | background | missing | Event narratives; no continuous calculation. | none |
| eq. 2.9 | 30 | Issuance, conversion, foundations, sell-down mechanics | background | missing | Event narratives; no continuous calculation. | none |
| eq. 2.10 | 32 | Issuance, conversion, foundations, sell-down mechanics | background | missing | Event narratives; no continuous calculation. | none |
| eq. 2.11 | 32 | Issuance, conversion, foundations, sell-down mechanics | background | missing | Event narratives; no continuous calculation. | none |
| eq. 2.12 | 33 | Issuance, conversion, foundations, sell-down mechanics | background | missing | Event narratives; no continuous calculation. | none |
| eq. 2.13 | 33 | Issuance, conversion, foundations, sell-down mechanics | background | missing | Event narratives; no continuous calculation. | none |
| eq. 2.14 | 35 | Issuance, conversion, foundations, sell-down mechanics | background | missing | Event narratives; no continuous calculation. | none |
| eq. 2.15 | 35 | EC constituency governance share range 20-40% | missing | missing | Board and governance shares are not structured data. | none |
| eq. 2.16 | 36 | Governance gap = G_EC - e | missing | missing | Needs the EC constituency's governance share, which is not published as data. | none |
| eq. 2.17 | 36 | Control is multidimensional | background | missing | Conceptual. | none |
| eq. 2.18 | 37 | Control is multidimensional | background | missing | Conceptual. | none |
| eq. 2.19 | 38 | Free-float market value = P x N x free-float | missing | missing | Free-float percentage is not in the free sources used; turnover is used instead. | marketability uses turnover and days to trade |
| eq. 2.20 | 38 | Justified P/B (repeat of 1.24) | implemented | `src/etf_cockpit/analysis/sparebank/book_calcs.py::justified_price_to_book` |  | See 1.24 |
| eq. 2.21 | 40 | Evidence of a residual EC pricing effect | background | missing | Interpretation of academic evidence. | none |
| eq. 2.22 | 40 | Observed gap = fundamental + structural + residual | missing | missing | Needs a peer-justified P/B model; the peer table shows observed P/B only. | none |
| eq. 2.23 | 40 | Implied cost of equity from P/B | implemented | `src/etf_cockpit/analysis/sparebank/book_calcs.py::implied_cost_of_equity` |  | implied_k shown in reverse valuation |
| eq. 2.24 | 40 | Is 3 percentage points of extra COE justified | background | missing | Question, not a formula. | none |
| eq. 2.25 | 42 | Merger effect on P/B | background | missing | Conceptual. | none |

## Chapter 3 equations

| Ref | Page | Item | Status | Locator | Limitation or reason | Score impact |
|---|---|---|---|---|---|---|
| eq. 3.1 | 46 | ROE = profit / average common equity | partial | `src/etf_cockpit/analysis/sparebank/bank_economics.py::owner_normalisation` | Closing owner equity; average not available | Same limitation as 1.22 |
| eq. 3.2 | 46 | ROE = ROA x leverage (DuPont) | missing | missing | Decomposition is not displayed. | none |
| eq. 3.3 | 47 | ROA and RWA-based decomposition | missing | missing | Decomposition is not displayed. | none |
| eq. 3.4 | 47 | ROA and RWA-based decomposition | missing | missing | Decomposition is not displayed. | none |
| eq. 3.5 | 47 | Normalised common equity required to run the franchise | partial | `src/etf_cockpit/analysis/sparebank/book_calcs.py::roe_on_required_capital` | roe_on_required_capital exists; required capital needs confirmed requirement | none until Pillar 3 confirmed |
| eq. 3.6 | 47 | Gross funding advantage FD = D x (alternative - deposit cost) | partial | `src/etf_cockpit/analysis/sparebank/book_calcs.py::deposit_franchise_advantage` | Function exists; deposit cost is not tagged in ESEF | deposit franchise unavailable |
| eq. 3.7 | 47 | Net funding advantage after service, acquisition, liquidity costs | missing | missing | Service, acquisition and liquidity costs are not reported per deposit. | none |
| eq. 3.8 | 48 | Deposit pricing power, deposit growth vs franchise, average vs marginal | background | missing | Conceptual; marginal spread is implemented under 4.22. | none |
| eq. 3.9 | 48 | Deposit pricing power, deposit growth vs franchise, average vs marginal | background | missing | Conceptual; marginal spread is implemented under 4.22. | none |
| eq. 3.10 | 48 | Deposit pricing power, deposit growth vs franchise, average vs marginal | background | missing | Conceptual; marginal spread is implemented under 4.22. | none |
| eq. 3.11 | 49 | Deposit relationship value (PV of cohort cash flows) | missing | missing | Needs cohort retention and pricing data; not published. | none |
| eq. 3.12 | 49 | Deposit relationship value (PV of cohort cash flows) | missing | missing | Needs cohort retention and pricing data; not published. | none |
| eq. 3.13 | 50 | Deposit relationship value (PV of cohort cash flows) | missing | missing | Needs cohort retention and pricing data; not published. | none |
| eq. 3.14 | 50 | Deposit relationship value (PV of cohort cash flows) | missing | missing | Needs cohort retention and pricing data; not published. | none |
| eq. 3.15 | 50 | Deposit relationship value (PV of cohort cash flows) | missing | missing | Needs cohort retention and pricing data; not published. | none |
| eq. 3.16 | 50 | Bayesian information advantage and relationship value | background | missing | Conceptual modelling. | none |
| eq. 3.17 | 51 | Bayesian information advantage and relationship value | background | missing | Conceptual modelling. | none |
| eq. 3.18 | 51 | Bayesian information advantage and relationship value | background | missing | Conceptual modelling. | none |
| eq. 3.19 | 51 | Bayesian information advantage and relationship value | background | missing | Conceptual modelling. | none |
| eq. 3.20 | 52 | Bayesian information advantage and relationship value | background | missing | Conceptual modelling. | none |
| eq. 3.21 | 54 | Local ownership plus shared industrial scale | background | missing | Conceptual. | none |
| eq. 3.22 | 54 | Cost/income ratio, normalised revenue, fixed plus variable cost model | partial | `src/etf_cockpit/analysis/bank_metric_facts.py::_financial_metric_facts` | cost_income_pct and cost_to_assets_pct computed; fixed/variable split not available | efficiency axis |
| eq. 3.23 | 54 | Cost/income ratio, normalised revenue, fixed plus variable cost model | partial | `src/etf_cockpit/analysis/bank_metric_facts.py::_financial_metric_facts` | cost_income_pct and cost_to_assets_pct computed; fixed/variable split not available | efficiency axis |
| eq. 3.24 | 54 | Cost/income ratio, normalised revenue, fixed plus variable cost model | partial | `src/etf_cockpit/analysis/bank_metric_facts.py::_financial_metric_facts` | cost_income_pct and cost_to_assets_pct computed; fixed/variable split not available | efficiency axis |
| eq. 3.25 | 54 | Cost/income ratio, normalised revenue, fixed plus variable cost model | partial | `src/etf_cockpit/analysis/bank_metric_facts.py::_financial_metric_facts` | cost_income_pct and cost_to_assets_pct computed; fixed/variable split not available | efficiency axis |
| eq. 3.26 | 55 | Bank as local franchise plus shared stack; self-cost is not low cost | background | missing | Conceptual. | none |
| eq. 3.27 | 55 | Bank as local franchise plus shared stack; self-cost is not low cost | background | missing | Conceptual. | none |
| eq. 3.28 | 55 | Alliance economic contribution | missing | missing | Alliance income is not structured in the free sources (associate income is excluded from cost/income). | none |
| eq. 3.29 | 56 | Fixed-cost pressure; alliance as merger substitute | background | missing | Conceptual. | none |
| eq. 3.30 | 56 | Fixed-cost pressure; alliance as merger substitute | background | missing | Conceptual. | none |
| eq. 3.31 | 57 | Loan price decomposition (opex, expected loss, capital, liquidity, margin) | partial | `src/etf_cockpit/analysis/sparebank/book_calcs.py::risk_adjusted_lending_spread` | Margin minus credit loss implemented; capital and liquidity charges are not separable | lending axis |
| eq. 3.32 | 57 | RAROC and economic value added per segment | missing | missing | Segment capital allocation is not published. | none |
| eq. 3.33 | 57 | RAROC and economic value added per segment | missing | missing | Segment capital allocation is not published. | none |
| eq. 3.34 | 57 | RAROC and economic value added per segment | missing | missing | Segment capital allocation is not published. | none |
| eq. 3.35 | 58 | Credit lifecycle | background | missing | Conceptual. | none |
| eq. 3.36 | 58 | Credit lifecycle | background | missing | Conceptual. | none |
| eq. 3.37 | 59 | RWA density | missing | missing | RWA comes only from the Pillar 3 queue; density is not displayed. | none |
| eq. 3.38 | 59 | Capital creation vs requirement relief | background | missing | Conceptual. | none |
| eq. 3.39 | 59 | Headroom vs management target | partial | `src/etf_cockpit/analysis/sparebank/book_calcs.py::cet1_headroom` | Requirement is used; management target is not collected | cet1_headroom_pp |
| eq. 3.40 | 59 | Surplus CET1 = headroom x RWA | implemented | `src/etf_cockpit/analysis/sparebank/book_calcs.py::surplus_cet1` |  | cet1_surplus_nok (display only) |
| eq. 3.41 | 60 | Incremental economic profit | implemented | `src/etf_cockpit/analysis/sparebank/book_calcs.py::growth_value_sign` |  | Growth value sign; withheld when owner book moves less than 3% |
| eq. 3.42 | 61 | Quality spread = sustainable ROE - COE | implemented | `src/etf_cockpit/analysis/sparebank/book_calcs.py::quality_spread` |  | normalised_roe_minus_cost_of_equity_pp (scored) |
| eq. 3.43 | 61 | Compounding quality = spread x reinvestment x duration | missing | missing | Duration of excess returns is a judgement input with no data. | none |

## Chapter 4 equations

| Ref | Page | Item | Status | Locator | Limitation or reason | Score impact |
|---|---|---|---|---|---|---|
| eq. 4.1 | 69 | Failure sequence, risk appetite, volume vs seasoned outcome | background | missing | Conceptual. | none |
| eq. 4.2 | 69 | Failure sequence, risk appetite, volume vs seasoned outcome | background | missing | Conceptual. | none |
| eq. 4.3 | 70 | Failure sequence, risk appetite, volume vs seasoned outcome | background | missing | Conceptual. | none |
| eq. 4.4 | 70 | Abnormal growth = bank growth - market growth | partial | `src/etf_cockpit/analysis/sparebank/book_calcs.py::growth_gap` | Function exists; market growth benchmark is not wired (loan growth vs deposit growth is used) | lending and funding axes |
| eq. 4.5 | 70 | Growth only where PV of the marginal relationship is positive | background | missing | Decision rule without data. | none |
| eq. 4.6 | 70 | Growth only where PV of the marginal relationship is positive | background | missing | Decision rule without data. | none |
| eq. 4.7 | 71 | Problem-loan ratio vs stock; capital relief is an option | background | missing | Conceptual. | none |
| eq. 4.8 | 71 | Problem-loan ratio vs stock; capital relief is an option | background | missing | Conceptual. | none |
| eq. 4.9 | 72 | Loan covariance and concentration | missing | missing | Needs loan-level correlation data. | none |
| eq. 4.10 | 72 | Macro factors, property residual equity, diversification | background | missing | Conceptual or sector-specific; no free data. | none |
| eq. 4.11 | 72 | Macro factors, property residual equity, diversification | background | missing | Conceptual or sector-specific; no free data. | none |
| eq. 4.12 | 72 | Macro factors, property residual equity, diversification | background | missing | Conceptual or sector-specific; no free data. | none |
| eq. 4.13 | 73 | Macro factors, property residual equity, diversification | background | missing | Conceptual or sector-specific; no free data. | none |
| eq. 4.14 | 73 | Macro factors, property residual equity, diversification | background | missing | Conceptual or sector-specific; no free data. | none |
| eq. 4.15 | 74 | Macro factors, property residual equity, diversification | background | missing | Conceptual or sector-specific; no free data. | none |
| eq. 4.16 | 74 | Macro factors, property residual equity, diversification | background | missing | Conceptual or sector-specific; no free data. | none |
| eq. 4.17 | 75 | Stressed loss on concentration buckets and loss/CET1 | partial | `src/etf_cockpit/analysis/sparebank/book_calcs.py::stressed_loss` | Functions exist; bucket PD and LGD are not published | none until supplied |
| eq. 4.18 | 75 | Stressed loss on concentration buckets and loss/CET1 | partial | `src/etf_cockpit/analysis/sparebank/book_calcs.py::stressed_loss` | Functions exist; bucket PD and LGD are not published | none until supplied |
| eq. 4.19 | 75 | Margin vs funding vs liquidity vs solvency risk | background | missing | Conceptual. | none |
| eq. 4.20 | 76 | NII = sum of asset yields and funding costs | background | missing | Decomposition identity. | none |
| eq. 4.21 | 76 | Change in NIM vs peers | missing | missing | Peer-relative NIM is not computed. | none |
| eq. 4.22 | 76 | Average vs marginal funding cost | partial | `src/etf_cockpit/analysis/sparebank/book_calcs.py::marginal_spread` | Functions exist; funding tranche costs are not tagged | none until supplied |
| eq. 4.23 | 77 | Deposit beta | partial | `src/etf_cockpit/analysis/sparebank/book_calcs.py::deposit_beta_from_changes` | Function exists; deposit rates are not tagged in ESEF | deposit_beta shown as unavailable with reason |
| eq. 4.24 | 77 | Deposit franchise quality | background | missing | Conceptual. | none |
| eq. 4.25 | 77 | Refinancing concentration | partial | `src/etf_cockpit/analysis/sparebank/book_calcs.py::refinancing_concentration` | Function exists; wholesale maturity is a note table | shown as unavailable with reason |
| eq. 4.26 | 77 | Refinancing price vs access risk | background | missing | Conceptual. | none |
| eq. 4.27 | 78 | Refinancing price vs access risk | background | missing | Conceptual. | none |
| eq. 4.28 | 78 | LCR and NSFR | implemented | `src/etf_cockpit/data/pillar3_queue.py::PILLAR3_METRICS` |  | lcr and nsfr (scored) once confirmed from Pillar 3 |
| eq. 4.29 | 78 | LCR and NSFR | implemented | `src/etf_cockpit/data/pillar3_queue.py::PILLAR3_METRICS` |  | lcr and nsfr (scored) once confirmed from Pillar 3 |
| eq. 4.30 | 78 | Deposit-funded is not liquidity-immune; governance and incentives | background | missing | Qualitative. | none |
| eq. 4.31 | 78 | Deposit-funded is not liquidity-immune; governance and incentives | background | missing | Qualitative. | none |
| eq. 4.32 | 79 | Deposit-funded is not liquidity-immune; governance and incentives | background | missing | Qualitative. | none |
| eq. 4.33 | 79 | Deposit-funded is not liquidity-immune; governance and incentives | background | missing | Qualitative. | none |
| eq. 4.34 | 79 | Deposit-funded is not liquidity-immune; governance and incentives | background | missing | Qualitative. | none |
| eq. 4.35 | 80 | Deposit-funded is not liquidity-immune; governance and incentives | background | missing | Qualitative. | none |
| eq. 4.36 | 80 | Deposit-funded is not liquidity-immune; governance and incentives | background | missing | Qualitative. | none |
| eq. 4.37 | 81 | Deposit-funded is not liquidity-immune; governance and incentives | background | missing | Qualitative. | none |
| eq. 4.38 | 81 | Risk-adjusted contribution of an activity | missing | missing | Segment data not published. | none |
| eq. 4.39 | 81 | Reward vs seasoned outcome; local information | background | missing | Conceptual. | none |
| eq. 4.40 | 81 | Reward vs seasoned outcome; local information | background | missing | Conceptual. | none |
| eq. 4.41 | 82 | Reward vs seasoned outcome; local information | background | missing | Conceptual. | none |
| eq. 4.42 | 83 | Merger NPV, value split, synergy probability, ownership post-merger | missing | missing | Merger deal terms are not structured data. | none |
| eq. 4.43 | 83 | Merger NPV, value split, synergy probability, ownership post-merger | missing | missing | Merger deal terms are not structured data. | none |
| eq. 4.44 | 83 | Merger NPV, value split, synergy probability, ownership post-merger | missing | missing | Merger deal terms are not structured data. | none |
| eq. 4.45 | 83 | Merger NPV, value split, synergy probability, ownership post-merger | missing | missing | Merger deal terms are not structured data. | none |
| eq. 4.46 | 83 | Merger NPV, value split, synergy probability, ownership post-merger | missing | missing | Merger deal terms are not structured data. | none |
| eq. 4.47 | 84 | Merger NPV, value split, synergy probability, ownership post-merger | missing | missing | Merger deal terms are not structured data. | none |
| eq. 4.48 | 84 | Merger NPV, value split, synergy probability, ownership post-merger | missing | missing | Merger deal terms are not structured data. | none |
| eq. 4.49 | 85 | Merger NPV, value split, synergy probability, ownership post-merger | missing | missing | Merger deal terms are not structured data. | none |
| eq. 4.50 | 85 | Merger NPV, value split, synergy probability, ownership post-merger | missing | missing | Merger deal terms are not structured data. | none |
| eq. 4.51 | 86 | Merger NPV, value split, synergy probability, ownership post-merger | missing | missing | Merger deal terms are not structured data. | none |
| eq. 4.52 | 86 | Merger NPV, value split, synergy probability, ownership post-merger | missing | missing | Merger deal terms are not structured data. | none |
| eq. 4.53 | 87 | Stage migration chain; Stage 2 as information | background | missing | Conceptual. | none |
| eq. 4.54 | 87 | Stage migration chain; Stage 2 as information | background | missing | Conceptual. | none |
| eq. 4.55 | 88 | Cure rate | partial | `src/etf_cockpit/analysis/sparebank/book_calcs.py::stage_share` | Function exists; stage migration tables are notes | none until supplied |
| eq. 4.56 | 88 | Roll rate | partial | `src/etf_cockpit/analysis/sparebank/book_calcs.py::stage_share` | Function exists; stage migration tables are notes | none until supplied |
| eq. 4.57 | 88 | Stage 3 coverage | partial | `src/etf_cockpit/analysis/sparebank/book_calcs.py::stage_share` | Function exists; Stage 3 allowance and exposure come from Pillar 3 | stage_3_coverage shown |
| eq. 4.58 | 88 | Expected loss from collateral recovery | background | missing | Illustration of LGD. | none |
| eq. 4.59 | 88 | Cost of risk = impairment / average gross loans | implemented | `src/etf_cockpit/analysis/sparebank/book_calcs.py::cost_of_risk` |  | cost_of_risk_bps (scored); net loans are used as a stated proxy for gross loans |
| eq. 4.60 | 89 | Migration stock plus realised flow; growth to Stage 2 to CoR to CET1 | background | missing | Conceptual chain. | none |
| eq. 4.61 | 89 | Migration stock plus realised flow; growth to Stage 2 to CoR to CET1 | background | missing | Conceptual chain. | none |
| eq. 4.62 | 89 | ECL roll-forward | missing | missing | ECL movement table is a note. | none |
| eq. 4.63 | 89 | Pre-tax identity | background | missing | Identity. | none |
| eq. 4.64 | 90 | CET1 roll-forward | background | missing | Identity; the next-period CET1 forecast is not made. | none |
| eq. 4.65 | 90 | CET1 ratio | implemented | `src/etf_cockpit/data/pillar3_queue.py::PILLAR3_METRICS` |  | See 1.15 |
| eq. 4.66 | 90 | Distance to management target | missing | missing | Management target is not published as data. | none |
| eq. 4.67 | 91 | Capital headroom to distribution capacity | background | missing | Conceptual. | none |
| eq. 4.68 | 91 | Capital headroom to distribution capacity | background | missing | Conceptual. | none |
| eq. 4.69 | 92 | Capital headroom to distribution capacity | background | missing | Conceptual. | none |
| eq. 4.70 | 92 | Capital raise need and dilution | implemented | `src/etf_cockpit/analysis/sparebank/book_calcs.py::required_capital_raise` |  | required_capital_raise and diluted_owner_book_per_ec; shown when stressed inputs exist |
| eq. 4.71 | 92 | Capital raise need and dilution | implemented | `src/etf_cockpit/analysis/sparebank/book_calcs.py::required_capital_raise` |  | required_capital_raise and diluted_owner_book_per_ec; shown when stressed inputs exist |
| eq. 4.72 | 95 | Tail risk and moat extrapolation | background | missing | Conceptual. | none |
| eq. 4.73 | 98 | Tail risk and moat extrapolation | background | missing | Conceptual. | none |

## Chapter 5 equations

| Ref | Page | Item | Status | Locator | Limitation or reason | Score impact |
|---|---|---|---|---|---|---|
| eq. 5.1 | 100 | Decision from expectations and intrinsic value | background | missing | Framing. | none |
| eq. 5.2 | 101 | Owner book, BVPS, EPS and value per EC | implemented | `src/etf_cockpit/analysis/sparebank/valuation.py::owner_valuation` |  | Owner per-EC figures |
| eq. 5.3 | 101 | Owner book, BVPS, EPS and value per EC | implemented | `src/etf_cockpit/analysis/sparebank/valuation.py::owner_valuation` |  | Owner per-EC figures |
| eq. 5.4 | 101 | Owner book, BVPS, EPS and value per EC | implemented | `src/etf_cockpit/analysis/sparebank/valuation.py::owner_valuation` |  | Owner per-EC figures |
| eq. 5.5 | 101 | Owner book, BVPS, EPS and value per EC | implemented | `src/etf_cockpit/analysis/sparebank/valuation.py::owner_valuation` |  | Owner per-EC figures |
| eq. 5.6 | 102 | Owner bridge before and after | background | missing | Narrative. | none |
| eq. 5.7 | 102 | Owner earnings and normalisation | partial | `src/etf_cockpit/analysis/sparebank/bank_economics.py::owner_normalisation` | Credit-loss normalisation only (haircut only, tax-effected); other one-offs are not auto-detected | efficiency axis |
| eq. 5.8 | 103 | Owner earnings and normalisation | partial | `src/etf_cockpit/analysis/sparebank/bank_economics.py::owner_normalisation` | Credit-loss normalisation only (haircut only, tax-effected); other one-offs are not auto-detected | efficiency axis |
| eq. 5.9 | 103 | Owner earnings and normalisation | partial | `src/etf_cockpit/analysis/sparebank/bank_economics.py::owner_normalisation` | Credit-loss normalisation only (haircut only, tax-effected); other one-offs are not auto-detected | efficiency axis |
| eq. 5.10 | 104 | Owner earnings and normalisation | partial | `src/etf_cockpit/analysis/sparebank/bank_economics.py::owner_normalisation` | Credit-loss normalisation only (haircut only, tax-effected); other one-offs are not auto-detected | efficiency axis |
| eq. 5.11 | 104 | ROE on required owner capital | partial | `src/etf_cockpit/analysis/sparebank/book_calcs.py::roe_on_required_capital` | Needs confirmed capital requirement | none until Pillar 3 confirmed |
| eq. 5.12 | 104 | ROE on required owner capital | partial | `src/etf_cockpit/analysis/sparebank/book_calcs.py::roe_on_required_capital` | Needs confirmed capital requirement | none until Pillar 3 confirmed |
| eq. 5.13 | 104 | CAPM cost of equity and EC cost of equity | missing | missing | Beta, equity risk premium and liquidity premia are not estimated; COE is the book illustrative 10% as a labelled default. | valuation uses default |
| eq. 5.14 | 104 | CAPM cost of equity and EC cost of equity | missing | missing | Beta, equity risk premium and liquidity premia are not estimated; COE is the book illustrative 10% as a labelled default. | valuation uses default |
| eq. 5.15 | 106 | Count each risk once | background | missing | Rule. | none |
| eq. 5.16 | 106 | Structural required-return gap and convergence | missing | missing | Not estimated; owner supplies COE. | none |
| eq. 5.17 | 106 | Structural required-return gap and convergence | missing | missing | Not estimated; owner supplies COE. | none |
| eq. 5.18 | 106 | Gordon growth value | implemented | `src/etf_cockpit/analysis/sparebank/book_calcs.py::justified_price_to_book` |  | Via the P/B form |
| eq. 5.19 | 106 | Growth and distributable earnings | implemented | `src/etf_cockpit/analysis/sparebank/book_calcs.py::justified_price_to_book` |  | Same function |
| eq. 5.20 | 107 | Growth and distributable earnings | implemented | `src/etf_cockpit/analysis/sparebank/book_calcs.py::justified_price_to_book` |  | Same function |
| eq. 5.21 | 107 | Growth and distributable earnings | implemented | `src/etf_cockpit/analysis/sparebank/book_calcs.py::justified_price_to_book` |  | Same function |
| eq. 5.22 | 107 | Justified P/B | implemented | `src/etf_cockpit/analysis/sparebank/book_calcs.py::justified_price_to_book` |  | See 1.24 |
| eq. 5.23 | 107 | P/B is not the valuation thesis | implemented | `configs/sparebank_scorecard_v1.yaml::owner_pb` |  | owner_pb is display-only; ROE vs COE is scored |
| eq. 5.24 | 107 | Sensitivity of P/B to g | missing | missing | Not displayed. | none |
| eq. 5.25 | 108 | Incremental ROE and growth value sign | implemented | `src/etf_cockpit/analysis/sparebank/book_calcs.py::growth_value_sign` |  | See 3.41 |
| eq. 5.26 | 108 | Incremental ROE and growth value sign | implemented | `src/etf_cockpit/analysis/sparebank/book_calcs.py::growth_value_sign` |  | See 3.41 |
| eq. 5.27 | 108 | Incremental ROE and growth value sign | implemented | `src/etf_cockpit/analysis/sparebank/book_calcs.py::growth_value_sign` |  | See 3.41 |
| eq. 5.28 | 109 | Residual income per EC | implemented | `src/etf_cockpit/analysis/sparebank/book_calcs.py::residual_income_per_unit` |  | residual income in the valuation panel |
| eq. 5.29 | 109 | Fade and terminal value | partial | `src/etf_cockpit/analysis/sparebank/valuation.py::_book_valuation` | Residual-income valuation exists; fade inputs are owner assumptions | none |
| eq. 5.30 | 109 | Fade and terminal value | partial | `src/etf_cockpit/analysis/sparebank/valuation.py::_book_valuation` | Residual-income valuation exists; fade inputs are owner assumptions | none |
| eq. 5.31 | 110 | Excess return duration | missing | missing | Judgement input with no data. | none |
| eq. 5.32 | 110 | Implied ROE and implied COE | implemented | `src/etf_cockpit/analysis/sparebank/book_calcs.py::implied_roe` |  | See 1.26 and 2.23 |
| eq. 5.33 | 110 | Implied ROE and implied COE | implemented | `src/etf_cockpit/analysis/sparebank/book_calcs.py::implied_roe` |  | See 1.26 and 2.23 |
| eq. 5.34 | 111 | Expectations gap | implemented | `src/etf_cockpit/analysis/sparebank/book_calcs.py::expectations_gap` |  | expectations_gap_pp (scored) |
| eq. 5.35 | 111 | Implied ROE worked examples | implemented | `src/etf_cockpit/analysis/sparebank/book_calcs.py::implied_roe` |  | Golden tests reproduce them |
| eq. 5.36 | 111 | Implied ROE worked examples | implemented | `src/etf_cockpit/analysis/sparebank/book_calcs.py::implied_roe` |  | Golden tests reproduce them |
| eq. 5.37 | 112 | Scenario probability and compare with analyst probability | partial | `src/etf_cockpit/analysis/sparebank/valuation.py::scenario_value` | Scenario value needs explicit owner weights | none |
| eq. 5.38 | 112 | Scenario probability and compare with analyst probability | partial | `src/etf_cockpit/analysis/sparebank/valuation.py::scenario_value` | Scenario value needs explicit owner weights | none |
| eq. 5.39 | 112 | Surplus CET1 | implemented | `src/etf_cockpit/analysis/sparebank/book_calcs.py::surplus_cet1` |  | See 3.40 |
| eq. 5.40 | 112 | Excess capital as maximum distributable | missing | missing | Dividend capacity is not computed. | none |
| eq. 5.41 | 112 | Capital = required + growth + excess | background | missing | Decomposition identity. | none |
| eq. 5.42 | 112 | Growth capital k x delta RWA | implemented | `src/etf_cockpit/analysis/sparebank/book_calcs.py::capital_self_funding_ratio` |  | capital_self_funding_gap_pp (display only) |
| eq. 5.43 | 113 | Sum of the parts: operating plus excess | partial | `src/etf_cockpit/analysis/sparebank/valuation.py::_book_valuation` | Value per EC shown; split of excess is not separated | none |
| eq. 5.44 | 113 | Sum of the parts: operating plus excess | partial | `src/etf_cockpit/analysis/sparebank/valuation.py::_book_valuation` | Value per EC shown; split of excess is not separated | none |
| eq. 5.45 | 113 | Payout symmetry gap | implemented | `src/etf_cockpit/analysis/sparebank/book_calcs.py::payout_symmetry_gap` |  | payout_symmetry_gap (display only) |
| eq. 5.46 | 114 | Buyback accretion | implemented | `src/etf_cockpit/analysis/sparebank/valuation.py::buyback_accretion` |  | buyback_accretion |
| eq. 5.47 | 114 | Buyback accretion | implemented | `src/etf_cockpit/analysis/sparebank/valuation.py::buyback_accretion` |  | buyback_accretion |
| eq. 5.48 | 114 | Buyback accretion | implemented | `src/etf_cockpit/analysis/sparebank/valuation.py::buyback_accretion` |  | buyback_accretion |
| eq. 5.49 | 114 | Buyback accretion | implemented | `src/etf_cockpit/analysis/sparebank/valuation.py::buyback_accretion` |  | buyback_accretion |
| eq. 5.50 | 115 | Return engine decomposition | background | missing | Conceptual. | none |
| eq. 5.51 | 115 | Return engine decomposition | background | missing | Conceptual. | none |
| eq. 5.52 | 116 | Scenario returns, IRR and holding-period value | partial | `src/etf_cockpit/analysis/sparebank/valuation.py::expected_irr` | expected_irr and scenario_value exist; weights are owner inputs | none |
| eq. 5.53 | 117 | Scenario returns, IRR and holding-period value | partial | `src/etf_cockpit/analysis/sparebank/valuation.py::expected_irr` | expected_irr and scenario_value exist; weights are owner inputs | none |
| eq. 5.54 | 117 | Scenario returns, IRR and holding-period value | partial | `src/etf_cockpit/analysis/sparebank/valuation.py::expected_irr` | expected_irr and scenario_value exist; weights are owner inputs | none |
| eq. 5.55 | 117 | Scenario returns, IRR and holding-period value | partial | `src/etf_cockpit/analysis/sparebank/valuation.py::expected_irr` | expected_irr and scenario_value exist; weights are owner inputs | none |
| eq. 5.56 | 117 | Scenario returns, IRR and holding-period value | partial | `src/etf_cockpit/analysis/sparebank/valuation.py::expected_irr` | expected_irr and scenario_value exist; weights are owner inputs | none |
| eq. 5.57 | 117 | Scenario returns, IRR and holding-period value | partial | `src/etf_cockpit/analysis/sparebank/valuation.py::expected_irr` | expected_irr and scenario_value exist; weights are owner inputs | none |
| eq. 5.58 | 117 | Scenario returns, IRR and holding-period value | partial | `src/etf_cockpit/analysis/sparebank/valuation.py::expected_irr` | expected_irr and scenario_value exist; weights are owner inputs | none |
| eq. 5.59 | 117 | Scenario returns, IRR and holding-period value | partial | `src/etf_cockpit/analysis/sparebank/valuation.py::expected_irr` | expected_irr and scenario_value exist; weights are owner inputs | none |
| eq. 5.60 | 118 | Scenario returns, IRR and holding-period value | partial | `src/etf_cockpit/analysis/sparebank/valuation.py::expected_irr` | expected_irr and scenario_value exist; weights are owner inputs | none |
| eq. 5.61 | 118 | Scenario returns, IRR and holding-period value | partial | `src/etf_cockpit/analysis/sparebank/valuation.py::expected_irr` | expected_irr and scenario_value exist; weights are owner inputs | none |
| eq. 5.62 | 120 | Natural variables and probabilistic outputs | missing | missing | Monte Carlo output is a documented non-goal. | none |
| eq. 5.63 | 121 | Natural variables and probabilistic outputs | missing | missing | Monte Carlo output is a documented non-goal. | none |
| eq. 5.64 | 122 | Buy the gap between price and defensible value | background | missing | Principle. | none |

## Chapter 6 equations

| Ref | Page | Item | Status | Locator | Limitation or reason | Score impact |
|---|---|---|---|---|---|---|
| eq. 6.1 | 124 | Merger value chain and structural discount | background | missing | Conceptual. | none |
| eq. 6.2 | 125 | Merger value chain and structural discount | background | missing | Conceptual. | none |
| eq. 6.3 | 125 | Merger value chain and structural discount | background | missing | Conceptual. | none |
| eq. 6.4 | 127 | Value split is not conversion ratio is not eierbrok | background | missing | Distinction. | none |
| eq. 6.5 | 127 | Merger valuation, premium, synergy and probability maths | missing | missing | Merger deal terms and synergy schedules are not structured data. | none |
| eq. 6.6 | 128 | Merger valuation, premium, synergy and probability maths | missing | missing | Merger deal terms and synergy schedules are not structured data. | none |
| eq. 6.7 | 128 | Merger valuation, premium, synergy and probability maths | missing | missing | Merger deal terms and synergy schedules are not structured data. | none |
| eq. 6.8 | 128 | Merger valuation, premium, synergy and probability maths | missing | missing | Merger deal terms and synergy schedules are not structured data. | none |
| eq. 6.9 | 129 | Merger valuation, premium, synergy and probability maths | missing | missing | Merger deal terms and synergy schedules are not structured data. | none |
| eq. 6.10 | 129 | Merger valuation, premium, synergy and probability maths | missing | missing | Merger deal terms and synergy schedules are not structured data. | none |
| eq. 6.11 | 129 | Merger valuation, premium, synergy and probability maths | missing | missing | Merger deal terms and synergy schedules are not structured data. | none |
| eq. 6.12 | 129 | Merger valuation, premium, synergy and probability maths | missing | missing | Merger deal terms and synergy schedules are not structured data. | none |
| eq. 6.13 | 129 | Merger valuation, premium, synergy and probability maths | missing | missing | Merger deal terms and synergy schedules are not structured data. | none |
| eq. 6.14 | 130 | Merger valuation, premium, synergy and probability maths | missing | missing | Merger deal terms and synergy schedules are not structured data. | none |
| eq. 6.15 | 131 | Merger valuation, premium, synergy and probability maths | missing | missing | Merger deal terms and synergy schedules are not structured data. | none |
| eq. 6.16 | 131 | Merger valuation, premium, synergy and probability maths | missing | missing | Merger deal terms and synergy schedules are not structured data. | none |
| eq. 6.17 | 132 | Merger valuation, premium, synergy and probability maths | missing | missing | Merger deal terms and synergy schedules are not structured data. | none |
| eq. 6.18 | 132 | Merger valuation, premium, synergy and probability maths | missing | missing | Merger deal terms and synergy schedules are not structured data. | none |
| eq. 6.19 | 133 | Merger valuation, premium, synergy and probability maths | missing | missing | Merger deal terms and synergy schedules are not structured data. | none |
| eq. 6.20 | 134 | Merger valuation, premium, synergy and probability maths | missing | missing | Merger deal terms and synergy schedules are not structured data. | none |
| eq. 6.21 | 134 | Merger valuation, premium, synergy and probability maths | missing | missing | Merger deal terms and synergy schedules are not structured data. | none |
| eq. 6.22 | 134 | Merger valuation, premium, synergy and probability maths | missing | missing | Merger deal terms and synergy schedules are not structured data. | none |
| eq. 6.23 | 135 | Bank headroom vs deployable vs EC capital | background | missing | Conceptual. | none |
| eq. 6.24 | 135 | Bank headroom vs deployable vs EC capital | background | missing | Conceptual. | none |
| eq. 6.25 | 135 | Owner-attributable deployable capital | missing | missing | Not computed. | none |
| eq. 6.26 | 135 | Owner-attributable deployable capital | missing | missing | Not computed. | none |
| eq. 6.27 | 136 | Repurchase creates value when P < V/N | implemented | `src/etf_cockpit/analysis/sparebank/valuation.py::buyback_accretion` |  | buyback_accretion |
| eq. 6.28 | 136 | Repurchase creates value when P < V/N | implemented | `src/etf_cockpit/analysis/sparebank/valuation.py::buyback_accretion` |  | buyback_accretion |
| eq. 6.29 | 136 | Capital allocation discipline | background | missing | Conceptual. | none |
| eq. 6.30 | 137 | Capital allocation discipline | background | missing | Conceptual. | none |
| eq. 6.31 | 137 | Justified P/B and implied COE | implemented | `src/etf_cockpit/analysis/sparebank/book_calcs.py::implied_cost_of_equity` |  | See 1.24 and 2.23 |
| eq. 6.32 | 137 | Justified P/B and implied COE | implemented | `src/etf_cockpit/analysis/sparebank/book_calcs.py::implied_cost_of_equity` |  | See 1.24 and 2.23 |
| eq. 6.33 | 137 | Justified P/B and implied COE | implemented | `src/etf_cockpit/analysis/sparebank/book_calcs.py::implied_cost_of_equity` |  | See 1.24 and 2.23 |
| eq. 6.34 | 138 | EC cost of equity decomposition | missing | missing | Not estimated. | none |
| eq. 6.35 | 138 | Shapley decomposition of multiple change | missing | missing | Not implemented; analytical attribution tool. | none |
| eq. 6.36 | 138 | Shapley decomposition of multiple change | missing | missing | Not implemented; analytical attribution tool. | none |
| eq. 6.37 | 138 | Shapley decomposition of multiple change | missing | missing | Not implemented; analytical attribution tool. | none |
| eq. 6.38 | 138 | Free-float market value and turnover velocity | partial | `configs/sparebank_scorecard_v1.yaml::median_turnover_nok_60d` | Turnover is rated; free-float percentage is not available | marketability axis |
| eq. 6.39 | 139 | Free-float market value and turnover velocity | partial | `configs/sparebank_scorecard_v1.yaml::median_turnover_nok_60d` | Turnover is rated; free-float percentage is not available | marketability axis |
| eq. 6.40 | 139 | Free-float market value and turnover velocity | partial | `configs/sparebank_scorecard_v1.yaml::median_turnover_nok_60d` | Turnover is rated; free-float percentage is not available | marketability axis |
| eq. 6.41 | 139 | Free-float market value and turnover velocity | partial | `configs/sparebank_scorecard_v1.yaml::median_turnover_nok_60d` | Turnover is rated; free-float percentage is not available | marketability axis |
| eq. 6.42 | 140 | Event probability-update value | missing | missing | Event model not implemented. | none |
| eq. 6.43 | 140 | Event probability-update value | missing | missing | Event model not implemented. | none |
| eq. 6.44 | 140 | Event probability-update value | missing | missing | Event model not implemented. | none |
| eq. 6.45 | 141 | Layers of evidence | background | missing | Rule. | none |
| eq. 6.46 | 142 | Layers of evidence | background | missing | Rule. | none |
| eq. 6.47 | 143 | Disagreement value | missing | missing | Not implemented. | none |
| eq. 6.48 | 143 | Disagreement value | missing | missing | Not implemented. | none |
| eq. 6.49 | 144 | Free-float ratio and structural mispricing | missing | missing | Not implemented. | none |
| eq. 6.50 | 144 | Free-float ratio and structural mispricing | missing | missing | Not implemented. | none |
| eq. 6.51 | 146 | Structural valuation residual and security quality | missing | missing | Peer regression model not implemented. | none |
| eq. 6.52 | 148 | Structural valuation residual and security quality | missing | missing | Peer regression model not implemented. | none |
| eq. 6.53 | 148 | Structural valuation residual and security quality | missing | missing | Peer regression model not implemented. | none |
| eq. 6.54 | 149 | Structural valuation residual and security quality | missing | missing | Peer regression model not implemented. | none |

## Chapter 7 equations

| Ref | Page | Item | Status | Locator | Limitation or reason | Score impact |
|---|---|---|---|---|---|---|
| eq. 7.1 | 152 | Transition thesis | background | missing | Framing. | none |
| eq. 7.2 | 152 | Transition thesis | background | missing | Framing. | none |
| eq. 7.3 | 153 | Transition thesis | background | missing | Framing. | none |
| eq. 7.4 | 154 | Justified P/B | implemented | `src/etf_cockpit/analysis/sparebank/book_calcs.py::justified_price_to_book` |  | See 1.24 |
| eq. 7.5 | 154 | Low valuation is not undervaluation | background | missing | Principle; scored via expectations gap instead of P/B. | none |
| eq. 7.6 | 155 | Valuation residual, return engines, event studies | missing | missing | Cross-sectional regression and event study framework is a documented non-goal. | none |
| eq. 7.7 | 155 | Valuation residual, return engines, event studies | missing | missing | Cross-sectional regression and event study framework is a documented non-goal. | none |
| eq. 7.8 | 156 | Valuation residual, return engines, event studies | missing | missing | Cross-sectional regression and event study framework is a documented non-goal. | none |
| eq. 7.9 | 156 | Valuation residual, return engines, event studies | missing | missing | Cross-sectional regression and event study framework is a documented non-goal. | none |
| eq. 7.10 | 156 | Valuation residual, return engines, event studies | missing | missing | Cross-sectional regression and event study framework is a documented non-goal. | none |
| eq. 7.11 | 157 | Valuation residual, return engines, event studies | missing | missing | Cross-sectional regression and event study framework is a documented non-goal. | none |
| eq. 7.12 | 157 | Valuation residual, return engines, event studies | missing | missing | Cross-sectional regression and event study framework is a documented non-goal. | none |
| eq. 7.13 | 158 | Valuation residual, return engines, event studies | missing | missing | Cross-sectional regression and event study framework is a documented non-goal. | none |
| eq. 7.14 | 158 | Free-float value, turnover, days to trade | partial | `src/etf_cockpit/analysis/sparebank/valuation.py::days_to_trade` | days_to_trade (hard gate); free-float not available | marketability axis |
| eq. 7.15 | 158 | Free-float value, turnover, days to trade | partial | `src/etf_cockpit/analysis/sparebank/valuation.py::days_to_trade` | days_to_trade (hard gate); free-float not available | marketability axis |
| eq. 7.16 | 158 | Free-float value, turnover, days to trade | partial | `src/etf_cockpit/analysis/sparebank/valuation.py::days_to_trade` | days_to_trade (hard gate); free-float not available | marketability axis |
| eq. 7.17 | 158 | Free-float value, turnover, days to trade | partial | `src/etf_cockpit/analysis/sparebank/valuation.py::days_to_trade` | days_to_trade (hard gate); free-float not available | marketability axis |
| eq. 7.18 | 159 | COE = base + liquidity premium + structure premium | missing | missing | Premiums are not estimated. | none |
| eq. 7.19 | 159 | Forward buy-and-hold abnormal return regression | missing | missing | Regression model is a documented non-goal. | none |
| eq. 7.20 | 163 | Merger and transition economics, clocks | missing | missing | Deal and catalyst data are not structured. | none |
| eq. 7.21 | 163 | Merger and transition economics, clocks | missing | missing | Deal and catalyst data are not structured. | none |
| eq. 7.22 | 163 | Merger and transition economics, clocks | missing | missing | Deal and catalyst data are not structured. | none |
| eq. 7.23 | 164 | Merger and transition economics, clocks | missing | missing | Deal and catalyst data are not structured. | none |
| eq. 7.24 | 165 | Merger and transition economics, clocks | missing | missing | Deal and catalyst data are not structured. | none |
| eq. 7.25 | 165 | Merger and transition economics, clocks | missing | missing | Deal and catalyst data are not structured. | none |
| eq. 7.26 | 166 | Merger and transition economics, clocks | missing | missing | Deal and catalyst data are not structured. | none |
| eq. 7.27 | 166 | Merger and transition economics, clocks | missing | missing | Deal and catalyst data are not structured. | none |
| eq. 7.28 | 167 | Merger and transition economics, clocks | missing | missing | Deal and catalyst data are not structured. | none |
| eq. 7.29 | 168 | Merger and transition economics, clocks | missing | missing | Deal and catalyst data are not structured. | none |
| eq. 7.30 | 169 | Catalyst probability, pessimistic states | background | missing | Principle. | none |
| eq. 7.31 | 170 | Catalyst probability, pessimistic states | background | missing | Principle. | none |
| eq. 7.32 | 170 | Catalyst probability, pessimistic states | background | missing | Principle. | none |
| eq. 7.33 | 171 | Implied stable ROE | implemented | `src/etf_cockpit/analysis/sparebank/book_calcs.py::implied_roe` |  | See 1.26 |
| eq. 7.34 | 171 | Expectations gap in future-state ROE | implemented | `src/etf_cockpit/analysis/sparebank/book_calcs.py::expectations_gap` |  | expectations_gap_pp |
| eq. 7.35 | 171 | Expectations gap in future-state ROE | implemented | `src/etf_cockpit/analysis/sparebank/book_calcs.py::expectations_gap` |  | expectations_gap_pp |
| eq. 7.36 | 171 | Mechanism to value chain | background | missing | Principle. | none |
| eq. 7.37 | 172 | Mechanism to value chain | background | missing | Principle. | none |
| eq. 7.38 | 172 | Value per legacy EC under transition | missing | missing | Needs transition and merger terms. | none |
| eq. 7.39 | 173 | Probability-weighted value | partial | `src/etf_cockpit/analysis/sparebank/valuation.py::scenario_value` | Needs owner weights | none |
| eq. 7.40 | 173 | Probability-weighted value | partial | `src/etf_cockpit/analysis/sparebank/valuation.py::scenario_value` | Needs owner weights | none |
| eq. 7.41 | 173 | Probability-weighted value | partial | `src/etf_cockpit/analysis/sparebank/valuation.py::scenario_value` | Needs owner weights | none |
| eq. 7.42 | 173 | Probability-weighted value | partial | `src/etf_cockpit/analysis/sparebank/valuation.py::scenario_value` | Needs owner weights | none |
| eq. 7.43 | 174 | Every transition mechanism enters value once | background | missing | Rule. | none |
| eq. 7.44 | 174 | Defensible no-catalyst intrinsic value | implemented | `src/etf_cockpit/analysis/sparebank/valuation.py::_book_valuation` |  | central_owner_value_per_ec |
| eq. 7.45 | 175 | Evidence-rich expectation-poor; decision tests | background | missing | Qualitative decision rules. | none |
| eq. 7.46 | 178 | Evidence-rich expectation-poor; decision tests | background | missing | Qualitative decision rules. | none |
| eq. 7.47 | 180 | Evidence-rich expectation-poor; decision tests | background | missing | Qualitative decision rules. | none |
| eq. 7.48 | 180 | Evidence-rich expectation-poor; decision tests | background | missing | Qualitative decision rules. | none |
| eq. 7.49 | 181 | Evidence-rich expectation-poor; decision tests | background | missing | Qualitative decision rules. | none |

## Rules and thresholds

| Ref | Page | Item | Status | Locator | Limitation or reason | Score impact |
|---|---|---|---|---|---|---|
| rule 1 | 48 | Deposit-to-loan is quantity, not franchise quality | implemented | `configs/sparebank_scorecard_v1.yaml::deposit_to_loan` |  | Kept as the weakest funding input |
| rule 2 | 107 | P/B is not the valuation thesis; sustainable ROE vs COE is | implemented | `configs/sparebank_scorecard_v1.yaml::owner_pb` |  | owner_pb and owner_pe are display-only |
| rule 3 | 114 | Capital allocation ladder is deliberately non-doctrinal | implemented | `configs/sparebank_scorecard_v1.yaml::capital_allocation` |  | Axis weight 0: shown, not scored |
| rule 4 | 9 | Stage 2 and Stage 3 shares of gross loans | partial | `src/etf_cockpit/data/pillar3_queue.py::PILLAR3_METRICS` | Stage shares are extracted from Pillar 3 documents and need owner confirmation | stage_3_ratio_pct (scored) once confirmed |
| rule 5 | 16, 111 | Illustrative COE 10% and growth 3% | implemented | `configs/sparebank_scorecard_v1.yaml::valuation_defaults` |  | Defaults are labelled with their source on every valuation figure |
| rule 6 | 64 | The book prints no numeric weights or anchors; prefer causal judgement with quantified sub-metrics | implemented | `configs/sparebank_scorecard_v1.yaml::formula_version` |  | Equal weights and anchors are judgement defaults, versioned |
| rule 7 | ch. 2 | Claim must resolve (matched owner pool) before per-EC owner figures | implemented | `src/etf_cockpit/analysis/sparebank/claim.py::build_claim_state` |  | Hard gate |
| rule 8 | ch. 2 | Facts known after the decision time are invisible | implemented | `src/etf_cockpit/analysis/sparebank/claim.py::build_claim_state` |  | Point in time |
| rule 9 | 103-104 | Normalise earnings by remove-the-cost-only-if-the-resource-disappears; no add-back of bad years | implemented | `src/etf_cockpit/analysis/sparebank/bank_economics.py::owner_normalisation` |  | efficiency axis |
| rule 10 | owner design | Pillar 3 / annual-report figures are semi-automatic: only owner-confirmed figures are evidence | implemented | `src/etf_cockpit/data/pillar3_queue.py::confirmed_figures` |  | Capital, liquidity and Stage 3 inputs |
| rule 11 | scorecard | Composite withheld below the minimum coverage floor | implemented | `src/etf_cockpit/analysis/sparebank/scorecard.py::min_coverage_for_composite` |  | Composite is None below 0.25 coverage |
| rule 12 | 114 | Dividends: EC and ownerless distributions, yield and payout symmetry | missing | missing | Dividend history and yield are not yet produced. | payout_symmetry_gap |
| rule 13 | owner design | Quarterly report import | missing | missing | Quarterly reports are not yet imported. | Fresher trailing figures |
| rule 14 | owner design | Score history per quarter with trend | missing | missing | Only annual score history exists. | Trend display |
| rule 15 | owner design | Non-ESEF banks (HSPG, SOGN, JAEREN, MELG, SKUE) via issuer PDFs | missing | missing | No structured filings for these banks. | Five banks stay unscored |
| rule 16 | owner design | All listed Norwegian ECs through the universe path | missing | missing | Universe limited to the banks already added. | Coverage of the universe |

## Tables

| Ref | Page | Item | Status | Locator | Limitation or reason | Score impact |
|---|---|---|---|---|---|---|
| table 1.1 |  | Simplified savings-bank balance sheet | implemented | `src/etf_cockpit/analysis/bank_metric_facts.py::_financial_metric_facts` |  | none |
| table 1.2 |  | Net-interest-income engine | implemented | `src/etf_cockpit/analysis/sparebank/book_calcs.py::net_interest_margin` |  | none |
| table 1.3 |  | CET1 stack | partial | `src/etf_cockpit/data/pillar3_queue.py::PILLAR3_METRICS` | Requirement and actual come from confirmed Pillar 3 figures | none |
| table 2.1 |  | Routes from heritage to private-market equity | background | missing | Descriptive table. | none |
| table 2.2 |  | Ownership fraction reconstruction | implemented | `src/etf_cockpit/analysis/sparebank/claim.py::reconstruct_eierbrok` |  | none |
| table 2.3 |  | Structural COE bridge | missing | missing | Illustrative analytical inputs; the structural COE is not estimated. | none |
| table 2.4 |  | Structural dashboard for an EC bank | partial | `src/etf_cockpit/application/instrument_detail_view.py::_sparebank_workspace` | Ownership passport is shown; governance and free-float rows are not available | none |
| table 3.1 |  | Four sources of high reported ROE | partial | `src/etf_cockpit/analysis/sparebank/bank_economics.py::owner_normalisation` | Only the credit-loss source is normalised automatically | none |
| table 3.2 |  | Three live quality questions | missing | missing | Questions are 2026 reporting specific and need analyst reading. | none |
| table 3.3 |  | Sustainable-ROE quality workflow | partial | `src/etf_cockpit/analysis/sparebank/bank_economics.py::owner_normalisation` | Credit-loss step implemented; other steps need analyst judgement | none |
| table 4.1 |  | Failure sequence indicators | background | missing | Descriptive ladder. | none |
| table 4.2 |  | Minimum capital-scenario architecture | missing | missing | Scenario engine is not implemented; stress inputs are not published. | none |
| table 4.3 |  | Leading indicator to owner consequence | background | missing | Descriptive map. | none |
| table 4.4 |  | When a strength becomes a failure mechanism | background | missing | Descriptive table. | none |
| table 5.1 |  | Minimum owner bridge before valuing an EC | implemented | `src/etf_cockpit/analysis/sparebank/bank_economics.py::owner_normalisation` |  | none |
| table 5.2 |  | Assumption burden ledger | missing | missing | Assumption sources are labelled on each value but no ledger table is produced. | none |
| table 5.3 |  | Bear/base/bull EC valuation output | partial | `src/etf_cockpit/analysis/sparebank/valuation.py::scenario_value` | Owner supplies scenario weights | none |
| table 5.4 |  | EC valuation checklist | background | missing | Process checklist. | none |
| table 6.1 |  | Five-ledger merger model | missing | missing | Merger model not implemented. | none |
| table 6.2 |  | Merger synergy buckets | missing | missing | Merger model not implemented. | none |
| table 6.3 |  | The merger clock | missing | missing | Merger model not implemented. | none |
| table 6.4 |  | Deal quality vs security valuation | background | missing | Process guidance. | none |
| table 6.5 |  | Merger underwriting stack | missing | missing | Merger model not implemented. | none |
| table 6.6 |  | What to ask at each merger stage | background | missing | Process guidance. | none |
| table 6.7 |  | One-page merger underwriting output | missing | missing | Merger model not implemented. | none |
| table 6.8 |  | Adapted evidence assessment, chapter 6 | background | missing | Evidence grading guidance. | none |
| table 7.1 |  | Transition-evidence ladder | missing | missing | No transition events are recorded. | none |
