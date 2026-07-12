# Review package: 3922afc48fb21ab22465ad890733caa5e0717afc..b24a46debf191d13332345b79808691ca35e9150

## Commits
b24a46d docs: record governance task 1 implementation evidence
9081909 feat: add fail-closed governance policy contracts

## Files changed
 .ai_worklog/task-governance-1-brief.md      |  43 ++++
 .ai_worklog/task-governance-1-report.md     | 108 +++++++++
 configs/feature_registry.yaml               |  28 +++
 configs/gate_policy.yaml                    |  15 ++
 configs/glossary.yaml                       |  18 ++
 configs/product_governance.yaml             |  33 +++
 configs/strategy_scope.yaml                 |  31 +++
 evidence/governance/policy_checksums.json   |  28 +++
 src/etf_cockpit/governance/models.py        | 328 ++++++++++++++++++++++++++++
 src/etf_cockpit/governance/product_scope.py | 249 +++++++++++++++++++++
 tests/test_feature_registry.py              |  76 +++++++
 tests/test_gate_policy.py                   |  85 +++++++
 tests/test_product_governance.py            |  91 ++++++++
 tests/test_strategy_scope.py                |  72 ++++++
 14 files changed, 1205 insertions(+)

## Diff
diff --git a/.ai_worklog/task-governance-1-brief.md b/.ai_worklog/task-governance-1-brief.md
new file mode 100644
index 0000000..262aa81
--- /dev/null
+++ b/.ai_worklog/task-governance-1-brief.md
@@ -0,0 +1,43 @@
+### Task 1: Define and load governance policies fail closed
+
+**Files:**
+
+- Create: `configs/product_governance.yaml`, `configs/feature_registry.yaml`, `configs/strategy_scope.yaml`, `configs/gate_policy.yaml`, `configs/glossary.yaml`, `src/etf_cockpit/governance/models.py`, `src/etf_cockpit/governance/product_scope.py`
+- Test: `tests/test_product_governance.py`, `tests/test_feature_registry.py`, `tests/test_strategy_scope.py`, `tests/test_gate_policy.py`
+
+**Consumes:** foundation wave checksum/evidence facilities.
+
+**Produces:** validated, checksum-bearing policy objects and diagnostic fail-closed loading mode.
+
+- [ ] **Step 1: Create failing policy tests**
+
+```python
+def test_execution_enabled_governance_configuration_is_rejected(tmp_path: Path) -> None:
+    path = write_yaml(tmp_path, {"authority": {"order_transmission": True}})
+    with pytest.raises(ValidationError, match="order_transmission"):
+        load_product_governance(path)
+
+def test_experimental_strategy_cannot_have_positive_score_authority() -> None:
+    with pytest.raises(ValidationError, match="score_authority"):
+        StrategyScopeEntry(lifecycle="experimental", score_authority=True)
+```
+
+- [ ] **Step 2: Run RED**
+
+Run: `.\.venv\Scripts\python.exe -m pytest tests\test_product_governance.py tests\test_feature_registry.py tests\test_strategy_scope.py tests\test_gate_policy.py -q`
+
+Expected: FAIL because governance policy models and files are absent.
+
+- [ ] **Step 3: Implement immutable policy models and checksum loading**
+
+All loaders return a Pydantic object, schema version and SHA-256 checksum. An invalid or absent policy yields `GovernanceLoadResult(diagnostic_mode=True)` with `manual_review`/`not_scoreable`, no research promotion and no portfolio review.
+
+- [ ] **Step 4: Run GREEN**
+
+Run: `.\.venv\Scripts\python.exe -m pytest tests\test_product_governance.py tests\test_feature_registry.py tests\test_strategy_scope.py tests\test_gate_policy.py -q`
+
+Expected: PASS; every production route and user-visible subsystem has one feature registry entry, and prohibited authority combinations fail validation.
+
+- [ ] **Step 5: Checkpoint policy provenance**
+
+Generate `evidence/governance/policy_checksums.json` with no secret values and attach it to the wave ledger.
diff --git a/.ai_worklog/task-governance-1-report.md b/.ai_worklog/task-governance-1-report.md
new file mode 100644
index 0000000..e3325c8
--- /dev/null
+++ b/.ai_worklog/task-governance-1-report.md
@@ -0,0 +1,108 @@
+# Wave 1 Governance Task 1 implementation report
+
+## Boundary and ownership
+
+Task: Wave 1 Governance Task 1 - define and load governance policies fail
+closed. Branch: `wave1/governance-task1`. Base: `3922afc48fb21ab22465ad890733caa5e0717afc`.
+Implementation commit: `9081909c9c2e5b679fcf11b8f7203560d17e3d51`.
+This task establishes policy contracts only. It does not migrate legacy action
+types, add the governance routes, create the Decision Journal, change issue
+ledgers or close `ISSUE-0008`, `ISSUE-0015`, `ISSUE-0030`, `ISSUE-0043` or
+`ISSUE-0047`; those requirements remain open for their later governance tasks
+and complete source/UI/package/browser evidence.
+
+The product boundary is preserved: every policy and load result carries
+`execution_allowed: false`; no broker, order, credential or external-upload
+capability was added.
+
+## RED - observed before policy implementation
+
+Command:
+
+```powershell
+& 'C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe' -m pytest tests\test_product_governance.py tests\test_feature_registry.py tests\test_strategy_scope.py tests\test_gate_policy.py -q
+```
+
+Result: exit 1 during collection with four genuine missing-module failures:
+`etf_cockpit.governance.models` and `etf_cockpit.governance.product_scope` did
+not exist. The tests were not syntactically invalid and did not pass before
+the implementation.
+
+## GREEN and refactor evidence
+
+- Focused policy suite after implementation and contract hardening: exit 0,
+  18 passed.
+- Wider affected regression:
+  `tests/test_product_governance.py tests/test_feature_registry.py
+  tests/test_strategy_scope.py tests/test_gate_policy.py
+  tests/test_closure_matrix.py tests/test_release_hardening.py
+  tests/operations/test_verification_records.py`: exit 0, 64 passed.
+- Ruff:
+  `& 'C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe' -m ruff check src/etf_cockpit/governance tests/test_product_governance.py tests/test_feature_registry.py tests/test_strategy_scope.py tests/test_gate_policy.py`
+  -> exit 0.
+- Compilation:
+  `& 'C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe' -m compileall -q src/etf_cockpit/governance tests/test_product_governance.py tests/test_feature_registry.py tests/test_strategy_scope.py tests/test_gate_policy.py`
+  -> exit 0.
+- Dependency check:
+  `& 'C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe' -m pip check`
+  -> `No broken requirements found.`
+- Policy provenance validator: five YAML SHA-256 values in
+  `evidence/governance/policy_checksums.json` matched their source bytes and
+  the manifest authority field is false.
+
+The full authoritative suite was rerun for regression comparison: 323 tests
+were collected, 316 passed and the same seven generated-data/identity failures
+as the clean baseline remained. They are unrelated to this policy task:
+missing generated trade-candidate CSV, absent secondary-tier rows, missing
+AURG/MSFT fixture rows and the 16-row identity fixture versus its historical
+45-row assertion. No new failure was introduced.
+
+## Delivered contract
+
+- `src/etf_cockpit/governance/models.py` contains frozen, extra-forbidden
+  Pydantic policy models, exact lifecycle/authority/severity vocabularies,
+  literal-false execution fields, uniqueness/order checks and contradiction
+  validators.
+- `src/etf_cockpit/governance/product_scope.py` loads all five local policies,
+  records source SHA-256 checksums and returns a diagnostic fail-closed result
+  for missing, malformed or incomplete files. Explicit positive authority
+  requests remain validation errors.
+- `configs/product_governance.yaml` is the canonical product statement and
+  authority boundary; feature, strategy, gate and glossary registries are
+  versioned and include the route/strategy/lifecycle evidence needed by later
+  governance tasks.
+- `evidence/governance/policy_checksums.json` records the five policy paths,
+  SHA-256 values, source checkpoint and `execution_allowed: false` without
+  secrets.
+- Four focused test modules exercise valid loading, checksums, immutability,
+  missing/invalid diagnostic mode, duplicate routes/IDs/orders, lifecycle and
+  authority contradictions and production-route coverage.
+
+## Compatibility and limitations
+
+The loader accepts the repository plan's `features`, `strategies`, `gates` and
+`glossary` YAML collection keys while normalising them to typed `entries`.
+Invalid or absent policies never become supported defaults: they return
+`manual_review`/`not_scoreable`, no research promotion and no portfolio review.
+Legacy action migration, central authority resolution, Decision Journal
+persistence, visible governance pages and package/browser evidence are
+explicitly deferred to Governance Tasks 2-5; they were not silently treated as
+complete here.
+
+## Source checksums at review handoff
+
+| Path | SHA-256 |
+|---|---|
+| `src/etf_cockpit/governance/models.py` | `d2558d4afa42a4379acc98c255b53c5526569f09fac624790fdc5009f37912be` |
+| `src/etf_cockpit/governance/product_scope.py` | `345f4f7c60c637eb521c592fe9659cf586bf735adeba22afc331b6ee7a886f8c` |
+| `tests/test_product_governance.py` | `7b717db7c7902a02a18db76a929cdc6df363ebafdb765ed29b30f17b77fab2d2` |
+| `tests/test_feature_registry.py` | `0898a8f9264105945a5eb8f433ba06288c94c1da9e8bfc89d2c3d2d1d31aa732` |
+| `tests/test_strategy_scope.py` | `de3af7455a57236189aac7cd7c567f005e9328e48fc1870510555af7477044cc` |
+| `tests/test_gate_policy.py` | `002eaa30f22edcff53caa18d0377b6c6cb7f076f8c96140415e8bfa60eb598d7` |
+
+## Review handoff
+
+The branch is ready for a fresh independent review of specification
+compliance and code quality. The reviewer must check the exact lifecycle and
+authority vocabularies, fail-closed behaviour, policy checksums, route
+coverage, no-authority invariant and the stated seven-test baseline.
diff --git a/configs/feature_registry.yaml b/configs/feature_registry.yaml
new file mode 100644
index 0000000..ee32cc3
--- /dev/null
+++ b/configs/feature_registry.yaml
@@ -0,0 +1,28 @@
+schema_version: "1.0"
+policy_id: feature-registry
+policy_version: "2026-07-12"
+execution_allowed: false
+executable_authority: false
+features:
+  - {feature_id: dashboard, route: "/", title: Simple Scores, lifecycle: supported, authority: research_state, required_data: [prices, evidence], tests: [test_simple_scores], visible: true}
+  - {feature_id: portfolio, route: "/portfolio", title: Portfolio Context, lifecycle: supported, authority: portfolio_review, required_data: [universe, prices], tests: [test_rebalancing], visible: true}
+  - {feature_id: signals, route: "/signals", title: Scores, lifecycle: supported, authority: research_state, required_data: [prices, evidence], tests: [test_simple_scores], visible: true}
+  - {feature_id: risk, route: "/risk", title: Risk Evidence, lifecycle: supported, authority: evidence_only, required_data: [prices, risk], tests: [test_risk_analytics], visible: true}
+  - {feature_id: etf_detail, route: "/etf", title: Instrument Detail, lifecycle: supported, authority: evidence_only, required_data: [prices, filings], tests: [test_instrument_detail], visible: true}
+  - {feature_id: backtests, route: "/backtests", title: Backtests, lifecycle: supported_with_limitations, authority: evidence_only, required_data: [prices], tests: [test_backtest_costs], visible: true}
+  - {feature_id: chatgpt_audit, route: "/chatgpt", title: Audit Notes, lifecycle: supported_with_limitations, authority: context_only, required_data: [evidence], tests: [test_chatgpt_import], visible: true}
+  - {feature_id: providers, route: "/providers", title: Provider Status, lifecycle: supported, authority: evidence_only, required_data: [provider_status], tests: [test_provider_registry], visible: true}
+  - {feature_id: evidence, route: "/evidence", title: Evidence Ledger, lifecycle: supported, authority: evidence_only, required_data: [evidence], tests: [test_evidence_ledger], visible: true}
+  - {feature_id: filings, route: "/filings", title: Filings and Statements, lifecycle: supported_with_limitations, authority: evidence_only, required_data: [filings], tests: [test_sec_facts_parser], visible: true}
+  - {feature_id: etf_disclosures, route: "/etf-disclosures", title: ETF Disclosures, lifecycle: supported_with_limitations, authority: evidence_only, required_data: [etf_documents], tests: [test_fund_documents], visible: true}
+  - {feature_id: news_context, route: "/news-context", title: News and Context, lifecycle: supported_with_limitations, authority: context_only, required_data: [news], tests: [test_news_context], visible: true}
+  - {feature_id: data_models, route: "/data-models", title: Data and Models, lifecycle: supported_with_limitations, authority: evidence_only, required_data: [models], tests: [test_model_shapes], visible: true}
+  - {feature_id: settings, route: "/settings", title: Settings, lifecycle: supported, authority: user_record, required_data: [configuration], tests: [test_release_hardening], visible: true}
+  - {feature_id: diagnostics, route: "/diagnostics", title: Diagnostics, lifecycle: supported, authority: evidence_only, required_data: [logs], tests: [test_workflow_runtime], visible: true}
+  - {feature_id: errors, route: "/errors", title: Errors and Recovery, lifecycle: supported, authority: evidence_only, required_data: [logs], tests: [test_error_recovery], visible: true}
+  - {feature_id: data_health, route: "/data-health", title: Data Health, lifecycle: supported, authority: evidence_only, required_data: [data_health], tests: [test_data_health], visible: true}
+  - {feature_id: universe, route: "/universe", title: Universe, lifecycle: supported_with_limitations, authority: evidence_only, required_data: [universe], tests: [test_universe_store], visible: true}
+  - {feature_id: onboarding, route: "/onboarding", title: First-run Setup, lifecycle: supported, authority: user_record, required_data: [configuration], tests: [test_onboarding], visible: true}
+  - {feature_id: what_changed, route: "/what-changed", title: What Changed, lifecycle: supported_with_limitations, authority: evidence_only, required_data: [score_history], tests: [test_run_changes], visible: true}
+  - {feature_id: instrument, route: "/instrument", title: Instrument Detail, lifecycle: supported, authority: evidence_only, required_data: [prices, evidence], tests: [test_instrument_detail], visible: true}
+  - {feature_id: import_export, route: "/import-export", title: Import and Export, lifecycle: supported_with_limitations, authority: evidence_only, required_data: [evidence], tests: [test_import_export], visible: true}
diff --git a/configs/gate_policy.yaml b/configs/gate_policy.yaml
new file mode 100644
index 0000000..4cd4727
--- /dev/null
+++ b/configs/gate_policy.yaml
@@ -0,0 +1,15 @@
+schema_version: "1.0"
+policy_id: gate-policy
+policy_version: "2026-07-12"
+execution_allowed: false
+executable_authority: false
+gates:
+  - {gate_id: identity, order: 1, severity: blocker, description: Instrument identity and source identity must be resolved}
+  - {gate_id: data_quality, order: 2, severity: blocker, description: "Data must be present, valid and fresh enough"}
+  - {gate_id: evidence, order: 3, severity: blocker, description: Required evidence must be source-linked and conflict-aware}
+  - {gate_id: model_validity, order: 4, severity: blocker, description: Model and backtest validity must be explicit}
+  - {gate_id: risk, order: 5, severity: blocker, description: Risk limits and unsupported asset controls must pass}
+  - {gate_id: valuation, order: 6, severity: authority_warning, description: Valuation context is advisory and may downgrade confidence}
+  - {gate_id: signal, order: 7, severity: authority_warning, description: Signal confirmation and data quality warnings remain visible}
+  - {gate_id: portfolio_fit, order: 8, severity: authority_warning, description: Portfolio context may require manual review}
+  - {gate_id: cost, order: 9, severity: authority_warning, description: Friction and edge-to-cost context is advisory}
diff --git a/configs/glossary.yaml b/configs/glossary.yaml
new file mode 100644
index 0000000..7bda670
--- /dev/null
+++ b/configs/glossary.yaml
@@ -0,0 +1,18 @@
+schema_version: "1.0"
+policy_id: governance-glossary
+policy_version: "2026-07-12"
+execution_allowed: false
+executable_authority: false
+glossary:
+  - {term: alpha, definition: Return relative to a selected benchmark over a stated period, authority_note: Context only; it does not bypass gates}
+  - {term: beta, definition: Sensitivity of returns to a benchmark, authority_note: Context only}
+  - {term: drawdown, definition: Decline from a prior peak in a value series, authority_note: Risk evidence}
+  - {term: PBO, definition: Probability of backtest overfitting, authority_note: Model-validity evidence}
+  - {term: deflated Sharpe, definition: Sharpe adjustment for multiple testing and non-normality, authority_note: Model-validity evidence}
+  - {term: MASE, definition: Mean absolute scaled error for forecast evaluation, authority_note: Forecast context}
+  - {term: calibration, definition: Agreement between predicted probabilities and observed outcomes, authority_note: Model-validity evidence}
+  - {term: slippage, definition: Difference between an assumed decision price and an observed fill proxy, authority_note: Cost context only}
+  - {term: edge-to-cost, definition: Estimated gross edge divided by estimated friction, authority_note: Cost gate context}
+  - {term: N/A, definition: A required value is unavailable or not applicable, authority_note: Missing evidence cannot increase authority}
+  - {term: manual_review, definition: A human must inspect evidence before any research promotion or portfolio review, authority_note: Non-executable state}
+  - {term: not_scoreable, definition: Required evidence or policy is unavailable, so no score is authoritative, authority_note: Fail-closed state}
diff --git a/configs/product_governance.yaml b/configs/product_governance.yaml
new file mode 100644
index 0000000..6d91692
--- /dev/null
+++ b/configs/product_governance.yaml
@@ -0,0 +1,33 @@
+schema_version: "1.0"
+policy_id: product-governance
+policy_version: "2026-07-12"
+execution_allowed: false
+executable_authority: false
+product:
+  canonical_name: "ETF AI Cockpit"
+  category: "local investment evidence and portfolio-research cockpit"
+  intended_user: "human private investor"
+  default_horizon: "long_horizon"
+  decision_owner: "user"
+authority:
+  maximum_operational_authority: "manual_research"
+  broker_execution: "forbidden"
+  execution_allowed: false
+  executable_authority: false
+  order_transmission: false
+  external_upload: false
+  credential_access: false
+  autonomous_portfolio_management: false
+  unvalidated_ai_score_authority: false
+default_research_state: research_candidate
+default_portfolio_review_state: not_applicable
+prohibited_claims:
+  - "guaranteed return"
+  - "autonomous financial adviser"
+  - "AI trading bot"
+  - "proven alpha"
+  - "broker execution enabled"
+required_disclosures:
+  - "Outputs are research evidence, not executable orders."
+  - "The user owns the final decision."
+  - "Unavailable or weak evidence can restrict authority."
diff --git a/configs/strategy_scope.yaml b/configs/strategy_scope.yaml
new file mode 100644
index 0000000..0f54ea9
--- /dev/null
+++ b/configs/strategy_scope.yaml
@@ -0,0 +1,31 @@
+schema_version: "1.0"
+policy_id: strategy-scope
+policy_version: "2026-07-12"
+execution_allowed: false
+executable_authority: false
+strategies:
+  - {strategy_id: etf_trend_momentum, name: ETF trend and momentum, lifecycle: supported, asset_scope: etf, authority: portfolio_review, score_authority: true, research_promotion_allowed: true, portfolio_review_allowed: true, required_data: [daily_prices, adjusted_returns], tests: [test_simple_scores]}
+  - {strategy_id: defensive_rotation, name: Defensive rotation and watchlist, lifecycle: supported, asset_scope: etf, authority: portfolio_review, score_authority: true, research_promotion_allowed: true, portfolio_review_allowed: true, required_data: [daily_prices, risk_metrics], tests: [test_rebalancing]}
+  - {strategy_id: stock_quality_momentum, name: Stock quality and momentum, lifecycle: supported, asset_scope: stock, authority: portfolio_review, score_authority: true, research_promotion_allowed: true, portfolio_review_allowed: true, required_data: [daily_prices, fundamentals], tests: [test_fundamentals]}
+  - {strategy_id: stock_value_momentum, name: Stock value and momentum, lifecycle: supported, asset_scope: stock, authority: portfolio_review, score_authority: true, research_promotion_allowed: true, portfolio_review_allowed: true, required_data: [daily_prices, fundamentals], tests: [test_fundamentals]}
+  - {strategy_id: long_only_ranking, name: Long-only ranking, lifecycle: supported, asset_scope: mixed, authority: research_state, score_authority: true, research_promotion_allowed: true, portfolio_review_allowed: true, required_data: [evidence, scores], tests: [test_simple_scores]}
+  - {strategy_id: manual_review, name: Manual review, lifecycle: supported_with_limitations, asset_scope: general, authority: context_only, score_authority: false, research_promotion_allowed: false, portfolio_review_allowed: false, required_data: [evidence], tests: [test_trade_proposals]}
+  - {strategy_id: news_sentiment, name: News and sentiment context, lifecycle: supported_with_limitations, asset_scope: mixed, authority: context_only, score_authority: false, research_promotion_allowed: false, portfolio_review_allowed: false, required_data: [news], tests: [test_news_context]}
+  - {strategy_id: llm_summaries, name: LLM summaries, lifecycle: supported_with_limitations, asset_scope: mixed, authority: context_only, score_authority: false, research_promotion_allowed: false, portfolio_review_allowed: false, required_data: [evidence], tests: [test_local_llm_audit]}
+  - {strategy_id: macro_notes, name: Macro notes, lifecycle: supported_with_limitations, asset_scope: mixed, authority: context_only, score_authority: false, research_promotion_allowed: false, portfolio_review_allowed: false, required_data: [macro], tests: [test_news_context]}
+  - {strategy_id: manual_notes, name: Manual notes, lifecycle: supported_with_limitations, asset_scope: general, authority: user_record, score_authority: false, research_promotion_allowed: false, portfolio_review_allowed: false, required_data: [user_notes], tests: [test_chatgpt_import]}
+  - {strategy_id: pair_trading, name: Pair trading research, lifecycle: research_only, asset_scope: stock, authority: none, score_authority: false, research_promotion_allowed: false, portfolio_review_allowed: false, paper_authority: true, required_data: [daily_prices, cointegration], tests: [test_asset_guardrails]}
+  - {strategy_id: futures, name: Futures research, lifecycle: research_only, asset_scope: general, score_authority: false, research_promotion_allowed: false, portfolio_review_allowed: false, required_data: [contract_data], tests: [test_asset_guardrails]}
+  - {strategy_id: intraday, name: Intraday research, lifecycle: research_only, asset_scope: mixed, score_authority: false, research_promotion_allowed: false, portfolio_review_allowed: false, required_data: [intraday_prices], tests: [test_asset_guardrails]}
+  - {strategy_id: options, name: Options research, lifecycle: research_only, asset_scope: stock, score_authority: false, research_promotion_allowed: false, portfolio_review_allowed: false, required_data: [options_chain], tests: [test_asset_guardrails]}
+  - {strategy_id: shorting, name: Shorting, lifecycle: rejected, asset_scope: stock, score_authority: false, research_promotion_allowed: false, portfolio_review_allowed: false, rejection_reason: Outside the approved long-only scope, tests: [test_asset_guardrails]}
+  - {strategy_id: event_driven_filings, name: Event-driven filings context, lifecycle: supported_with_limitations, asset_scope: mixed, authority: context_only, score_authority: false, research_promotion_allowed: false, portfolio_review_allowed: false, required_data: [filings], tests: [test_sec_facts_parser]}
+  - {strategy_id: alternative_data, name: Alternative data research, lifecycle: research_only, asset_scope: mixed, score_authority: false, research_promotion_allowed: false, portfolio_review_allowed: false, required_data: [source_quality], tests: [test_data_contracts]}
+  - {strategy_id: martingale, name: Martingale, lifecycle: rejected, asset_scope: general, score_authority: false, research_promotion_allowed: false, portfolio_review_allowed: false, rejection_reason: Unbounded loss and no approved evidence basis, tests: [test_asset_guardrails]}
+  - {strategy_id: grid, name: Grid, lifecycle: rejected, asset_scope: general, score_authority: false, research_promotion_allowed: false, portfolio_review_allowed: false, rejection_reason: Unsupported execution and risk assumptions, tests: [test_asset_guardrails]}
+  - {strategy_id: rl_agents, name: Reinforcement-learning agents, lifecycle: rejected, asset_scope: general, score_authority: false, research_promotion_allowed: false, portfolio_review_allowed: false, rejection_reason: No approved autonomous authority, tests: [test_asset_guardrails]}
+  - {strategy_id: llm_only_management, name: LLM-only management, lifecycle: rejected, asset_scope: general, score_authority: false, research_promotion_allowed: false, portfolio_review_allowed: false, rejection_reason: LLM output is non-authoritative context, tests: [test_local_llm_audit]}
+  - {strategy_id: model_only_trading, name: Model-only trading, lifecycle: rejected, asset_scope: general, score_authority: false, research_promotion_allowed: false, portfolio_review_allowed: false, rejection_reason: Model output cannot replace evidence and gates, tests: [test_model_shapes]}
+  - {strategy_id: return_screenshots, name: Return screenshots as evidence, lifecycle: rejected, asset_scope: general, score_authority: false, research_promotion_allowed: false, portfolio_review_allowed: false, rejection_reason: Screenshots are not reproducible evidence, tests: [test_data_contracts]}
+  - {strategy_id: unvalidated_sentiment, name: Unvalidated sentiment, lifecycle: rejected, asset_scope: mixed, score_authority: false, research_promotion_allowed: false, portfolio_review_allowed: false, rejection_reason: Sentiment cannot directly alter score authority, tests: [test_news_context]}
+  - {strategy_id: future_broker_architecture, name: Future broker architecture, lifecycle: future_only, asset_scope: general, authority: none, score_authority: false, research_promotion_allowed: false, portfolio_review_allowed: false, rejection_reason: Requires a separately approved future programme, tests: [test_release_hardening]}
diff --git a/evidence/governance/policy_checksums.json b/evidence/governance/policy_checksums.json
new file mode 100644
index 0000000..b245eac
--- /dev/null
+++ b/evidence/governance/policy_checksums.json
@@ -0,0 +1,28 @@
+{
+  "schema_version": "1.0",
+  "generated_at_utc": "2026-07-12T01:11:39Z",
+  "source_commit": "3922afc48fb21ab22465ad890733caa5e0717afc",
+  "execution_allowed": false,
+  "policies": {
+    "product_governance": {
+      "path": "configs/product_governance.yaml",
+      "sha256": "2b904e26fe3f23dc2179b73d1a525b060587ba76535b4fd344dc295cbf7e4f22"
+    },
+    "feature_registry": {
+      "path": "configs/feature_registry.yaml",
+      "sha256": "1768ed4dc613c2eb9a2a6b0756eed8b6bc600c0ccc4121cbb007fe64326cd63e"
+    },
+    "strategy_scope": {
+      "path": "configs/strategy_scope.yaml",
+      "sha256": "d27e363cb3135271dfe85d7e85a535a39f27cddd613171693443db442f28706d"
+    },
+    "gate_policy": {
+      "path": "configs/gate_policy.yaml",
+      "sha256": "08417a30155b2e42b540d125f1c12d719a1bec2ac99c703ed5d969d17f619adc"
+    },
+    "glossary": {
+      "path": "configs/glossary.yaml",
+      "sha256": "9798d4c74ef8352a43fc4aca3399104a5e064ad3dd74aae0aa8c0705f43f81d7"
+    }
+  }
+}
diff --git a/src/etf_cockpit/governance/models.py b/src/etf_cockpit/governance/models.py
new file mode 100644
index 0000000..cd8d720
--- /dev/null
+++ b/src/etf_cockpit/governance/models.py
@@ -0,0 +1,328 @@
+"""Immutable, checksum-bearing governance policy contracts.
+
+The governance files are deliberately represented by small, strict Pydantic
+models.  A policy can describe advisory research and review authority, but the
+execution boundary is encoded as ``Literal[False]`` in every model so a YAML
+value cannot opt the application into an executable mode.
+"""
+
+from __future__ import annotations
+
+from typing import Generic, Literal, TypeVar
+
+from pydantic import BaseModel, ConfigDict, Field, PositiveInt, field_validator, model_validator
+
+
+SCHEMA_VERSION = "1.0"
+Checksum = str
+Lifecycle = Literal[
+    "supported",
+    "supported_with_limitations",
+    "experimental",
+    "research_only",
+    "future_only",
+    "rejected",
+]
+Authority = Literal[
+    "evidence_only",
+    "context_only",
+    "research_state",
+    "portfolio_review",
+    "user_record",
+    "none",
+]
+ResearchState = Literal["research_candidate", "manual_review", "not_scoreable"]
+GateSeverity = Literal["blocker", "authority_warning", "notice"]
+
+
+class ImmutableModel(BaseModel):
+    """Base contract for policy data loaded from local YAML."""
+
+    model_config = ConfigDict(
+        extra="forbid",
+        frozen=True,
+        str_strip_whitespace=True,
+        validate_assignment=True,
+    )
+
+
+class AuthorityPolicy(ImmutableModel):
+    """The non-executable authority boundary shared by governance policies."""
+
+    execution_allowed: Literal[False] = False
+    executable_authority: Literal[False] = False
+    order_transmission: Literal[False] = False
+    external_upload: Literal[False] = False
+    credential_access: Literal[False] = False
+    maximum_operational_authority: Literal["manual_research"] = "manual_research"
+    broker_execution: Literal["forbidden"] = "forbidden"
+    autonomous_portfolio_management: Literal[False] = False
+    unvalidated_ai_score_authority: Literal[False] = False
+
+
+class ProductDefinition(ImmutableModel):
+    canonical_name: str = Field(min_length=1)
+    category: str = Field(min_length=1)
+    intended_user: str = Field(min_length=1)
+    default_horizon: str = Field(min_length=1)
+    decision_owner: Literal["user"] = "user"
+
+
+class PolicyModel(ImmutableModel):
+    """Common metadata and immutable execution boundary for a policy."""
+
+    schema_version: str = Field(default=SCHEMA_VERSION, min_length=1)
+    policy_id: str = Field(min_length=1)
+    policy_version: str = Field(min_length=1)
+    execution_allowed: Literal[False] = False
+    executable_authority: Literal[False] = False
+    checksum: str = "unavailable"
+
+    @field_validator("checksum")
+    @classmethod
+    def validate_checksum(cls, value: str) -> str:
+        if value == "unavailable":
+            return value
+        if len(value) != 64 or any(char not in "0123456789abcdefABCDEF" for char in value):
+            raise ValueError("checksum must be a SHA-256 hexadecimal digest")
+        return value.lower()
+
+
+class ProductGovernancePolicy(PolicyModel):
+    """Top-level product authority and fail-closed defaults."""
+
+    product: ProductDefinition = Field(
+        default_factory=lambda: ProductDefinition(
+            canonical_name="ETF AI Cockpit",
+            category="local investment evidence and portfolio-research cockpit",
+            intended_user="human private investor",
+            default_horizon="long_horizon",
+        )
+    )
+    authority: AuthorityPolicy = Field(default_factory=AuthorityPolicy)
+    prohibited_claims: tuple[str, ...] = ()
+    required_disclosures: tuple[str, ...] = ()
+    default_research_state: str = "research_candidate"
+    default_portfolio_review_state: str = "not_applicable"
+
+    @model_validator(mode="after")
+    def validate_authority_boundary(self) -> ProductGovernancePolicy:
+        for field_name in (
+            "execution_allowed",
+            "executable_authority",
+        ):
+            if getattr(self, field_name) is not False or getattr(self.authority, field_name) is not False:
+                raise ValueError(f"{field_name} must remain false")
+        return self
+
+
+class FeatureRegistryEntry(ImmutableModel):
+    """One user-visible feature or production route."""
+
+    feature_id: str = Field(default="unnamed", min_length=1)
+    route: str = Field(min_length=1)
+    title: str = ""
+    lifecycle: Lifecycle = "supported"
+    authority: Authority = "none"
+    required_data: tuple[str, ...] = ()
+    tests: tuple[str, ...] = ()
+    visible: bool = True
+    score_authority: bool = False
+    research_promotion_allowed: bool = False
+    portfolio_review_allowed: bool = False
+    execution_allowed: Literal[False] = False
+
+    @field_validator("route")
+    @classmethod
+    def validate_route(cls, value: str) -> str:
+        if not value.startswith("/"):
+            raise ValueError("route must start with '/'")
+        return value
+
+    @model_validator(mode="after")
+    def validate_lifecycle_authority(self) -> FeatureRegistryEntry:
+        if self.lifecycle in {"experimental", "research_only", "future_only", "rejected"} and (
+            self.score_authority or self.research_promotion_allowed or self.portfolio_review_allowed
+        ):
+            raise ValueError("lifecycle does not permit positive authority")
+        return self
+
+
+class FeatureRegistryPolicy(PolicyModel):
+    """Registry of routes and visible product subsystems."""
+
+    entries: tuple[FeatureRegistryEntry, ...] = ()
+
+    @model_validator(mode="after")
+    def validate_unique_features_and_routes(self) -> FeatureRegistryPolicy:
+        feature_ids = [entry.feature_id for entry in self.entries]
+        routes = [entry.route for entry in self.entries]
+        if len(feature_ids) != len(set(feature_ids)):
+            raise ValueError("feature_id values must be unique")
+        if len(routes) != len(set(routes)):
+            raise ValueError("route values must be unique")
+        return self
+
+
+class StrategyScopeEntry(ImmutableModel):
+    """Strategy lifecycle and the authority that strategy may contribute."""
+
+    strategy_id: str = Field(default="unnamed", min_length=1)
+    name: str = ""
+    lifecycle: Lifecycle = "supported"
+    asset_scope: Literal["etf", "stock", "mixed", "general"] = "general"
+    authority: Authority = "none"
+    score_authority: bool = False
+    research_promotion_allowed: bool = False
+    portfolio_review_allowed: bool = False
+    paper_authority: bool = False
+    required_data: tuple[str, ...] = ()
+    limitations: tuple[str, ...] = ()
+    linked_issues: tuple[str, ...] = ()
+    promotion_conditions: tuple[str, ...] = ()
+    rejection_reason: str = ""
+    tests: tuple[str, ...] = ()
+    execution_allowed: Literal[False] = False
+
+    @model_validator(mode="after")
+    def validate_strategy_authority(self) -> StrategyScopeEntry:
+        if self.lifecycle == "rejected" and (
+            self.score_authority or self.research_promotion_allowed or self.portfolio_review_allowed
+        ):
+            raise ValueError("rejected strategies cannot have positive authority")
+        if self.lifecycle in {"experimental", "research_only", "future_only"} and self.score_authority:
+            raise ValueError("score_authority is not permitted for this lifecycle")
+        if self.lifecycle in {"experimental", "research_only", "future_only"} and self.research_promotion_allowed:
+            raise ValueError("research_promotion_allowed is not permitted for this lifecycle")
+        if self.lifecycle in {"experimental", "research_only", "future_only"} and self.portfolio_review_allowed:
+            raise ValueError("portfolio_review_allowed is not permitted for this lifecycle")
+        if self.lifecycle in {"future_only", "rejected"} and self.authority != "none":
+            raise ValueError("future-only and rejected strategies cannot have authority")
+        return self
+
+
+class StrategyScopePolicy(PolicyModel):
+    """Supported, context-only, research-only and rejected strategy families."""
+
+    entries: tuple[StrategyScopeEntry, ...] = ()
+
+    @model_validator(mode="after")
+    def validate_unique_strategies(self) -> StrategyScopePolicy:
+        identifiers = [entry.strategy_id for entry in self.entries]
+        if len(identifiers) != len(set(identifiers)):
+            raise ValueError("strategy_id values must be unique")
+        return self
+
+
+class GatePolicyEntry(ImmutableModel):
+    """One ordered gate in the authority ladder."""
+
+    gate_id: str = Field(min_length=1)
+    order: PositiveInt = 1
+    severity: GateSeverity = "notice"
+    description: str = ""
+    research_promotion_allowed: bool = False
+    portfolio_review_allowed: bool = False
+    execution_allowed: Literal[False] = False
+
+    @model_validator(mode="after")
+    def validate_gate_authority(self) -> GatePolicyEntry:
+        if self.severity == "blocker" and (
+            self.research_promotion_allowed or self.portfolio_review_allowed
+        ):
+            raise ValueError("blocker gates cannot allow research_promotion_allowed or portfolio_review_allowed")
+        return self
+
+
+class GatePolicy(PolicyModel):
+    """Ordered, monotonic gate policy."""
+
+    gates: tuple[GatePolicyEntry, ...] = ()
+
+    @model_validator(mode="after")
+    def validate_unique_gate_order(self) -> GatePolicy:
+        identifiers = [gate.gate_id for gate in self.gates]
+        orders = [gate.order for gate in self.gates]
+        if len(identifiers) != len(set(identifiers)):
+            raise ValueError("gate_id values must be unique")
+        if len(orders) != len(set(orders)):
+            raise ValueError("order values must be unique")
+        if orders and orders != sorted(orders):
+            raise ValueError("gates must be ordered by order")
+        return self
+
+
+class GlossaryEntry(ImmutableModel):
+    term: str = Field(min_length=1)
+    definition: str = Field(min_length=1)
+    authority_note: str = ""
+
+
+class GlossaryPolicy(PolicyModel):
+    entries: tuple[GlossaryEntry, ...] = ()
+
+    @model_validator(mode="after")
+    def validate_unique_terms(self) -> GlossaryPolicy:
+        terms = [entry.term.casefold() for entry in self.entries]
+        if len(terms) != len(set(terms)):
+            raise ValueError("glossary terms must be unique")
+        return self
+
+
+PolicyT = TypeVar("PolicyT", bound=PolicyModel)
+
+
+class GovernanceLoadResult(ImmutableModel, Generic[PolicyT]):
+    """Result of loading one policy, including fail-closed diagnostics."""
+
+    policy: PolicyT | None = None
+    schema_version: str = "unknown"
+    checksum: str = "unavailable"
+    diagnostic_mode: bool = False
+    diagnostics: tuple[str, ...] = ()
+    research_state: ResearchState = "manual_review"
+    score_state: Literal["not_scoreable"] = "not_scoreable"
+    research_promotion_allowed: Literal[False] = False
+    portfolio_review_allowed: Literal[False] = False
+    execution_allowed: Literal[False] = False
+    executable_authority: Literal[False] = False
+
+    @property
+    def value(self) -> PolicyT | None:
+        """Compatibility alias for callers that call the payload ``value``."""
+
+        return self.policy
+
+    @property
+    def model(self) -> PolicyT | None:
+        """Compatibility alias for callers that call the payload ``model``."""
+
+        return self.policy
+
+    @property
+    def valid(self) -> bool:
+        return not self.diagnostic_mode and self.policy is not None
+
+    @property
+    def scoreable(self) -> bool:
+        return self.score_state != "not_scoreable"
+
+
+__all__ = [
+    "SCHEMA_VERSION",
+    "AuthorityPolicy",
+    "FeatureRegistryEntry",
+    "FeatureRegistryPolicy",
+    "GatePolicy",
+    "GatePolicyEntry",
+    "GlossaryEntry",
+    "GlossaryPolicy",
+    "GovernanceLoadResult",
+    "ImmutableModel",
+    "Authority",
+    "ProductDefinition",
+    "PolicyModel",
+    "ProductGovernancePolicy",
+    "StrategyScopeEntry",
+    "StrategyScopePolicy",
+]
diff --git a/src/etf_cockpit/governance/product_scope.py b/src/etf_cockpit/governance/product_scope.py
new file mode 100644
index 0000000..b3055c2
--- /dev/null
+++ b/src/etf_cockpit/governance/product_scope.py
@@ -0,0 +1,249 @@
+"""Fail-closed loaders for the local governance policy set."""
+
+from __future__ import annotations
+
+import hashlib
+from dataclasses import dataclass
+from pathlib import Path
+from typing import Any, Mapping, TypeVar
+
+import yaml
+from pydantic import ValidationError
+
+from etf_cockpit.core.paths import CONFIG_DIR
+from etf_cockpit.governance.models import (
+    FeatureRegistryPolicy,
+    GatePolicy,
+    GlossaryPolicy,
+    GovernanceLoadResult,
+    PolicyModel,
+    ProductGovernancePolicy,
+    StrategyScopePolicy,
+)
+
+
+@dataclass(frozen=True)
+class PolicyPaths:
+    product: Path
+    feature_registry: Path
+    strategy_scope: Path
+    gate_policy: Path
+    glossary: Path
+
+
+DEFAULT_POLICY_PATHS = PolicyPaths(
+    product=CONFIG_DIR / "product_governance.yaml",
+    feature_registry=CONFIG_DIR / "feature_registry.yaml",
+    strategy_scope=CONFIG_DIR / "strategy_scope.yaml",
+    gate_policy=CONFIG_DIR / "gate_policy.yaml",
+    glossary=CONFIG_DIR / "glossary.yaml",
+)
+
+PRODUCT_GOVERNANCE_PATH = DEFAULT_POLICY_PATHS.product
+FEATURE_REGISTRY_PATH = DEFAULT_POLICY_PATHS.feature_registry
+STRATEGY_SCOPE_PATH = DEFAULT_POLICY_PATHS.strategy_scope
+GATE_POLICY_PATH = DEFAULT_POLICY_PATHS.gate_policy
+GLOSSARY_PATH = DEFAULT_POLICY_PATHS.glossary
+
+PolicyClassT = TypeVar("PolicyClassT", bound=PolicyModel)
+
+
+def _sha256_bytes(payload: bytes) -> str:
+    return hashlib.sha256(payload).hexdigest()
+
+
+def _diagnostic(
+    *,
+    schema_version: str,
+    checksum: str,
+    message: str,
+) -> GovernanceLoadResult[PolicyModel]:
+    return GovernanceLoadResult(
+        policy=None,
+        schema_version=schema_version,
+        checksum=checksum,
+        diagnostic_mode=True,
+        diagnostics=(message,),
+        research_state="manual_review",
+        score_state="not_scoreable",
+        research_promotion_allowed=False,
+        portfolio_review_allowed=False,
+        execution_allowed=False,
+        executable_authority=False,
+    )
+
+
+def _truthy(value: object) -> bool:
+    if isinstance(value, bool):
+        return value
+    if isinstance(value, (int, float)):
+        return value != 0
+    if isinstance(value, str):
+        return value.strip().casefold() in {"true", "yes", "on", "1"}
+    return False
+
+
+def _has_positive_authority(value: object) -> bool:
+    if isinstance(value, Mapping):
+        for key, item in value.items():
+            if str(key) in {
+                "execution_allowed",
+                "executable_authority",
+                "order_transmission",
+                "external_upload",
+                "credential_access",
+            } and _truthy(item):
+                return True
+            if _has_positive_authority(item):
+                return True
+    elif isinstance(value, list):
+        return any(_has_positive_authority(item) for item in value)
+    return False
+
+
+def _normalise_payload(model_class: type[PolicyClassT], raw: Mapping[str, Any]) -> dict[str, Any]:
+    payload = dict(raw)
+    if model_class is ProductGovernancePolicy:
+        authority = payload.get("authority")
+        if isinstance(authority, Mapping):
+            authority_payload = dict(authority)
+            payload["authority"] = authority_payload
+            for key in ("execution_allowed", "executable_authority"):
+                if key not in payload and key in authority_payload:
+                    payload[key] = authority_payload[key]
+    elif model_class is FeatureRegistryPolicy and "entries" not in payload:
+        payload["entries"] = payload.pop("features", ())
+    elif model_class is StrategyScopePolicy and "entries" not in payload:
+        payload["entries"] = payload.pop("strategies", ())
+    elif model_class is GatePolicy and "gates" not in payload:
+        payload["gates"] = payload.pop("entries", ())
+    elif model_class is GlossaryPolicy and "entries" not in payload:
+        payload["entries"] = payload.pop("glossary", payload.pop("terms", ()))
+    return payload
+
+
+def _validation_is_explicitly_contradictory(error: ValidationError) -> bool:
+    message = str(error).casefold()
+    return any(
+        marker in message
+        for marker in (
+            "execution_allowed",
+            "executable_authority",
+            "order_transmission",
+            "external_upload",
+            "credential_access",
+            "score_authority",
+            "research_promotion_allowed",
+            "portfolio_review_allowed",
+            "authority",
+            "route values must be unique",
+            "order values must be unique",
+            "feature_id values must be unique",
+            "strategy_id values must be unique",
+        )
+    )
+
+
+def _load_policy(
+    path: Path,
+    model_class: type[PolicyClassT],
+    *,
+    policy_name: str,
+) -> GovernanceLoadResult[PolicyClassT]:
+    source = Path(path)
+    try:
+        raw_bytes = source.read_bytes()
+    except OSError as exc:
+        return _diagnostic(schema_version="unknown", checksum="unavailable", message=f"{policy_name} policy unavailable: {exc}")  # type: ignore[return-value]
+
+    checksum = _sha256_bytes(raw_bytes)
+    try:
+        loaded = yaml.safe_load(raw_bytes.decode("utf-8"))
+    except (UnicodeDecodeError, yaml.YAMLError) as exc:
+        return _diagnostic(schema_version="unknown", checksum=checksum, message=f"{policy_name} policy could not be parsed: {exc}")  # type: ignore[return-value]
+    if not isinstance(loaded, Mapping):
+        return _diagnostic(schema_version="unknown", checksum=checksum, message=f"{policy_name} policy must be a mapping")  # type: ignore[return-value]
+
+    schema_version = str(loaded.get("schema_version") or "unknown")
+    required_headers = {"schema_version", "policy_id", "policy_version"}
+    has_headers = required_headers.issubset(loaded)
+    positive_authority = _has_positive_authority(loaded)
+    payload = _normalise_payload(model_class, loaded)
+    if not has_headers and not positive_authority:
+        return _diagnostic(
+            schema_version=schema_version,
+            checksum=checksum,
+            message=f"{policy_name} policy is missing required metadata",
+        )  # type: ignore[return-value]
+
+    try:
+        policy = model_class.model_validate(payload)
+        policy = policy.model_copy(update={"checksum": checksum})
+    except ValidationError as exc:
+        if _validation_is_explicitly_contradictory(exc):
+            raise
+        return _diagnostic(
+            schema_version=schema_version,
+            checksum=checksum,
+            message=f"{policy_name} policy failed validation: {exc}",
+        )  # type: ignore[return-value]
+
+    return GovernanceLoadResult(
+        policy=policy,
+        schema_version=policy.schema_version,
+        checksum=checksum,
+        diagnostic_mode=False,
+        diagnostics=(),
+        research_state="manual_review",
+        score_state="not_scoreable",
+        research_promotion_allowed=False,
+        portfolio_review_allowed=False,
+        execution_allowed=False,
+        executable_authority=False,
+    )
+
+
+def load_product_governance(path: Path | None = None) -> GovernanceLoadResult[ProductGovernancePolicy]:
+    """Load product authority policy, remaining diagnostic-only on absence."""
+
+    return _load_policy(Path(path or PRODUCT_GOVERNANCE_PATH), ProductGovernancePolicy, policy_name="product governance")
+
+
+def load_feature_registry(path: Path | None = None) -> GovernanceLoadResult[FeatureRegistryPolicy]:
+    """Load the route/feature registry."""
+
+    return _load_policy(Path(path or FEATURE_REGISTRY_PATH), FeatureRegistryPolicy, policy_name="feature registry")
+
+
+def load_strategy_scope(path: Path | None = None) -> GovernanceLoadResult[StrategyScopePolicy]:
+    """Load strategy lifecycle and authority scope."""
+
+    return _load_policy(Path(path or STRATEGY_SCOPE_PATH), StrategyScopePolicy, policy_name="strategy scope")
+
+
+def load_gate_policy(path: Path | None = None) -> GovernanceLoadResult[GatePolicy]:
+    """Load the ordered fail-closed gate policy."""
+
+    return _load_policy(Path(path or GATE_POLICY_PATH), GatePolicy, policy_name="gate policy")
+
+
+def load_glossary(path: Path | None = None) -> GovernanceLoadResult[GlossaryPolicy]:
+    """Load explanatory glossary terms used by later governance surfaces."""
+
+    return _load_policy(Path(path or GLOSSARY_PATH), GlossaryPolicy, policy_name="glossary")
+
+
+__all__ = [
+    "DEFAULT_POLICY_PATHS",
+    "FEATURE_REGISTRY_PATH",
+    "GATE_POLICY_PATH",
+    "GLOSSARY_PATH",
+    "PRODUCT_GOVERNANCE_PATH",
+    "PolicyPaths",
+    "STRATEGY_SCOPE_PATH",
+    "load_feature_registry",
+    "load_gate_policy",
+    "load_glossary",
+    "load_product_governance",
+    "load_strategy_scope",
+]
diff --git a/tests/test_feature_registry.py b/tests/test_feature_registry.py
new file mode 100644
index 0000000..fccbd63
--- /dev/null
+++ b/tests/test_feature_registry.py
@@ -0,0 +1,76 @@
+from __future__ import annotations
+
+from pathlib import Path
+
+import pytest
+import yaml
+from pydantic import ValidationError
+
+from etf_cockpit.app.router import PAGES
+from etf_cockpit.governance.models import FeatureRegistryEntry
+from etf_cockpit.governance.product_scope import (
+    DEFAULT_POLICY_PATHS,
+    load_feature_registry,
+)
+
+
+def write_yaml(root: Path, payload: object) -> Path:
+    path = root / "feature_registry.yaml"
+    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
+    return path
+
+
+def test_feature_registry_covers_every_production_route() -> None:
+    result = load_feature_registry(DEFAULT_POLICY_PATHS.feature_registry)
+
+    assert result.diagnostic_mode is False
+    assert result.policy is not None
+    entries = result.policy.entries
+    assert len({entry.feature_id for entry in entries}) == len(entries)
+    assert len({entry.route for entry in entries}) == len(entries)
+    assert set(PAGES).issubset({entry.route for entry in entries})
+    assert all(entry.visible is True for entry in entries)
+    assert all(entry.execution_allowed is False for entry in entries)
+
+
+def test_feature_registry_rejects_duplicate_routes(tmp_path: Path) -> None:
+    path = write_yaml(
+        tmp_path,
+        {
+            "schema_version": "1.0",
+            "policy_id": "features",
+            "policy_version": "1",
+            "execution_allowed": False,
+            "features": [
+                {"feature_id": "one", "route": "/", "lifecycle": "supported"},
+                {"feature_id": "two", "route": "/", "lifecycle": "supported"},
+            ],
+        },
+    )
+
+    with pytest.raises(ValidationError, match="route"):
+        load_feature_registry(path)
+
+
+def test_invalid_feature_registry_fails_closed(tmp_path: Path) -> None:
+    path = write_yaml(tmp_path, {"features": [{"feature_id": "missing-route"}]})
+
+    result = load_feature_registry(path)
+
+    assert result.diagnostic_mode is True
+    assert result.policy is None
+    assert result.research_state == "manual_review"
+    assert result.score_state == "not_scoreable"
+    assert result.research_promotion_allowed is False
+    assert result.portfolio_review_allowed is False
+    assert result.execution_allowed is False
+
+
+def test_experimental_feature_cannot_gain_positive_score_authority() -> None:
+    with pytest.raises(ValidationError, match="positive authority"):
+        FeatureRegistryEntry(
+            feature_id="experimental",
+            route="/experimental",
+            lifecycle="experimental",
+            score_authority=True,
+        )
diff --git a/tests/test_gate_policy.py b/tests/test_gate_policy.py
new file mode 100644
index 0000000..c7250bd
--- /dev/null
+++ b/tests/test_gate_policy.py
@@ -0,0 +1,85 @@
+from __future__ import annotations
+
+from pathlib import Path
+
+import pytest
+import yaml
+from pydantic import ValidationError
+
+from etf_cockpit.governance.models import GatePolicyEntry
+from etf_cockpit.governance.product_scope import (
+    DEFAULT_POLICY_PATHS,
+    load_gate_policy,
+)
+
+
+def write_yaml(root: Path, payload: object) -> Path:
+    path = root / "gate_policy.yaml"
+    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
+    return path
+
+
+def test_default_gate_policy_is_ordered_and_fail_closed() -> None:
+    result = load_gate_policy(DEFAULT_POLICY_PATHS.gate_policy)
+
+    assert result.diagnostic_mode is False
+    assert result.policy is not None
+    names = [gate.gate_id for gate in result.policy.gates]
+    assert names == [
+        "identity",
+        "data_quality",
+        "evidence",
+        "model_validity",
+        "risk",
+        "valuation",
+        "signal",
+        "portfolio_fit",
+        "cost",
+    ]
+    assert all(gate.execution_allowed is False for gate in result.policy.gates)
+    assert result.policy.execution_allowed is False
+    assert {gate.severity for gate in result.policy.gates} == {"blocker", "authority_warning"}
+
+
+def test_blocking_gate_cannot_allow_research_promotion() -> None:
+    with pytest.raises(ValidationError, match="research_promotion_allowed"):
+        GatePolicyEntry(
+            gate_id="identity",
+            order=1,
+            severity="blocker",
+            research_promotion_allowed=True,
+            portfolio_review_allowed=False,
+        )
+
+
+def test_gate_policy_rejects_duplicate_order(tmp_path: Path) -> None:
+    path = write_yaml(
+        tmp_path,
+        {
+            "schema_version": "1.0",
+            "policy_id": "gates",
+            "policy_version": "1",
+            "execution_allowed": False,
+            "gates": [
+                {"gate_id": "first", "order": 1, "severity": "blocker"},
+                {"gate_id": "second", "order": 1, "severity": "notice"},
+            ],
+        },
+    )
+
+    with pytest.raises(ValidationError, match="order"):
+        load_gate_policy(path)
+
+
+def test_invalid_gate_policy_fails_closed(tmp_path: Path) -> None:
+    path = write_yaml(tmp_path, {"gates": [{"gate_id": "unknown", "severity": "bad"}]})
+
+    result = load_gate_policy(path)
+
+    assert result.diagnostic_mode is True
+    assert result.policy is None
+    assert result.research_state == "manual_review"
+    assert result.score_state == "not_scoreable"
+    assert result.research_promotion_allowed is False
+    assert result.portfolio_review_allowed is False
+    assert result.execution_allowed is False
diff --git a/tests/test_product_governance.py b/tests/test_product_governance.py
new file mode 100644
index 0000000..d571451
--- /dev/null
+++ b/tests/test_product_governance.py
@@ -0,0 +1,91 @@
+from __future__ import annotations
+
+import hashlib
+from pathlib import Path
+
+import pytest
+import yaml
+from pydantic import ValidationError
+
+from etf_cockpit.governance.models import ProductGovernancePolicy
+from etf_cockpit.governance.product_scope import (
+    DEFAULT_POLICY_PATHS,
+    GovernanceLoadResult,
+    load_product_governance,
+)
+
+
+def write_yaml(root: Path, payload: object) -> Path:
+    path = root / "policy.yaml"
+    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
+    return path
+
+
+def test_execution_enabled_governance_configuration_is_rejected(tmp_path: Path) -> None:
+    path = write_yaml(tmp_path, {"authority": {"order_transmission": True}})
+
+    with pytest.raises(ValidationError, match="order_transmission"):
+        load_product_governance(path)
+
+
+def test_product_policy_is_immutable_and_checksum_bearing() -> None:
+    result = load_product_governance(DEFAULT_POLICY_PATHS.product)
+
+    assert isinstance(result, GovernanceLoadResult)
+    assert result.policy is not None
+    assert result.schema_version == result.policy.schema_version == "1.0"
+    assert result.checksum == result.policy.checksum
+    assert result.checksum == hashlib.sha256(DEFAULT_POLICY_PATHS.product.read_bytes()).hexdigest()
+    assert result.execution_allowed is False
+    assert result.policy.product.canonical_name == "ETF AI Cockpit"
+    assert result.policy.authority.maximum_operational_authority == "manual_research"
+    assert result.policy.authority.broker_execution == "forbidden"
+    with pytest.raises(ValidationError):
+        result.policy.policy_version = "tampered"
+
+
+def test_missing_product_policy_fails_closed_to_diagnostic_mode(tmp_path: Path) -> None:
+    result = load_product_governance(tmp_path / "missing.yaml")
+
+    assert result.diagnostic_mode is True
+    assert result.policy is None
+    assert result.research_state == "manual_review"
+    assert result.score_state == "not_scoreable"
+    assert result.research_promotion_allowed is False
+    assert result.portfolio_review_allowed is False
+    assert result.execution_allowed is False
+    assert result.checksum == "unavailable"
+
+
+def test_product_policy_rejects_any_positive_authority_flag(tmp_path: Path) -> None:
+    path = write_yaml(
+        tmp_path,
+        {
+            "schema_version": "1.0",
+            "policy_id": "test",
+            "policy_version": "1",
+            "authority": {
+                "execution_allowed": True,
+                "executable_authority": False,
+                "order_transmission": False,
+            },
+        },
+    )
+
+    with pytest.raises(ValidationError, match="execution_allowed"):
+        load_product_governance(path)
+
+
+def test_product_model_rejects_extra_fields() -> None:
+    with pytest.raises(ValidationError):
+        ProductGovernancePolicy(
+            schema_version="1.0",
+            policy_id="test",
+            policy_version="1",
+            authority={
+                "execution_allowed": False,
+                "executable_authority": False,
+                "order_transmission": False,
+            },
+            unexpected="not permitted",
+        )
diff --git a/tests/test_strategy_scope.py b/tests/test_strategy_scope.py
new file mode 100644
index 0000000..a90da92
--- /dev/null
+++ b/tests/test_strategy_scope.py
@@ -0,0 +1,72 @@
+from __future__ import annotations
+
+from pathlib import Path
+
+import pytest
+import yaml
+from pydantic import ValidationError
+
+from etf_cockpit.governance.models import StrategyScopeEntry
+from etf_cockpit.governance.product_scope import (
+    DEFAULT_POLICY_PATHS,
+    load_strategy_scope,
+)
+
+
+def write_yaml(root: Path, payload: object) -> Path:
+    path = root / "strategy_scope.yaml"
+    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
+    return path
+
+
+def test_experimental_strategy_cannot_have_positive_score_authority() -> None:
+    with pytest.raises(ValidationError, match="score_authority"):
+        StrategyScopeEntry(lifecycle="experimental", score_authority=True)
+
+
+def test_rejected_strategy_cannot_have_any_authority() -> None:
+    with pytest.raises(ValidationError, match="authority"):
+        StrategyScopeEntry(
+            strategy_id="martingale",
+            lifecycle="rejected",
+            score_authority=False,
+            research_promotion_allowed=True,
+        )
+
+
+def test_default_strategy_scope_contains_supported_and_rejected_families() -> None:
+    result = load_strategy_scope(DEFAULT_POLICY_PATHS.strategy_scope)
+
+    assert result.diagnostic_mode is False
+    assert result.policy is not None
+    by_id = {entry.strategy_id: entry for entry in result.policy.entries}
+    assert by_id["etf_trend_momentum"].lifecycle == "supported"
+    assert by_id["pair_trading"].lifecycle == "research_only"
+    assert by_id["martingale"].lifecycle == "rejected"
+    assert by_id["llm_only_management"].score_authority is False
+    assert all(entry.execution_allowed is False for entry in result.policy.entries)
+
+
+def test_invalid_strategy_scope_fails_closed(tmp_path: Path) -> None:
+    path = write_yaml(
+        tmp_path,
+        {
+            "schema_version": "1.0",
+            "policy_id": "strategies",
+            "policy_version": "1",
+            "execution_allowed": False,
+            "strategies": [{"strategy_id": "bad", "lifecycle": "experimental", "score_authority": True}],
+        },
+    )
+
+    with pytest.raises(ValidationError, match="score_authority"):
+        load_strategy_scope(path)
+
+
+def test_missing_strategy_scope_fails_closed(tmp_path: Path) -> None:
+    result = load_strategy_scope(tmp_path / "missing.yaml")
+
+    assert result.diagnostic_mode is True
+    assert result.research_state == "manual_review"
+    assert result.score_state == "not_scoreable"
+    assert result.execution_allowed is False
