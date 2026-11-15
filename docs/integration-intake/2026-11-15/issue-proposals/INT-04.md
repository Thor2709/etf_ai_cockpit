# INT-04 — Quality, earnings-quality and distress scores (native formulas)

**Status: proposal only; not a canonical GitHub issue.**

- Priority: `P1`; gate `G3`; lane `A`; estimated size `medium`
- Logical prerequisites: `INT-03`; source-file serialization: `-`
- Readiness: `READY`
- Intended files: `analysis/stock_metrics.py; analysis/formula_registry.py; data/stock_research.py; analysis/stock_evidence.py`
- Baseline: `Thor2709/etf_ai_cockpit@1afe17c09fb53299f7c46459254d94ce8323acd1`
- Authority: canonical issue admission must be reviewed by project root and generated via the repository's guarded control process.

## Proposed technical issue

Quality, earnings-quality and distress scores (native formulas)
- Gate G3 | Priority P1 | Size medium | Depends on: INT-03 | Features: F0051, F0052, F0053, F0054, F0180
- Decision: native implementation. FinanceToolkit (v2.3.3, `375f820d`, MIT) is the formula reference only. Reason: its model files import other `financetoolkit.*` modules by absolute path (`piotroski_model.py` needs `ratios.efficiency_model` and `ratios.liquidity_model`), the package pins pandas >= 3, and the formulas are short.
- Reference functions (variant names only): `models/piotroski_model.py` (`get_piotroski_score`), `models/altman_model.py` (`get_altman_z_score`), `models/beneish_model.py` (`get_beneish_m_score`), `models/quality_model.py` (`get_accruals_ratios`), `ratios/valuation_model.py` (`get_buyback_yield`, `get_shareholder_yield`).
- Targets: `analysis/stock_metrics.py` (pure functions beside the existing ones; unused formulas at `:741`, `:750`, `:759`, `:768` get callers), `analysis/formula_registry.py` (`FormulaSpec:19`), `data/stock_research.py` (`profitability_analysis:87`, `balance_sheet_analysis:296`, `_distress_metric:2612`), `analysis/stock_evidence.py` (`METRIC_LABELS:151-181`).
- Scores (each returns `Metric`, `analysis/stock_metrics.py:147`): `piotroski_f` (9 criteria, two consecutive fiscal years), `altman_z` (original, public manufacturers; `altman_like` stays beside it), `beneish_m` (8 indices), `sloan_accruals` (on average total assets), `gross_profitability` (gross profit / total assets), `net_share_issuance`, `buyback_yield`, `shareholder_yield`, `sbc_adjusted_fcf`.
- Formula schema (frozen in the registry for each score): inputs, period basis (FY or trailing four quarters), ending or average denominator, lag, currency consistency, behaviour for a zero or negative denominator (`not_meaningful`), sector applicability (banks, insurers: `not_meaningful`), and any difference from the reference variant.
- Acceptance: one fixture per score computed by hand from the published definition; a missing input gives `unavailable`; a bank gives `not_meaningful`; a negative-equity case gives the documented state.
- Out of scope: score weights (INT-05).
