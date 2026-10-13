# T-INTCP correction handoff

TASK_ID: T-INTCP
MODEL/EFFORT: model=gpt-6.1-sol effort=high
STATUS: partial (all 18 findings implemented; acceptance blocked)
Branch: bf/integration
Base: 3fbbb9cd4a21da02ba59e72369f29cf6f91d3db4
Requested local commit: fix(int): Sol review findings
Commit state: not created. Git staging failed before commit because linked-worktree Git metadata is outside the writable workspace.

## Per-finding outcome and focused evidence

Tests below live in tests/test_bugfix_<train lowercase>.py. Counts include parameterised cases.

| Finding | Outcome | Focused test | Passing cases |
| --- | --- | --- | ---: |
| T-NUM 1 | Fixed: finite quality/confidence before thresholding. | test_int_num_1_non_finite_quality_is_ineligible | 8 |
| T-NUM 2 | Fixed: wide-history conflicts unavailable per instrument, independent of row order. | test_int_num_2_wide_history_conflicts_are_order_independent | 1 |
| T-NUM 3 | Fixed: invalid/undated rows excluded from latest, horizon, score and distribution selection. Legacy fixture acceptance escalated below. | test_int_num_3_undated_forecasts_never_select_as_latest | 3 |
| T-PIT 1 | Fixed: exact feature and default availability times preserved; calendar delay alone uses normalization. | test_int_pit_1_intraday_feature_time_defaults_availability_exactly | 1 |
| T-PIT 2 | Fixed: unverifiable quote timestamps make quote evidence unavailable. | test_int_pit_2_unverifiable_quote_timestamps_are_unavailable | 2 |
| T-PIT 3 | Fixed: eligible dated UI fixture restores missing q25/q75, exact complete quantile pass-through and incomplete-row rejection. Stale rejection tested separately. | test_int_pit_3_stale_forecast_rejection_is_separate_from_quantile_passthrough; tests/ui/test_page_stock_research.py::test_forecast_quantiles_are_passed_through_never_interpolated | 1 new case; restored UI test passed in module run |
| T-STORE 1 | Fixed: required dates take precedence; every holdings date alias checked for mixed dates/conflicts. | test_int_store_1_holdings_date_alias_cannot_mask_required_dates | 2 |
| T-IO 1 | Fixed: both published artifacts backed up and restored after partial deletion or directory replacement failure. | test_int_io_1_publication_failure_restores_both_artifacts | 2 |
| T-IO 2 | Fixed: BackupManifest.inventory_checksums retains current inventory; checksums keeps the existing sparse payload contract. | test_int_io_2_three_archive_chain_preserves_deletions | 1 |
| T-IO 3 | Fixed: retain deleted destination bytes and restore them when deletion/write-group fails; replacements publish after successful deletions. | test_int_io_3_failed_restore_preserves_every_original_file | 2 |
| T-IO 4 | Fixed: reject and record linked/reparse source roots before traversal. | test_int_io_4_direct_linked_roots_are_excluded_before_traversal; test_int_io_4_direct_directory_link_does_not_archive_target | 4 |
| T-IO 5 | Fixed: transformed cache names have a reserved tilde namespace; manifests/generation records retain raw identities. | test_int_io_5_transformed_identifiers_do_not_share_manifests_or_generations | 1 |
| T-IO 6 | Fixed in direct helper core/secure_update.py: hexadecimal ASCII signature/hash validation before comparison. | test_int_io_6_malformed_detached_signature_blocks_certification | 12 |
| T-SB 1 | Fixed: positive unfilled quantity requires finite end price or END_PRICE_MISSING. | test_int_sb_1_unfilled_shortfall_requires_finite_end_price | 5 |
| T-SB 2 | Fixed: existing numeric helper catches OverflowError for both bridges. | test_int_sb_2_overflowing_bridge_inputs_are_unavailable | 1 |
| T-UIA 1 | Fixed: reserved tilde suffix separates transformed and literal workspace identities while preserving the cleaned-name prefix. | test_int_uia_1_literal_transformed_workspace_name_cannot_overwrite | 1 |
| T-UIA 2 | Fixed: live PID plus exact server-returned identity required; separate per-instance assets. Existing own-server assertions retained with an identity fixture. | test_int_uia_2_live_reused_pid_does_not_authorise_foreign_http; test_int_uia_2_assets_and_record_have_unique_per_instance_identity | 4 |
| T-UIA 3 | Fixed: automatic bar domain includes zero; negative bar endpoints must remain inside plot. | test_int_uia_3_negative_bar_endpoints_stay_inside_plot | 1 |

Unique new focused cases: 52. The final non-ASCII signature fixture uses a Unicode escape to prevent shell encoding loss; its 12 affected cases were revalidated successfully.

## FILES_CHANGED

- src/etf_cockpit/analysis/sparebank/valuation.py
- src/etf_cockpit/app/components/chartkit/bars.py
- src/etf_cockpit/app/flet_app.py
- src/etf_cockpit/chatgpt_bridge/export_pack.py
- src/etf_cockpit/core/paths.py
- src/etf_cockpit/core/secure_update.py
- src/etf_cockpit/core/values.py
- src/etf_cockpit/data/backup_restore.py
- src/etf_cockpit/data/bulk_cache.py
- src/etf_cockpit/data/evidence_ledger.py
- src/etf_cockpit/data/import_export.py
- src/etf_cockpit/features/etf_economics.py
- src/etf_cockpit/features/feature_store.py
- src/etf_cockpit/models/forecast_scores.py
- src/etf_cockpit/portfolio/stress_testing.py
- tests/test_bugfix_t-io.py
- tests/test_bugfix_t-num.py
- tests/test_bugfix_t-pit.py
- tests/test_bugfix_t-sb.py
- tests/test_bugfix_t-store.py
- tests/test_bugfix_t-uia.py
- tests/ui/test_page_stock_research.py
- docs/development/bf-intcp-HANDOFF.md

Every file is named by the findings, a direct helper (core/secure_update.py), an allowed bugfix test, the explicitly allowed UI restoration, or this handoff. No out-of-scope file was edited. Earlier train work is retained.

## TESTS+RESULTS

No repo-wide suite, generators, programme check, network request, push or delegation was run. The addopts override removes duplicate -q so pytest prints counts; selections and assertions remain unchanged.

Corrected focused run:

```powershell
python -m pytest -q --tb=line -p no:cacheprovider -o addopts='' tests/test_bugfix_t-io.py tests/test_bugfix_t-num.py tests/test_bugfix_t-pit.py tests/test_bugfix_t-sb.py tests/test_bugfix_t-store.py tests/test_bugfix_t-uia.py -k 'test_int_'
```

Result: 52 passed, 117 deselected in 8.49s. All bugfix files and UI tests were also included in the module run.

Final affected signature cases:

```powershell
python -m pytest -q --tb=line -p no:cacheprovider -o addopts='' tests/test_bugfix_t-io.py -k 'test_int_io_6'
```

Result: 12 passed, 36 deselected in 2.05s.

Complete requested selection plus existing module tests was attempted:

```powershell
$bugfixTests = (Get-ChildItem tests/test_bugfix_*.py).FullName
python -m pytest -q --tb=line -p no:cacheprovider -o addopts='' $bugfixTests tests/ui/test_page_stock_research.py tests/test_evidence_ledger.py tests/test_stress_testing.py tests/test_forecast_distributions.py tests/test_forecast_uncertainty.py tests/test_feature_store.py tests/test_etf_economics.py tests/test_etf_economics_production.py tests/test_import_export.py tests/test_backup_restore.py tests/operations/test_backups.py tests/test_bulk_cache.py tests/test_release_certification.py tests/test_secure_update.py tests/test_sparebank_valuation.py tests/test_sparebank_events.py tests/test_sparebank_bank_economics.py tests/test_paths.py tests/test_comparison_workspace.py tests/test_flet_startup.py tests/ui/test_charts_bars_lines.py tests/test_release_hardening.py tests/test_complete_audit_packet.py
```

Result: 1 collection error in 7.35s; no test bodies ran. tests/test_etf_economics.py collection fails creating/cleaning a TemporaryDirectory under logs/pytest_system_tmp. Independent diagnostic command:

```powershell
python -m pytest -q --tb=long -p no:cacheprovider -o addopts='' tests/test_etf_economics.py
```

Result: 1 collection error in 4.28s. The same root cause reproduced twice; that approach was stopped. Primary exceptions from the first attempt, verbatim:

```text
E   FileNotFoundError: [WinError 3] Het systeem kan het opgegeven pad niet vinden: 'C:\\dev\\etf-BF-INT\\logs\\pytest_system_tmp\\tmpvlhhmk48\\data\\storage'
E   PermissionError: [WinError 5] Toegang geweigerd: 'C:\\dev\\etf-BF-INT\\logs\\pytest_system_tmp\\tmpvlhhmk48\\data'
E   PermissionError: [WinError 5] Toegang geweigerd: 'C:\\dev\\etf-BF-INT\\logs\\pytest_system_tmp\\tmpvlhhmk48'
```

Remaining module tests ran independently; the collection error remains a blocker:

```powershell
$bugfixTests = (Get-ChildItem tests/test_bugfix_*.py).FullName
python -m pytest -q --tb=line -p no:cacheprovider -o addopts='' $bugfixTests tests/ui/test_page_stock_research.py tests/test_evidence_ledger.py tests/test_stress_testing.py tests/test_forecast_distributions.py tests/test_forecast_uncertainty.py tests/test_feature_store.py tests/test_etf_economics_production.py tests/test_import_export.py tests/test_backup_restore.py tests/operations/test_backups.py tests/test_bulk_cache.py tests/test_release_certification.py tests/test_secure_update.py tests/test_sparebank_valuation.py tests/test_sparebank_events.py tests/test_sparebank_bank_economics.py tests/test_paths.py tests/test_comparison_workspace.py tests/test_flet_startup.py tests/ui/test_charts_bars_lines.py tests/test_release_hardening.py tests/test_complete_audit_packet.py
```

Result: 2 failed, 425 passed, 132 warnings in 259.77s. Verbatim output retained below. Workspace-prefix failure was then fixed in the allowed source file, retaining its original assertions. Undated forecast fixture failure remains because its test file is outside the write set. Neither failing identifier nor the collection error appears in the supplied gate-fails-1b733dc4.txt baseline.

Final path/workspace rerun:

```powershell
python -m pytest -q --tb=line -p no:cacheprovider -o addopts='' tests/test_paths.py tests/test_comparison_workspace.py tests/test_bugfix_t-uia.py::test_p06_n007_colliding_workspace_names_get_two_files tests/test_bugfix_t-uia.py::test_int_uia_1_literal_transformed_workspace_name_cannot_overwrite
```

Result: 8 passed, 64 warnings in 46.11s. Unchanged passing module evidence was reused.

Earlier fixture-development attempts reported four failures (pass count not recorded), then 2 failed / 50 passed / 134 deselected. Fixtures were corrected for partial stress coverage, object-return access and transaction guard/directory setup; unavailable-evidence and original-file assertions were retained or strengthened. The initial bugfix/UI-only invocation's result handle was not retained: outcome UNVERIFIED, unused as acceptance evidence.

## ASSUMPTIONS/RISKS

- execution_allowed remains false. Tests use synthetic or existing fixtures; no external identifiers or financial evidence were fabricated.
- Literal safe workspace/cache names keep their paths. Cleaned names use new reserved-namespace paths; existing cleaned-name artifacts are not automatically migrated by this packet.
- Symlink/junction/reparse source-root branches have unit coverage; an actual directly supplied Windows directory junction was exercised. Physical Windows directory symlinks were not independently created.
- Restore rollback covers operation exceptions. Power-loss/process-crash recovery of deletion steps was not tested or redesigned.
- Underlying Windows permission-denial cause is UNVERIFIED. No harness, ACL or shared persistence changes were attempted.

## NEEDS_OPUS_DECISION

1. Authorize updating tests/test_release_hardening.py::test_valid_forecast_rows_become_model_score_inputs, outside the write set, to supply an eligible dated forecast fixture using existing module fixture dates while preserving both assertions. The successful fixture omits forecast_date; permitting it in source violates the approved fail-closed rule. Actual remaining failure: KeyError: 'VWCE' at tests/test_release_hardening.py:715.
2. Provide a permitted test environment or approve a bounded harness correction for the repeated tests/test_etf_economics.py collection PermissionError. Its test bodies remain unexecuted; this failure is outside the baseline and cannot be accepted.
3. Stage and commit this preserved patch in an environment with write access to the linked worktree's Git metadata. The current permission profile allows workspace file edits but rejects creation of the external index.lock. No metadata relocation, index workaround or permission change was attempted.

Git staging failure, verbatim:

```text
fatal: Unable to create 'C:/Users/thor2/Desktop/Trading App/etf_ai_cockpit/.git/worktrees/etf-BF-INT/index.lock': Permission denied
```

NEXT_STEP: retain the working-tree patch, resolve the fixture and collection blockers, run affected checks, and create the requested local commit as "fix(int): Sol review findings" from an environment with permitted Git metadata writes.

## COMPLETION CHECKLIST

- All 18 numbered findings implemented with focused train tests.
- Stock Research assertions restored; stale rejection separately tested.
- Every named test file exists and was invoked. tests/test_etf_economics.py bodies remain blocked at collection, reported above.
- No assertions weakened, skipped or deleted to make evidence pass; no out-of-scope tests edited.
- Write set checked with git diff --stat and git status --porcelain. Added/edited lines are LF; original mixed endings on unchanged export_pack.py lines retained to avoid churn. git diff --check clean.
- Full acceptance incomplete; no claim of a passing complete validation gate.
- Requested commit remains blocked at Git staging; no commit or push was made.

## Remaining-module output before final path-prefix correction

```text
........................................................................ [ 16%]
........................................................................ [ 33%]
........................................................................ [ 50%]
........................................................................ [ 67%]
.................................................................F...... [ 84%]
................................................F..................      [100%]
================================== FAILURES ===================================
E   AssertionError: assert False
     +  where False = <built-in method startswith of str object at 0x000001CE0F63CEB0>('latest_comparison-')
     +    where <built-in method startswith of str object at 0x000001CE0F63CEB0> = 'latest_comparison~c89f217b6a9dcd67dae37e62c67192f432f8f792c7edab21479e08d78248996a.json'.startswith
     +      where 'latest_comparison~c89f217b6a9dcd67dae37e62c67192f432f8f792c7edab21479e08d78248996a.json' = WindowsPath('C:/dev/etf-BF-INT/logs/pytest_system_tmp/cases/case_5ba47023d30e46a79433bd6f94f2cc15/latest_comparison~c89f217b6a9dcd67dae37e62c67192f432f8f792c7edab21479e08d78248996a.json').name
C:\dev\etf-BF-INT\tests\test_comparison_workspace.py:115: AssertionError: assert False
E   KeyError: 'VWCE'
C:\dev\etf-BF-INT\tests\test_release_hardening.py:715: KeyError: 'VWCE'
============================== warnings summary ===============================
tests/test_bugfix_t-uib.py: 64 warnings
tests/test_release_hardening.py: 64 warnings
  C:\Users\thor2\AppData\Local\Programs\Python\Python312\Lib\site-packages\numpy\lib\_nanfunctions_impl.py:1213: RuntimeWarning: Mean of empty slice
    return np.nanmean(a, axis, out=out, keepdims=keepdims)

tests/test_release_hardening.py::test_audit_export_contains_validation_and_risk_gate_reports
tests/test_release_hardening.py::test_audit_export_includes_imported_manual_news_notes
  C:\dev\etf-BF-INT\src\etf_cockpit\portfolio\allocation.py:35: FutureWarning: Downcasting object dtype arrays on .fillna, .ffill, .bfill is deprecated and will change in a future version. Call result.infer_objects(copy=False) instead. To opt-in to the future behavior, set `pd.set_option('future.no_silent_downcasting', True)`
    merged["current_weight"] = merged["current_weight"].fillna(0.0)

tests/test_release_hardening.py::test_audit_export_contains_validation_and_risk_gate_reports
tests/test_release_hardening.py::test_audit_export_includes_imported_manual_news_notes
  C:\dev\etf-BF-INT\src\etf_cockpit\portfolio\allocation.py:36: FutureWarning: Downcasting object dtype arrays on .fillna, .ffill, .bfill is deprecated and will change in a future version. Call result.infer_objects(copy=False) instead. To opt-in to the future behavior, set `pd.set_option('future.no_silent_downcasting', True)`
    merged["market_value_eur"] = merged["market_value_eur"].fillna(0.0)

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
=========================== short test summary info ===========================
FAILED tests/test_comparison_workspace.py::test_saved_workspace_is_local_versioned_and_reproducible
FAILED tests/test_release_hardening.py::test_valid_forecast_rows_become_model_score_inputs
2 failed, 425 passed, 132 warnings in 259.77s (0:04:19)

```
