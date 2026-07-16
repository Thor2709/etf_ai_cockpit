# Task 16 Post-Phase 2 Follow-up Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended for bounded parser/test tasks) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make mixed-direction news headlines fail closed in the Task 16 contradiction panel while preserving context-only authority and the completed Phase 2 verification workflow.

**Architecture:** Extend the existing deterministic headline-direction guard in `news_context.py`; when positive and negative direction terms both occur, classify the headline as unsupported rather than choosing one direction. The contradiction builder already omits unsupported rows, so no new authority, locking or provider mechanism is needed.

**Tech Stack:** Python 3.13-compatible code, pandas, pytest, the existing release verification-record and staged-evidence workflow.

## Global Constraints

- Modify only Task 16 source, regression-test, worklog/checkpoint and this plan files.
- Preserve `execution_allowed=false`, local-first behaviour and `executable_authority=false` for news.
- Do not close `ISSUE-0023`, `ISSUE-0025`, `ISSUE-0054` or `ISSUE-0055`; closure remains a later closure task.
- Do not begin Task 17 or create another worktree.
- Run commands synchronously and never duplicate or interrupt a running command.

---

### Task 1: Prove mixed-direction headlines fail closed

**Files:**
- Modify: `tests/test_news_context.py:168`
- Test: `tests/test_news_context.py`

**Interfaces:**
- Consumes: `build_news_contradiction_rows(news, prices)`.
- Produces: Regression coverage proving a headline containing both directional vocabularies is excluded from contradiction evidence.

- [ ] **Step 1: Write the failing test**

```python
def test_mixed_direction_headline_is_unavailable_for_contradiction_checks() -> None:
    news = pd.DataFrame([{
        "news_id": "mixed",
        "instrument_id": "MSFT",
        "headline": "MSFT shares rise despite a loss outlook",
        "published_at": "2026-07-10T10:00:00+00:00",
    }])
    prices = pd.DataFrame([
        {"instrument_id": "MSFT", "date": "2026-07-10", "adjusted_close": 100.0},
        {"instrument_id": "MSFT", "date": "2026-07-11", "adjusted_close": 95.0},
    ])

    contradictions = build_news_contradiction_rows(news, prices)

    assert contradictions.empty
```

- [ ] **Step 2: Run the regression and observe the expected failure**

Run:

```powershell
& 'C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe' -m pytest tests/test_news_context.py::test_mixed_direction_headline_is_unavailable_for_contradiction_checks -q
```

Expected: FAIL because the current positive-first classifier emits an `up` contradiction row.

### Task 2: Implement the minimal fail-closed classifier

**Files:**
- Modify: `src/etf_cockpit/data/news_context.py:234-236`
- Test: `tests/test_news_context.py`

**Interfaces:**
- Consumes: the existing positive/negative token-boundary checks.
- Produces: `headline_direction="unknown"` whenever both or neither direction is supported, preserving existing `up`/`down` behaviour for unambiguous headlines.

- [ ] **Step 1: Change only the direction selection**

```python
headline_direction = (
    "up"
    if has_positive and not has_negative
    else "down"
    if has_negative and not has_positive
    else "unknown"
)
```

- [ ] **Step 2: Run the focused Task 16 tests**

Run:

```powershell
& 'C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe' -m pytest tests/test_fundamentals.py tests/test_news_context.py tests/test_optional_providers.py tests/test_news_ui.py tests/ui/test_screener_ui.py tests/test_yfinance_provider.py -q
```

Expected: all selected tests pass.

### Task 3: Record the bounded follow-up and checkpoint

**Files:**
- Create: `.ai_worklog/task-16-fix7-report.md`
- Modify: `RUN_STATE.json`
- Modify: `docs/superpowers/plans/2026-07-11-etf-ai-cockpit-programme-index.md`
- Modify: `docs/superpowers/plans/2026-07-11-etf-ai-cockpit-progress-ledger.md`

Record the RED/GREEN result, the exact affected tests, the independent-review outcome, the Phase 2 base commit, the current branch and the deliberate decision to leave all four Task 16 issues closure-pending. The checkpoint’s next action is PR integration and post-merge verification; it must not dispatch Task 17.

### Task 4: Verify, review and integrate

- [ ] Run the focused Task 16 bundle, scoped Ruff, targeted compilation and `git diff --check`.
- [ ] Dispatch one independent reviewer for the complete Task 16 follow-up diff and address only verified findings.
- [ ] Commit the reviewed Task 16 changes, push `wave4/task16-post-phase2`, create a non-draft PR to `main`, merge it normally and verify `origin/main` contains the merge commit.
