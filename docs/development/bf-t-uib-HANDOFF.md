# bf/t-uib handoff — bug-hunt batch (P07)

All 17 IDs fixed as their BUGFIX-PLAN-2026-10-10.md rows describe; one test each in `tests/test_bugfix_t-uib.py`
(`test_p07_nXXX`). No NEEDS_OPUS_DECISION items. No existing test assertions changed.

- N001 import_export: armed rollback stores `(batch, reason)`; second click runs only if unchanged, else re-arms.
- N002 import_export: one `_invalidate_preview()` called from type/locale/authority `on_change`.
- N003 stress_lab: `load()` clears every shock field before writing the saved ones.
- N004 stress_lab: per-scenario `revisions` dict instead of one `nonlocal revision`.
- N005 jobs: `refresh()` checks `api.jobs_store_status()` first; failure shows "Job store unavailable: <reason>", keeps rows.
- N006 jobs: `refresh(announce=False)` after cancel so the cancel message stays.
- N007 jobs: header shows "{shown} of {total}" plus a note when `next_offset` is set.
- N008 news_context: rows kept with sentiment tag, `_apply_filter` toggles `visible`.
- N009 macro_factors: `_charts(horizon)` cuts observations at `last_date − horizon`; callback swaps holder content.
- N010 etf_disclosures / filings: segment shows/hides its matching card.
- N012 plugins/registry: capability check (`unsupported`), `import` → `import_data` handler map.
- N013 training_centre: numeric-first sort key via `finite_float_or_none`.
- N014 comparison: duplicate labels get ` · {key}` suffix.
- N016 portfolio_optimiser: Disclosures live in `disclosure_host`, rebuilt at end of `run()` (and on invalid input).
- N017 forward_evidence: `_render_recent()` fills `recent_host`, called from `refresh()`.
- N018 what_changed: `chosen` looked up in the filtered rows; absent → empty detail and `state["selected"]=None`
  (added key `what-changed.path` to the detail holder for the test).
- N021 forward_evidence: outcomes card built from `entries` (matured/pending counts) in `_render_recent()`.

Files: app/pages/{comparison,etf_disclosures,filings,forward_evidence,import_export,jobs,macro_factors,news_context,
portfolio_optimiser,stress_lab,training_centre,what_changed}.py, plugins/registry.py, tests/test_bugfix_t-uib.py.

Tests: `python -m pytest -q --tb=line -p no:cacheprovider tests/test_bugfix_t-uib.py` → 17 passed.
Existing page/plugin tests (94 files grepped for the changed modules): 25 failures, all listed in gate-fails-1b733dc4.txt (base failures); none new.
