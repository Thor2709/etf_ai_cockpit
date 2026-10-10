# T-GATE implementation handoff

TASK_ID: T-GATE

MODEL/EFFORT: model=gpt-6.1-sol effort=high

STATUS: blocked

Branch: bf/t-gate. Original checkpoint: a7ef62458cfadd76b586ab1301d46345b0cf009c.

Packet authority: the supplied T-GATE packet and its 144-node failure list. No delegation, network, push, new dependency, owner-data edit, skipped listed test or weakened assertion.

## Second pass: D2-D7 owner decisions (2026-10-10)

Starting branch/head: bf/t-gate at b96f40f9bef5c6c4ca008cea14b4df27b43a997c. All earlier committed work is retained. The supplied failure-list input was already untracked and remains excluded from the deliverable.

STATUS: blocked. NEEDS_OPUS_DECISION: D2's assertion-only retarget assumes native components already exist. The current captured pipeline instead gives **all 14 unranked bank instruments 12 ordinary components**, with source IDs `yfinance:prices`, `yfinance:fundamentals`, `yfinance:analyst_estimates`, `model:baseline`, `model:timesfm` and `model:toto`; none carries a native scorecard identifier. There are 44 ranked ordinary instruments. This is not an empty-component assertion that can be corrected by a native exception.

The current product explicitly falls back to generic stock scoring below the native evidence floor (`src/etf_cockpit/signals/simple_scores.py:1478`, `:1481`, `:1483`, `:1702`) and excludes all bank instruments from ordinary ranks (`:922`). The native-score constructor itself supplies an empty component list (`:2049`). These paths were read in this session. No native identifier or financial value has been invented, no golden was regenerated, and no scoring behavior was changed. Owner must specify the treatment of below-floor bank rows and authorize the exact native-component projection before D2 can meet its strict assertion.

Per-decision implementation:

- D2: blocked by the independently captured product behavior above. The non-vacuity assertion is retained.
- D3: implemented in `scripts/import_official_filing.py:138`. When orgnr is supplied, reject an absent registry orgnr or a mismatch before output-directory creation, archival or publication. The current UniverseRecord has no orgnr field; supplied orgnr therefore fails closed until verified registry metadata exists. No organisation number was added.
- D4: implemented in `scripts/diag/owner_identity_migration.py:29`. Certificate ISIN fixes are read from verified canonical YAML registry records; the hardcoded bank issuer/ISIN entry was removed. Other existing fixes are retained.
- D5: implemented in `scripts/smoke_app.py:213`. Require AURG's registry identity to be verified and nonempty, and compare the score's ISIN with that registry value. No ISIN literal was added.
- D6: implemented. Canonical release stamps replace display-version suffixes; tutorials use current setup/import/export actions; the methodology index links the Sparebank book-gap page. Existing data-dictionary/application-API/completion generators ran. Completion generation retained only docs outputs; README.md and CHANGELOG.md writes were suppressed to respect the write set.
- D7: not implemented after the mandatory D2 ambiguity stop. The exploratory summary-test retarget was discarded; all four current assertions remain committed and unchanged. Fixed horizontal rows were observed but no product layout was altered.

The requested checks and commit blocker are recorded below. The historical first-pass sections below are retained as historical evidence; their next-step/permission statements do not supersede this second-pass packet.

### Second-pass requested checks

Environment: Windows / Python 3.12.10; PYTHONPATH=C:/Users/thor2/AppData/Local/Temp reuses the first pass's existing runner-only Windows tempfile ACL workaround. Linux remains UNVERIFIED.

Final focused result: **9 passed, 5 failed, 0 skipped, 0 errors; 14 collected**. Per decision: D2 0/1; D3 1/0; D4 1/0; D5 1/0; D6 6/0; D7 0/4 (passed/failed).

Exact child command:

```text
python -m pytest -q --tb=line -p no:cacheprovider tests/refactor_parity/test_scoreboard_golden.py::test_scoreboard_golden_is_not_vacuous tests/test_norway_official_filing.py::test_wrong_issuer_and_orgnr_are_rejected tests/test_sparebank_onboarding.py::test_source_has_no_hardcoded_sparebank_issuer_table tests/issue0014/test_browser_workflows.py::test_real_loopback_http_startup_uses_offline_source_smoke tests/test_b00_control_plane.py::test_completion_document_check_is_offline_and_fresh tests/test_documentation_integrity.py::test_data_dictionary_version_matches_project_release tests/test_documentation_integrity.py::test_generated_documentation_has_no_drift tests/test_user_documentation.py::test_documentation_release_stamps_match_project_version tests/test_user_documentation.py::test_documented_on_screen_labels_exist_in_application_source tests/test_user_documentation.py::test_methodology_index_links_every_architecture_and_sdd_page tests/test_responsive_summary_pages.py::test_summary_cards_reflow_natively_and_keep_session[/screener] tests/test_responsive_summary_pages.py::test_summary_cards_reflow_natively_and_keep_session[/signals] tests/test_task17_ui_contracts.py::test_what_changed_uses_compact_responsive_instrument_cards_without_horizontal_table tests/test_u1_home_pages.py::test_onboarding_leads_with_setup_and_discloses_details --junitxml=C:/Users/thor2/AppData/Local/Temp/t-gate-second-pass-focus.xml
```

Verbatim failure output:

```text
F.........FFFF                                                           [100%]
================================== FAILURES ===================================
E   assert False
     +  where False = all(<generator object test_scoreboard_golden_is_not_vacuous.<locals>.<genexpr> at 0x000002B8DB5CA6C0>)
C:\dev\etf-BF-T-GATE\tests\refactor_parity\test_scoreboard_golden.py:44: assert False
E   StopIteration
C:\dev\etf-BF-T-GATE\tests\test_responsive_summary_pages.py:46: StopIteration
E   StopIteration
C:\dev\etf-BF-T-GATE\tests\test_responsive_summary_pages.py:46: StopIteration
E   assert False
     +  where False = any(<generator object test_what_changed_uses_compact_responsive_instrument_cards_without_horizontal_table.<locals>.<genexpr> at 0x000002B8DB5C99A0>)
C:\dev\etf-BF-T-GATE\tests\test_task17_ui_contracts.py:82: assert False
E   AttributeError: 'PageView' object has no attribute 'key'
C:\dev\etf-BF-T-GATE\tests\test_u1_home_pages.py:57: AttributeError: 'PageView' object has no attribute 'key'
=========================== short test summary info ===========================
FAILED tests/refactor_parity/test_scoreboard_golden.py::test_scoreboard_golden_is_not_vacuous
FAILED tests/test_responsive_summary_pages.py::test_summary_cards_reflow_natively_and_keep_session[/screener]
FAILED tests/test_responsive_summary_pages.py::test_summary_cards_reflow_natively_and_keep_session[/signals]
FAILED tests/test_task17_ui_contracts.py::test_what_changed_uses_compact_responsive_instrument_cards_without_horizontal_table
FAILED tests/test_u1_home_pages.py::test_onboarding_leads_with_setup_and_discloses_details
```

Full-list command (135 targets, excluding only the nine named D1 golden checks, retaining D2):

```powershell
$env:PYTHONPATH='C:/Users/thor2/AppData/Local/Temp'
$gateNodes = Get-Content C:/Users/thor2/AppData/Local/Temp/t-gate-second-pass-full-nodes.txt
python -m pytest -q --tb=line -p no:cacheprovider @gateNodes --junitxml=C:/Users/thor2/AppData/Local/Temp/t-gate-second-pass-full.xml *> C:/Users/thor2/AppData/Local/Temp/t-gate-second-pass-full.log
$gateExit = $LASTEXITCODE
Get-Content C:/Users/thor2/AppData/Local/Temp/t-gate-second-pass-full.log
exit $gateExit
```

The full-node runner input was built from every line of the supplied gate-fails-1b733dc4.txt: convert the dotted module prefix to a slash path plus .py, retain the exact ::test/parameter suffix, and exclude the nine D1 nodes recorded below. Exactly 135 existing test-file targets were verified before starting.

FULL_LIST_RESULT_PENDING

### Second-pass commit blocker

The requested commit `fix(gate): decisions D2-D7` was not created. Staging the 15 verified in-scope deliverable paths failed with exit 128. Verbatim error:

```text
fatal: Unable to create 'C:/Users/thor2/Desktop/Trading App/etf_ai_cockpit/.git/worktrees/etf-BF-T-GATE/index.lock': Permission denied
```

The shared metadata path is outside the writable workspace; escalation is unavailable. No permission workaround, index relocation, commit or push was attempted. This is separate from the unresolved D2/D7 product acceptance.

## Result

Completed implementation full-list run: **121 passed, 23 failed, 0 skipped, 0 errors; 144 collected**. Every remaining failure is individually recorded below as NEEDS_OPUS_DECISION. The Linux release gate is not green.

Validation ran on Windows/Python 3.12.10, not the Linux release host. Windows sandbox tempfile creation with mode 0700 produced ACL-inaccessible directories. A runner-only temporary sitecustomize changes that mode to 0777 on Windows, loaded through PYTHONPATH=C:/Users/thor2/AppData/Local/Temp. No repository permissions/configuration or product code was changed for this workaround. Linux behavior remains UNVERIFIED until rerun there.

## Root-cause groups

### G1: Score-history normalization and component history

Supply the absent effective_at column before selecting the canonical history schema; retain all scoped component history. Existing nullable schema assertions remain intact. The interrupted score-history correction was retained.

Result: 14 passed; 0 owner-decision failures. Tests:

- `tests/bughunt/test_fix_p_extras.py::test_s8_03_serialized_appends_preserve_both_runs`
- `tests/bughunt/test_repro_s8.py::test_s8_02_existing_unreadable_history_blocks_append`
- `tests/test_run_changes.py::test_run_comparison_can_load_history_by_run_ids`
- `tests/test_score_history.py::test_classification_override_invalidates_canonical_history_read_but_preserves_raw_audit_row`
- `tests/test_score_history.py::test_empty_complete_run_replaces_only_supplied_run_rows`
- `tests/test_score_history.py::test_invalid_history_rows_are_dropped_without_crashing`
- `tests/test_score_history.py::test_score_history_append_is_idempotent_by_run_and_snapshot`
- `tests/test_score_history.py::test_score_history_append_normalises_legacy_store_before_duplicate_detection`
- `tests/test_score_history.py::test_score_history_preserves_run_dimensions_and_never_grants_execution_authority`
- `tests/test_score_history.py::test_score_history_publishes_paired_csv_and_rolls_back_on_group_failure`
- `tests/test_score_history.py::test_score_history_replaces_changed_snapshot_for_same_run_without_duplicate_instruments`
- `tests/test_sparebank_native_score_display.py::test_latest_sparebank_scores_takes_latest_native_run`
- `tests/test_task19_instrument_detail.py::test_metric_history_local_route_preserves_all_scoped_components[VWCE]`
- `tests/test_task19_instrument_detail.py::test_metric_history_local_route_preserves_all_scoped_components[metric-stock]`

### G2: Backtest cache identity

Exclude signals absent from the backtest price universe before persisting structural diagnostics. This removes research-only SADG from that backtest trace and restores exact structure-column cache matching without bypassing freshness, checksum, universe or structure-cap guards.

Result: 5 passed; 0 owner-decision failures. Tests:

- `tests/test_backtest_lab.py::test_backtest_cache_reader_uses_one_complete_snapshot_under_interleaving`
- `tests/test_backtest_lab.py::test_backtest_service_reuses_mixed_availability_integer_diagnostics`
- `tests/test_backtest_lab.py::test_backtest_service_reuses_quality_momentum_cache_after_persistence`
- `tests/test_backtest_lab.py::test_backtest_service_round_trips_genuinely_unavailable_operational_rows`
- `tests/test_issue_0104_corrections.py::test_real_260_session_backtest_accepts_structural_holdings`

### G3: Instrument detail, valuation and sector evidence

Retain and finish the interrupted local valuation workspace. Restore native-dialog session ownership, dismissal and stale-callback cleanup, invalid-evidence rejection, structured/scalar evidence, complete bounded record disclosure, ETF holdings CSV fallback coverage, score-component history, sector/fundamental/fixed-income evidence, provenance, candle ambiguity and audit export. Nullable signal/score values fail closed. Retarget removed internals to the current kit controls and evidence panels with the same behavioral assertions.

Result: 32 passed; 0 owner-decision failures. Tests:

- `tests/test_candles.py::test_instrument_detail_renders_candle_evidence_section`
- `tests/test_cyclical_sector_adapters.py::test_default_facade_selector_state_render_and_ui_metadata`
- `tests/test_etf_economics.py::test_etf_economics_ui_renders_scalar_tracking_coverage`
- `tests/test_financial_sector_adapters.py::test_verified_available_projection_flows_facade_selector_and_page_contract`
- `tests/test_fixed_income_market_data.py::test_selector_and_page_expose_non_executable_market_data`
- `tests/test_innovation_sector_adapters.py::test_formula_registry_and_verified_ui_projection_are_versioned_and_fail_closed`
- `tests/test_issue0010_instrument_detail.py::test_issue0010_instrument_detail_exposes_non_executable_thesis_diary`
- `tests/test_real_asset_sector_adapters.py::test_projection_flows_through_selector_state_and_page`
- `tests/test_sparebank_certification.py::test_teaching_bank_production_route_exposes_scorecard_and_workspace`
- `tests/test_statement_normalisation.py::test_fundamentals_surface_exposes_reported_and_restated_statement_history`
- `tests/test_task19_instrument_detail.py::test_crowding_attribution_renders_canonical_broad_alpha_value`
- `tests/test_task19_instrument_detail.py::test_detail_disclosure_keeps_every_record_and_bounds_scroll`
- `tests/test_task19_instrument_detail.py::test_fundamentals_panel_renders_complete_five_section_provenance`
- `tests/test_task19_instrument_detail.py::test_instrument_detail_exposes_functional_export_control_and_disabled_state`
- `tests/test_task19_instrument_detail.py::test_instrument_detail_reads_holdings_csv_mirror_when_parquet_is_unavailable`
- `tests/test_task19_instrument_detail.py::test_instrument_detail_registers_visible_fundamentals_acceptance_surface`
- `tests/test_task19_instrument_detail.py::test_score_panel_nullable_scoreboard_and_signal_values_fail_closed`
- `tests/test_task19_instrument_detail.py::test_valuation_invalid_selected_evidence_blocks_panel[available_at-0000-not-a-date]`
- `tests/test_task19_instrument_detail.py::test_valuation_invalid_selected_evidence_blocks_panel[available_at-2026-07-01T08:00:00]`
- `tests/test_task19_instrument_detail.py::test_valuation_invalid_selected_evidence_blocks_panel[available_at-None]`
- `tests/test_task19_instrument_detail.py::test_valuation_invalid_selected_evidence_blocks_panel[end-bad_value6]`
- `tests/test_task19_instrument_detail.py::test_valuation_invalid_selected_evidence_blocks_panel[end-not-a-date]`
- `tests/test_task19_instrument_detail.py::test_valuation_invalid_selected_evidence_blocks_panel[value-True]`
- `tests/test_task19_instrument_detail.py::test_valuation_invalid_selected_evidence_blocks_panel[value-inf]`
- `tests/test_task19_instrument_detail.py::test_valuation_invalid_selected_evidence_blocks_panel[value-nan]`
- `tests/test_task19_instrument_detail.py::test_valuation_scenario_controls_are_local_and_invalidate`
- `tests/test_task19_instrument_detail.py::test_valuation_visible_in_detail_for_stock_and_etf[etf]`
- `tests/test_task19_instrument_detail.py::test_valuation_workspace_native_dialog_session_and_focus`
- `tests/test_valuation_workspace_lifecycle.py::test_real_shell_render_discards_only_owned_workspace[/instrument/NEW]`
- `tests/test_valuation_workspace_lifecycle.py::test_real_shell_render_discards_only_owned_workspace[/instrument/OLD]`
- `tests/test_valuation_workspace_lifecycle.py::test_repeated_workspace_dismissal_releases_sessions[False]`
- `tests/test_valuation_workspace_lifecycle.py::test_repeated_workspace_dismissal_releases_sessions[True]`

### G4: Local operations records and paper ledger

Restore persisted previews, explicit confirmation, workflow-scoped workers, cancellation, terminal status, event-policy invalidation and proposal-review evidence using existing application contracts. Sum every paginated holding; reject missing account IDs; distinguish repeated equal partial fills with per-intent fill IDs and retain retry idempotence. Restore the Records tab. Every workflow remains local and execution_allowed=false.

Result: 11 passed; 0 owner-decision failures. Tests:

- `tests/bughunt/test_repro_s11.py::test_s11_01_operation_worker_is_scoped_to_its_workflow`
- `tests/bughunt/test_repro_s11.py::test_s11_02_failed_job_is_not_recorded_completed`
- `tests/bughunt/test_repro_s11.py::test_s11_03_portfolio_context_includes_all_holdings`
- `tests/bughunt/test_repro_s11.py::test_s11_04_cancelled_worker_preserves_new_preview`
- `tests/bughunt/test_repro_s1.py::test_s1_07_equal_partial_fill_actions_not_silently_dropped`
- `tests/test_operations_workspace.py::test_cancelled_paper_preview_stays_cancelled`
- `tests/test_operations_workspace.py::test_operations_explicit_policy_disables_confirmation_on_missing_calendar`
- `tests/test_operations_workspace.py::test_operations_workspace_can_open_local_paper_account`
- `tests/test_operations_workspace.py::test_operations_workspace_exposes_paper_live_training_and_audit_states`
- `tests/test_operations_workspace.py::test_paper_preview_starts_once_and_reaches_a_durable_result`
- `tests/test_operations_workspace.py::test_proposal_review_records_manual_review_until_immutable_evidence_exists`

### G5: Risk and macro lineage

Restore persisted crowding/attribution and friction/edge evidence, SCOREBOARD_PATH, and real robust-estimator comparison instead of a permanent unavailable placeholder. Restore macro vintage/source/revision lineage and scenario decision time. Missing or non-finite evidence remains unavailable; execution_allowed=false.

Result: 9 passed; 0 owner-decision failures. Tests:

- `tests/test_macro_factors_ui.py::test_macro_factors_workspace_is_registered_and_declares_safe_boundaries`
- `tests/test_macro_factors_ui.py::test_macro_page_binds_every_producer_to_snapshot_cutoff_and_renders_lineage`
- `tests/test_macro_factors_ui.py::test_macro_page_fails_closed_with_explicit_unavailable_when_cutoff_missing`
- `tests/test_robust_risk.py::test_risk_workspace_surfaces_robust_risk_evidence`
- `tests/test_task18_ui.py::test_instrument_detail_friction_non_finite_values_are_unavailable`
- `tests/test_task18_ui.py::test_instrument_detail_renders_cost_edge_fields`
- `tests/test_task18_ui.py::test_risk_crowding_counts_distinct_explicit_warning_cluster_ids`
- `tests/test_task18_ui.py::test_risk_friction_panel_formats_non_finite_edge_values_as_unavailable`
- `tests/test_task18_ui.py::test_risk_page_renders_cost_edge_fields_and_unavailable_state`

### G6: Kit callbacks and import/workflow controls

Await asynchronous kit callbacks and set the actual disabled control property. Keep import preview validation messages visible and read selected browser bytes. Use native keyboard-operable FilledButton controls for primary dashboard workflows. Retarget popup-menu selection to the existing Field/menu rather than introducing an unregistered acceptance key.

Result: 3 passed; 0 owner-decision failures. Tests:

- `tests/bughunt/test_repro_s11.py::test_s11_06_browser_import_uses_selected_bytes`
- `tests/test_import_export.py::test_settings_references_actual_version_and_changelog_files`
- `tests/test_workflow_runtime.py::test_primary_dashboard_workflows_are_keyboard_operable_buttons`

### G7: Current controls, fixtures and traversal

Retarget obsolete attributes/controls to current PageView, segment groups, fields, switches, kit cards and menus. Avoid walking PageView.content and body twice. Supply complete existing configuration/snapshot fixtures, use supported analysis_depth=full, exercise credential deletion confirmation, and retain restore corruption/companion assertions. Preserve VWCE as the explicit intended benchmark and reorder the fixture so it cannot accidentally be the first enabled instrument.

Result: 31 passed; 0 owner-decision failures. Tests:

- `tests/bughunt/test_repro_s10.py::test_s10_05_save_uses_current_controls`
- `tests/bughunt/test_repro_s10.py::test_s10_08_strategy_can_toggle_twice_without_navigation`
- `tests/bughunt/test_repro_s11.py::test_s11_05_comparison_workspace_save_accepts_snapshot_date`
- `tests/bughunt/test_repro_s11.py::test_s11_07_completed_llm_audit_is_not_shown_as_unrun`
- `tests/test_accessible_tables.py::test_backtests_page_connects_real_chart_and_accessible_table_helpers`
- `tests/test_accessible_tables.py::test_settings_page_documents_issue_0044_packaged_update_workflow`
- `tests/test_application_api.py::test_jobs_page_consumes_application_api_view_models`
- `tests/test_backup_restore.py::test_commit_restore_rechecks_companions_after_preview`
- `tests/test_backup_restore.py::test_encrypted_partial_preview_checks_destination_consistency`
- `tests/test_backup_restore.py::test_settings_revision_mismatch_is_rejected_before_writes`
- `tests/test_e2e_advanced.py::test_portfolio_import_and_reconcile_source_controls`
- `tests/test_e2e_advanced.py::test_settings_page_previews_and_saves_local_settings`
- `tests/test_frontend_design_system.py::test_dashboard_summary_cards_are_inherently_responsive`
- `tests/test_frontend_design_system.py::test_shell_command_palette_filters_and_navigates`
- `tests/test_issue0032_broker_architecture.py::test_system_map_exposes_future_only_architecture_without_action_control`
- `tests/test_issue_0053_digest.py::test_dashboard_generation_keeps_each_accepted_category_visible`
- `tests/test_issue_0053_digest.py::test_dashboard_uses_one_cutoff_and_complete_alert_population`
- `tests/test_news_ui.py::test_dashboard_news_digest_shows_unavailable_or_canonical_context`
- `tests/test_portfolio_import_ui.py::test_portfolio_import_controls_are_registered_and_non_executable`
- `tests/test_settings_run_publication.py::test_feature_service_does_not_use_first_enabled_instrument_as_benchmark`
- `tests/test_task17_ui_contracts.py::test_what_changed_exposes_instrument_search_and_dimension_filters`
- `tests/test_u1_home_pages.py::test_summary_kpis_have_stable_keys_and_no_inline_as_of`
- `tests/test_u7_lab_pages.py::test_panel_uses_kit_glass_with_key_and_label`
- `tests/ui/test_decision_journal_ui.py::test_decision_journal_is_local_only_with_one_primary_save_action`
- `tests/ui/test_portfolio_b_restyle_ui.py::test_page_uses_kit_panels_with_deterministic_unique_keys[decision-journal]`
- `tests/ui/test_portfolio_b_restyle_ui.py::test_page_uses_kit_panels_with_deterministic_unique_keys[forward-evidence]`
- `tests/ui/test_portfolio_b_restyle_ui.py::test_page_uses_kit_panels_with_deterministic_unique_keys[operations]`
- `tests/ui/test_portfolio_b_restyle_ui.py::test_page_uses_kit_panels_with_deterministic_unique_keys[portfolio-optimiser]`
- `tests/ui/test_portfolio_b_restyle_ui.py::test_page_uses_kit_panels_with_deterministic_unique_keys[risk]`
- `tests/ui/test_portfolio_b_restyle_ui.py::test_page_uses_kit_panels_with_deterministic_unique_keys[stress-lab]`
- `tests/ui/test_u6_universe_map_ui.py::test_catalogue_unreadable_state_is_honest`

### G8: Lazy startup and deferred rendering

Inspect underlying lazy storage without triggering it. Align test routes with deferred-render generation guards and isolate route-ownership tests from deferred scheduling. Keep actual loader, painted-placeholder, shell rebuild and workspace ownership assertions.

Result: 5 passed; 0 owner-decision failures. Tests:

- `tests/test_flet_startup.py::test_native_queued_navigation_has_one_render_owner`
- `tests/test_startup_lazy.py::test_backtest_route_loads_on_worker_behind_loading_shell`
- `tests/test_startup_lazy.py::test_snapshot_defers_backtest_and_lazy_result_matches_eager_result`
- `tests/test_ui_staged_rendering.py::test_deferred_pageview_rebuilds_shell_after_the_placeholder`
- `tests/test_ui_staged_rendering.py::test_deferred_section_is_filled_after_the_placeholder_is_painted`

### G9: Packaged configuration paths

Resolve ESEF extension configuration and stock-fundamentals fallback from the existing runtime ROOT/CONFIG_DIR rather than source-file ancestors, so packaged/frozen layouts use their actual local configuration.

Result: 1 passed; 0 owner-decision failures. Tests:

- `tests/release/test_frozen_layout.py::test_no_module_derives_configs_from_file_parents`

### G10: Application import boundaries

Route UI preference and unavailable-financial-projection imports through existing application facades. Resolve the existing GeoJSON package resource without importing a presentation module into application.ui_views.sectors. No new dependency or identifier.

Result: 1 passed; 0 owner-decision failures. Tests:

- `tests/test_import_layering.py::test_no_new_layering_violations`

### G11: Setup, health, diagnostics and update evidence

Use the actual opt-in Toggle for ticker validation, disabled when no validator exists; preserve typed quota/offline setup behavior. Restore visible health-export errors and anomaly review/canonical metadata. Assert current health detail dialogs and diagnostic exception/fingerprint labels including the actual fingerprint and secret redaction. Restore update-verification/notices/intake evidence and their existing registered keys.

Result: 9 passed; 0 owner-decision failures. Tests:

- `tests/test_credentials.py::test_settings_saves_resolves_and_deletes_credentials_by_active_provider_id`
- `tests/test_data_health.py::test_data_health_export_failure_is_visible_and_refreshes_page`
- `tests/test_data_health.py::test_data_health_ui_names_cache_provenance_and_failure_columns`
- `tests/test_onboarding.py::test_onboarding_save_reloads_active_state`
- `tests/test_onboarding.py::test_onboarding_ui_exposes_opt_in_online_validator_seam`
- `tests/test_onboarding.py::test_online_toggle_is_disabled_without_validator`
- `tests/test_onboarding.py::test_ui_typed_quota_result_is_visible_and_saves_offline_setup`
- `tests/test_supply_chain_scan.py::test_settings_page_exposes_update_verification_and_notices`
- `tests/test_trust_critical_artifacts.py::test_diagnostics_ui_displays_redacted_exception_fingerprint`

### D1: NEEDS_OPUS_DECISION: golden path and attribution

The harness writes tests/fixtures/refactor_parity/{backtest,persisted_schema,scoreboard,snapshot}.json, not the allowed tests/refactor_parity/golden directory. No golden was regenerated. Authorize the actual paths before refreshing with ETF_REFRESH_REFACTOR_GOLDENS=1 and rerunning without it. Attribution must be limited to VWCE as-of anchoring, zero forecast weights and Sparebank scorecard v1.2.x. The observed diff also includes 59 versus 58 instruments, 28 versus 30 snapshot fields, new transactional storage/run-manifest schema and structural signal-trace filtering; these need separate attribution/approval rather than a blanket scoring refresh.

Result: 0 passed; 9 owner-decision failures. Tests:

- `tests/refactor_parity/test_backtest_golden.py::test_backtest_matches_golden`
- `tests/refactor_parity/test_clock_independence.py::test_goldens_do_not_depend_on_the_wall_clock[backtest]`
- `tests/refactor_parity/test_clock_independence.py::test_goldens_do_not_depend_on_the_wall_clock[persisted_schema]`
- `tests/refactor_parity/test_clock_independence.py::test_goldens_do_not_depend_on_the_wall_clock[scoreboard]`
- `tests/refactor_parity/test_clock_independence.py::test_goldens_do_not_depend_on_the_wall_clock[snapshot]`
- `tests/refactor_parity/test_persisted_schema_golden.py::test_persisted_schema_golden_covers_the_required_families`
- `tests/refactor_parity/test_persisted_schema_golden.py::test_persisted_schemas_match_golden`
- `tests/refactor_parity/test_scoreboard_golden.py::test_scoreboard_matches_golden`
- `tests/refactor_parity/test_snapshot_golden.py::test_snapshot_digest_matches_golden`

### D2: NEEDS_OPUS_DECISION: unranked native-bank components

Ordinary cohort ranks were fixed to remain contiguous while native banks stay unranked. The remaining non-vacuity assertion requires every unranked instrument to have zero components, conflicting with the current native Sparebank scorecard components. Do not remove those components to satisfy the old invariant. Owner must define the intended native-bank exception and equally strong coverage.

Result: 0 passed; 1 owner-decision failures. Tests:

- `tests/refactor_parity/test_scoreboard_golden.py::test_scoreboard_golden_is_not_vacuous`

### D3: NEEDS_OPUS_DECISION: official-filing organisation validation

scripts/import_official_filing.py accepts orgnr but does not validate it before publishing the filing. The wrong-organisation-number rejection test is correct and was retained. The necessary importer/authoritative organisation binding lies outside the write set. Authorize that script and any verified identity metadata needed; never invent an organisation number or weaken the rejection assertion.

Result: 0 passed; 1 owner-decision failures. Tests:

- `tests/test_norway_official_filing.py::test_wrong_issuer_and_orgnr_are_rejected`

### D4: NEEDS_OPUS_DECISION: hardcoded diagnostic issuer

The guard reports scripts/diag/owner_identity_migration.py containing an unapproved hardcoded MORG issuer. That script is outside the write set. Owner must authorize replacing the legacy diagnostic identifier with canonical registry-driven identity. The test and registry were retained.

Result: 0 passed; 1 owner-decision failures. Tests:

- `tests/test_sparebank_onboarding.py::test_source_has_no_hardcoded_sparebank_issuer_table`

### D5: NEEDS_OPUS_DECISION: stale offline-smoke identity

scripts/smoke_app.py requires AURG.isin == needs_verification; configs/universe.yaml now records the verified ISIN NO0006001601 and isin_status=verified. The UI preserves canonical identity correctly. Authorize retargeting the script to the current verified registry; do not corrupt the registry or invent an identifier. The initial unregistered import-type key issue was removed; the smoke now reaches this independent identity failure.

Result: 0 passed; 1 owner-decision failures. Tests:

- `tests/issue0014/test_browser_workflows.py::test_real_loopback_http_startup_uses_offline_source_smoke`

### D6: NEEDS_OPUS_DECISION: documentation outside the write set

Generated reconciliation current-state-diff/package-discrepancies and data-dictionary outputs are stale; release stamps include a display version where the existing checks require the exact canonical stamp. Tutorials still name removed actions and the methodology index omits architecture/sparebank-book-gap-2026-10.md. Necessary documentation/generator outputs are outside the sole allowed handoff document. Authorize exact documentation updates/generation after the source checkpoint; do not weaken source-label, release-version or offline freshness assertions.

Result: 0 passed; 6 owner-decision failures. Tests:

- `tests/test_b00_control_plane.py::test_completion_document_check_is_offline_and_fresh`
- `tests/test_documentation_integrity.py::test_data_dictionary_version_matches_project_release`
- `tests/test_documentation_integrity.py::test_generated_documentation_has_no_drift`
- `tests/test_user_documentation.py::test_documentation_release_stamps_match_project_version`
- `tests/test_user_documentation.py::test_documented_on_screen_labels_exist_in_application_source`
- `tests/test_user_documentation.py::test_methodology_index_links_every_architecture_and_sdd_page`

### D7: NEEDS_OPUS_DECISION: old layout contracts versus current page design

The current Signals page has a four-item KPI strip and truthful unavailable empty evidence rather than five old responsive summary cards; Screener has screen/stock-quality summaries and no old global _summary helper. What Changed intentionally renders a kit table/selected path rather than the old responsive instrument cards. Onboarding uses a four-step flow rather than a first-page save/date plus three collapsed ExpansionTiles. These structural/semantic assertions cannot be mechanically retargeted with equal strength. Owner must choose restoring the old layout contracts or specify equally strong contracts for the current design. All four assertions/tests remain unchanged.

Result: 0 passed; 4 owner-decision failures. Tests:

- `tests/test_responsive_summary_pages.py::test_summary_cards_reflow_natively_and_keep_session[/screener]`
- `tests/test_responsive_summary_pages.py::test_summary_cards_reflow_natively_and_keep_session[/signals]`
- `tests/test_task17_ui_contracts.py::test_what_changed_uses_compact_responsive_instrument_cards_without_horizontal_table`
- `tests/test_u1_home_pages.py::test_onboarding_leads_with_setup_and_discloses_details`

## Exact checks and results

All pytest commands below use the environment PYTHONPATH=C:/Users/thor2/AppData/Local/Temp. XML/log artifacts are runner-only files in that directory.

The initial run executed all 66 failing test files in one invocation on the resumed pre-correction state: 1,045 tests, 912 pass markers, 132 failures and one pre-existing Windows symlink skip; exit 1. Counts were reconstructed from progress markers and corroborated by 132 FAILED summary entries because double-quiet output omitted a count summary. This historical result is not acceptance evidence for the completed source.

Initial command family: `python -m pytest -q --tb=line -p no:cacheprovider` with all 66 distinct files from the node inventory below. Original target order/additional argv are UNVERIFIED; this historical check is not reused for final acceptance. Log: `t-gate-initial-2.txt`.

```text
python -m pytest -q --tb=line -p no:cacheprovider tests/test_task19_instrument_detail.py tests/test_valuation_workspace_lifecycle.py tests/test_operations_workspace.py tests/bughunt/test_repro_s10.py tests/bughunt/test_repro_s11.py --junitxml=C:\Users\thor2\AppData\Local\Temp\t-gate-focus3.xml
```
Result: 177 passed, 9 failed, 0 skipped, 0 errors (186 collected).

```text
python -m pytest -q --tb=line -p no:cacheprovider tests/test_operations_workspace.py tests/bughunt/test_repro_s1.py tests/bughunt/test_repro_s10.py tests/bughunt/test_repro_s11.py tests/test_startup_lazy.py tests/test_ui_staged_rendering.py tests/test_onboarding.py tests/test_data_health.py tests/test_macro_factors_ui.py tests/test_credentials.py tests/test_backup_restore.py tests/test_robust_risk.py --junitxml=C:\Users\thor2\AppData\Local\Temp\t-gate-focused4.xml
```
Result: 183 passed, 3 failed, 1 skipped, 0 errors (187 collected).

```text
python -m pytest -q --tb=line -p no:cacheprovider tests/test_data_health.py tests/test_credentials.py tests/test_backup_restore.py --junitxml=C:\Users\thor2\AppData\Local\Temp\t-gate-focused5.xml
```
Result: 61 passed, 1 failed, 0 skipped, 0 errors (62 collected).

```text
python -m pytest -q --tb=line -p no:cacheprovider tests/test_data_health.py --junitxml=C:\Users\thor2\AppData\Local\Temp\t-gate-focused6.xml
```
Result: 18 passed, 1 failed, 0 skipped, 0 errors (19 collected).

```text
python -m pytest -q --tb=line -p no:cacheprovider tests/test_import_layering.py --junitxml=C:\Users\thor2\AppData\Local\Temp\t-gate-layering.xml
```
Result: 5 passed, 1 failed, 0 skipped, 0 errors (6 collected).

```text
python -m pytest -q --tb=line -p no:cacheprovider tests/test_candles.py tests/test_import_layering.py tests/test_issue0032_broker_architecture.py tests/test_issue_0053_digest.py tests/test_supply_chain_scan.py tests/test_portfolio_import_ui.py tests/test_task17_ui_contracts.py tests/test_data_health.py --junitxml=C:\Users\thor2\AppData\Local\Temp\t-gate-focused7.xml
```
Result: 82 passed, 4 failed, 0 skipped, 0 errors (86 collected).

```text
python -m pytest -q --tb=line -p no:cacheprovider tests/test_candles.py tests/test_data_health.py tests/test_issue0032_broker_architecture.py tests/test_task19_instrument_detail.py tests/test_trust_critical_artifacts.py tests/bughunt/test_repro_s11.py tests/test_credentials.py tests/test_supply_chain_scan.py --junitxml=C:\Users\thor2\AppData\Local\Temp\t-gate-focused8.xml
```
Result: 242 passed, 1 failed, 0 skipped, 0 errors (243 collected).

```text
python -m pytest -q --tb=line -p no:cacheprovider tests/test_data_health.py tests/test_trust_critical_artifacts.py --junitxml=C:\Users\thor2\AppData\Local\Temp\t-gate-focused9.xml
```
Result: 45 passed, 0 failed, 0 skipped, 0 errors (45 collected).

```text
python -m pytest -q --tb=line -p no:cacheprovider tests/test_candles.py --junitxml=C:\Users\thor2\AppData\Local\Temp\t-gate-focused10.xml
```
Result: 13 passed, 0 failed, 0 skipped, 0 errors (13 collected).

```text
python -m pytest -q --tb=line -p no:cacheprovider tests/issue0014/test_browser_workflows.py::test_real_loopback_http_startup_uses_offline_source_smoke --junitxml=C:\Users\thor2\AppData\Local\Temp\t-gate-browser-final.xml
```
Result: 0 passed, 1 failed, 0 skipped, 0 errors (1 collected).

The only focused-batch skip is the existing unlisted `tests/test_onboarding.py::test_descendant_symlink_fails_before_onboarding_writes`: `directory symlinks are unavailable on this platform`. No listed node was skipped. `tests/bughunt/test_repro_s3.py` has no node in the supplied list and was not run.

Two diagnostic cache runs exercised `tests/test_backtest_lab.py::test_backtest_service_reuses_quality_momentum_cache_after_persistence` with `-p gate_trace_plugin`, each 0 passed/1 failed before the cache root correction; the plugin was temporary runner instrumentation. Remaining historical argv are UNVERIFIED. The final list verifies all four listed cache tests with the plugin absent.

Earlier full listed run: 108 passed, 36 failed, 0 skipped, 0 errors; 144 collected.

Completed implementation full listed run: 121 passed, 23 failed, 0 skipped, 0 errors; 144 collected.

The full-list commands use exactly the inventory below (all 144 nodes). The earlier XML argument was `--junitxml=C:/Users/thor2/AppData/Local/Temp/t-gate-final-list.xml`; the completed-implementation XML argument is `--junitxml=C:/Users/thor2/AppData/Local/Temp/t-gate-completed-list.xml`. The completed command ran through subprocess.run with a 1,800-second timeout. The browser-only check used a 360-second timeout.

Exact completed full-list argv:

```json
[
  "python",
  "-m",
  "pytest",
  "-q",
  "--tb=line",
  "-p",
  "no:cacheprovider",
  "tests/bughunt/test_fix_p_extras.py::test_s8_03_serialized_appends_preserve_both_runs",
  "tests/bughunt/test_repro_s10.py::test_s10_05_save_uses_current_controls",
  "tests/bughunt/test_repro_s10.py::test_s10_08_strategy_can_toggle_twice_without_navigation",
  "tests/bughunt/test_repro_s11.py::test_s11_01_operation_worker_is_scoped_to_its_workflow",
  "tests/bughunt/test_repro_s11.py::test_s11_02_failed_job_is_not_recorded_completed",
  "tests/bughunt/test_repro_s11.py::test_s11_03_portfolio_context_includes_all_holdings",
  "tests/bughunt/test_repro_s11.py::test_s11_04_cancelled_worker_preserves_new_preview",
  "tests/bughunt/test_repro_s11.py::test_s11_05_comparison_workspace_save_accepts_snapshot_date",
  "tests/bughunt/test_repro_s11.py::test_s11_06_browser_import_uses_selected_bytes",
  "tests/bughunt/test_repro_s11.py::test_s11_07_completed_llm_audit_is_not_shown_as_unrun",
  "tests/bughunt/test_repro_s1.py::test_s1_07_equal_partial_fill_actions_not_silently_dropped",
  "tests/bughunt/test_repro_s8.py::test_s8_02_existing_unreadable_history_blocks_append",
  "tests/issue0014/test_browser_workflows.py::test_real_loopback_http_startup_uses_offline_source_smoke",
  "tests/refactor_parity/test_backtest_golden.py::test_backtest_matches_golden",
  "tests/refactor_parity/test_clock_independence.py::test_goldens_do_not_depend_on_the_wall_clock[backtest]",
  "tests/refactor_parity/test_clock_independence.py::test_goldens_do_not_depend_on_the_wall_clock[persisted_schema]",
  "tests/refactor_parity/test_clock_independence.py::test_goldens_do_not_depend_on_the_wall_clock[scoreboard]",
  "tests/refactor_parity/test_clock_independence.py::test_goldens_do_not_depend_on_the_wall_clock[snapshot]",
  "tests/refactor_parity/test_persisted_schema_golden.py::test_persisted_schema_golden_covers_the_required_families",
  "tests/refactor_parity/test_persisted_schema_golden.py::test_persisted_schemas_match_golden",
  "tests/refactor_parity/test_scoreboard_golden.py::test_scoreboard_golden_is_not_vacuous",
  "tests/refactor_parity/test_scoreboard_golden.py::test_scoreboard_matches_golden",
  "tests/refactor_parity/test_snapshot_golden.py::test_snapshot_digest_matches_golden",
  "tests/release/test_frozen_layout.py::test_no_module_derives_configs_from_file_parents",
  "tests/test_accessible_tables.py::test_backtests_page_connects_real_chart_and_accessible_table_helpers",
  "tests/test_accessible_tables.py::test_settings_page_documents_issue_0044_packaged_update_workflow",
  "tests/test_application_api.py::test_jobs_page_consumes_application_api_view_models",
  "tests/test_b00_control_plane.py::test_completion_document_check_is_offline_and_fresh",
  "tests/test_backtest_lab.py::test_backtest_cache_reader_uses_one_complete_snapshot_under_interleaving",
  "tests/test_backtest_lab.py::test_backtest_service_reuses_mixed_availability_integer_diagnostics",
  "tests/test_backtest_lab.py::test_backtest_service_reuses_quality_momentum_cache_after_persistence",
  "tests/test_backtest_lab.py::test_backtest_service_round_trips_genuinely_unavailable_operational_rows",
  "tests/test_backup_restore.py::test_commit_restore_rechecks_companions_after_preview",
  "tests/test_backup_restore.py::test_encrypted_partial_preview_checks_destination_consistency",
  "tests/test_backup_restore.py::test_settings_revision_mismatch_is_rejected_before_writes",
  "tests/test_candles.py::test_instrument_detail_renders_candle_evidence_section",
  "tests/test_credentials.py::test_settings_saves_resolves_and_deletes_credentials_by_active_provider_id",
  "tests/test_cyclical_sector_adapters.py::test_default_facade_selector_state_render_and_ui_metadata",
  "tests/test_data_health.py::test_data_health_export_failure_is_visible_and_refreshes_page",
  "tests/test_data_health.py::test_data_health_ui_names_cache_provenance_and_failure_columns",
  "tests/test_documentation_integrity.py::test_data_dictionary_version_matches_project_release",
  "tests/test_documentation_integrity.py::test_generated_documentation_has_no_drift",
  "tests/test_e2e_advanced.py::test_portfolio_import_and_reconcile_source_controls",
  "tests/test_e2e_advanced.py::test_settings_page_previews_and_saves_local_settings",
  "tests/test_etf_economics.py::test_etf_economics_ui_renders_scalar_tracking_coverage",
  "tests/test_financial_sector_adapters.py::test_verified_available_projection_flows_facade_selector_and_page_contract",
  "tests/test_fixed_income_market_data.py::test_selector_and_page_expose_non_executable_market_data",
  "tests/test_flet_startup.py::test_native_queued_navigation_has_one_render_owner",
  "tests/test_frontend_design_system.py::test_dashboard_summary_cards_are_inherently_responsive",
  "tests/test_frontend_design_system.py::test_shell_command_palette_filters_and_navigates",
  "tests/test_import_export.py::test_settings_references_actual_version_and_changelog_files",
  "tests/test_import_layering.py::test_no_new_layering_violations",
  "tests/test_innovation_sector_adapters.py::test_formula_registry_and_verified_ui_projection_are_versioned_and_fail_closed",
  "tests/test_issue0010_instrument_detail.py::test_issue0010_instrument_detail_exposes_non_executable_thesis_diary",
  "tests/test_issue0032_broker_architecture.py::test_system_map_exposes_future_only_architecture_without_action_control",
  "tests/test_issue_0053_digest.py::test_dashboard_generation_keeps_each_accepted_category_visible",
  "tests/test_issue_0053_digest.py::test_dashboard_uses_one_cutoff_and_complete_alert_population",
  "tests/test_issue_0104_corrections.py::test_real_260_session_backtest_accepts_structural_holdings",
  "tests/test_macro_factors_ui.py::test_macro_factors_workspace_is_registered_and_declares_safe_boundaries",
  "tests/test_macro_factors_ui.py::test_macro_page_binds_every_producer_to_snapshot_cutoff_and_renders_lineage",
  "tests/test_macro_factors_ui.py::test_macro_page_fails_closed_with_explicit_unavailable_when_cutoff_missing",
  "tests/test_news_ui.py::test_dashboard_news_digest_shows_unavailable_or_canonical_context",
  "tests/test_norway_official_filing.py::test_wrong_issuer_and_orgnr_are_rejected",
  "tests/test_onboarding.py::test_onboarding_save_reloads_active_state",
  "tests/test_onboarding.py::test_onboarding_ui_exposes_opt_in_online_validator_seam",
  "tests/test_onboarding.py::test_online_toggle_is_disabled_without_validator",
  "tests/test_onboarding.py::test_ui_typed_quota_result_is_visible_and_saves_offline_setup",
  "tests/test_operations_workspace.py::test_cancelled_paper_preview_stays_cancelled",
  "tests/test_operations_workspace.py::test_operations_explicit_policy_disables_confirmation_on_missing_calendar",
  "tests/test_operations_workspace.py::test_operations_workspace_can_open_local_paper_account",
  "tests/test_operations_workspace.py::test_operations_workspace_exposes_paper_live_training_and_audit_states",
  "tests/test_operations_workspace.py::test_paper_preview_starts_once_and_reaches_a_durable_result",
  "tests/test_operations_workspace.py::test_proposal_review_records_manual_review_until_immutable_evidence_exists",
  "tests/test_portfolio_import_ui.py::test_portfolio_import_controls_are_registered_and_non_executable",
  "tests/test_real_asset_sector_adapters.py::test_projection_flows_through_selector_state_and_page",
  "tests/test_responsive_summary_pages.py::test_summary_cards_reflow_natively_and_keep_session[/screener]",
  "tests/test_responsive_summary_pages.py::test_summary_cards_reflow_natively_and_keep_session[/signals]",
  "tests/test_robust_risk.py::test_risk_workspace_surfaces_robust_risk_evidence",
  "tests/test_run_changes.py::test_run_comparison_can_load_history_by_run_ids",
  "tests/test_score_history.py::test_classification_override_invalidates_canonical_history_read_but_preserves_raw_audit_row",
  "tests/test_score_history.py::test_empty_complete_run_replaces_only_supplied_run_rows",
  "tests/test_score_history.py::test_invalid_history_rows_are_dropped_without_crashing",
  "tests/test_score_history.py::test_score_history_append_is_idempotent_by_run_and_snapshot",
  "tests/test_score_history.py::test_score_history_append_normalises_legacy_store_before_duplicate_detection",
  "tests/test_score_history.py::test_score_history_preserves_run_dimensions_and_never_grants_execution_authority",
  "tests/test_score_history.py::test_score_history_publishes_paired_csv_and_rolls_back_on_group_failure",
  "tests/test_score_history.py::test_score_history_replaces_changed_snapshot_for_same_run_without_duplicate_instruments",
  "tests/test_settings_run_publication.py::test_feature_service_does_not_use_first_enabled_instrument_as_benchmark",
  "tests/test_sparebank_certification.py::test_teaching_bank_production_route_exposes_scorecard_and_workspace",
  "tests/test_sparebank_native_score_display.py::test_latest_sparebank_scores_takes_latest_native_run",
  "tests/test_sparebank_onboarding.py::test_source_has_no_hardcoded_sparebank_issuer_table",
  "tests/test_startup_lazy.py::test_backtest_route_loads_on_worker_behind_loading_shell",
  "tests/test_startup_lazy.py::test_snapshot_defers_backtest_and_lazy_result_matches_eager_result",
  "tests/test_statement_normalisation.py::test_fundamentals_surface_exposes_reported_and_restated_statement_history",
  "tests/test_supply_chain_scan.py::test_settings_page_exposes_update_verification_and_notices",
  "tests/test_task17_ui_contracts.py::test_what_changed_exposes_instrument_search_and_dimension_filters",
  "tests/test_task17_ui_contracts.py::test_what_changed_uses_compact_responsive_instrument_cards_without_horizontal_table",
  "tests/test_task18_ui.py::test_instrument_detail_friction_non_finite_values_are_unavailable",
  "tests/test_task18_ui.py::test_instrument_detail_renders_cost_edge_fields",
  "tests/test_task18_ui.py::test_risk_crowding_counts_distinct_explicit_warning_cluster_ids",
  "tests/test_task18_ui.py::test_risk_friction_panel_formats_non_finite_edge_values_as_unavailable",
  "tests/test_task18_ui.py::test_risk_page_renders_cost_edge_fields_and_unavailable_state",
  "tests/test_task19_instrument_detail.py::test_crowding_attribution_renders_canonical_broad_alpha_value",
  "tests/test_task19_instrument_detail.py::test_detail_disclosure_keeps_every_record_and_bounds_scroll",
  "tests/test_task19_instrument_detail.py::test_fundamentals_panel_renders_complete_five_section_provenance",
  "tests/test_task19_instrument_detail.py::test_instrument_detail_exposes_functional_export_control_and_disabled_state",
  "tests/test_task19_instrument_detail.py::test_instrument_detail_reads_holdings_csv_mirror_when_parquet_is_unavailable",
  "tests/test_task19_instrument_detail.py::test_instrument_detail_registers_visible_fundamentals_acceptance_surface",
  "tests/test_task19_instrument_detail.py::test_metric_history_local_route_preserves_all_scoped_components[VWCE]",
  "tests/test_task19_instrument_detail.py::test_metric_history_local_route_preserves_all_scoped_components[metric-stock]",
  "tests/test_task19_instrument_detail.py::test_score_panel_nullable_scoreboard_and_signal_values_fail_closed",
  "tests/test_task19_instrument_detail.py::test_valuation_invalid_selected_evidence_blocks_panel[available_at-0000-not-a-date]",
  "tests/test_task19_instrument_detail.py::test_valuation_invalid_selected_evidence_blocks_panel[available_at-2026-07-01T08:00:00]",
  "tests/test_task19_instrument_detail.py::test_valuation_invalid_selected_evidence_blocks_panel[available_at-None]",
  "tests/test_task19_instrument_detail.py::test_valuation_invalid_selected_evidence_blocks_panel[end-bad_value6]",
  "tests/test_task19_instrument_detail.py::test_valuation_invalid_selected_evidence_blocks_panel[end-not-a-date]",
  "tests/test_task19_instrument_detail.py::test_valuation_invalid_selected_evidence_blocks_panel[value-True]",
  "tests/test_task19_instrument_detail.py::test_valuation_invalid_selected_evidence_blocks_panel[value-inf]",
  "tests/test_task19_instrument_detail.py::test_valuation_invalid_selected_evidence_blocks_panel[value-nan]",
  "tests/test_task19_instrument_detail.py::test_valuation_scenario_controls_are_local_and_invalidate",
  "tests/test_task19_instrument_detail.py::test_valuation_visible_in_detail_for_stock_and_etf[etf]",
  "tests/test_task19_instrument_detail.py::test_valuation_workspace_native_dialog_session_and_focus",
  "tests/test_trust_critical_artifacts.py::test_diagnostics_ui_displays_redacted_exception_fingerprint",
  "tests/test_u1_home_pages.py::test_onboarding_leads_with_setup_and_discloses_details",
  "tests/test_u1_home_pages.py::test_summary_kpis_have_stable_keys_and_no_inline_as_of",
  "tests/test_u7_lab_pages.py::test_panel_uses_kit_glass_with_key_and_label",
  "tests/test_ui_staged_rendering.py::test_deferred_pageview_rebuilds_shell_after_the_placeholder",
  "tests/test_ui_staged_rendering.py::test_deferred_section_is_filled_after_the_placeholder_is_painted",
  "tests/test_user_documentation.py::test_documentation_release_stamps_match_project_version",
  "tests/test_user_documentation.py::test_documented_on_screen_labels_exist_in_application_source",
  "tests/test_user_documentation.py::test_methodology_index_links_every_architecture_and_sdd_page",
  "tests/test_valuation_workspace_lifecycle.py::test_real_shell_render_discards_only_owned_workspace[/instrument/NEW]",
  "tests/test_valuation_workspace_lifecycle.py::test_real_shell_render_discards_only_owned_workspace[/instrument/OLD]",
  "tests/test_valuation_workspace_lifecycle.py::test_repeated_workspace_dismissal_releases_sessions[False]",
  "tests/test_valuation_workspace_lifecycle.py::test_repeated_workspace_dismissal_releases_sessions[True]",
  "tests/test_workflow_runtime.py::test_primary_dashboard_workflows_are_keyboard_operable_buttons",
  "tests/ui/test_decision_journal_ui.py::test_decision_journal_is_local_only_with_one_primary_save_action",
  "tests/ui/test_portfolio_b_restyle_ui.py::test_page_uses_kit_panels_with_deterministic_unique_keys[decision-journal]",
  "tests/ui/test_portfolio_b_restyle_ui.py::test_page_uses_kit_panels_with_deterministic_unique_keys[forward-evidence]",
  "tests/ui/test_portfolio_b_restyle_ui.py::test_page_uses_kit_panels_with_deterministic_unique_keys[operations]",
  "tests/ui/test_portfolio_b_restyle_ui.py::test_page_uses_kit_panels_with_deterministic_unique_keys[portfolio-optimiser]",
  "tests/ui/test_portfolio_b_restyle_ui.py::test_page_uses_kit_panels_with_deterministic_unique_keys[risk]",
  "tests/ui/test_portfolio_b_restyle_ui.py::test_page_uses_kit_panels_with_deterministic_unique_keys[stress-lab]",
  "tests/ui/test_u6_universe_map_ui.py::test_catalogue_unreadable_state_is_honest",
  "--junitxml=C:\\Users\\thor2\\AppData\\Local\\Temp\\t-gate-completed-list.xml"
]
```

## Every listed node

| Test | Result | Root cause / owner decision | Evidence XML |
| --- | --- | --- | --- |
| `tests/bughunt/test_fix_p_extras.py::test_s8_03_serialized_appends_preserve_both_runs` | PASS | G1 | `t-gate-completed-list.xml` |
| `tests/bughunt/test_repro_s10.py::test_s10_05_save_uses_current_controls` | PASS | G7 | `t-gate-completed-list.xml` |
| `tests/bughunt/test_repro_s10.py::test_s10_08_strategy_can_toggle_twice_without_navigation` | PASS | G7 | `t-gate-completed-list.xml` |
| `tests/bughunt/test_repro_s11.py::test_s11_01_operation_worker_is_scoped_to_its_workflow` | PASS | G4 | `t-gate-completed-list.xml` |
| `tests/bughunt/test_repro_s11.py::test_s11_02_failed_job_is_not_recorded_completed` | PASS | G4 | `t-gate-completed-list.xml` |
| `tests/bughunt/test_repro_s11.py::test_s11_03_portfolio_context_includes_all_holdings` | PASS | G4 | `t-gate-completed-list.xml` |
| `tests/bughunt/test_repro_s11.py::test_s11_04_cancelled_worker_preserves_new_preview` | PASS | G4 | `t-gate-completed-list.xml` |
| `tests/bughunt/test_repro_s11.py::test_s11_05_comparison_workspace_save_accepts_snapshot_date` | PASS | G7 | `t-gate-completed-list.xml` |
| `tests/bughunt/test_repro_s11.py::test_s11_06_browser_import_uses_selected_bytes` | PASS | G6 | `t-gate-completed-list.xml` |
| `tests/bughunt/test_repro_s11.py::test_s11_07_completed_llm_audit_is_not_shown_as_unrun` | PASS | G7 | `t-gate-completed-list.xml` |
| `tests/bughunt/test_repro_s1.py::test_s1_07_equal_partial_fill_actions_not_silently_dropped` | PASS | G4 | `t-gate-completed-list.xml` |
| `tests/bughunt/test_repro_s8.py::test_s8_02_existing_unreadable_history_blocks_append` | PASS | G1 | `t-gate-completed-list.xml` |
| `tests/issue0014/test_browser_workflows.py::test_real_loopback_http_startup_uses_offline_source_smoke` | NEEDS_OPUS_DECISION | D5 | `t-gate-completed-list.xml` |
| `tests/refactor_parity/test_backtest_golden.py::test_backtest_matches_golden` | NEEDS_OPUS_DECISION | D1 | `t-gate-completed-list.xml` |
| `tests/refactor_parity/test_clock_independence.py::test_goldens_do_not_depend_on_the_wall_clock[backtest]` | NEEDS_OPUS_DECISION | D1 | `t-gate-completed-list.xml` |
| `tests/refactor_parity/test_clock_independence.py::test_goldens_do_not_depend_on_the_wall_clock[persisted_schema]` | NEEDS_OPUS_DECISION | D1 | `t-gate-completed-list.xml` |
| `tests/refactor_parity/test_clock_independence.py::test_goldens_do_not_depend_on_the_wall_clock[scoreboard]` | NEEDS_OPUS_DECISION | D1 | `t-gate-completed-list.xml` |
| `tests/refactor_parity/test_clock_independence.py::test_goldens_do_not_depend_on_the_wall_clock[snapshot]` | NEEDS_OPUS_DECISION | D1 | `t-gate-completed-list.xml` |
| `tests/refactor_parity/test_persisted_schema_golden.py::test_persisted_schema_golden_covers_the_required_families` | NEEDS_OPUS_DECISION | D1 | `t-gate-completed-list.xml` |
| `tests/refactor_parity/test_persisted_schema_golden.py::test_persisted_schemas_match_golden` | NEEDS_OPUS_DECISION | D1 | `t-gate-completed-list.xml` |
| `tests/refactor_parity/test_scoreboard_golden.py::test_scoreboard_golden_is_not_vacuous` | NEEDS_OPUS_DECISION | D2 | `t-gate-completed-list.xml` |
| `tests/refactor_parity/test_scoreboard_golden.py::test_scoreboard_matches_golden` | NEEDS_OPUS_DECISION | D1 | `t-gate-completed-list.xml` |
| `tests/refactor_parity/test_snapshot_golden.py::test_snapshot_digest_matches_golden` | NEEDS_OPUS_DECISION | D1 | `t-gate-completed-list.xml` |
| `tests/release/test_frozen_layout.py::test_no_module_derives_configs_from_file_parents` | PASS | G9 | `t-gate-completed-list.xml` |
| `tests/test_accessible_tables.py::test_backtests_page_connects_real_chart_and_accessible_table_helpers` | PASS | G7 | `t-gate-completed-list.xml` |
| `tests/test_accessible_tables.py::test_settings_page_documents_issue_0044_packaged_update_workflow` | PASS | G7 | `t-gate-completed-list.xml` |
| `tests/test_application_api.py::test_jobs_page_consumes_application_api_view_models` | PASS | G7 | `t-gate-completed-list.xml` |
| `tests/test_b00_control_plane.py::test_completion_document_check_is_offline_and_fresh` | NEEDS_OPUS_DECISION | D6 | `t-gate-completed-list.xml` |
| `tests/test_backtest_lab.py::test_backtest_cache_reader_uses_one_complete_snapshot_under_interleaving` | PASS | G2 | `t-gate-completed-list.xml` |
| `tests/test_backtest_lab.py::test_backtest_service_reuses_mixed_availability_integer_diagnostics` | PASS | G2 | `t-gate-completed-list.xml` |
| `tests/test_backtest_lab.py::test_backtest_service_reuses_quality_momentum_cache_after_persistence` | PASS | G2 | `t-gate-completed-list.xml` |
| `tests/test_backtest_lab.py::test_backtest_service_round_trips_genuinely_unavailable_operational_rows` | PASS | G2 | `t-gate-completed-list.xml` |
| `tests/test_backup_restore.py::test_commit_restore_rechecks_companions_after_preview` | PASS | G7 | `t-gate-completed-list.xml` |
| `tests/test_backup_restore.py::test_encrypted_partial_preview_checks_destination_consistency` | PASS | G7 | `t-gate-completed-list.xml` |
| `tests/test_backup_restore.py::test_settings_revision_mismatch_is_rejected_before_writes` | PASS | G7 | `t-gate-completed-list.xml` |
| `tests/test_candles.py::test_instrument_detail_renders_candle_evidence_section` | PASS | G3 | `t-gate-completed-list.xml` |
| `tests/test_credentials.py::test_settings_saves_resolves_and_deletes_credentials_by_active_provider_id` | PASS | G11 | `t-gate-completed-list.xml` |
| `tests/test_cyclical_sector_adapters.py::test_default_facade_selector_state_render_and_ui_metadata` | PASS | G3 | `t-gate-completed-list.xml` |
| `tests/test_data_health.py::test_data_health_export_failure_is_visible_and_refreshes_page` | PASS | G11 | `t-gate-completed-list.xml` |
| `tests/test_data_health.py::test_data_health_ui_names_cache_provenance_and_failure_columns` | PASS | G11 | `t-gate-completed-list.xml` |
| `tests/test_documentation_integrity.py::test_data_dictionary_version_matches_project_release` | NEEDS_OPUS_DECISION | D6 | `t-gate-completed-list.xml` |
| `tests/test_documentation_integrity.py::test_generated_documentation_has_no_drift` | NEEDS_OPUS_DECISION | D6 | `t-gate-completed-list.xml` |
| `tests/test_e2e_advanced.py::test_portfolio_import_and_reconcile_source_controls` | PASS | G7 | `t-gate-completed-list.xml` |
| `tests/test_e2e_advanced.py::test_settings_page_previews_and_saves_local_settings` | PASS | G7 | `t-gate-completed-list.xml` |
| `tests/test_etf_economics.py::test_etf_economics_ui_renders_scalar_tracking_coverage` | PASS | G3 | `t-gate-completed-list.xml` |
| `tests/test_financial_sector_adapters.py::test_verified_available_projection_flows_facade_selector_and_page_contract` | PASS | G3 | `t-gate-completed-list.xml` |
| `tests/test_fixed_income_market_data.py::test_selector_and_page_expose_non_executable_market_data` | PASS | G3 | `t-gate-completed-list.xml` |
| `tests/test_flet_startup.py::test_native_queued_navigation_has_one_render_owner` | PASS | G8 | `t-gate-completed-list.xml` |
| `tests/test_frontend_design_system.py::test_dashboard_summary_cards_are_inherently_responsive` | PASS | G7 | `t-gate-completed-list.xml` |
| `tests/test_frontend_design_system.py::test_shell_command_palette_filters_and_navigates` | PASS | G7 | `t-gate-completed-list.xml` |
| `tests/test_import_export.py::test_settings_references_actual_version_and_changelog_files` | PASS | G6 | `t-gate-completed-list.xml` |
| `tests/test_import_layering.py::test_no_new_layering_violations` | PASS | G10 | `t-gate-completed-list.xml` |
| `tests/test_innovation_sector_adapters.py::test_formula_registry_and_verified_ui_projection_are_versioned_and_fail_closed` | PASS | G3 | `t-gate-completed-list.xml` |
| `tests/test_issue0010_instrument_detail.py::test_issue0010_instrument_detail_exposes_non_executable_thesis_diary` | PASS | G3 | `t-gate-completed-list.xml` |
| `tests/test_issue0032_broker_architecture.py::test_system_map_exposes_future_only_architecture_without_action_control` | PASS | G7 | `t-gate-completed-list.xml` |
| `tests/test_issue_0053_digest.py::test_dashboard_generation_keeps_each_accepted_category_visible` | PASS | G7 | `t-gate-completed-list.xml` |
| `tests/test_issue_0053_digest.py::test_dashboard_uses_one_cutoff_and_complete_alert_population` | PASS | G7 | `t-gate-completed-list.xml` |
| `tests/test_issue_0104_corrections.py::test_real_260_session_backtest_accepts_structural_holdings` | PASS | G2 | `t-gate-completed-list.xml` |
| `tests/test_macro_factors_ui.py::test_macro_factors_workspace_is_registered_and_declares_safe_boundaries` | PASS | G5 | `t-gate-completed-list.xml` |
| `tests/test_macro_factors_ui.py::test_macro_page_binds_every_producer_to_snapshot_cutoff_and_renders_lineage` | PASS | G5 | `t-gate-completed-list.xml` |
| `tests/test_macro_factors_ui.py::test_macro_page_fails_closed_with_explicit_unavailable_when_cutoff_missing` | PASS | G5 | `t-gate-completed-list.xml` |
| `tests/test_news_ui.py::test_dashboard_news_digest_shows_unavailable_or_canonical_context` | PASS | G7 | `t-gate-completed-list.xml` |
| `tests/test_norway_official_filing.py::test_wrong_issuer_and_orgnr_are_rejected` | NEEDS_OPUS_DECISION | D3 | `t-gate-completed-list.xml` |
| `tests/test_onboarding.py::test_onboarding_save_reloads_active_state` | PASS | G11 | `t-gate-completed-list.xml` |
| `tests/test_onboarding.py::test_onboarding_ui_exposes_opt_in_online_validator_seam` | PASS | G11 | `t-gate-completed-list.xml` |
| `tests/test_onboarding.py::test_online_toggle_is_disabled_without_validator` | PASS | G11 | `t-gate-completed-list.xml` |
| `tests/test_onboarding.py::test_ui_typed_quota_result_is_visible_and_saves_offline_setup` | PASS | G11 | `t-gate-completed-list.xml` |
| `tests/test_operations_workspace.py::test_cancelled_paper_preview_stays_cancelled` | PASS | G4 | `t-gate-completed-list.xml` |
| `tests/test_operations_workspace.py::test_operations_explicit_policy_disables_confirmation_on_missing_calendar` | PASS | G4 | `t-gate-completed-list.xml` |
| `tests/test_operations_workspace.py::test_operations_workspace_can_open_local_paper_account` | PASS | G4 | `t-gate-completed-list.xml` |
| `tests/test_operations_workspace.py::test_operations_workspace_exposes_paper_live_training_and_audit_states` | PASS | G4 | `t-gate-completed-list.xml` |
| `tests/test_operations_workspace.py::test_paper_preview_starts_once_and_reaches_a_durable_result` | PASS | G4 | `t-gate-completed-list.xml` |
| `tests/test_operations_workspace.py::test_proposal_review_records_manual_review_until_immutable_evidence_exists` | PASS | G4 | `t-gate-completed-list.xml` |
| `tests/test_portfolio_import_ui.py::test_portfolio_import_controls_are_registered_and_non_executable` | PASS | G7 | `t-gate-completed-list.xml` |
| `tests/test_real_asset_sector_adapters.py::test_projection_flows_through_selector_state_and_page` | PASS | G3 | `t-gate-completed-list.xml` |
| `tests/test_responsive_summary_pages.py::test_summary_cards_reflow_natively_and_keep_session[/screener]` | NEEDS_OPUS_DECISION | D7 | `t-gate-completed-list.xml` |
| `tests/test_responsive_summary_pages.py::test_summary_cards_reflow_natively_and_keep_session[/signals]` | NEEDS_OPUS_DECISION | D7 | `t-gate-completed-list.xml` |
| `tests/test_robust_risk.py::test_risk_workspace_surfaces_robust_risk_evidence` | PASS | G5 | `t-gate-completed-list.xml` |
| `tests/test_run_changes.py::test_run_comparison_can_load_history_by_run_ids` | PASS | G1 | `t-gate-completed-list.xml` |
| `tests/test_score_history.py::test_classification_override_invalidates_canonical_history_read_but_preserves_raw_audit_row` | PASS | G1 | `t-gate-completed-list.xml` |
| `tests/test_score_history.py::test_empty_complete_run_replaces_only_supplied_run_rows` | PASS | G1 | `t-gate-completed-list.xml` |
| `tests/test_score_history.py::test_invalid_history_rows_are_dropped_without_crashing` | PASS | G1 | `t-gate-completed-list.xml` |
| `tests/test_score_history.py::test_score_history_append_is_idempotent_by_run_and_snapshot` | PASS | G1 | `t-gate-completed-list.xml` |
| `tests/test_score_history.py::test_score_history_append_normalises_legacy_store_before_duplicate_detection` | PASS | G1 | `t-gate-completed-list.xml` |
| `tests/test_score_history.py::test_score_history_preserves_run_dimensions_and_never_grants_execution_authority` | PASS | G1 | `t-gate-completed-list.xml` |
| `tests/test_score_history.py::test_score_history_publishes_paired_csv_and_rolls_back_on_group_failure` | PASS | G1 | `t-gate-completed-list.xml` |
| `tests/test_score_history.py::test_score_history_replaces_changed_snapshot_for_same_run_without_duplicate_instruments` | PASS | G1 | `t-gate-completed-list.xml` |
| `tests/test_settings_run_publication.py::test_feature_service_does_not_use_first_enabled_instrument_as_benchmark` | PASS | G7 | `t-gate-completed-list.xml` |
| `tests/test_sparebank_certification.py::test_teaching_bank_production_route_exposes_scorecard_and_workspace` | PASS | G3 | `t-gate-completed-list.xml` |
| `tests/test_sparebank_native_score_display.py::test_latest_sparebank_scores_takes_latest_native_run` | PASS | G1 | `t-gate-completed-list.xml` |
| `tests/test_sparebank_onboarding.py::test_source_has_no_hardcoded_sparebank_issuer_table` | NEEDS_OPUS_DECISION | D4 | `t-gate-completed-list.xml` |
| `tests/test_startup_lazy.py::test_backtest_route_loads_on_worker_behind_loading_shell` | PASS | G8 | `t-gate-completed-list.xml` |
| `tests/test_startup_lazy.py::test_snapshot_defers_backtest_and_lazy_result_matches_eager_result` | PASS | G8 | `t-gate-completed-list.xml` |
| `tests/test_statement_normalisation.py::test_fundamentals_surface_exposes_reported_and_restated_statement_history` | PASS | G3 | `t-gate-completed-list.xml` |
| `tests/test_supply_chain_scan.py::test_settings_page_exposes_update_verification_and_notices` | PASS | G11 | `t-gate-completed-list.xml` |
| `tests/test_task17_ui_contracts.py::test_what_changed_exposes_instrument_search_and_dimension_filters` | PASS | G7 | `t-gate-completed-list.xml` |
| `tests/test_task17_ui_contracts.py::test_what_changed_uses_compact_responsive_instrument_cards_without_horizontal_table` | NEEDS_OPUS_DECISION | D7 | `t-gate-completed-list.xml` |
| `tests/test_task18_ui.py::test_instrument_detail_friction_non_finite_values_are_unavailable` | PASS | G5 | `t-gate-completed-list.xml` |
| `tests/test_task18_ui.py::test_instrument_detail_renders_cost_edge_fields` | PASS | G5 | `t-gate-completed-list.xml` |
| `tests/test_task18_ui.py::test_risk_crowding_counts_distinct_explicit_warning_cluster_ids` | PASS | G5 | `t-gate-completed-list.xml` |
| `tests/test_task18_ui.py::test_risk_friction_panel_formats_non_finite_edge_values_as_unavailable` | PASS | G5 | `t-gate-completed-list.xml` |
| `tests/test_task18_ui.py::test_risk_page_renders_cost_edge_fields_and_unavailable_state` | PASS | G5 | `t-gate-completed-list.xml` |
| `tests/test_task19_instrument_detail.py::test_crowding_attribution_renders_canonical_broad_alpha_value` | PASS | G3 | `t-gate-completed-list.xml` |
| `tests/test_task19_instrument_detail.py::test_detail_disclosure_keeps_every_record_and_bounds_scroll` | PASS | G3 | `t-gate-completed-list.xml` |
| `tests/test_task19_instrument_detail.py::test_fundamentals_panel_renders_complete_five_section_provenance` | PASS | G3 | `t-gate-completed-list.xml` |
| `tests/test_task19_instrument_detail.py::test_instrument_detail_exposes_functional_export_control_and_disabled_state` | PASS | G3 | `t-gate-completed-list.xml` |
| `tests/test_task19_instrument_detail.py::test_instrument_detail_reads_holdings_csv_mirror_when_parquet_is_unavailable` | PASS | G3 | `t-gate-completed-list.xml` |
| `tests/test_task19_instrument_detail.py::test_instrument_detail_registers_visible_fundamentals_acceptance_surface` | PASS | G3 | `t-gate-completed-list.xml` |
| `tests/test_task19_instrument_detail.py::test_metric_history_local_route_preserves_all_scoped_components[VWCE]` | PASS | G1 | `t-gate-completed-list.xml` |
| `tests/test_task19_instrument_detail.py::test_metric_history_local_route_preserves_all_scoped_components[metric-stock]` | PASS | G1 | `t-gate-completed-list.xml` |
| `tests/test_task19_instrument_detail.py::test_score_panel_nullable_scoreboard_and_signal_values_fail_closed` | PASS | G3 | `t-gate-completed-list.xml` |
| `tests/test_task19_instrument_detail.py::test_valuation_invalid_selected_evidence_blocks_panel[available_at-0000-not-a-date]` | PASS | G3 | `t-gate-completed-list.xml` |
| `tests/test_task19_instrument_detail.py::test_valuation_invalid_selected_evidence_blocks_panel[available_at-2026-07-01T08:00:00]` | PASS | G3 | `t-gate-completed-list.xml` |
| `tests/test_task19_instrument_detail.py::test_valuation_invalid_selected_evidence_blocks_panel[available_at-None]` | PASS | G3 | `t-gate-completed-list.xml` |
| `tests/test_task19_instrument_detail.py::test_valuation_invalid_selected_evidence_blocks_panel[end-bad_value6]` | PASS | G3 | `t-gate-completed-list.xml` |
| `tests/test_task19_instrument_detail.py::test_valuation_invalid_selected_evidence_blocks_panel[end-not-a-date]` | PASS | G3 | `t-gate-completed-list.xml` |
| `tests/test_task19_instrument_detail.py::test_valuation_invalid_selected_evidence_blocks_panel[value-True]` | PASS | G3 | `t-gate-completed-list.xml` |
| `tests/test_task19_instrument_detail.py::test_valuation_invalid_selected_evidence_blocks_panel[value-inf]` | PASS | G3 | `t-gate-completed-list.xml` |
| `tests/test_task19_instrument_detail.py::test_valuation_invalid_selected_evidence_blocks_panel[value-nan]` | PASS | G3 | `t-gate-completed-list.xml` |
| `tests/test_task19_instrument_detail.py::test_valuation_scenario_controls_are_local_and_invalidate` | PASS | G3 | `t-gate-completed-list.xml` |
| `tests/test_task19_instrument_detail.py::test_valuation_visible_in_detail_for_stock_and_etf[etf]` | PASS | G3 | `t-gate-completed-list.xml` |
| `tests/test_task19_instrument_detail.py::test_valuation_workspace_native_dialog_session_and_focus` | PASS | G3 | `t-gate-completed-list.xml` |
| `tests/test_trust_critical_artifacts.py::test_diagnostics_ui_displays_redacted_exception_fingerprint` | PASS | G11 | `t-gate-completed-list.xml` |
| `tests/test_u1_home_pages.py::test_onboarding_leads_with_setup_and_discloses_details` | NEEDS_OPUS_DECISION | D7 | `t-gate-completed-list.xml` |
| `tests/test_u1_home_pages.py::test_summary_kpis_have_stable_keys_and_no_inline_as_of` | PASS | G7 | `t-gate-completed-list.xml` |
| `tests/test_u7_lab_pages.py::test_panel_uses_kit_glass_with_key_and_label` | PASS | G7 | `t-gate-completed-list.xml` |
| `tests/test_ui_staged_rendering.py::test_deferred_pageview_rebuilds_shell_after_the_placeholder` | PASS | G8 | `t-gate-completed-list.xml` |
| `tests/test_ui_staged_rendering.py::test_deferred_section_is_filled_after_the_placeholder_is_painted` | PASS | G8 | `t-gate-completed-list.xml` |
| `tests/test_user_documentation.py::test_documentation_release_stamps_match_project_version` | NEEDS_OPUS_DECISION | D6 | `t-gate-completed-list.xml` |
| `tests/test_user_documentation.py::test_documented_on_screen_labels_exist_in_application_source` | NEEDS_OPUS_DECISION | D6 | `t-gate-completed-list.xml` |
| `tests/test_user_documentation.py::test_methodology_index_links_every_architecture_and_sdd_page` | NEEDS_OPUS_DECISION | D6 | `t-gate-completed-list.xml` |
| `tests/test_valuation_workspace_lifecycle.py::test_real_shell_render_discards_only_owned_workspace[/instrument/NEW]` | PASS | G3 | `t-gate-completed-list.xml` |
| `tests/test_valuation_workspace_lifecycle.py::test_real_shell_render_discards_only_owned_workspace[/instrument/OLD]` | PASS | G3 | `t-gate-completed-list.xml` |
| `tests/test_valuation_workspace_lifecycle.py::test_repeated_workspace_dismissal_releases_sessions[False]` | PASS | G3 | `t-gate-completed-list.xml` |
| `tests/test_valuation_workspace_lifecycle.py::test_repeated_workspace_dismissal_releases_sessions[True]` | PASS | G3 | `t-gate-completed-list.xml` |
| `tests/test_workflow_runtime.py::test_primary_dashboard_workflows_are_keyboard_operable_buttons` | PASS | G6 | `t-gate-completed-list.xml` |
| `tests/ui/test_decision_journal_ui.py::test_decision_journal_is_local_only_with_one_primary_save_action` | PASS | G7 | `t-gate-completed-list.xml` |
| `tests/ui/test_portfolio_b_restyle_ui.py::test_page_uses_kit_panels_with_deterministic_unique_keys[decision-journal]` | PASS | G7 | `t-gate-completed-list.xml` |
| `tests/ui/test_portfolio_b_restyle_ui.py::test_page_uses_kit_panels_with_deterministic_unique_keys[forward-evidence]` | PASS | G7 | `t-gate-completed-list.xml` |
| `tests/ui/test_portfolio_b_restyle_ui.py::test_page_uses_kit_panels_with_deterministic_unique_keys[operations]` | PASS | G7 | `t-gate-completed-list.xml` |
| `tests/ui/test_portfolio_b_restyle_ui.py::test_page_uses_kit_panels_with_deterministic_unique_keys[portfolio-optimiser]` | PASS | G7 | `t-gate-completed-list.xml` |
| `tests/ui/test_portfolio_b_restyle_ui.py::test_page_uses_kit_panels_with_deterministic_unique_keys[risk]` | PASS | G7 | `t-gate-completed-list.xml` |
| `tests/ui/test_portfolio_b_restyle_ui.py::test_page_uses_kit_panels_with_deterministic_unique_keys[stress-lab]` | PASS | G7 | `t-gate-completed-list.xml` |
| `tests/ui/test_u6_universe_map_ui.py::test_catalogue_unreadable_state_is_honest` | PASS | G7 | `t-gate-completed-list.xml` |

## Remaining failure messages (verbatim JSON values)

Messages below are the complete failure.message attributes from the latest XML, represented as JSON string literals so whitespace is preserved losslessly without trailing-whitespace violations. Source traceback paths reflect the Windows runner.

### tests/issue0014/test_browser_workflows.py::test_real_loopback_http_startup_uses_offline_source_smoke

Decision: D5

```json
"RuntimeError: packaged offline smoke was not runnable (1): smoke_port requested=51151 selected=51151 reason=port 51151 is free\n\nTraceback (most recent call last):\n  File \"C:\\dev\\etf-BF-T-GATE\\logs\\pytest_system_tmp\\cases\\case_0e73b881cfb24cb99846944916811e7e\\browser-smoke\\scripts\\smoke_app.py\", line 218, in <module>\n    raise SystemExit(main())\n                     ^^^^^^\n  File \"C:\\dev\\etf-BF-T-GATE\\logs\\pytest_system_tmp\\cases\\case_0e73b881cfb24cb99846944916811e7e\\browser-smoke\\scripts\\smoke_app.py\", line 73, in main\n    _verify_score_groups()\n  File \"C:\\dev\\etf-BF-T-GATE\\logs\\pytest_system_tmp\\cases\\case_0e73b881cfb24cb99846944916811e7e\\browser-smoke\\scripts\\smoke_app.py\", line 212, in _verify_score_groups\n    raise RuntimeError(\"Sparebanken group did not preserve AURG needs_verification ISIN.\")\nRuntimeError: Sparebanken group did not preserve AURG needs_verification ISIN."
```

### tests/refactor_parity/test_backtest_golden.py::test_backtest_matches_golden

Decision: D1

```json
"AssertionError: backtest.json: 351 difference(s); first ones:\n  $.results.cagr[0]: 0.044500397269018555 != 0.04411701191273498\n  $.results.cagr[1]: -0.02896316773528962 != -0.02832877395991673\n  $.results.cagr[2]: -0.029119065847836745 != -0.03120195218935551\n  $.results.cagr[3]: -0.035948622142720654 != -0.03359231173403898\n  $.results.cagr[6]: -0.02896316773528973 != -0.028328773959916398\n  $.results.volatility[0]: 0.10394614797584885 != 0.1041378101935884\n  $.results.volatility[1]: 0.1060290053556065 != 0.10613077221387077\n  $.results.volatility[2]: 0.10926068577512518 != 0.109226752846371\n  $.results.volatility[3]: 0.11071216225943463 != 0.11100290679353018\n  $.results.volatility[6]: 0.10602900535560654 != 0.10613077221387075\n  $.results.sharpe[0]: 0.4188580645455948 != 0.41456185295081116\n  $.results.sharpe[1]: -0.27719659361321247 != -0.2707770418950264\n  $.results.sharpe[2]: -0.2704672763333997 != -0.29021371576497274\n  $.results.sharpe[3]: -0.33068353568565234 != -0.30782523851891314\n  $.results.sharpe[6]: -0.2771965936132137 != -0.2707770418950237\n  $.results.sortino[0]: 0.6941310031353365 != 0.6865557993444231\n  $.results.sortino[1]: -0.4456268431472637 != -0.4355948689332995\n  $.results.sortino[2]: -0.443240349108007 != -0.4751518349058419\n  $.results.sortino[3]: -0.5243887170779065 != -0.4918374613259773\n  $.results.sortino[6]: -0.4456268431472656 != -0.4355948689332953\n  $.results.max_drawdown[0]: -0.18000441321230953 != -0.18068103855435458\n  $.results.max_drawdown[1]: -0.20624446974629151 != -0.20669874250710008\n  $.results.max_drawdown[2]: -0.21317184932821454 != -0.21490731617854497\n  $.results.max_drawdown[3]: -0.21247650388098938 != -0.213663513578364\n  $.results.max_drawdown[6]: -0.20624446974629185 != -0.2066987425070993"
```

### tests/refactor_parity/test_clock_independence.py::test_goldens_do_not_depend_on_the_wall_clock[backtest]

Decision: D1

```json
"AssertionError: backtest.json: 351 difference(s); first ones:\n  $.results.cagr[0]: 0.044500397269018555 != 0.04411701191273498\n  $.results.cagr[1]: -0.02896316773528962 != -0.02832877395991673\n  $.results.cagr[2]: -0.029119065847836745 != -0.03120195218935551\n  $.results.cagr[3]: -0.035948622142720654 != -0.03359231173403898\n  $.results.cagr[6]: -0.02896316773528973 != -0.028328773959916398\n  $.results.volatility[0]: 0.10394614797584885 != 0.1041378101935884\n  $.results.volatility[1]: 0.1060290053556065 != 0.10613077221387077\n  $.results.volatility[2]: 0.10926068577512518 != 0.109226752846371\n  $.results.volatility[3]: 0.11071216225943463 != 0.11100290679353018\n  $.results.volatility[6]: 0.10602900535560654 != 0.10613077221387075\n  $.results.sharpe[0]: 0.4188580645455948 != 0.41456185295081116\n  $.results.sharpe[1]: -0.27719659361321247 != -0.2707770418950264\n  $.results.sharpe[2]: -0.2704672763333997 != -0.29021371576497274\n  $.results.sharpe[3]: -0.33068353568565234 != -0.30782523851891314\n  $.results.sharpe[6]: -0.2771965936132137 != -0.2707770418950237\n  $.results.sortino[0]: 0.6941310031353365 != 0.6865557993444231\n  $.results.sortino[1]: -0.4456268431472637 != -0.4355948689332995\n  $.results.sortino[2]: -0.443240349108007 != -0.4751518349058419\n  $.results.sortino[3]: -0.5243887170779065 != -0.4918374613259773\n  $.results.sortino[6]: -0.4456268431472656 != -0.4355948689332953\n  $.results.max_drawdown[0]: -0.18000441321230953 != -0.18068103855435458\n  $.results.max_drawdown[1]: -0.20624446974629151 != -0.20669874250710008\n  $.results.max_drawdown[2]: -0.21317184932821454 != -0.21490731617854497\n  $.results.max_drawdown[3]: -0.21247650388098938 != -0.213663513578364\n  $.results.max_drawdown[6]: -0.20624446974629185 != -0.2066987425070993"
```

### tests/refactor_parity/test_clock_independence.py::test_goldens_do_not_depend_on_the_wall_clock[persisted_schema]

Decision: D1

```json
"AssertionError: persisted_schema.json: 46 difference(s); first ones:\n  $.files: keys ['data/backtests/backtest_metadata.json', 'data/backtests/backtest_metadata.json.meta.json', 'data/backtests/backtest_results.csv', 'data/backtests/backtest_results.csv.meta.json', 'data/backtests/equity_curves.csv', 'data/backtests/equity_curves.csv.meta.json', 'data/backtests/quality_momentum_evidence.csv', 'data/backtests/quality_momentum_evidence.csv.meta.json', 'data/backtests/signal_log.csv', 'data/backtests/signal_log.csv.meta.json', 'data/backtests/trade_log.csv', 'data/backtests/trade_log.csv.meta.json', 'data/clean/etf_disclosures.csv', 'data/clean/etf_disclosures.parquet', 'data/clean/etf_report_conflicts.csv', 'data/clean/etf_report_conflicts.parquet', 'data/clean/etf_report_records.csv', 'data/clean/etf_report_records.parquet', 'data/clean/filings_statements.csv', 'data/clean/filings_statements.parquet', 'data/clean/filings_statements.parquet.guard', 'data/clean/index_methodology_records.csv', 'data/clean/index_methodology_records.parquet', 'data/clean/instrument_identity.csv', 'data/clean/instrument_identity.parquet', 'data/clean/news_context.csv', 'data/clean/news_context.parquet', 'data/clean/news_timestamp_validation.csv', 'data/clean/news_timestamp_validation.parquet', 'data/clean/priips_kid_records.csv', 'data/clean/priips_kid_records.parquet', 'data/clean/provider_probe_results.csv', 'data/clean/provider_probe_results.parquet', 'data/clean/source_conflicts.csv', 'data/clean/source_conflicts.parquet', 'data/derived/benchmark_attribution.csv', 'data/derived/benchmark_attribution.parquet', 'data/derived/correlation_clusters.csv', 'data/derived/correlation_clusters.parquet', 'data/derived/evidence_ledger.csv', 'data/derived/evidence_ledger.parquet', 'data/derived/feature_drivers.csv', 'data/derived/feature_drivers.parquet', 'data/derived/market_regime.csv', 'data/derived/market_regime.json', 'data/derived/model_calibration.csv', 'data/derived/model_calibration.parquet', 'data/derived/run_manifests/backtest__s54eb00f2a924.json', 'data/derived/run_manifests/features_2026-09-30__s54eb00f2a924.json', 'data/derived/run_manifests/forecast_20260930__s54eb00f2a924.json', 'data/derived/run_manifests/score_<stamp>_<8hex>.json', 'data/derived/score_components.csv', 'data/derived/score_components.parquet', 'data/derived/score_formula_registry.json', 'data/derived/score_history.csv', 'data/derived/score_history.parquet', 'data/derived/score_metric_history.csv', 'data/derived/score_metric_history.parquet', 'data/derived/scoreboard.csv', 'data/derived/scoreboard.json', 'data/derived/scoreboard.parquet', 'data/derived/strategy_templates.csv', 'data/derived/version_registry.json', 'data/features/features_daily.parquet', 'data/features/features_daily.parquet.meta.json', 'data/forecasts/forecast_results_yfinance_20260930.csv', 'data/forecasts/forecast_results_yfinance_20260930.csv.meta.json', 'data/portfolios/current_holdings.csv', 'data/raw/prices/sample_prices.csv', 'data/validated/prices/prices_daily.parquet'] != ['data/backtests/backtest_metadata.json', 'data/backtests/backtest_metadata.json.meta.json', 'data/backtests/backtest_results.csv', 'data/backtests/backtest_results.csv.meta.json', 'data/backtests/equity_curves.csv', 'data/backtests/equity_curves.csv.meta.json', 'data/backtests/quality_momentum_evidence.csv', 'data/backtests/quality_momentum_evidence.csv.meta.json', 'data/backtests/signal_log.csv', 'data/backtests/signal_log.csv.meta.json', 'data/backtests/trade_log.csv', 'data/backtests/trade_log.csv.meta.json', 'data/clean/etf_disclosures.csv', 'data/clean/etf_disclosures.parquet', 'data/clean/etf_report_conflicts.csv', 'data/clean/etf_report_conflicts.parquet', 'data/clean/etf_report_records.csv', 'data/clean/etf_report_records.parquet', 'data/clean/filings_statements.csv', 'data/clean/filings_statements.parquet', 'data/clean/filings_statements.parquet.guard', 'data/clean/index_methodology_records.csv', 'data/clean/index_methodology_records.parquet', 'data/clean/instrument_identity.csv', 'data/clean/instrument_identity.parquet', 'data/clean/news_context.csv', 'data/clean/news_context.parquet', 'data/clean/news_timestamp_validation.csv', 'data/clean/news_timestamp_validation.parquet', 'data/clean/priips_kid_records.csv', 'data/clean/priips_kid_records.parquet', 'data/clean/provider_probe_results.csv', 'data/clean/provider_probe_results.parquet', 'data/clean/source_conflicts.csv', 'data/clean/source_conflicts.parquet', 'data/derived/benchmark_attribution.csv', 'data/derived/benchmark_attribution.parquet', 'data/derived/correlation_clusters.csv', 'data/derived/correlation_clusters.parquet', 'data/derived/evidence_ledger.csv', 'data/derived/evidence_ledger.parquet', 'data/derived/feature_drivers.csv', 'data/derived/feature_drivers.parquet', 'data/derived/market_regime.csv', 'data/derived/market_regime.json', 'data/derived/model_calibration.csv', 'data/derived/model_calibration.parquet', 'data/derived/run_manifests/backtest__s5944577a97bd.json', 'data/derived/run_manifests/features_2026-09-30__s5944577a97bd.json', 'data/derived/run_manifests/forecast_20260930__s5944577a97bd.json', 'data/derived/run_manifests/score_<stamp>_<8hex>.json', 'data/derived/score_components.csv', 'data/derived/score_components.parquet', 'data/derived/score_formula_registry.json', 'data/derived/score_history.csv', 'data/derived/score_history.parquet', 'data/derived/score_metric_history.csv', 'data/derived/score_metric_history.parquet', 'data/derived/scoreboard.csv', 'data/derived/scoreboard.json', 'data/derived/scoreboard.parquet', 'data/derived/strategy_templates.csv', 'data/derived/version_registry.json', 'data/features/features_daily.parquet', 'data/features/features_daily.parquet.meta.json', 'data/forecasts/forecast_results_yfinance_20260930.csv', 'data/forecasts/forecast_results_yfinance_20260930.csv.meta.json', 'data/portfolios/current_holdings.csv', 'data/raw/prices/sample_prices.csv', 'data/storage/cockpit.sqlite3', 'data/validated/prices/prices_daily.parquet']\n  $.forecast_file.frame.shape[0]: 885 != 870\n  $.forecast_file.frame.numeric_columns.horizon_days.count: 885 != 870\n  $.forecast_file.frame.numeric_columns.horizon_days.sum: 68145.0 != 66990.0\n  $.forecast_file.frame.numeric_columns.expected_return.nan_count: 590 != 580\n  $.forecast_file.frame.numeric_columns.expected_return.count: 295 != 290\n  $.forecast_file.frame.numeric_columns.expected_return.sum: 0.5879154247674752 != 0.6053910381913706\n  $.forecast_file.frame.numeric_columns.expected_return.mean: 0.001992933643279577 != 0.0020875553041081745\n  $.forecast_file.frame.numeric_columns.expected_excess_return.nan_count: 885 != 870\n  $.forecast_file.frame.numeric_columns.q10_return.nan_count: 590 != 580\n  $.forecast_file.frame.numeric_columns.q10_return.count: 295 != 290\n  $.forecast_file.frame.numeric_columns.q10_return.sum: -32.64403842869774 != -32.090846675014284\n  $.forecast_file.frame.numeric_columns.q10_return.mean: -0.11065775738541607 != -0.11065809198280788\n  $.forecast_file.frame.numeric_columns.q50_return.nan_count: 590 != 580\n  $.forecast_file.frame.numeric_columns.q50_return.count: 295 != 290\n  $.forecast_file.frame.numeric_columns.q50_return.sum: 0.5879154247674752 != 0.6053910381913706\n  $.forecast_file.frame.numeric_columns.q50_return.mean: 0.001992933643279577 != 0.0020875553041081745\n  $.forecast_file.frame.numeric_columns.q90_return.nan_count: 590 != 580\n  $.forecast_file.frame.numeric_columns.q90_return.count: 295 != 290\n  $.forecast_file.frame.numeric_columns.q90_return.sum: 33.819869278232694 != 33.301628751397025\n  $.forecast_file.frame.numeric_columns.q90_return.mean: 0.11464362467197524 != 0.11483320259102422\n  $.forecast_file.frame.numeric_columns.forecast_vol.nan_count: 590 != 580\n  $.forecast_file.frame.numeric_columns.forecast_vol.count: 295 != 290\n  $.forecast_file.frame.numeric_columns.forecast_vol.sum: 25.962463948019696 != 25.54393571344191\n  $.forecast_file.frame.numeric_columns.forecast_vol.mean: 0.08800835236616845 != 0.08808253694290315"
```

### tests/refactor_parity/test_clock_independence.py::test_goldens_do_not_depend_on_the_wall_clock[scoreboard]

Decision: D1

```json
"AssertionError: scoreboard.json: 28 difference(s); first ones:\n  $.score_objects.order: length 59 != 58\n  $.score_objects.instrument_key: length 59 != 58\n  $.score_objects.final_score_10: length 59 != 58\n  $.score_objects.rank: length 59 != 58\n  $.score_objects.score_rank: length 59 != 58\n  $.score_objects.final_action: length 59 != 58\n  $.score_objects.one_line_reason: length 59 != 58\n  $.score_objects.warnings: length 59 != 58\n  $.score_objects.strategy_templates: length 59 != 58\n  $.score_objects.model_versions_used: length 59 != 58\n  $.score_objects.forecast_status: length 59 != 58\n  $.score_objects.news_inventory: length 59 != 58\n  $.score_objects.internal_intent: length 59 != 58\n  $.score_objects.authority_decision: length 59 != 58\n  $.score_objects.canonical_score: length 59 != 58\n  $.score_objects.valid_component_count: length 59 != 58\n  $.score_objects.total_component_count: length 59 != 58\n  $.score_objects.components: length 59 != 58\n  $.shape[0]: 59 != 58\n  $.shape[1]: 205 != 209\n  $.columns: length 205 != 209\n  $.dtypes: keys ['instrument_id', 'symbol', 'name', 'instrument_currency', 'isin', 'isin_status', 'asset_type', 'analysis_tier', 'data_policy', 'source_group', 'current_price', 'latest_price_date', 'evidence_score_10', 'evidence_quality_10', 'risk_friction_10', 'final_label', 'research_state', 'portfolio_review_state', 'analysis_status', 'research_promotion_allowed', 'portfolio_review_allowed', 'execution_allowed', 'legacy_action', 'migration_version', 'gate_policy_version', 'gate_policy_checksum', 'schema_version', 'decision', 'blocked_by', 'reason_short', 'model_authority_label', 'backtest_trust_label', 'backtest_trust_score_10', 'model_calibration_label', 'model_calibration_score_10', 'market_regime_label', 'market_regime_score_10', 'portfolio_fit_label', 'portfolio_fit_score_10', 'strategy_template_label', 'strategy_template_descriptions', 'evidence_sample_days', 'evidence_maturity_state', 'evidence_maturity_label', 'too_good_to_be_true_warning', 'evidence_sanity_warnings', 'evidence_warning_count', 'benchmark_id', 'benchmark_period_days', 'benchmark_return', 'instrument_period_return', 'benchmark_beta', 'benchmark_correlation', 'alpha_proxy', 'alpha_t_stat', 'benchmark_attribution_label', 'cash_instrument_return', 'cash_return', 'excess_over_cash', 'cash_instrument_id', 'cash_currency', 'cash_unit', 'cash_dataset_kind', 'cash_start_date', 'cash_end_date', 'cash_horizon_years', 'cash_rate', 'cash_vintage', 'cash_comparison_status', 'cash_comparison_reason', 'cash_source_id', 'cash_source_authority', 'cash_source_checksum', 'cash_source_terms', 'cash_methodology', 'cash_mapping_methodology', 'cash_day_count', 'cash_compounding', 'cash_reinvestment', 'cash_effective_at', 'cash_published_at', 'cash_available_at', 'cash_curve_id', 'cash_curve_version', 'cash_curve_revision', 'cash_curve_type', 'cash_extrapolation_allowed', 'cash_fallback', 'cash_fallback_from', 'cash_interpolation', 'cash_freshness', 'cash_freshness_status', 'cash_decision_time', 'cash_knowledge_cutoff', 'inflation_context', 'sector_theme_warning', 'backtest_validity', 'model_contamination_risk', 'model_authority_reason', 'calibration_required', 'gross_expected_edge_bps', 'estimated_total_cost_bps', 'net_expected_edge_bps', 'edge_to_cost_ratio', 'cost_stress_scenario', 'gross_expected_return', 'q10_expected_return', 'q50_expected_return', 'q90_expected_return', 'expected_return_horizon_days', 'net_q10_expected_return', 'net_expected_return', 'net_q90_expected_return', 'expected_return_order_value_eur', 'expected_return_cost_bps', 'expected_return_cost_eur', 'expected_return_cost_ratio', 'expected_return_distribution_version', 'expected_return_source_dataset', 'crowding_cluster_id', 'crowding_cluster_label', 'crowding_warning', 'crowding_average_peer_correlation', 'crowding_sample_size', 'crowding_as_of', 'crowding_source_dataset', 'crowding_pair_sample_size', 'crowding_cluster_weight', 'crowding_cluster_risk_contribution', 'crowding_ranking_coverage', 'crowding_top_ranked_concentration', 'crowding_top_ranked_theme_concentration', 'crowding_top_ranked_theme_warning', 'sector_return', 'sector_relative_return', 'sector_beta', 'sector_correlation', 'sector_alpha_proxy', 'sector_attribution_status', 'attribution_sample_size', 'attribution_as_of', 'attribution_source_dataset', 'theme_return', 'theme_relative_return', 'theme_beta', 'theme_correlation', 'theme_alpha_proxy', 'theme_attribution_status', 'theme_sample_size', 'friction_status', 'friction_reason', 'formula_version', 'formula_checksum', 'source_vintage_hash', 'classification_version_id', 'classification_invalidation_hash', 'classification_dependency_status', 'canonical_attractiveness_10', 'canonical_expected_return_10', 'canonical_risk_implementation_10', 'canonical_evidence_confidence_10', 'canonical_coverage', 'canonical_warnings', 'valid_components', 'total_components', 'source_quality', 'data_quality_score_10', 'data_quality_status', 'data_quality_authority', 'momentum_score_10', 'momentum_status', 'momentum_authority', 'trend_score_10', 'trend_status', 'trend_authority', 'risk_score_10', 'risk_status', 'risk_authority', 'relative_strength_score_10', 'relative_strength_status', 'relative_strength_authority', 'liquidity_cost_score_10', 'liquidity_cost_status', 'liquidity_cost_authority', 'etf_exposure_score_10', 'etf_exposure_status', 'etf_exposure_authority', 'baseline_score_10', 'baseline_status', 'baseline_authority', 'timesfm_score_10', 'timesfm_status', 'timesfm_authority', 'toto_score_10', 'toto_status', 'toto_authority', 'stock_value_score_10', 'stock_value_status', 'stock_value_authority', 'stock_quality_score_10', 'stock_quality_status', 'stock_quality_authority', 'analyst_revision_score_10', 'analyst_revision_status', 'analyst_revision_authority'] != ['instrument_id', 'symbol', 'name', 'instrument_currency', 'isin', 'isin_status', 'asset_type', 'analysis_tier', 'data_policy', 'source_group', 'current_price', 'latest_price_date', 'evidence_score_10', 'evidence_quality_10', 'risk_friction_10', 'final_label', 'research_state', 'portfolio_review_state', 'analysis_status', 'research_promotion_allowed', 'portfolio_review_allowed', 'execution_allowed', 'legacy_action', 'migration_version', 'gate_policy_version', 'gate_policy_checksum', 'schema_version', 'decision', 'blocked_by', 'reason_short', 'final_combined_score_10', 'coverage', 'missing_components', 'identity_conflict_reason', 'model_authority_label', 'backtest_trust_label', 'backtest_trust_score_10', 'model_calibration_label', 'model_calibration_score_10', 'market_regime_label', 'market_regime_score_10', 'portfolio_fit_label', 'portfolio_fit_score_10', 'strategy_template_label', 'strategy_template_descriptions', 'evidence_sample_days', 'evidence_maturity_state', 'evidence_maturity_label', 'too_good_to_be_true_warning', 'evidence_sanity_warnings', 'evidence_warning_count', 'benchmark_id', 'benchmark_period_days', 'benchmark_return', 'instrument_period_return', 'benchmark_beta', 'benchmark_correlation', 'alpha_proxy', 'alpha_t_stat', 'benchmark_attribution_label', 'cash_instrument_return', 'cash_return', 'excess_over_cash', 'cash_instrument_id', 'cash_currency', 'cash_unit', 'cash_dataset_kind', 'cash_start_date', 'cash_end_date', 'cash_horizon_years', 'cash_rate', 'cash_vintage', 'cash_comparison_status', 'cash_comparison_reason', 'cash_source_id', 'cash_source_authority', 'cash_source_checksum', 'cash_source_terms', 'cash_methodology', 'cash_mapping_methodology', 'cash_day_count', 'cash_compounding', 'cash_reinvestment', 'cash_effective_at', 'cash_published_at', 'cash_available_at', 'cash_curve_id', 'cash_curve_version', 'cash_curve_revision', 'cash_curve_type', 'cash_extrapolation_allowed', 'cash_fallback', 'cash_fallback_from', 'cash_interpolation', 'cash_freshness', 'cash_freshness_status', 'cash_decision_time', 'cash_knowledge_cutoff', 'inflation_context', 'sector_theme_warning', 'backtest_validity', 'model_contamination_risk', 'model_authority_reason', 'calibration_required', 'gross_expected_edge_bps', 'estimated_total_cost_bps', 'net_expected_edge_bps', 'edge_to_cost_ratio', 'cost_stress_scenario', 'gross_expected_return', 'q10_expected_return', 'q50_expected_return', 'q90_expected_return', 'expected_return_horizon_days', 'net_q10_expected_return', 'net_expected_return', 'net_q90_expected_return', 'expected_return_order_value_eur', 'expected_return_cost_bps', 'expected_return_cost_eur', 'expected_return_cost_ratio', 'expected_return_distribution_version', 'expected_return_source_dataset', 'crowding_cluster_id', 'crowding_cluster_label', 'crowding_warning', 'crowding_average_peer_correlation', 'crowding_sample_size', 'crowding_as_of', 'crowding_source_dataset', 'crowding_pair_sample_size', 'crowding_cluster_weight', 'crowding_cluster_risk_contribution', 'crowding_ranking_coverage', 'crowding_top_ranked_concentration', 'crowding_top_ranked_theme_concentration', 'crowding_top_ranked_theme_warning', 'sector_return', 'sector_relative_return', 'sector_beta', 'sector_correlation', 'sector_alpha_proxy', 'sector_attribution_status', 'attribution_sample_size', 'attribution_as_of', 'attribution_source_dataset', 'theme_return', 'theme_relative_return', 'theme_beta', 'theme_correlation', 'theme_alpha_proxy', 'theme_attribution_status', 'theme_sample_size', 'friction_status', 'friction_reason', 'formula_version', 'formula_checksum', 'source_vintage_hash', 'classification_version_id', 'classification_invalidation_hash', 'classification_dependency_status', 'canonical_attractiveness_10', 'canonical_expected_return_10', 'canonical_risk_implementation_10', 'canonical_evidence_confidence_10', 'canonical_coverage', 'canonical_warnings', 'valid_components', 'total_components', 'source_quality', 'data_quality_score_10', 'data_quality_status', 'data_quality_authority', 'momentum_score_10', 'momentum_status', 'momentum_authority', 'trend_score_10', 'trend_status', 'trend_authority', 'risk_score_10', 'risk_status', 'risk_authority', 'relative_strength_score_10', 'relative_strength_status', 'relative_strength_authority', 'liquidity_cost_score_10', 'liquidity_cost_status', 'liquidity_cost_authority', 'etf_exposure_score_10', 'etf_exposure_status', 'etf_exposure_authority', 'baseline_score_10', 'baseline_status', 'baseline_authority', 'timesfm_score_10', 'timesfm_status', 'timesfm_authority', 'toto_score_10', 'toto_status', 'toto_authority', 'stock_value_score_10', 'stock_value_status', 'stock_value_authority', 'stock_quality_score_10', 'stock_quality_status', 'stock_quality_authority', 'analyst_revision_score_10', 'analyst_revision_status', 'analyst_revision_authority']\n  $.order: length 59 != 58\n  $.columns_by_name: keys ['instrument_id', 'symbol', 'name', 'instrument_currency', 'isin', 'isin_status', 'asset_type', 'analysis_tier', 'data_policy', 'source_group', 'current_price', 'latest_price_date', 'evidence_score_10', 'evidence_quality_10', 'risk_friction_10', 'final_label', 'research_state', 'portfolio_review_state', 'analysis_status', 'research_promotion_allowed', 'portfolio_review_allowed', 'execution_allowed', 'legacy_action', 'migration_version', 'gate_policy_version', 'gate_policy_checksum', 'schema_version', 'decision', 'blocked_by', 'reason_short', 'model_authority_label', 'backtest_trust_label', 'backtest_trust_score_10', 'model_calibration_label', 'model_calibration_score_10', 'market_regime_label', 'market_regime_score_10', 'portfolio_fit_label', 'portfolio_fit_score_10', 'strategy_template_label', 'strategy_template_descriptions', 'evidence_sample_days', 'evidence_maturity_state', 'evidence_maturity_label', 'too_good_to_be_true_warning', 'evidence_sanity_warnings', 'evidence_warning_count', 'benchmark_id', 'benchmark_period_days', 'benchmark_return', 'instrument_period_return', 'benchmark_beta', 'benchmark_correlation', 'alpha_proxy', 'alpha_t_stat', 'benchmark_attribution_label', 'cash_instrument_return', 'cash_return', 'excess_over_cash', 'cash_instrument_id', 'cash_currency', 'cash_unit', 'cash_dataset_kind', 'cash_start_date', 'cash_end_date', 'cash_horizon_years', 'cash_rate', 'cash_vintage', 'cash_comparison_status', 'cash_comparison_reason', 'cash_source_id', 'cash_source_authority', 'cash_source_checksum', 'cash_source_terms', 'cash_methodology', 'cash_mapping_methodology', 'cash_day_count', 'cash_compounding', 'cash_reinvestment', 'cash_effective_at', 'cash_published_at', 'cash_available_at', 'cash_curve_id', 'cash_curve_version', 'cash_curve_revision', 'cash_curve_type', 'cash_extrapolation_allowed', 'cash_fallback', 'cash_fallback_from', 'cash_interpolation', 'cash_freshness', 'cash_freshness_status', 'cash_decision_time', 'cash_knowledge_cutoff', 'inflation_context', 'sector_theme_warning', 'backtest_validity', 'model_contamination_risk', 'model_authority_reason', 'calibration_required', 'gross_expected_edge_bps', 'estimated_total_cost_bps', 'net_expected_edge_bps', 'edge_to_cost_ratio', 'cost_stress_scenario', 'gross_expected_return', 'q10_expected_return', 'q50_expected_return', 'q90_expected_return', 'expected_return_horizon_days', 'net_q10_expected_return', 'net_expected_return', 'net_q90_expected_return', 'expected_return_order_value_eur', 'expected_return_cost_bps', 'expected_return_cost_eur', 'expected_return_cost_ratio', 'expected_return_distribution_version', 'expected_return_source_dataset', 'crowding_cluster_id', 'crowding_cluster_label', 'crowding_warning', 'crowding_average_peer_correlation', 'crowding_sample_size', 'crowding_as_of', 'crowding_source_dataset', 'crowding_pair_sample_size', 'crowding_cluster_weight', 'crowding_cluster_risk_contribution', 'crowding_ranking_coverage', 'crowding_top_ranked_concentration', 'crowding_top_ranked_theme_concentration', 'crowding_top_ranked_theme_warning', 'sector_return', 'sector_relative_return', 'sector_beta', 'sector_correlation', 'sector_alpha_proxy', 'sector_attribution_status', 'attribution_sample_size', 'attribution_as_of', 'attribution_source_dataset', 'theme_return', 'theme_relative_return', 'theme_beta', 'theme_correlation', 'theme_alpha_proxy', 'theme_attribution_status', 'theme_sample_size', 'friction_status', 'friction_reason', 'formula_version', 'formula_checksum', 'source_vintage_hash', 'classification_version_id', 'classification_invalidation_hash', 'classification_dependency_status', 'canonical_attractiveness_10', 'canonical_expected_return_10', 'canonical_risk_implementation_10', 'canonical_evidence_confidence_10', 'canonical_coverage', 'canonical_warnings', 'valid_components', 'total_components', 'source_quality', 'data_quality_score_10', 'data_quality_status', 'data_quality_authority', 'momentum_score_10', 'momentum_status', 'momentum_authority', 'trend_score_10', 'trend_status', 'trend_authority', 'risk_score_10', 'risk_status', 'risk_authority', 'relative_strength_score_10', 'relative_strength_status', 'relative_strength_authority', 'liquidity_cost_score_10', 'liquidity_cost_status', 'liquidity_cost_authority', 'etf_exposure_score_10', 'etf_exposure_status', 'etf_exposure_authority', 'baseline_score_10', 'baseline_status', 'baseline_authority', 'timesfm_score_10', 'timesfm_status', 'timesfm_authority', 'toto_score_10', 'toto_status', 'toto_authority', 'stock_value_score_10', 'stock_value_status', 'stock_value_authority', 'stock_quality_score_10', 'stock_quality_status', 'stock_quality_authority', 'analyst_revision_score_10', 'analyst_revision_status', 'analyst_revision_authority'] != ['instrument_id', 'symbol', 'name', 'instrument_currency', 'isin', 'isin_status', 'asset_type', 'analysis_tier', 'data_policy', 'source_group', 'current_price', 'latest_price_date', 'evidence_score_10', 'evidence_quality_10', 'risk_friction_10', 'final_label', 'research_state', 'portfolio_review_state', 'analysis_status', 'research_promotion_allowed', 'portfolio_review_allowed', 'execution_allowed', 'legacy_action', 'migration_version', 'gate_policy_version', 'gate_policy_checksum', 'schema_version', 'decision', 'blocked_by', 'reason_short', 'final_combined_score_10', 'coverage', 'missing_components', 'identity_conflict_reason', 'model_authority_label', 'backtest_trust_label', 'backtest_trust_score_10', 'model_calibration_label', 'model_calibration_score_10', 'market_regime_label', 'market_regime_score_10', 'portfolio_fit_label', 'portfolio_fit_score_10', 'strategy_template_label', 'strategy_template_descriptions', 'evidence_sample_days', 'evidence_maturity_state', 'evidence_maturity_label', 'too_good_to_be_true_warning', 'evidence_sanity_warnings', 'evidence_warning_count', 'benchmark_id', 'benchmark_period_days', 'benchmark_return', 'instrument_period_return', 'benchmark_beta', 'benchmark_correlation', 'alpha_proxy', 'alpha_t_stat', 'benchmark_attribution_label', 'cash_instrument_return', 'cash_return', 'excess_over_cash', 'cash_instrument_id', 'cash_currency', 'cash_unit', 'cash_dataset_kind', 'cash_start_date', 'cash_end_date', 'cash_horizon_years', 'cash_rate', 'cash_vintage', 'cash_comparison_status', 'cash_comparison_reason', 'cash_source_id', 'cash_source_authority', 'cash_source_checksum', 'cash_source_terms', 'cash_methodology', 'cash_mapping_methodology', 'cash_day_count', 'cash_compounding', 'cash_reinvestment', 'cash_effective_at', 'cash_published_at', 'cash_available_at', 'cash_curve_id', 'cash_curve_version', 'cash_curve_revision', 'cash_curve_type', 'cash_extrapolation_allowed', 'cash_fallback', 'cash_fallback_from', 'cash_interpolation', 'cash_freshness', 'cash_freshness_status', 'cash_decision_time', 'cash_knowledge_cutoff', 'inflation_context', 'sector_theme_warning', 'backtest_validity', 'model_contamination_risk', 'model_authority_reason', 'calibration_required', 'gross_expected_edge_bps', 'estimated_total_cost_bps', 'net_expected_edge_bps', 'edge_to_cost_ratio', 'cost_stress_scenario', 'gross_expected_return', 'q10_expected_return', 'q50_expected_return', 'q90_expected_return', 'expected_return_horizon_days', 'net_q10_expected_return', 'net_expected_return', 'net_q90_expected_return', 'expected_return_order_value_eur', 'expected_return_cost_bps', 'expected_return_cost_eur', 'expected_return_cost_ratio', 'expected_return_distribution_version', 'expected_return_source_dataset', 'crowding_cluster_id', 'crowding_cluster_label', 'crowding_warning', 'crowding_average_peer_correlation', 'crowding_sample_size', 'crowding_as_of', 'crowding_source_dataset', 'crowding_pair_sample_size', 'crowding_cluster_weight', 'crowding_cluster_risk_contribution', 'crowding_ranking_coverage', 'crowding_top_ranked_concentration', 'crowding_top_ranked_theme_concentration', 'crowding_top_ranked_theme_warning', 'sector_return', 'sector_relative_return', 'sector_beta', 'sector_correlation', 'sector_alpha_proxy', 'sector_attribution_status', 'attribution_sample_size', 'attribution_as_of', 'attribution_source_dataset', 'theme_return', 'theme_relative_return', 'theme_beta', 'theme_correlation', 'theme_alpha_proxy', 'theme_attribution_status', 'theme_sample_size', 'friction_status', 'friction_reason', 'formula_version', 'formula_checksum', 'source_vintage_hash', 'classification_version_id', 'classification_invalidation_hash', 'classification_dependency_status', 'canonical_attractiveness_10', 'canonical_expected_return_10', 'canonical_risk_implementation_10', 'canonical_evidence_confidence_10', 'canonical_coverage', 'canonical_warnings', 'valid_components', 'total_components', 'source_quality', 'data_quality_score_10', 'data_quality_status', 'data_quality_authority', 'momentum_score_10', 'momentum_status', 'momentum_authority', 'trend_score_10', 'trend_status', 'trend_authority', 'risk_score_10', 'risk_status', 'risk_authority', 'relative_strength_score_10', 'relative_strength_status', 'relative_strength_authority', 'liquidity_cost_score_10', 'liquidity_cost_status', 'liquidity_cost_authority', 'etf_exposure_score_10', 'etf_exposure_status', 'etf_exposure_authority', 'baseline_score_10', 'baseline_status', 'baseline_authority', 'timesfm_score_10', 'timesfm_status', 'timesfm_authority', 'toto_score_10', 'toto_status', 'toto_authority', 'stock_value_score_10', 'stock_value_status', 'stock_value_authority', 'stock_quality_score_10', 'stock_quality_status', 'stock_quality_authority', 'analyst_revision_score_10', 'analyst_revision_status', 'analyst_revision_authority']\n  $.canonical_projection.shape[0]: 59 != 58"
```

### tests/refactor_parity/test_clock_independence.py::test_goldens_do_not_depend_on_the_wall_clock[snapshot]

Decision: D1

```json
"AssertionError: snapshot.json: 276 difference(s); first ones:\n  $.snapshot_fields: length 28 != 30\n  $.frames.prices.shape[0]: 53100 != 52200\n  $.frames.prices.numeric_columns.open.count: 53100 != 52200\n  $.frames.prices.numeric_columns.open.sum: 4712484.077768902 != 4598719.972632969\n  $.frames.prices.numeric_columns.open.mean: 88.7473460973428 != 88.09808376691511\n  $.frames.prices.numeric_columns.high.count: 53100 != 52200\n  $.frames.prices.numeric_columns.high.sum: 4737128.11759236 != 4622768.403404292\n  $.frames.prices.numeric_columns.high.mean: 89.21145230870734 != 88.55878167441172\n  $.frames.prices.numeric_columns.low.count: 53100 != 52200\n  $.frames.prices.numeric_columns.low.sum: 4688197.6256793775 != 4575024.521272723\n  $.frames.prices.numeric_columns.low.mean: 88.2899741182557 != 87.64414791710196\n  $.frames.prices.numeric_columns.close.count: 53100 != 52200\n  $.frames.prices.numeric_columns.close.sum: 4712731.146732758 != 4598960.962465105\n  $.frames.prices.numeric_columns.close.mean: 88.75199899685043 != 88.10270043036599\n  $.frames.prices.numeric_columns.adjusted_close.count: 53100 != 52200\n  $.frames.prices.numeric_columns.adjusted_close.sum: 4712731.146732758 != 4598960.962465105\n  $.frames.prices.numeric_columns.adjusted_close.mean: 88.75199899685043 != 88.10270043036599\n  $.frames.prices.numeric_columns.volume.count: 53100 != 52200\n  $.frames.prices.numeric_columns.volume.sum: 43721415081.0 != 42510319446.0\n  $.frames.prices.numeric_columns.volume.mean: 823378.8150847458 != 814373.9357471265\n  $.frames.prices.non_float_digest: 'a0cff5d6e964c43c0ff8c31b7e662dd2c1648319c5b09f9839eee73df324682c' != '5400b17b4702a139f89d43192617c1a5a1d6b2071bbb45c56f67d0098f901859'\n  $.frames.features.shape[0]: 15458 != 15196\n  $.frames.features.numeric_columns.return_1d_log.nan_count: 59 != 58\n  $.frames.features.numeric_columns.return_1d_log.count: 15399 != 15138\n  $.frames.features.numeric_columns.return_1d_log.sum: 2.279989031314973 != 2.1877289470085577"
```

### tests/refactor_parity/test_persisted_schema_golden.py::test_persisted_schema_golden_covers_the_required_families

Decision: D1

```json
"AssertionError: data/derived/run_manifests/backtest__s54eb00f2a924.json\nassert 'data/derived/run_manifests/backtest__s54eb00f2a924.json' in {'data/backtests/backtest_metadata.json', 'data/backtests/backtest_metadata.json.meta.json', 'data/backtests/backtest_...backtest_results.csv.meta.json', 'data/backtests/equity_curves.csv', 'data/backtests/equity_curves.csv.meta.json', ...}"
```

### tests/refactor_parity/test_persisted_schema_golden.py::test_persisted_schemas_match_golden

Decision: D1

```json
"AssertionError: persisted_schema.json: 46 difference(s); first ones:\n  $.files: keys ['data/backtests/backtest_metadata.json', 'data/backtests/backtest_metadata.json.meta.json', 'data/backtests/backtest_results.csv', 'data/backtests/backtest_results.csv.meta.json', 'data/backtests/equity_curves.csv', 'data/backtests/equity_curves.csv.meta.json', 'data/backtests/quality_momentum_evidence.csv', 'data/backtests/quality_momentum_evidence.csv.meta.json', 'data/backtests/signal_log.csv', 'data/backtests/signal_log.csv.meta.json', 'data/backtests/trade_log.csv', 'data/backtests/trade_log.csv.meta.json', 'data/clean/etf_disclosures.csv', 'data/clean/etf_disclosures.parquet', 'data/clean/etf_report_conflicts.csv', 'data/clean/etf_report_conflicts.parquet', 'data/clean/etf_report_records.csv', 'data/clean/etf_report_records.parquet', 'data/clean/filings_statements.csv', 'data/clean/filings_statements.parquet', 'data/clean/filings_statements.parquet.guard', 'data/clean/index_methodology_records.csv', 'data/clean/index_methodology_records.parquet', 'data/clean/instrument_identity.csv', 'data/clean/instrument_identity.parquet', 'data/clean/news_context.csv', 'data/clean/news_context.parquet', 'data/clean/news_timestamp_validation.csv', 'data/clean/news_timestamp_validation.parquet', 'data/clean/priips_kid_records.csv', 'data/clean/priips_kid_records.parquet', 'data/clean/provider_probe_results.csv', 'data/clean/provider_probe_results.parquet', 'data/clean/source_conflicts.csv', 'data/clean/source_conflicts.parquet', 'data/derived/benchmark_attribution.csv', 'data/derived/benchmark_attribution.parquet', 'data/derived/correlation_clusters.csv', 'data/derived/correlation_clusters.parquet', 'data/derived/evidence_ledger.csv', 'data/derived/evidence_ledger.parquet', 'data/derived/feature_drivers.csv', 'data/derived/feature_drivers.parquet', 'data/derived/market_regime.csv', 'data/derived/market_regime.json', 'data/derived/model_calibration.csv', 'data/derived/model_calibration.parquet', 'data/derived/run_manifests/backtest__s54eb00f2a924.json', 'data/derived/run_manifests/features_2026-09-30__s54eb00f2a924.json', 'data/derived/run_manifests/forecast_20260930__s54eb00f2a924.json', 'data/derived/run_manifests/score_<stamp>_<8hex>.json', 'data/derived/score_components.csv', 'data/derived/score_components.parquet', 'data/derived/score_formula_registry.json', 'data/derived/score_history.csv', 'data/derived/score_history.parquet', 'data/derived/score_metric_history.csv', 'data/derived/score_metric_history.parquet', 'data/derived/scoreboard.csv', 'data/derived/scoreboard.json', 'data/derived/scoreboard.parquet', 'data/derived/strategy_templates.csv', 'data/derived/version_registry.json', 'data/features/features_daily.parquet', 'data/features/features_daily.parquet.meta.json', 'data/forecasts/forecast_results_yfinance_20260930.csv', 'data/forecasts/forecast_results_yfinance_20260930.csv.meta.json', 'data/portfolios/current_holdings.csv', 'data/raw/prices/sample_prices.csv', 'data/validated/prices/prices_daily.parquet'] != ['data/backtests/backtest_metadata.json', 'data/backtests/backtest_metadata.json.meta.json', 'data/backtests/backtest_results.csv', 'data/backtests/backtest_results.csv.meta.json', 'data/backtests/equity_curves.csv', 'data/backtests/equity_curves.csv.meta.json', 'data/backtests/quality_momentum_evidence.csv', 'data/backtests/quality_momentum_evidence.csv.meta.json', 'data/backtests/signal_log.csv', 'data/backtests/signal_log.csv.meta.json', 'data/backtests/trade_log.csv', 'data/backtests/trade_log.csv.meta.json', 'data/clean/etf_disclosures.csv', 'data/clean/etf_disclosures.parquet', 'data/clean/etf_report_conflicts.csv', 'data/clean/etf_report_conflicts.parquet', 'data/clean/etf_report_records.csv', 'data/clean/etf_report_records.parquet', 'data/clean/filings_statements.csv', 'data/clean/filings_statements.parquet', 'data/clean/filings_statements.parquet.guard', 'data/clean/index_methodology_records.csv', 'data/clean/index_methodology_records.parquet', 'data/clean/instrument_identity.csv', 'data/clean/instrument_identity.parquet', 'data/clean/news_context.csv', 'data/clean/news_context.parquet', 'data/clean/news_timestamp_validation.csv', 'data/clean/news_timestamp_validation.parquet', 'data/clean/priips_kid_records.csv', 'data/clean/priips_kid_records.parquet', 'data/clean/provider_probe_results.csv', 'data/clean/provider_probe_results.parquet', 'data/clean/source_conflicts.csv', 'data/clean/source_conflicts.parquet', 'data/derived/benchmark_attribution.csv', 'data/derived/benchmark_attribution.parquet', 'data/derived/correlation_clusters.csv', 'data/derived/correlation_clusters.parquet', 'data/derived/evidence_ledger.csv', 'data/derived/evidence_ledger.parquet', 'data/derived/feature_drivers.csv', 'data/derived/feature_drivers.parquet', 'data/derived/market_regime.csv', 'data/derived/market_regime.json', 'data/derived/model_calibration.csv', 'data/derived/model_calibration.parquet', 'data/derived/run_manifests/backtest__s5944577a97bd.json', 'data/derived/run_manifests/features_2026-09-30__s5944577a97bd.json', 'data/derived/run_manifests/forecast_20260930__s5944577a97bd.json', 'data/derived/run_manifests/score_<stamp>_<8hex>.json', 'data/derived/score_components.csv', 'data/derived/score_components.parquet', 'data/derived/score_formula_registry.json', 'data/derived/score_history.csv', 'data/derived/score_history.parquet', 'data/derived/score_metric_history.csv', 'data/derived/score_metric_history.parquet', 'data/derived/scoreboard.csv', 'data/derived/scoreboard.json', 'data/derived/scoreboard.parquet', 'data/derived/strategy_templates.csv', 'data/derived/version_registry.json', 'data/features/features_daily.parquet', 'data/features/features_daily.parquet.meta.json', 'data/forecasts/forecast_results_yfinance_20260930.csv', 'data/forecasts/forecast_results_yfinance_20260930.csv.meta.json', 'data/portfolios/current_holdings.csv', 'data/raw/prices/sample_prices.csv', 'data/storage/cockpit.sqlite3', 'data/validated/prices/prices_daily.parquet']\n  $.forecast_file.frame.shape[0]: 885 != 870\n  $.forecast_file.frame.numeric_columns.horizon_days.count: 885 != 870\n  $.forecast_file.frame.numeric_columns.horizon_days.sum: 68145.0 != 66990.0\n  $.forecast_file.frame.numeric_columns.expected_return.nan_count: 590 != 580\n  $.forecast_file.frame.numeric_columns.expected_return.count: 295 != 290\n  $.forecast_file.frame.numeric_columns.expected_return.sum: 0.5879154247674752 != 0.6053910381913706\n  $.forecast_file.frame.numeric_columns.expected_return.mean: 0.001992933643279577 != 0.0020875553041081745\n  $.forecast_file.frame.numeric_columns.expected_excess_return.nan_count: 885 != 870\n  $.forecast_file.frame.numeric_columns.q10_return.nan_count: 590 != 580\n  $.forecast_file.frame.numeric_columns.q10_return.count: 295 != 290\n  $.forecast_file.frame.numeric_columns.q10_return.sum: -32.64403842869774 != -32.090846675014284\n  $.forecast_file.frame.numeric_columns.q10_return.mean: -0.11065775738541607 != -0.11065809198280788\n  $.forecast_file.frame.numeric_columns.q50_return.nan_count: 590 != 580\n  $.forecast_file.frame.numeric_columns.q50_return.count: 295 != 290\n  $.forecast_file.frame.numeric_columns.q50_return.sum: 0.5879154247674752 != 0.6053910381913706\n  $.forecast_file.frame.numeric_columns.q50_return.mean: 0.001992933643279577 != 0.0020875553041081745\n  $.forecast_file.frame.numeric_columns.q90_return.nan_count: 590 != 580\n  $.forecast_file.frame.numeric_columns.q90_return.count: 295 != 290\n  $.forecast_file.frame.numeric_columns.q90_return.sum: 33.819869278232694 != 33.301628751397025\n  $.forecast_file.frame.numeric_columns.q90_return.mean: 0.11464362467197524 != 0.11483320259102422\n  $.forecast_file.frame.numeric_columns.forecast_vol.nan_count: 590 != 580\n  $.forecast_file.frame.numeric_columns.forecast_vol.count: 295 != 290\n  $.forecast_file.frame.numeric_columns.forecast_vol.sum: 25.962463948019696 != 25.54393571344191\n  $.forecast_file.frame.numeric_columns.forecast_vol.mean: 0.08800835236616845 != 0.08808253694290315"
```

### tests/refactor_parity/test_scoreboard_golden.py::test_scoreboard_golden_is_not_vacuous

Decision: D2

```json
"assert False\n +  where False = all(<generator object test_scoreboard_golden_is_not_vacuous.<locals>.<genexpr> at 0x0000029EA79E7D80>)"
```

### tests/refactor_parity/test_scoreboard_golden.py::test_scoreboard_matches_golden

Decision: D1

```json
"AssertionError: scoreboard.json: 28 difference(s); first ones:\n  $.score_objects.order: length 59 != 58\n  $.score_objects.instrument_key: length 59 != 58\n  $.score_objects.final_score_10: length 59 != 58\n  $.score_objects.rank: length 59 != 58\n  $.score_objects.score_rank: length 59 != 58\n  $.score_objects.final_action: length 59 != 58\n  $.score_objects.one_line_reason: length 59 != 58\n  $.score_objects.warnings: length 59 != 58\n  $.score_objects.strategy_templates: length 59 != 58\n  $.score_objects.model_versions_used: length 59 != 58\n  $.score_objects.forecast_status: length 59 != 58\n  $.score_objects.news_inventory: length 59 != 58\n  $.score_objects.internal_intent: length 59 != 58\n  $.score_objects.authority_decision: length 59 != 58\n  $.score_objects.canonical_score: length 59 != 58\n  $.score_objects.valid_component_count: length 59 != 58\n  $.score_objects.total_component_count: length 59 != 58\n  $.score_objects.components: length 59 != 58\n  $.shape[0]: 59 != 58\n  $.shape[1]: 205 != 209\n  $.columns: length 205 != 209\n  $.dtypes: keys ['instrument_id', 'symbol', 'name', 'instrument_currency', 'isin', 'isin_status', 'asset_type', 'analysis_tier', 'data_policy', 'source_group', 'current_price', 'latest_price_date', 'evidence_score_10', 'evidence_quality_10', 'risk_friction_10', 'final_label', 'research_state', 'portfolio_review_state', 'analysis_status', 'research_promotion_allowed', 'portfolio_review_allowed', 'execution_allowed', 'legacy_action', 'migration_version', 'gate_policy_version', 'gate_policy_checksum', 'schema_version', 'decision', 'blocked_by', 'reason_short', 'model_authority_label', 'backtest_trust_label', 'backtest_trust_score_10', 'model_calibration_label', 'model_calibration_score_10', 'market_regime_label', 'market_regime_score_10', 'portfolio_fit_label', 'portfolio_fit_score_10', 'strategy_template_label', 'strategy_template_descriptions', 'evidence_sample_days', 'evidence_maturity_state', 'evidence_maturity_label', 'too_good_to_be_true_warning', 'evidence_sanity_warnings', 'evidence_warning_count', 'benchmark_id', 'benchmark_period_days', 'benchmark_return', 'instrument_period_return', 'benchmark_beta', 'benchmark_correlation', 'alpha_proxy', 'alpha_t_stat', 'benchmark_attribution_label', 'cash_instrument_return', 'cash_return', 'excess_over_cash', 'cash_instrument_id', 'cash_currency', 'cash_unit', 'cash_dataset_kind', 'cash_start_date', 'cash_end_date', 'cash_horizon_years', 'cash_rate', 'cash_vintage', 'cash_comparison_status', 'cash_comparison_reason', 'cash_source_id', 'cash_source_authority', 'cash_source_checksum', 'cash_source_terms', 'cash_methodology', 'cash_mapping_methodology', 'cash_day_count', 'cash_compounding', 'cash_reinvestment', 'cash_effective_at', 'cash_published_at', 'cash_available_at', 'cash_curve_id', 'cash_curve_version', 'cash_curve_revision', 'cash_curve_type', 'cash_extrapolation_allowed', 'cash_fallback', 'cash_fallback_from', 'cash_interpolation', 'cash_freshness', 'cash_freshness_status', 'cash_decision_time', 'cash_knowledge_cutoff', 'inflation_context', 'sector_theme_warning', 'backtest_validity', 'model_contamination_risk', 'model_authority_reason', 'calibration_required', 'gross_expected_edge_bps', 'estimated_total_cost_bps', 'net_expected_edge_bps', 'edge_to_cost_ratio', 'cost_stress_scenario', 'gross_expected_return', 'q10_expected_return', 'q50_expected_return', 'q90_expected_return', 'expected_return_horizon_days', 'net_q10_expected_return', 'net_expected_return', 'net_q90_expected_return', 'expected_return_order_value_eur', 'expected_return_cost_bps', 'expected_return_cost_eur', 'expected_return_cost_ratio', 'expected_return_distribution_version', 'expected_return_source_dataset', 'crowding_cluster_id', 'crowding_cluster_label', 'crowding_warning', 'crowding_average_peer_correlation', 'crowding_sample_size', 'crowding_as_of', 'crowding_source_dataset', 'crowding_pair_sample_size', 'crowding_cluster_weight', 'crowding_cluster_risk_contribution', 'crowding_ranking_coverage', 'crowding_top_ranked_concentration', 'crowding_top_ranked_theme_concentration', 'crowding_top_ranked_theme_warning', 'sector_return', 'sector_relative_return', 'sector_beta', 'sector_correlation', 'sector_alpha_proxy', 'sector_attribution_status', 'attribution_sample_size', 'attribution_as_of', 'attribution_source_dataset', 'theme_return', 'theme_relative_return', 'theme_beta', 'theme_correlation', 'theme_alpha_proxy', 'theme_attribution_status', 'theme_sample_size', 'friction_status', 'friction_reason', 'formula_version', 'formula_checksum', 'source_vintage_hash', 'classification_version_id', 'classification_invalidation_hash', 'classification_dependency_status', 'canonical_attractiveness_10', 'canonical_expected_return_10', 'canonical_risk_implementation_10', 'canonical_evidence_confidence_10', 'canonical_coverage', 'canonical_warnings', 'valid_components', 'total_components', 'source_quality', 'data_quality_score_10', 'data_quality_status', 'data_quality_authority', 'momentum_score_10', 'momentum_status', 'momentum_authority', 'trend_score_10', 'trend_status', 'trend_authority', 'risk_score_10', 'risk_status', 'risk_authority', 'relative_strength_score_10', 'relative_strength_status', 'relative_strength_authority', 'liquidity_cost_score_10', 'liquidity_cost_status', 'liquidity_cost_authority', 'etf_exposure_score_10', 'etf_exposure_status', 'etf_exposure_authority', 'baseline_score_10', 'baseline_status', 'baseline_authority', 'timesfm_score_10', 'timesfm_status', 'timesfm_authority', 'toto_score_10', 'toto_status', 'toto_authority', 'stock_value_score_10', 'stock_value_status', 'stock_value_authority', 'stock_quality_score_10', 'stock_quality_status', 'stock_quality_authority', 'analyst_revision_score_10', 'analyst_revision_status', 'analyst_revision_authority'] != ['instrument_id', 'symbol', 'name', 'instrument_currency', 'isin', 'isin_status', 'asset_type', 'analysis_tier', 'data_policy', 'source_group', 'current_price', 'latest_price_date', 'evidence_score_10', 'evidence_quality_10', 'risk_friction_10', 'final_label', 'research_state', 'portfolio_review_state', 'analysis_status', 'research_promotion_allowed', 'portfolio_review_allowed', 'execution_allowed', 'legacy_action', 'migration_version', 'gate_policy_version', 'gate_policy_checksum', 'schema_version', 'decision', 'blocked_by', 'reason_short', 'final_combined_score_10', 'coverage', 'missing_components', 'identity_conflict_reason', 'model_authority_label', 'backtest_trust_label', 'backtest_trust_score_10', 'model_calibration_label', 'model_calibration_score_10', 'market_regime_label', 'market_regime_score_10', 'portfolio_fit_label', 'portfolio_fit_score_10', 'strategy_template_label', 'strategy_template_descriptions', 'evidence_sample_days', 'evidence_maturity_state', 'evidence_maturity_label', 'too_good_to_be_true_warning', 'evidence_sanity_warnings', 'evidence_warning_count', 'benchmark_id', 'benchmark_period_days', 'benchmark_return', 'instrument_period_return', 'benchmark_beta', 'benchmark_correlation', 'alpha_proxy', 'alpha_t_stat', 'benchmark_attribution_label', 'cash_instrument_return', 'cash_return', 'excess_over_cash', 'cash_instrument_id', 'cash_currency', 'cash_unit', 'cash_dataset_kind', 'cash_start_date', 'cash_end_date', 'cash_horizon_years', 'cash_rate', 'cash_vintage', 'cash_comparison_status', 'cash_comparison_reason', 'cash_source_id', 'cash_source_authority', 'cash_source_checksum', 'cash_source_terms', 'cash_methodology', 'cash_mapping_methodology', 'cash_day_count', 'cash_compounding', 'cash_reinvestment', 'cash_effective_at', 'cash_published_at', 'cash_available_at', 'cash_curve_id', 'cash_curve_version', 'cash_curve_revision', 'cash_curve_type', 'cash_extrapolation_allowed', 'cash_fallback', 'cash_fallback_from', 'cash_interpolation', 'cash_freshness', 'cash_freshness_status', 'cash_decision_time', 'cash_knowledge_cutoff', 'inflation_context', 'sector_theme_warning', 'backtest_validity', 'model_contamination_risk', 'model_authority_reason', 'calibration_required', 'gross_expected_edge_bps', 'estimated_total_cost_bps', 'net_expected_edge_bps', 'edge_to_cost_ratio', 'cost_stress_scenario', 'gross_expected_return', 'q10_expected_return', 'q50_expected_return', 'q90_expected_return', 'expected_return_horizon_days', 'net_q10_expected_return', 'net_expected_return', 'net_q90_expected_return', 'expected_return_order_value_eur', 'expected_return_cost_bps', 'expected_return_cost_eur', 'expected_return_cost_ratio', 'expected_return_distribution_version', 'expected_return_source_dataset', 'crowding_cluster_id', 'crowding_cluster_label', 'crowding_warning', 'crowding_average_peer_correlation', 'crowding_sample_size', 'crowding_as_of', 'crowding_source_dataset', 'crowding_pair_sample_size', 'crowding_cluster_weight', 'crowding_cluster_risk_contribution', 'crowding_ranking_coverage', 'crowding_top_ranked_concentration', 'crowding_top_ranked_theme_concentration', 'crowding_top_ranked_theme_warning', 'sector_return', 'sector_relative_return', 'sector_beta', 'sector_correlation', 'sector_alpha_proxy', 'sector_attribution_status', 'attribution_sample_size', 'attribution_as_of', 'attribution_source_dataset', 'theme_return', 'theme_relative_return', 'theme_beta', 'theme_correlation', 'theme_alpha_proxy', 'theme_attribution_status', 'theme_sample_size', 'friction_status', 'friction_reason', 'formula_version', 'formula_checksum', 'source_vintage_hash', 'classification_version_id', 'classification_invalidation_hash', 'classification_dependency_status', 'canonical_attractiveness_10', 'canonical_expected_return_10', 'canonical_risk_implementation_10', 'canonical_evidence_confidence_10', 'canonical_coverage', 'canonical_warnings', 'valid_components', 'total_components', 'source_quality', 'data_quality_score_10', 'data_quality_status', 'data_quality_authority', 'momentum_score_10', 'momentum_status', 'momentum_authority', 'trend_score_10', 'trend_status', 'trend_authority', 'risk_score_10', 'risk_status', 'risk_authority', 'relative_strength_score_10', 'relative_strength_status', 'relative_strength_authority', 'liquidity_cost_score_10', 'liquidity_cost_status', 'liquidity_cost_authority', 'etf_exposure_score_10', 'etf_exposure_status', 'etf_exposure_authority', 'baseline_score_10', 'baseline_status', 'baseline_authority', 'timesfm_score_10', 'timesfm_status', 'timesfm_authority', 'toto_score_10', 'toto_status', 'toto_authority', 'stock_value_score_10', 'stock_value_status', 'stock_value_authority', 'stock_quality_score_10', 'stock_quality_status', 'stock_quality_authority', 'analyst_revision_score_10', 'analyst_revision_status', 'analyst_revision_authority']\n  $.order: length 59 != 58\n  $.columns_by_name: keys ['instrument_id', 'symbol', 'name', 'instrument_currency', 'isin', 'isin_status', 'asset_type', 'analysis_tier', 'data_policy', 'source_group', 'current_price', 'latest_price_date', 'evidence_score_10', 'evidence_quality_10', 'risk_friction_10', 'final_label', 'research_state', 'portfolio_review_state', 'analysis_status', 'research_promotion_allowed', 'portfolio_review_allowed', 'execution_allowed', 'legacy_action', 'migration_version', 'gate_policy_version', 'gate_policy_checksum', 'schema_version', 'decision', 'blocked_by', 'reason_short', 'model_authority_label', 'backtest_trust_label', 'backtest_trust_score_10', 'model_calibration_label', 'model_calibration_score_10', 'market_regime_label', 'market_regime_score_10', 'portfolio_fit_label', 'portfolio_fit_score_10', 'strategy_template_label', 'strategy_template_descriptions', 'evidence_sample_days', 'evidence_maturity_state', 'evidence_maturity_label', 'too_good_to_be_true_warning', 'evidence_sanity_warnings', 'evidence_warning_count', 'benchmark_id', 'benchmark_period_days', 'benchmark_return', 'instrument_period_return', 'benchmark_beta', 'benchmark_correlation', 'alpha_proxy', 'alpha_t_stat', 'benchmark_attribution_label', 'cash_instrument_return', 'cash_return', 'excess_over_cash', 'cash_instrument_id', 'cash_currency', 'cash_unit', 'cash_dataset_kind', 'cash_start_date', 'cash_end_date', 'cash_horizon_years', 'cash_rate', 'cash_vintage', 'cash_comparison_status', 'cash_comparison_reason', 'cash_source_id', 'cash_source_authority', 'cash_source_checksum', 'cash_source_terms', 'cash_methodology', 'cash_mapping_methodology', 'cash_day_count', 'cash_compounding', 'cash_reinvestment', 'cash_effective_at', 'cash_published_at', 'cash_available_at', 'cash_curve_id', 'cash_curve_version', 'cash_curve_revision', 'cash_curve_type', 'cash_extrapolation_allowed', 'cash_fallback', 'cash_fallback_from', 'cash_interpolation', 'cash_freshness', 'cash_freshness_status', 'cash_decision_time', 'cash_knowledge_cutoff', 'inflation_context', 'sector_theme_warning', 'backtest_validity', 'model_contamination_risk', 'model_authority_reason', 'calibration_required', 'gross_expected_edge_bps', 'estimated_total_cost_bps', 'net_expected_edge_bps', 'edge_to_cost_ratio', 'cost_stress_scenario', 'gross_expected_return', 'q10_expected_return', 'q50_expected_return', 'q90_expected_return', 'expected_return_horizon_days', 'net_q10_expected_return', 'net_expected_return', 'net_q90_expected_return', 'expected_return_order_value_eur', 'expected_return_cost_bps', 'expected_return_cost_eur', 'expected_return_cost_ratio', 'expected_return_distribution_version', 'expected_return_source_dataset', 'crowding_cluster_id', 'crowding_cluster_label', 'crowding_warning', 'crowding_average_peer_correlation', 'crowding_sample_size', 'crowding_as_of', 'crowding_source_dataset', 'crowding_pair_sample_size', 'crowding_cluster_weight', 'crowding_cluster_risk_contribution', 'crowding_ranking_coverage', 'crowding_top_ranked_concentration', 'crowding_top_ranked_theme_concentration', 'crowding_top_ranked_theme_warning', 'sector_return', 'sector_relative_return', 'sector_beta', 'sector_correlation', 'sector_alpha_proxy', 'sector_attribution_status', 'attribution_sample_size', 'attribution_as_of', 'attribution_source_dataset', 'theme_return', 'theme_relative_return', 'theme_beta', 'theme_correlation', 'theme_alpha_proxy', 'theme_attribution_status', 'theme_sample_size', 'friction_status', 'friction_reason', 'formula_version', 'formula_checksum', 'source_vintage_hash', 'classification_version_id', 'classification_invalidation_hash', 'classification_dependency_status', 'canonical_attractiveness_10', 'canonical_expected_return_10', 'canonical_risk_implementation_10', 'canonical_evidence_confidence_10', 'canonical_coverage', 'canonical_warnings', 'valid_components', 'total_components', 'source_quality', 'data_quality_score_10', 'data_quality_status', 'data_quality_authority', 'momentum_score_10', 'momentum_status', 'momentum_authority', 'trend_score_10', 'trend_status', 'trend_authority', 'risk_score_10', 'risk_status', 'risk_authority', 'relative_strength_score_10', 'relative_strength_status', 'relative_strength_authority', 'liquidity_cost_score_10', 'liquidity_cost_status', 'liquidity_cost_authority', 'etf_exposure_score_10', 'etf_exposure_status', 'etf_exposure_authority', 'baseline_score_10', 'baseline_status', 'baseline_authority', 'timesfm_score_10', 'timesfm_status', 'timesfm_authority', 'toto_score_10', 'toto_status', 'toto_authority', 'stock_value_score_10', 'stock_value_status', 'stock_value_authority', 'stock_quality_score_10', 'stock_quality_status', 'stock_quality_authority', 'analyst_revision_score_10', 'analyst_revision_status', 'analyst_revision_authority'] != ['instrument_id', 'symbol', 'name', 'instrument_currency', 'isin', 'isin_status', 'asset_type', 'analysis_tier', 'data_policy', 'source_group', 'current_price', 'latest_price_date', 'evidence_score_10', 'evidence_quality_10', 'risk_friction_10', 'final_label', 'research_state', 'portfolio_review_state', 'analysis_status', 'research_promotion_allowed', 'portfolio_review_allowed', 'execution_allowed', 'legacy_action', 'migration_version', 'gate_policy_version', 'gate_policy_checksum', 'schema_version', 'decision', 'blocked_by', 'reason_short', 'final_combined_score_10', 'coverage', 'missing_components', 'identity_conflict_reason', 'model_authority_label', 'backtest_trust_label', 'backtest_trust_score_10', 'model_calibration_label', 'model_calibration_score_10', 'market_regime_label', 'market_regime_score_10', 'portfolio_fit_label', 'portfolio_fit_score_10', 'strategy_template_label', 'strategy_template_descriptions', 'evidence_sample_days', 'evidence_maturity_state', 'evidence_maturity_label', 'too_good_to_be_true_warning', 'evidence_sanity_warnings', 'evidence_warning_count', 'benchmark_id', 'benchmark_period_days', 'benchmark_return', 'instrument_period_return', 'benchmark_beta', 'benchmark_correlation', 'alpha_proxy', 'alpha_t_stat', 'benchmark_attribution_label', 'cash_instrument_return', 'cash_return', 'excess_over_cash', 'cash_instrument_id', 'cash_currency', 'cash_unit', 'cash_dataset_kind', 'cash_start_date', 'cash_end_date', 'cash_horizon_years', 'cash_rate', 'cash_vintage', 'cash_comparison_status', 'cash_comparison_reason', 'cash_source_id', 'cash_source_authority', 'cash_source_checksum', 'cash_source_terms', 'cash_methodology', 'cash_mapping_methodology', 'cash_day_count', 'cash_compounding', 'cash_reinvestment', 'cash_effective_at', 'cash_published_at', 'cash_available_at', 'cash_curve_id', 'cash_curve_version', 'cash_curve_revision', 'cash_curve_type', 'cash_extrapolation_allowed', 'cash_fallback', 'cash_fallback_from', 'cash_interpolation', 'cash_freshness', 'cash_freshness_status', 'cash_decision_time', 'cash_knowledge_cutoff', 'inflation_context', 'sector_theme_warning', 'backtest_validity', 'model_contamination_risk', 'model_authority_reason', 'calibration_required', 'gross_expected_edge_bps', 'estimated_total_cost_bps', 'net_expected_edge_bps', 'edge_to_cost_ratio', 'cost_stress_scenario', 'gross_expected_return', 'q10_expected_return', 'q50_expected_return', 'q90_expected_return', 'expected_return_horizon_days', 'net_q10_expected_return', 'net_expected_return', 'net_q90_expected_return', 'expected_return_order_value_eur', 'expected_return_cost_bps', 'expected_return_cost_eur', 'expected_return_cost_ratio', 'expected_return_distribution_version', 'expected_return_source_dataset', 'crowding_cluster_id', 'crowding_cluster_label', 'crowding_warning', 'crowding_average_peer_correlation', 'crowding_sample_size', 'crowding_as_of', 'crowding_source_dataset', 'crowding_pair_sample_size', 'crowding_cluster_weight', 'crowding_cluster_risk_contribution', 'crowding_ranking_coverage', 'crowding_top_ranked_concentration', 'crowding_top_ranked_theme_concentration', 'crowding_top_ranked_theme_warning', 'sector_return', 'sector_relative_return', 'sector_beta', 'sector_correlation', 'sector_alpha_proxy', 'sector_attribution_status', 'attribution_sample_size', 'attribution_as_of', 'attribution_source_dataset', 'theme_return', 'theme_relative_return', 'theme_beta', 'theme_correlation', 'theme_alpha_proxy', 'theme_attribution_status', 'theme_sample_size', 'friction_status', 'friction_reason', 'formula_version', 'formula_checksum', 'source_vintage_hash', 'classification_version_id', 'classification_invalidation_hash', 'classification_dependency_status', 'canonical_attractiveness_10', 'canonical_expected_return_10', 'canonical_risk_implementation_10', 'canonical_evidence_confidence_10', 'canonical_coverage', 'canonical_warnings', 'valid_components', 'total_components', 'source_quality', 'data_quality_score_10', 'data_quality_status', 'data_quality_authority', 'momentum_score_10', 'momentum_status', 'momentum_authority', 'trend_score_10', 'trend_status', 'trend_authority', 'risk_score_10', 'risk_status', 'risk_authority', 'relative_strength_score_10', 'relative_strength_status', 'relative_strength_authority', 'liquidity_cost_score_10', 'liquidity_cost_status', 'liquidity_cost_authority', 'etf_exposure_score_10', 'etf_exposure_status', 'etf_exposure_authority', 'baseline_score_10', 'baseline_status', 'baseline_authority', 'timesfm_score_10', 'timesfm_status', 'timesfm_authority', 'toto_score_10', 'toto_status', 'toto_authority', 'stock_value_score_10', 'stock_value_status', 'stock_value_authority', 'stock_quality_score_10', 'stock_quality_status', 'stock_quality_authority', 'analyst_revision_score_10', 'analyst_revision_status', 'analyst_revision_authority']\n  $.canonical_projection.shape[0]: 59 != 58"
```

### tests/refactor_parity/test_snapshot_golden.py::test_snapshot_digest_matches_golden

Decision: D1

```json
"AssertionError: snapshot.json: 276 difference(s); first ones:\n  $.snapshot_fields: length 28 != 30\n  $.frames.prices.shape[0]: 53100 != 52200\n  $.frames.prices.numeric_columns.open.count: 53100 != 52200\n  $.frames.prices.numeric_columns.open.sum: 4712484.077768902 != 4598719.972632969\n  $.frames.prices.numeric_columns.open.mean: 88.7473460973428 != 88.09808376691511\n  $.frames.prices.numeric_columns.high.count: 53100 != 52200\n  $.frames.prices.numeric_columns.high.sum: 4737128.11759236 != 4622768.403404292\n  $.frames.prices.numeric_columns.high.mean: 89.21145230870734 != 88.55878167441172\n  $.frames.prices.numeric_columns.low.count: 53100 != 52200\n  $.frames.prices.numeric_columns.low.sum: 4688197.6256793775 != 4575024.521272723\n  $.frames.prices.numeric_columns.low.mean: 88.2899741182557 != 87.64414791710196\n  $.frames.prices.numeric_columns.close.count: 53100 != 52200\n  $.frames.prices.numeric_columns.close.sum: 4712731.146732758 != 4598960.962465105\n  $.frames.prices.numeric_columns.close.mean: 88.75199899685043 != 88.10270043036599\n  $.frames.prices.numeric_columns.adjusted_close.count: 53100 != 52200\n  $.frames.prices.numeric_columns.adjusted_close.sum: 4712731.146732758 != 4598960.962465105\n  $.frames.prices.numeric_columns.adjusted_close.mean: 88.75199899685043 != 88.10270043036599\n  $.frames.prices.numeric_columns.volume.count: 53100 != 52200\n  $.frames.prices.numeric_columns.volume.sum: 43721415081.0 != 42510319446.0\n  $.frames.prices.numeric_columns.volume.mean: 823378.8150847458 != 814373.9357471265\n  $.frames.prices.non_float_digest: 'a0cff5d6e964c43c0ff8c31b7e662dd2c1648319c5b09f9839eee73df324682c' != '5400b17b4702a139f89d43192617c1a5a1d6b2071bbb45c56f67d0098f901859'\n  $.frames.features.shape[0]: 15458 != 15196\n  $.frames.features.numeric_columns.return_1d_log.nan_count: 59 != 58\n  $.frames.features.numeric_columns.return_1d_log.count: 15399 != 15138\n  $.frames.features.numeric_columns.return_1d_log.sum: 2.279989031314973 != 2.1877289470085577"
```

### tests/test_b00_control_plane.py::test_completion_document_check_is_offline_and_fresh

Decision: D6

```json
"AssertionError: STALE: docs/product-completion/reconciliation/2026-07-21-2337f69/current-state-diff.md, docs/product-completion/reconciliation/2026-07-21-2337f69/package-discrepancies.md\n  \nassert 1 == 0\n +  where 1 = CompletedProcess(args=['C:\\\\Users\\\\thor2\\\\AppData\\\\Local\\\\Programs\\\\Python\\\\Python312\\\\python.exe', 'scripts/generate_...urrent-state-diff.md, docs/product-completion/reconciliation/2026-07-21-2337f69/package-discrepancies.md\\n', stderr='').returncode"
```

### tests/test_documentation_integrity.py::test_data_dictionary_version_matches_project_release

Decision: D6

```json
"AssertionError: assert 'Release vers...1.0-beta.1`).' == 'Release version: `1.1.0b1`.'\n  \n  - Release version: `1.1.0b1`.\n  + Release version: `1.1.0b1` (display: `1.1.0-beta.1`)."
```

### tests/test_documentation_integrity.py::test_generated_documentation_has_no_drift

Decision: D6

```json
"AssertionError: ('generate_data_dictionary.py', 'STALE: C:\\\\dev\\\\etf-BF-T-GATE\\\\docs\\\\reference\\\\data-dictionary.md\n  first differing line 3: expected: Release version: `1.1.0b1`.\n  actual: Release version: `1.1.0b1` (display: `1.1.0-beta.1`).\n  ', '')\nassert 1 == 0\n +  where 1 = CompletedProcess(args=['C:\\\\Users\\\\thor2\\\\AppData\\\\Local\\\\Programs\\\\Python\\\\Python312\\\\python.exe', 'C:\\\\dev\\\\etf-BF-T... 3: expected: Release version: `1.1.0b1`.\\nactual: Release version: `1.1.0b1` (display: `1.1.0-beta.1`).\\n', stderr='').returncode"
```

### tests/test_norway_official_filing.py::test_wrong_issuer_and_orgnr_are_rejected

Decision: D3

```json
"Failed: DID NOT RAISE ValueError"
```

### tests/test_responsive_summary_pages.py::test_summary_cards_reflow_natively_and_keep_session[/screener]

Decision: D7

```json
"StopIteration"
```

### tests/test_responsive_summary_pages.py::test_summary_cards_reflow_natively_and_keep_session[/signals]

Decision: D7

```json
"StopIteration"
```

### tests/test_sparebank_onboarding.py::test_source_has_no_hardcoded_sparebank_issuer_table

Decision: D4

```json
"AssertionError: assert {'scripts/smo...py': {'MING'}} == {'scripts/smo...py': {'MING'}}\n  \n  Omitting 2 identical items, use -vv to show\n  Left contains 1 more item:\n  {'scripts/diag/owner_identity_migration.py': {'MORG'}}\n  Use -v to get more diff"
```

### tests/test_task17_ui_contracts.py::test_what_changed_uses_compact_responsive_instrument_cards_without_horizontal_table

Decision: D7

```json
"assert False\n +  where False = any(<generator object test_what_changed_uses_compact_responsive_instrument_cards_without_horizontal_table.<locals>.<genexpr> at 0x0000029EA0FEC120>)"
```

### tests/test_u1_home_pages.py::test_onboarding_leads_with_setup_and_discloses_details

Decision: D7

```json
"AttributeError: 'PageView' object has no attribute 'key'"
```

### tests/test_user_documentation.py::test_documentation_release_stamps_match_project_version

Decision: D6

```json
"AssertionError: README.md\nassert 'Release version: `1.1.0b1`.' in ['# Documentation index', '', 'Release version: `1.1.0b1` (display: `1.1.0-beta.1`).', '']"
```

### tests/test_user_documentation.py::test_documented_on_screen_labels_exist_in_application_source

Decision: D6

```json
"AssertionError: ('TUTORIALS.md', ['Dry-run validate', 'Export decision journal', 'Export scoreboard', 'Export watchlist', 'Stage import', 'Validate tickers online (optional)'])\nassert not ['Dry-run validate', 'Export decision journal', 'Export scoreboard', 'Export watchlist', 'Stage import', 'Validate tickers online (optional)']"
```

### tests/test_user_documentation.py::test_methodology_index_links_every_architecture_and_sdd_page

Decision: D6

```json
"AssertionError: ['architecture/sparebank-book-gap-2026-10.md']\nassert not ['architecture/sparebank-book-gap-2026-10.md']"
```

## Goldens

Regenerated files: **none**. No refresh environment variable was enabled. Proposed existing fixtures requiring owner path authorization: `tests/fixtures/refactor_parity/backtest.json`, `persisted_schema.json`, `scoreboard.json`, `snapshot.json`. No attribution is claimed for unregenerated artifacts.

## Changed files

- `src/etf_cockpit/app/components/kit/controls.py`
- `src/etf_cockpit/app/components/shell/depth_dialog.py`
- `src/etf_cockpit/app/pages/_p1_common.py`
- `src/etf_cockpit/app/pages/data_health.py`
- `src/etf_cockpit/app/pages/import_export.py`
- `src/etf_cockpit/app/pages/instrument_detail.py`
- `src/etf_cockpit/app/pages/macro_factors.py`
- `src/etf_cockpit/app/pages/onboarding.py`
- `src/etf_cockpit/app/pages/operations.py`
- `src/etf_cockpit/app/pages/risk.py`
- `src/etf_cockpit/app/pages/settings.py`
- `src/etf_cockpit/app/pages/system_map.py`
- `src/etf_cockpit/app/state.py`
- `src/etf_cockpit/application/instrument_detail_view.py`
- `src/etf_cockpit/application/settings.py`
- `src/etf_cockpit/application/ui_views/sectors.py`
- `src/etf_cockpit/backtest/engine.py`
- `src/etf_cockpit/data/esef_extensions.py`
- `src/etf_cockpit/data/score_history.py`
- `src/etf_cockpit/data/stock_fundamentals.py`
- `src/etf_cockpit/signals/simple_scores.py`
- `tests/bughunt/test_repro_s1.py`
- `tests/bughunt/test_repro_s10.py`
- `tests/bughunt/test_repro_s11.py`
- `tests/test_accessible_tables.py`
- `tests/test_application_api.py`
- `tests/test_backup_restore.py`
- `tests/test_candles.py`
- `tests/test_credentials.py`
- `tests/test_data_health.py`
- `tests/test_e2e_advanced.py`
- `tests/test_flet_startup.py`
- `tests/test_frontend_design_system.py`
- `tests/test_issue_0053_digest.py`
- `tests/test_news_ui.py`
- `tests/test_operations_workspace.py`
- `tests/test_portfolio_import_ui.py`
- `tests/test_settings_run_publication.py`
- `tests/test_startup_lazy.py`
- `tests/test_statement_normalisation.py`
- `tests/test_task17_ui_contracts.py`
- `tests/test_task19_instrument_detail.py`
- `tests/test_trust_critical_artifacts.py`
- `tests/test_u1_home_pages.py`
- `tests/test_u7_lab_pages.py`
- `tests/test_ui_staged_rendering.py`
- `tests/test_valuation_workspace_lifecycle.py`
- `tests/ui/test_decision_journal_ui.py`
- `tests/ui/test_portfolio_b_restyle_ui.py`
- `tests/ui/test_u6_universe_map_ui.py`
- `docs/development/bf-t-gate-HANDOFF.md`

## Completion checklist

- Acceptance 1: all 144 tests exist and ran; each has passing evidence or an exact owner decision above.
- Acceptance 2: no assertions weakened, tests skipped/deleted, or out-of-scope tests edited. Pre-existing platform skip is disclosed.
- Acceptance 3: golden regeneration is blocked by the actual path mismatch and additional unattributed changes, recorded as D1. No unauthorized golden write.
- The two interrupted source edits were inspected and retained where correct; no owner data was touched. The pre-existing untracked failure-list input remains untouched and is not included in commits.
- Product execution_allowed remains false; no order transmission, network or push.
- All modified tests are members of the supplied failing test-file list. Only allowed source, failing tests and this handoff document are changed.
- Changed files use LF. `git -c core.autocrlf=false diff --check` passed before the handoff was written; final verification/commit record follows below.

## Next step

First preserve this tested source checkpoint in an authorized Git session (D8 below). Owner must then resolve D1-D7 and authorize the exact out-of-scope golden/script/document paths or current-layout contracts. Then implement those bounded decisions, regenerate only approved goldens with explicit attribution and rerun without refresh, and run the completed list on the Linux release host. No release-readiness claim.

## D8: NEEDS_OPUS_DECISION - Git metadata permission

No local commit was created. Staging failed before any commit attempt because this worktree uses shared Git metadata outside the writable workspace. The managed environment allows writes under C:/dev/etf-BF-T-GATE, while the index resides under C:/Users/thor2/Desktop/Trading App/etf_ai_cockpit/.git/worktrees/etf-BF-T-GATE. Approval escalation is unavailable in this session; no permission workaround or Git relocation was attempted.

Failed command (exit 128):

```text
git -c core.autocrlf=false add -- src/etf_cockpit/data/score_history.py src/etf_cockpit/backtest/engine.py src/etf_cockpit/signals/simple_scores.py src/etf_cockpit/application/instrument_detail_view.py src/etf_cockpit/data/esef_extensions.py src/etf_cockpit/data/stock_fundamentals.py tests/test_settings_run_publication.py
```

Verbatim Git error:

```text
fatal: Unable to create 'C:/Users/thor2/Desktop/Trading App/etf_ai_cockpit/.git/worktrees/etf-BF-T-GATE/index.lock': Permission denied
```

The requested commit output is therefore blocked by environment authority, independently of the 23 product-gate owner decisions. Branch remains bf/t-gate at a7ef62458cfadd76b586ab1301d46345b0cf009c, with the tested changes uncommitted.

Planned logical commits, not executed:

- `fix(gate): repair history and backtest evidence`: the seven paths in the failed staging command.
- `fix(gate): restore instrument evidence and valuation`: instrument_detail.py and the instrument-detail, candle, statement-normalisation and valuation-lifecycle test retargeting.
- `fix(gate): restore local operations and risk evidence`: operations.py, risk.py, macro_factors.py and operations/bughunt test retargeting.
- `fix(gate): align current controls and application boundaries`: the remaining listed source and test changes.
- `fix(gate): record verified results and owner decisions`: this handoff only.

Do not include the pre-existing untracked failure-list input in these commits. No push is authorized.

## Final workspace verification

- `git -c core.autocrlf=false diff --check`: passed (exit 0). The untracked handoff was independently checked for LF and trailing whitespace; passed.
- `git -c core.autocrlf=false diff --stat`: 50 tracked files, 911 insertions, 319 deletions. The new handoff is additional and is not included in Git's unstaged tracked-file stat.
- `git status --porcelain`: all actual source/test changes remain unstaged; the handoff and the pre-existing failure-list input are untracked. No commits, staged changes or push.
- Scope/LF audit: all 51 actual changed/new deliverable files are in the packet write set (21 source files, 29 failing test files, one handoff). No out-of-scope deliverable was created.
- Git status also reports diagnostics.py as modified, but its bytes exactly equal HEAD and its diff is empty. The reason for that residual status entry is UNVERIFIED; no diagnostics.py content change belongs to the deliverable. An authorized Git session can refresh the index.
- Original branch/head were rechecked: bf/t-gate at a7ef62458cfadd76b586ab1301d46345b0cf009c.
