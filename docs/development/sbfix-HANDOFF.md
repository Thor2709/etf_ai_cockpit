# SBFIX handoff

Status: PARTIAL

## Per-criterion result

1. PARTIAL. Pillar 3 replacement confirmations retain the original confirmation time and use `superseded_at`; cutoff selection returns the figure active then. `quarterly_score_history` now accepts a decision time and filters later runs. The instrument workspace does not pass its decision time, and score history does not retain `effective_at`.
2. DONE. Statement flow values are selected by filing identity and matching start/end duration. Pillar 3 evidence is filtered by reporting period. Missing or incompatible inputs carry reason codes.
3. DONE. Weighted and closing certificate counts remain separate. Missing closing count leaves closing valuation unavailable. Missing gavefond blocks reconstruction unless a reported ownership fraction is used.
4. DONE. Reported ROE remains visible while sustainable ROE is unavailable when the bridge lacks evidence. An explicit sustainable-ROE owner assumption is labelled and can resolve it; dependent justified and reverse valuation return unavailable without sustainable ROE.
5. DONE. One Sparebank assumption normalizer maps supported aliases, converts percent aliases, and adds defaults only when aliases are absent. `_book_valuation` reads canonical keys.
6. PARTIAL. Economics uses `net_interest_margin`; scorecard input rows display source citations beside calculation IDs. History grouping and separate run timestamp columns are implemented when reporting-period data is supplied, but production history lacks that field and its workspace call omits the decision-time argument.

## Tests and validation

The packet command as written failed before collecting tests in Windows PowerShell because PowerShell passed `tests/test_sparebank_*.py` literally:

```text
python -m pytest -q --tb=line -p no:cacheprovider tests/test_sparebank_*.py tests/test_simple_scores.py tests/test_instrument_detail.py
ERROR: file or directory not found: tests/test_sparebank_*.py
```

The equivalent command with the matching Sparebank test paths expanded passed: **208 passed, 0 failed**.

```powershell
$sparebankTestFiles = Get-ChildItem -Path tests -Filter 'test_sparebank_*.py' | ForEach-Object { $_.FullName }
python -m pytest -q --tb=line -p no:cacheprovider @sparebankTestFiles tests/test_simple_scores.py tests/test_instrument_detail.py
```

`git diff --check` passed. No commit was created.

## Files changed

- `src/etf_cockpit/analysis/sparebank/bank_economics.py`
- `src/etf_cockpit/analysis/sparebank/claim.py`
- `src/etf_cockpit/analysis/sparebank/models.py`
- `src/etf_cockpit/analysis/sparebank/scorecard.py`
- `src/etf_cockpit/analysis/sparebank/valuation.py`
- `src/etf_cockpit/app/pages/_sparebank_view.py`
- `src/etf_cockpit/application/financial_institution_views.py`
- `src/etf_cockpit/application/sparebank_evidence.py`
- `src/etf_cockpit/application/sparebank_peers.py`
- `src/etf_cockpit/data/pillar3_queue.py`
- `tests/test_sparebank_claim.py`
- `tests/test_sparebank_sb2.py`
- `tests/test_sparebank_sb2_data.py`
- `tests/test_sparebank_sb2_view.py`
- `docs/development/sbfix-HANDOFF.md`

## NEEDS_OPUS_DECISION

The history criteria require two changes outside the packet write set:

- `src/etf_cockpit/application/instrument_detail_view.py`: pass `_sparebank_workspace`'s `decision_time` to `quarterly_score_history`.
- `src/etf_cockpit/data/score_history.py`: persist and retain `effective_at` in score history. The existing score writer also needs the reporting period added to its input row in `financial_institution_views.py`.

Without those changes, production history has no reporting-period quarter to group and does not apply the workspace cutoff. The helper and UI are prepared for the fields once that scope is authorized.
