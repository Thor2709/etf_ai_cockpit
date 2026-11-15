# INT-03 — Statement line-item expansion

**Status: proposal only; not a canonical GitHub issue.**

- Priority: `P1`; gate `G1`; lane `A`; estimated size `medium`
- Logical prerequisites: `-`; source-file serialization: `-`
- Readiness: `READY`
- Intended files: `configs/stock_fundamentals_v1.yaml; analysis/stock_metrics.py; data/stock_fundamentals.py; data/stock_sources.py; parsers/sec_facts.py; parsers/esef_ixbrl.py`
- Baseline: `Thor2709/etf_ai_cockpit@1afe17c09fb53299f7c46459254d94ce8323acd1`
- Authority: canonical issue admission must be reviewed by project root and generated via the repository's guarded control process.

## Proposed technical issue

Statement line-item expansion
- Gate G1 | Priority P1 | Size medium | Depends on: none | Features: F0017, F0021, F0023, F0054, F0061
- Upstream (reference data): `dgunning/edgartools` v6.1.0 (`c7ae63b5`, MIT) `edgar/xbrl/standardization/concept_mappings.json` as a list of US-GAAP concept synonyms. Arelle stays the ESEF parser.
- Targets: `configs/stock_fundamentals_v1.yaml` (concepts `:42-65`), `analysis/stock_metrics.py` (`FLOW_FIELDS:35`, `BALANCE_FIELDS:52`, `PERIOD_FIELDS:63`, `ytd_to_discrete:801`), `data/stock_fundamentals.py` (`PERIOD_COLUMNS:42-45`, `_row_period:360`), `data/stock_sources.py` (`parse_edgar_companyfacts:313`, taxonomy filter `:328-329`), `parsers/sec_facts.py` (canonical map `:180-199`), `parsers/esef_ixbrl.py` (concept map `:56-82`).
- Field schema (the issue freezes this table; tags are candidates and each is confirmed against the taxonomy before it is added):

| Field | Kind | Sign | US-GAAP candidates | IFRS candidates (verify) |
|---|---|---|---|---|
| `current_assets` | balance | + | `AssetsCurrent` | `CurrentAssets` |
| `current_liabilities` | balance | + | `LiabilitiesCurrent` | `CurrentLiabilities` |
| `receivables` | balance | + | `AccountsReceivableNetCurrent` | `TradeAndOtherCurrentReceivables` |
| `inventory` | balance | + | `InventoryNet` | `Inventories` |
| `retained_earnings` | balance | signed | `RetainedEarningsAccumulatedDeficit` | `RetainedEarnings` |
| `ppe_net` | balance | + | `PropertyPlantAndEquipmentNet` | `PropertyPlantAndEquipment` |
| `goodwill` | balance | + | `Goodwill` | `Goodwill` |
| `sga` | flow | + (expense) | `SellingGeneralAndAdministrativeExpense` | `SellingGeneralAndAdministrativeExpense` |
| `rd_expense` | flow | + (expense) | `ResearchAndDevelopmentExpense` | `ResearchAndDevelopmentExpense` |
| `stock_based_compensation` | flow | + | `ShareBasedCompensation` | `AdjustmentsForSharebasedPayments` |
| `gross_buybacks` | flow | + (cash out) | `PaymentsForRepurchaseOfCommonStock` | `PaymentsToAcquireOrRedeemEntitysShares` |
| `share_issuance` | flow | + (cash in) | `ProceedsFromIssuanceOfCommonStock` | `ProceedsFromIssuingShares` |
| `shares_diluted` | flow (average) | + | `WeightedAverageNumberOfDilutedSharesOutstanding` | `AdjustedWeightedAverageShares` |
| `eps_diluted` | flow | signed | `EarningsPerShareDiluted` | `DilutedEarningsLossPerShare` |

- Rules: each field carries unit and currency; flow fields reported year-to-date are made discrete with `ytd_to_discrete` (today it has no caller); Q4 = FY minus Q1-Q3 as for the existing flows; "earliest filed wins" and the 120-day rule stay; a missing tag gives `unavailable`; a reported zero gives `reported_zero`; read `ifrs-full` facts for 20-F filers.
- Acceptance: one US fixture and one ESEF (non-US) fixture yield every new field with status `observed`; a filer without the tag yields `unavailable`; a year-to-date cash-flow fact yields the correct discrete quarter; outputs for the existing fields are byte-identical.
- Out of scope: new metrics (INT-04).
