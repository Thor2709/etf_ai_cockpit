# bf/t-uia handoff (bug-hunt batch, 18 IDs)

All 18 IDs fixed; none escalated (NEEDS_OPUS_DECISION: none). Tests: `tests/test_bugfix_t-uia.py`, one `test_<id>` each.

| ID | Result |
|---|---|
| CHAT-P05-N002 | fixed: Operations page sends `fill_id=ui-<uuid4>` once per submit (`pages/operations.py`) |
| P05-N003 | fixed (doc only): rebalance help line states sale proceeds are assumed available / settlement buffer (`pages/portfolio.py`) |
| P06-N001 | fixed: `AppState.load` uses `copy.copy(_shared_snapshot())`; `apply_universe_config` already reassigns frames |
| P06-N002 | fixed: `_body_scrolls(height, narrow)` used by `apply_body_mode` and relayout before/after (`router.py`) |
| P06-N003 / P06-N012 | fixed: `build_topbar(width=...)` accepts a getter; closures and `refresh_chrome` use `mode["width"]` |
| P06-N004 | fixed: failed section filler logs `deferred_section_failure` and shows a `Note("This section could not load: <Type>")` |
| P06-N005 | fixed: `_PAGE_UPDATE_SWAP_LOCK` (RLock) held for the whole `_deferred_page_update` block |
| P06-N006 | fixed: `_route_parts(route)` shared by `_page_route` and `navigate_to` |
| P06-N007 | fixed: new `core/paths.safe_file_stem` (H:stem; `-<sha256[:12]>` suffix when cleaning changed the name) used by workspaces. P02-N003 (bulk_cache) not in this train and may reuse it |
| P06-N008 | fixed: reuse only when `data/runtime/web_instance.json` (`WEB_INSTANCE_PATH`, written on start via `atomic_write_json`) names the port and a live pid |
| P06-N009 | fixed: `AppState.message_serial` bumped on every `last_message` assignment; toast dedups on it |
| P06-N010 | fixed: `execution_allowed` forced `False` on save and on load |
| P06-N013 | fixed: `grouped_bar_chart` line segment only between adjacent category indices |
| P06-N014 | fixed: `y_min` defaults to `min(0, min(known))`; bars drawn signed from the zero baseline |
| P06-N015 | fixed: `today` positioned on the data's own scale; not drawn outside `[x0, x1]` |
| P06-N016 | fixed: glossary load error returns `[]` without caching |
| P06-N017 | fixed: `choose()` sets `current` then `overlay.hide()` (its `on_hide` rebuilds); second `rebuild()` removed |

Existing test assertions updated (pinned the buggy behaviour): `tests/test_comparison_workspace.py::test_saved_workspace_is_local_versioned_and_reproducible` (cleaned name now carries `-<hash>`; asserts via `safe_file_stem`); `tests/test_flet_startup.py::test_reuse_existing_web_server_opens_ready_local_app` (also stubs `_is_own_web_instance`).

Files: `app/components/chartkit/{bars,lines}.py`, `app/components/shell/{search,topbar}.py`, `app/{flet_app,router,state,workspaces}.py`, `app/pages/{operations,portfolio}.py`, `core/paths.py`, `tests/test_bugfix_t-uia.py`, this file.

Validation: `python -m pytest -q --tb=line -p no:cacheprovider tests/test_bugfix_t-uia.py` → 18 passed. 132 existing test files touching the changed modules were run in 4 shards: every failure is listed in `gate-fails-1b733dc4.txt` (base failures) except `test_performance_policy::test_startup_import_timing_stays_within_versioned_budget` (timing flake under load; passes alone) and the two assertions updated above (now green).
