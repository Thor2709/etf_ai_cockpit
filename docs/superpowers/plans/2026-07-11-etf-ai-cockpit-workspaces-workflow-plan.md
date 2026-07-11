# Workflow Workspaces, Accessibility and Local Research Operations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` with a fresh implementer and a fresh reviewer for each task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete `UI-01` through `UI-05` and `WORK-01` through `WORK-04` by converting the current flat Flet route surface into semantic workflow/entity workspaces with a job centre, saved research queue, source-linked calendar/brief and safe local scheduler/alerts.

**Architecture:** Preserve every existing route by aliases/redirects while introducing typed route metadata and committed view models. Pages read repositories/query services only; they do not calculate analytics, call providers or write canonical data during render.

**Tech Stack:** Flet, Pydantic, existing router/theme/components, DuckDB/PyArrow query services, optional APScheduler only after package proof, RFC 5545-compatible local iCalendar parser, pytest and Playwright/Chrome.

## Global Constraints

- No scope drift; do not create broker, order, credential or external-upload functionality.
- Evidence, analysis, research state, portfolio review and user decisions stay separate; `execution_allowed` remains `false`.
- Preserve the revision-protected universe store, atomic I/O/recovery, Data Health, provider/evidence contracts, source-aware score eligibility, session trace, audit manifests, router and Flet shell.
- Use narrow adapters and migrations; do not perform unrelated refactoring.
- Do not initialise Git, create a worktree, commit, push, create a pull request, delete user data or modify a remote service.
- Reuse current dark research-cockpit tokens/components; do not introduce filler, marketing cards, decorative emoji, gradients or invented values.
- Every visible surface exposes text/icon/semantic state, keyboard focus and applicable loading, empty, partial, stale, unavailable, success and error states.
- Record a RED command before behavioural code, a GREEN command afterwards, then refactor and rerun the focused regression.
- No issue state changes until fresh source, migration, test, package, browser, audit and independent-review evidence exists.

---

## File structure and interfaces

| File | Responsibility |
|---|---|
| Create `app/routes.py`, `app/view_models.py`, reusable components under `app/components/` | typed route/workspace/page-state and shared accessibility controls |
| Modify `app/router.py:1-182`, `app/flet_app.py`, `app/theme.py`, current pages | aliases, workflow navigation, entity deep links and committed view model loading |
| Create `workflow/screens.py`, `queue.py`, `calendar.py`, `scheduler.py`, `alerts.py`, `daily_brief.py`, `ical.py`, `clock.py` | saved screen/queue/calendar/scheduler/alert/brief state |
| Create relevant Flet workspace pages and UI tests | Home, Research, Portfolio, Evidence, Validation & Models, Operations, Settings & Help |

**Interfaces:**

```python
class RouteDefinition(BaseModel):
    route_id: str
    path_template: str
    workspace: str
    feature_id: str
    allowed_tabs: list[str]
    entity_parameter: str | None

class PageViewState(BaseModel):
    route_id: str
    entity_id: str | None
    tab: str | None
    as_of_time: datetime | None
    status: Literal["loading", "ready", "partial", "empty", "error"]

class DailyBrief(BaseModel):
    brief_id: str
    deterministic_manifest_hash: str
    citations: list[str]
    no_material_change: bool
```

### Task 1: Introduce a typed workspace router, semantic shell and entity deep-link state

**Files:**

- Create: `app/routes.py`, `app/view_models.py`, `app/components/adaptive_navigation.py`, `app/components/accessibility.py`, `tests/ui/test_route_registry.py`, `test_adaptive_navigation.py`, `test_accessibility_semantics.py`
- Modify: `app/router.py:1-182`, `app/flet_app.py`, existing navigation shell/components

**Consumes:** governance feature registry and registry entity IDs.

**Produces:** one route declaration per route, workflow navigation, aliases and deep-link/back/reload view state.

- [ ] **Step 1: Write RED route/semantic tests**

```python
def test_legacy_route_redirects_without_losing_selected_entity_context() -> None:
    result = resolve_route("/instrument/ASML?tab=evidence")
    assert result.definition.workspace == "Research"
    assert result.view_state.entity_id == "asml_xams"
    assert result.view_state.tab == "evidence"

def test_all_navigation_controls_have_semantic_labels() -> None:
    assert semantic_coverage(build_shell(state)).missing_labels == []
```

- [ ] **Step 2: Run RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\ui\test_route_registry.py tests\ui\test_adaptive_navigation.py tests\ui\test_accessibility_semantics.py -q`

Expected: FAIL because current `PAGES` is a flat tuple registry with no entity/workspace/page state model.

- [ ] **Step 3: Implement route registry and adaptive Flet shell**

Keep old paths as aliases. Group routes into Home, Research, Portfolio, Evidence, Validation & Models, Operations and Settings & Help. Use a wide sidebar, medium rail/drawer and narrow stacked layout. Semantic labels, visible focus and text/icon state are mandatory.

- [ ] **Step 4: Run GREEN and direct-link regression**

Run: `.\.venv\Scripts\python.exe -m pytest tests\ui\test_route_registry.py tests\ui\test_adaptive_navigation.py tests\ui\test_accessibility_semantics.py tests\test_flet_startup.py -q`

Expected: PASS; direct launch, back, reload, invalid/retired entity and lifecycle-unavailable routes are explicit.

- [ ] **Step 5: Save route map evidence**

Export route registry, aliases, semantic locator coverage and package deep-link test plan.

### Task 2: Build shared page states, Job Centre and attention-first Home

**Files:**

- Create: `app/components/empty_state.py`, `partial_state.py`, `error_state.py`, `skeleton.py`, `job_centre.py`, `notification_centre.py`, `tests/ui/test_page_states.py`, `test_job_centre_ui.py`, `test_home_ui.py`
- Modify: `app/pages/dashboard.py:1-end`, `core/workflow.py`, operational event projections

**Consumes:** Wave 0 operational event/workflow records and typed page state.

**Produces:** persistent readable job state and Home sections derived from one committed snapshot.

- [ ] **Step 1: Write RED job/attention tests**

```python
def test_failed_job_remains_visible_with_recovery_action() -> None:
    centre = build_job_centre([failed_run])
    assert "Retry" in text_of(centre)
    assert semantics_of(centre).button("Retry workflow").focusable

def test_home_shows_no_material_change_without_invented_metrics() -> None:
    home = build_home(empty_attention_snapshot)
    assert "No material source-backed change" in text_of(home)
```

- [ ] **Step 2: Run RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\ui\test_page_states.py tests\ui\test_job_centre_ui.py tests\ui\test_home_ui.py -q`

Expected: FAIL because dashboard owns raw action/thread state and no shared job/page-state components exist.

- [ ] **Step 3: Implement committed-view model components**

Home presents system status, attention, what changed, research queue, portfolio, upcoming events, quick workflows and source-cited daily brief. The shell Job Centre derives state from workflow events and never starts work from page render.

- [ ] **Step 4: Run GREEN**

Run: `.\.venv\Scripts\python.exe -m pytest tests\ui\test_page_states.py tests\ui\test_job_centre_ui.py tests\ui\test_home_ui.py tests\test_e2e_workflow.py -q`

Expected: PASS, including simultaneous navigation, queue/coalescing, error/recovery and offline/empty paths.

- [ ] **Step 5: Capture Home/job source and package evidence**

Record keyboard navigation, live-region events, failed/retry state and 1366×768/150% screenshots.

### Task 3: Deliver research score/entity/document/event/job workspaces and side sheets

**Files:**

- Create: `app/components/side_sheet.py`, `source_citation.py`, workspace pages/selectors, `tests/ui/test_score_table_ui.py`, `test_instrument_workspace_ui.py`, `test_document_workspace_ui.py`
- Modify: score, instrument detail, evidence, filings, ETF disclosure, news and diagnostics pages

**Consumes:** decision report, registry entity route, citation and event models.

**Produces:** consistent quick/full entity inspection with authority-first score display.

- [ ] **Step 1: Write RED authority/focus tests**

```python
def test_score_side_sheet_places_failed_gate_before_total_score() -> None:
    sheet = build_score_side_sheet(failed_gate_report)
    assert text_of(sheet).index("Identity blocker") < text_of(sheet).index("Champion score")

def test_side_sheet_restores_focus_after_close() -> None:
    assert close_side_sheet(opened_from=trigger).focus_target is trigger
```

- [ ] **Step 2: Run RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\ui\test_score_table_ui.py tests\ui\test_instrument_workspace_ui.py tests\ui\test_document_workspace_ui.py -q`

Expected: FAIL because existing expansion/table pages have no shared side sheet/full entity contract.

- [ ] **Step 3: Implement side-sheet/full-workspace pattern**

Scores use semantic row actions, gate summary, N/A text and responsive stacked compact cards. Instrument workspace has Overview, Evidence, Fundamentals/Product, Signals, Risk & Friction, Portfolio Fit, Forecasts/Models, History & Changes and Journal tabs. Document/event/job workspaces preserve citation/as-of/entity context.

- [ ] **Step 4: Run GREEN and route/browser regression**

Run: `.\.venv\Scripts\python.exe -m pytest tests\ui\test_score_table_ui.py tests\ui\test_instrument_workspace_ui.py tests\ui\test_document_workspace_ui.py tests\test_instrument_detail.py -q`

Expected: PASS; narrow side sheet becomes a full-screen dialog/page and focus/back state survives.

- [ ] **Step 5: Complete content/accessibility review**

Inspect content/filler, hierarchy/rhythm, interaction states, keyboard/contrast and source/package responsive parity separately; record each result.

### Task 4: Create saved screens, research queue, source-linked calendar and daily brief

**Files:**

- Create: `workflow/screens.py`, `queue.py`, `calendar.py`, `ical.py`, `materiality.py`, `daily_brief.py`, UI pages, `tests/workflow/test_saved_screens.py`, `test_research_queue.py`, `test_calendar.py`, `test_ical.py`, `test_daily_brief.py`
- Modify: evidence events, What Changed page and Home integration

**Consumes:** catalogue query service, evidence events, Decision Journal and workflow event trace.

**Produces:** reproducible screen results, non-authoritative queue items, calendar events and source-cited deterministic brief.

- [ ] **Step 1: Write RED reproducibility/citation tests**

```python
def test_same_screen_snapshot_replays_same_result_ids() -> None:
    first = run_saved_screen(screen, as_of=AS_OF)
    second = run_saved_screen(screen, as_of=AS_OF)
    assert second.output_manifest_id == first.output_manifest_id

def test_daily_brief_rejects_uncited_factual_item() -> None:
    with pytest.raises(ValueError, match="citation"):
        build_daily_brief([uncited_fact], manifest=manifest)
```

- [ ] **Step 2: Run RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\workflow\test_saved_screens.py tests\workflow\test_research_queue.py tests\workflow\test_calendar.py tests\workflow\test_ical.py tests\workflow\test_daily_brief.py -q`

Expected: FAIL because candidate CSV/What Changed have no persisted screen/queue/calendar/brief contracts.

- [ ] **Step 3: Implement versioned local workflow records**

Screen runs retain query/as-of/generation hash/diff; queue priority is workflow urgency only. Calendar source events preserve status/timezone/date precision/version. iCalendar supports a safe RFC 5545 subset. Brief builds deterministic materiality/citation payload first; optional LLM only rewrites validated items.

- [ ] **Step 4: Run GREEN and UI journeys**

Run: `.\.venv\Scripts\python.exe -m pytest tests\workflow\test_saved_screens.py tests\workflow\test_research_queue.py tests\workflow\test_calendar.py tests\workflow\test_ical.py tests\workflow\test_daily_brief.py -q`

Expected: PASS; lower-authority/context source cannot create an unsupported factual alert/brief claim.

- [ ] **Step 5: Store reproducibility evidence**

Export representative screen manifests, queue state, calendar roundtrip, brief citation coverage and no-material-change sample.

### Task 5: Build persisted local scheduler, alerts, reminders and Automation settings

**Files:**

- Create: `workflow/scheduler.py`, `schedule_store.py`, `alerts.py`, `alert_rules.py`, `reminders.py`, `notifications.py`, `clock.py`, `tests/workflow/test_scheduler.py`, `test_clock.py`, `test_alert_rules.py`, `test_alert_instances.py`, `test_notifications.py`
- Create: Automation/notification UI tests and page
- Modify: existing scheduler scaffold, workflow coordinator and Settings route

**Consumes:** workflow event trace, daily brief, calendar and action coordinator.

**Produces:** one local scheduler per data root, typed schedule/alert records and in-app delivery with cooldown/quiet hours.

- [ ] **Step 1: Write RED DST/dedup/safety tests**

```python
def test_scheduler_coalesces_missed_run_after_dst_forward_jump(fake_clock: FakeClock) -> None:
    outcome = scheduler.reconcile_after_startup(fake_clock)
    assert outcome.enqueued_run_count == 1
    assert outcome.misfire_recorded is True

def test_repeated_provider_outage_creates_one_suppressed_alert_after_cooldown() -> None:
    alerts = evaluate_rule(outage_rule, repeated_outage_events)
    assert len(alerts.created) == 1
    assert alerts.suppressed_count > 0
```

- [ ] **Step 2: Run RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\workflow\test_scheduler.py tests\workflow\test_clock.py tests\workflow\test_alert_rules.py tests\workflow\test_alert_instances.py -q`

Expected: FAIL because the current scheduler is a configuration stub with no persisted lock/misfire/alert state.

- [ ] **Step 3: Implement enqueue-only local scheduler and alert engine**

Schedules store IANA timezone, dependency, coalescing, misfire, max-instance and quiet-hour policy. Scheduler threads enqueue the existing workflow coordinator only; they never perform page work. Alerts preserve evidence refs, condition hash, dedup key, acknowledgement, suppression and delivery result. Desktop notification is optional; in-app notification is required.

- [ ] **Step 4: Run GREEN and package-restart tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests\workflow\test_scheduler.py tests\workflow\test_clock.py tests\workflow\test_alert_rules.py tests\workflow\test_alert_instances.py tests\workflow\test_notifications.py -q`

Expected: PASS, including fake clock/DST, duplicate app instance, disabled/read-only mode, notification failure and package restart fixtures.

- [ ] **Step 5: Complete UI and independent review**

Verify Automation/notification UI at all required viewports/zoom, keyboard-only operation, alert explainability and no execution authority. The reviewer must inspect source/package parity and a scheduler restart evidence bundle.
